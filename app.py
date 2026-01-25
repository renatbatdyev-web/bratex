from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.secret_key = "bratex_secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DB = os.path.join(BASE_DIR, "users.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ================== DB HELPERS ==================

def get_users_db():
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_worker_db(username):
    path = os.path.join(BASE_DIR, f"{username}.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ================== INIT ==================

def init_users_db():
    conn = get_users_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    # добавляем колонку type если её нет
    c.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in c.fetchall()]
    if "type" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN type TEXT DEFAULT 'worker'")

    if "owner_admin" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN owner_admin TEXT")

    # главный админ всегда admin, пароль обновляется автоматически
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, type) VALUES (?, ?, ?)",
                  ("admin", "48444448r61222261r", "admin"))
    else:
        c.execute("UPDATE users SET password=? WHERE username='admin'", ("48444448r61222261r",))
        c.execute("UPDATE users SET type='admin' WHERE username='admin'")

    conn.commit()
    conn.close()


def init_worker_db(username):
    conn = get_worker_db(username)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        description TEXT,
        barcode TEXT,
        qr_code TEXT,
        quantity INTEGER,
        image TEXT,
        category TEXT,
        size TEXT,
        height TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS sales_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        name TEXT,
        barcode TEXT,
        quantity INTEGER,
        sale_time TEXT
    )
    """)

    conn.commit()
    conn.close()


init_users_db()

# создаём sales_history всем существующим работникам
conn = get_users_db()
c = conn.cursor()
c.execute("SELECT username, password FROM users WHERE type='admin' AND username != 'admin'")
users = c.fetchall()
conn.close()

for u in users:
    init_worker_db(u["username"])


# ================== AUTH ==================

@app.route("/", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("login")
        password = request.form.get("password")

        conn = get_users_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()

        if user:
            session["user"] = username
            session["type"] = user["type"]
            if user["type"] == "admin":
                return redirect("/admin_workers_panel")
            else:
                return redirect("/worker")
        else:
            error = "Неверный логин или пароль"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ================== ADMIN ==================

@app.route("/admin")
def admin_panel():
    if session.get("type") != "admin":
        return redirect("/")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username != 'admin'")
    users = c.fetchall()
    conn.close()

    return render_template("admin_panel.html", users=users)


@app.route("/admin/create_user", methods=["POST"])
def create_user():
    if session.get("type") != "admin":
        return redirect("/")

    username = request.form.get("username")
    password = request.form.get("password")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (username, password, type) VALUES (?, ?, ?)", (username, password, "worker"))
    conn.commit()
    conn.close()

    init_worker_db(username)

    return redirect("/admin")


@app.route("/admin/user/<int:user_id>")
def view_user(user_id):
    if session.get("type") != "admin":
        return redirect("/")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    user = c.fetchone()
    conn.close()

    return render_template("admin_user_card.html", user=user)


@app.route("/admin/user/<username>/<category>", methods=["GET", "POST"])
def admin_user_products(username, category):
    if session.get("type") != "admin":
        return redirect("/")

    conn = get_worker_db(username)
    c = conn.cursor()

    search = request.args.get("search", "").strip()

    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        barcode = request.form.get("barcode")
        qr_code = request.form.get("qr_code")
        quantity = request.form.get("quantity")
        size = request.form.get("size")
        height = request.form.get("height")

        image_file = request.files.get("image")
        image_name = None

        if image_file and image_file.filename:
            image_name = secure_filename(image_file.filename)
            image_file.save(os.path.join(UPLOAD_FOLDER, image_name))

        c.execute("""
            INSERT INTO products (name, description, barcode, qr_code, quantity, image, category, size, height)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, description, barcode, qr_code, quantity, image_name, category, size, height))
        conn.commit()

    if search:
        c.execute("""
            SELECT * FROM products
            WHERE category=? AND (name LIKE ? OR barcode LIKE ? OR qr_code LIKE ?)
        """, (category, f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        c.execute("SELECT * FROM products WHERE category=?", (category,))

    products = c.fetchall()
    conn.close()

    return render_template(
        "products_list.html",
        products=products,
        category=category,
        user=username,
        is_admin=True,
        search=search
    )


# ================== WORKER MENU ==================

@app.route("/worker")
def worker_menu():
    if "user" not in session or session.get("type") != "worker":
        return redirect("/")

    return render_template("worker_menu.html", username=session["user"])


@app.route("/worker/warehouse")
def worker_warehouse_menu():
    if "user" not in session or session.get("type") != "worker":
        return redirect("/")

    return render_template("warehouse_menu.html", username=session["user"])


# ================== WORKER PRODUCTS ==================

@app.route("/worker/<category>", methods=["GET", "POST"])
def worker_products(category):
    if "user" not in session or session.get("type") != "worker":
        return redirect("/")

    username = session["user"]
    conn = get_worker_db(username)
    c = conn.cursor()

    search = request.args.get("search", "").strip()

    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        barcode = request.form.get("barcode")
        qr_code = request.form.get("qr_code")
        quantity = request.form.get("quantity")
        size = request.form.get("size")
        height = request.form.get("height")

        image_file = request.files.get("image")
        image_name = None

        if image_file and image_file.filename:
            image_name = secure_filename(image_file.filename)
            image_file.save(os.path.join(UPLOAD_FOLDER, image_name))

        c.execute("""
            INSERT INTO products (name, description, barcode, qr_code, quantity, image, category, size, height)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, description, barcode, qr_code, quantity, image_name, category, size, height))
        conn.commit()

    if search:
        c.execute("""
            SELECT * FROM products
            WHERE category=? AND (name LIKE ? OR barcode LIKE ? OR qr_code LIKE ?)
        """, (category, f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        c.execute("SELECT * FROM products WHERE category=?", (category,))

    products = c.fetchall()
    conn.close()

    return render_template(
        "products_list.html",
        products=products,
        category=category,
        user=username,
        is_admin=False,
        search=search
    )


# ================== EDIT PRODUCT ==================

@app.route("/product/<username>/<int:product_id>")
def view_product(username, product_id):
    if "user" not in session:
        return redirect("/")

    conn = get_worker_db(username)
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id=?", (product_id,))
    product = c.fetchone()
    conn.close()

    if not product:
        return "Товар не найден", 404

    return render_template("view_product.html", product=product, user=username)


@app.route("/product/<username>/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(username, product_id):
    if "user" not in session:
        return redirect("/")

    # работникам запрещено редактирование
    if session.get("type") == "worker":
        return redirect(f"/product/{username}/{product_id}")

    conn = get_worker_db(username)
    c = conn.cursor()

    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        barcode = request.form.get("barcode")
        qr_code = request.form.get("qr_code")
        quantity = request.form.get("quantity")
        size = request.form.get("size")
        height = request.form.get("height")

        image_file = request.files.get("image")
        image_name = None

        if image_file and image_file.filename:
            image_name = secure_filename(image_file.filename)
            image_file.save(os.path.join(UPLOAD_FOLDER, image_name))
            c.execute("""
                UPDATE products
                SET name=?, description=?, barcode=?, qr_code=?, quantity=?, image=?
                WHERE id=?
            """, (name, description, barcode, qr_code, quantity, image_name, product_id))
        else:
            c.execute("""
                UPDATE products
                SET name=?, description=?, barcode=?, qr_code=?, quantity=?
                WHERE id=?
            """, (name, description, barcode, qr_code, quantity, product_id))

        conn.commit()
        conn.close()

        return redirect(request.referrer)

    c.execute("SELECT * FROM products WHERE id=?", (product_id,))
    product = c.fetchone()
    conn.close()

    return render_template("edit_product.html", product=product, user=username)


# ================== SALE ==================

@app.route("/worker/sale", methods=["GET", "POST"])
def worker_sale():
    if "user" not in session or session.get("type") != "worker":
        return redirect("/")

    username = session["user"]
    conn = get_worker_db(username)
    c = conn.cursor()

    error = None
    success = None

    found_product = None
    code_value = ""

    # PREVIEW по GET (после сканирования)
    code_preview = request.args.get("code", "").strip()
    if code_preview:
        code_value = code_preview
        c.execute("SELECT * FROM products WHERE barcode=? OR qr_code=?", (code_preview, code_preview))
        found_product = c.fetchone()

    # ПРОДАЖА только по кнопке
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        code_value = code
        qty = int(request.form.get("quantity", 0))

        c.execute("SELECT * FROM products WHERE barcode=? OR qr_code=?", (code, code))
        product = c.fetchone()

        if not product:
            error = "Товар не найден"
        elif product["quantity"] < qty:
            error = "Недостаточно товара на складе"
        else:
            new_qty = product["quantity"] - qty
            c.execute("UPDATE products SET quantity=? WHERE id=?", (new_qty, product["id"]))

            c.execute("""
                INSERT INTO sales_history (product_id, name, barcode, quantity, sale_time)
                VALUES (?, ?, ?, ?, ?)
            """, (
                product["id"],
                product["name"],
                product["barcode"],
                qty,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))

            conn.commit()
            success = "Продажа выполнена"

            # показать обновлённый остаток сразу после продажи
            c.execute("SELECT * FROM products WHERE id=?", (product["id"],))
            found_product = c.fetchone()

    conn.close()
    return render_template(
        "sale.html",
        error=error,
        success=success,
        found_product=found_product,
        code_value=code_value
    )



# ================== SALES HISTORY ==================

@app.route("/worker/sales_history")
def sales_history():
    if "user" not in session or session.get("type") != "worker":
        return redirect("/")

    username = session["user"]
    conn = get_worker_db(username)
    c = conn.cursor()
    c.execute("SELECT * FROM sales_history ORDER BY id DESC")
    history = c.fetchall()
    conn.close()

    return render_template("sales_history.html", history=history)


# ================== DELETE ==================

@app.route("/delete_product/<username>/<int:product_id>/<category>")
def delete_product(username, product_id, category):
    if "user" not in session:
        return redirect("/")

    conn = get_worker_db(username)
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    conn.close()

    if session.get("user") == "admin":
        return redirect(f"/admin/user/{username}/{category}")
    else:
        return redirect(f"/worker/{category}")



@app.route("/admin/create_admin", methods=["POST"])
def create_admin():
    if session.get("type") != "admin":
        return redirect("/")

    login = request.form.get("login","").strip()
    password = request.form.get("password","").strip()
    password2 = request.form.get("password2","").strip()

    if not login or not password:
        return redirect("/admin")

    if password != password2:
        return redirect("/admin")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (username, password, type) VALUES (?, ?, ?)", (login, password, "admin"))
    conn.commit()
    conn.close()

    return redirect("/admin")


@app.route("/admin/admins")
def admins_list():
    if session.get("type") != "admin":
        return redirect("/")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("SELECT username, password FROM users WHERE type='admin' AND username != 'admin'")
    admins = c.fetchall()
    conn.close()

    return render_template("admins_list.html", admins=admins)




@app.route("/admin_workers_panel/create_worker", methods=["POST"])
def create_worker_by_admin():
    if "user" not in session:
        return redirect("/")

    if session.get("type") != "admin":
        return redirect("/")

    # обычный админ создаёт работника
    username = request.form.get("username")
    password = request.form.get("password")

    if not username or not password:
        return redirect("/admin_workers_panel")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (username, password, type, owner_admin) VALUES (?, ?, ?, ?)",
              (username, password, "worker", session.get("user")))
    conn.commit()
    conn.close()

    init_worker_db(username)

    return redirect("/admin_workers_panel")


# ================== ADMIN WORKERS PANEL ==================

@app.route("/admin_workers_panel")
def admin_workers_panel():
    if "user" not in session:
        return redirect("/")

    if session.get("type") != "admin":
        return redirect("/")

    if session.get("user") == "admin":
        return redirect("/admin")

    # список работников (все кроме admin-аккаунтов)
    conn = get_users_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE type='worker' AND owner_admin=?", (session.get("user"),))
    workers = c.fetchall()
    conn.close()

    return render_template("admin_workers_panel.html", workers=workers)



@app.route("/admin/delete_worker/<username>")
def delete_worker(username):
    if "user" not in session or session.get("type") != "admin":
        return redirect("/")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username=? AND type='worker'", (username,))
    conn.commit()
    conn.close()
    return redirect("/admin_workers_panel")


@app.route("/admin/edit_worker/<username>", methods=["GET","POST"])
def edit_worker(username):
    if "user" not in session or session.get("type") != "admin":
        return redirect("/")

    conn = get_users_db()
    c = conn.cursor()

    if request.method=="POST":
        new_name=request.form.get("new_username")
        new_pass=request.form.get("new_password")
        if new_name:
            c.execute("UPDATE users SET username=? WHERE username=?", (new_name, username))
            username=new_name
        if new_pass:
            c.execute("UPDATE users SET password=? WHERE username=?", (new_pass, username))
        conn.commit()
        conn.close()
        return redirect("/admin_workers_panel")

    c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    worker=c.fetchone()
    conn.close()
    return render_template("edit_worker.html", worker=worker)



@app.route("/size_table")
def size_table():
    if "user" not in session:
        return redirect("/")
    return render_template("size_table.html", title="Размеры")



@app.route("/admin/size_manage")
def admin_size_manage():
    if "user" not in session:
        return redirect("/")
    if session.get("type") != "admin":
        return redirect("/size_table")
    return render_template("size_admin.html")





@app.route("/worker/<category>/table")
def worker_size_table(category):
    if "user" not in session:
        return redirect("/")
    username = session["user"] if session.get("user") != "admin" else None
    if session.get("type") == "admin":
        username = request.args.get("user", "")
    conn = get_worker_db(username)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,description TEXT,barcode TEXT,qr_code TEXT,quantity INTEGER,size TEXT,height TEXT,image TEXT,category TEXT)")
    conn.commit()
    c.execute("SELECT size, height, SUM(quantity) as qty FROM products WHERE category=? GROUP BY size, height", (category,))
    rows = c.fetchall()
    conn.close()
    data = {(r["size"], r["height"]): r["qty"] for r in rows}
    title = "Мужские размеры" if category=="male" else "Женские размеры"
    return render_template("size_table.html", title=title, data=data)




# ================== RETURN SALE ==================


@app.route("/worker/return_sale/<int:sale_id>", methods=["POST"])
def return_sale(sale_id):
    if "user" not in session or session.get("type") != "worker":
        return redirect("/")

    username = session["user"]
    conn = get_worker_db(username)
    c = conn.cursor()

    return_qty = int(request.form.get("return_qty", 0))

    c.execute("SELECT * FROM sales_history WHERE id=?", (sale_id,))
    sale = c.fetchone()

    if sale and return_qty > 0 and return_qty <= sale["quantity"]:
        c.execute("SELECT * FROM products WHERE id=?", (sale["product_id"],))
        product = c.fetchone()

        if product:
            new_qty = product["quantity"] + return_qty
            c.execute("UPDATE products SET quantity=? WHERE id=?", (new_qty, product["id"]))

        # если вернули полностью — удаляем продажу
        if return_qty == sale["quantity"]:
            c.execute("DELETE FROM sales_history WHERE id=?", (sale_id,))
        else:
            # если частично — уменьшаем количество в истории
            remaining = sale["quantity"] - return_qty
            c.execute("UPDATE sales_history SET quantity=? WHERE id=?", (remaining, sale_id))

        conn.commit()

    conn.close()
    return redirect("/worker/sales_history")




@app.route("/admin/change_admin_password/<username>", methods=["POST"])
def change_admin_password(username):
    if session.get("user") != "admin":
        return redirect("/")

    new_pass = request.form.get("new_password","").strip()
    if not new_pass:
        return redirect("/admin/admins")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("UPDATE users SET password=? WHERE username=? AND type='admin'", (new_pass, username))
    conn.commit()
    conn.close()

    return redirect("/admin/admins")


# ================== RUN ==================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



