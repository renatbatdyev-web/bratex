from flask import Flask, render_template, request, redirect, session
import os
from werkzeug.utils import secure_filename
from datetime import datetime

import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = "bratex_secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ================== DB HELPERS ==================

def get_users_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def get_worker_db(username):
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )

# ================== INIT ==================

def init_users_db():
    conn = get_users_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    c.execute("SELECT * FROM users WHERE username=%s", ("admin",))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (username, password) VALUES (%s,%s)",
            ("admin", "admin")
        )

    conn.commit()
    conn.close()

def init_worker_db(username):
    conn = get_worker_db(username)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        owner TEXT,
        name TEXT,
        description TEXT,
        barcode TEXT,
        qr_code TEXT,
        quantity INTEGER,
        image TEXT,
        category TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS sales_history (
        id SERIAL PRIMARY KEY,
        owner TEXT,
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

conn = get_users_db()
c = conn.cursor()
c.execute("SELECT username FROM users WHERE username != %s", ("admin",))
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
        c.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, password)
        )
        user = c.fetchone()
        conn.close()

        if user:
            session["user"] = username
            if username == "admin":
                return redirect("/admin")
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
    if session.get("user") != "admin":
        return redirect("/")

    conn = get_users_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username != %s", ("admin",))
    users = c.fetchall()
    conn.close()

    return render_template("admin_panel.html", users=users)

@app.route("/admin/create_user", methods=["POST"])
def create_user():
    if session.get("user") != "admin":
        return redirect("/")

    username = request.form.get("username")
    password = request.form.get("password")

    conn = get_users_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (username, password) VALUES (%s,%s)",
        (username, password)
    )
    conn.commit()
    conn.close()

    init_worker_db(username)

    return redirect("/admin")

@app.route("/admin/user/<username>")
def view_user(username):
    if session.get("user") != "admin":
        return redirect("/")

    return render_template("admin_user_card.html", user={"username": username})

@app.route("/admin/user/<username>/<category>", methods=["GET", "POST"])
def admin_user_products(username, category):
    if session.get("user") != "admin":
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

        image_file = request.files.get("image")
        image_name = None
        if image_file and image_file.filename:
            image_name = secure_filename(image_file.filename)
            image_file.save(os.path.join(UPLOAD_FOLDER, image_name))

        c.execute("""
            INSERT INTO products
            (owner, name, description, barcode, qr_code, quantity, image, category)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (username, name, description, barcode, qr_code, quantity, image_name, category))
        conn.commit()

    if search:
        c.execute("""
            SELECT * FROM products
            WHERE owner=%s AND category=%s
            AND (name ILIKE %s OR barcode ILIKE %s OR qr_code ILIKE %s)
        """, (username, category, f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        c.execute(
            "SELECT * FROM products WHERE owner=%s AND category=%s",
            (username, category)
        )

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
    if "user" not in session or session["user"] == "admin":
        return redirect("/")
    return render_template("worker_menu.html", username=session["user"])

@app.route("/worker/warehouse")
def worker_warehouse_menu():
    if "user" not in session or session["user"] == "admin":
        return redirect("/")
    return render_template("warehouse_menu.html", username=session["user"])

# ================== WORKER PRODUCTS ==================

@app.route("/worker/<category>", methods=["GET", "POST"])
def worker_products(category):
    if "user" not in session or session["user"] == "admin":
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

        image_file = request.files.get("image")
        image_name = None
        if image_file and image_file.filename:
            image_name = secure_filename(image_file.filename)
            image_file.save(os.path.join(UPLOAD_FOLDER, image_name))

        c.execute("""
            INSERT INTO products
            (owner, name, description, barcode, qr_code, quantity, image, category)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (username, name, description, barcode, qr_code, quantity, image_name, category))
        conn.commit()

    if search:
        c.execute("""
            SELECT * FROM products
            WHERE owner=%s AND category=%s
            AND (name ILIKE %s OR barcode ILIKE %s OR qr_code ILIKE %s)
        """, (username, category, f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        c.execute(
            "SELECT * FROM products WHERE owner=%s AND category=%s",
            (username, category)
        )

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

# ================== SALE ==================

@app.route("/worker/sale", methods=["GET", "POST"])
def worker_sale():
    if "user" not in session or session["user"] == "admin":
        return redirect("/")

    username = session["user"]
    conn = get_worker_db(username)
    c = conn.cursor()

    error = None
    success = None
    product = None

    if request.method == "POST" and request.form.get("action") == "preview":
        code = request.form.get("code", "").strip()
        c.execute(
            "SELECT * FROM products WHERE owner=%s AND (barcode=%s OR qr_code=%s)",
            (username, code, code)
        )
        product = c.fetchone()
        if not product:
            error = "Товар не найден"

    if request.method == "POST" and request.form.get("action") == "sell":
        product_id = int(request.form.get("product_id"))
        qty = int(request.form.get("quantity"))

        c.execute(
            "SELECT * FROM products WHERE id=%s AND owner=%s",
            (product_id, username)
        )
        product = c.fetchone()

        if not product:
            error = "Товар не найден"
        elif product["quantity"] < qty:
            error = "Недостаточно товара на складе"
        else:
            c.execute(
                "UPDATE products SET quantity=%s WHERE id=%s",
                (product["quantity"] - qty, product_id)
            )

            c.execute("""
                INSERT INTO sales_history
                (owner, product_id, name, barcode, quantity, sale_time)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                username,
                product["id"],
                product["name"],
                product["barcode"],
                qty,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))

            conn.commit()
            success = "Продажа выполнена"
            product = None

    conn.close()

    return render_template(
        "sale.html",
        error=error,
        success=success,
        product=product
    )

# ================== SALES HISTORY ==================

@app.route("/worker/sales_history")
def sales_history():
    if "user" not in session or session["user"] == "admin":
        return redirect("/")

    username = session["user"]
    conn = get_worker_db(username)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM sales_history WHERE owner=%s ORDER BY id DESC",
        (username,)
    )
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
    c.execute(
        "DELETE FROM products WHERE id=%s AND owner=%s",
        (product_id, username)
    )
    conn.commit()
    conn.close()

    if session.get("user") == "admin":
        return redirect(f"/admin/user/{username}/{category}")
    else:
        return redirect(f"/worker/{category}")

# ================== RUN ==================

if __name__ == "__main__":
  # app.run(debug=True)
