import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
from datetime import datetime, timedelta
import calendar
import hashlib
import secrets
import csv

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.backends.backend_pdf import PdfPages


# ============================================================
# CONFIGURATION
# ============================================================

DB_NAME = "expenses.db"

BG = "#F4F7FB"
CARD = "#FFFFFF"
DARK = "#172033"
TEXT = "#263449"
MUTED = "#6B778C"
BLUE = "#2563EB"
BLUE_DARK = "#1D4ED8"
GREEN = "#16A34A"
RED = "#DC2626"
ORANGE = "#EA580C"
PURPLE = "#7C3AED"
BORDER = "#E2E8F0"

current_user_id = None
current_username = None

root = None
login_frame = None
dashboard_frame = None
user_label = None
status_label = None

tree = None
amount_var = None
category_var = None
date_var = None
description_var = None
search_var = None
filter_category_var = None
budget_var = None

username_entry = None
password_entry = None
reg_username_entry = None
reg_password_entry = None
reg_confirm_entry = None
amount_entry = None
category_combo = None
date_entry = None
description_entry = None
budget_entry = None
search_entry = None
filter_combo = None

card_values = {}


# ============================================================
# ENTER KEY NAVIGATION
# ============================================================

def enter_next(widget, next_widget=None, command=None):
    """Move focus to the next field when Enter is pressed.
    This binding is attached directly to the widget and runs before
    Tkinter's normal Entry/Combobox keyboard processing.
    """
    def handler(event=None):
        if command is not None:
            command()
        elif next_widget is not None:
            next_widget.focus_set()
            try:
                next_widget.selection_range(0, tk.END)
            except Exception:
                pass
        return "break"

    widget.bind("<Return>", handler, add="+")
    widget.bind("<KP_Enter>", handler, add="+")
    widget.bind("<KeyPress-Return>", handler, add="+")
    widget.bind("<KeyPress-KP_Enter>", handler, add="+")


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return sqlite3.connect(DB_NAME)


def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT
        )
    """)

    # Add user_id to an existing expenses table if needed.
    cursor.execute("PRAGMA table_info(expenses)")
    expense_columns = [row[1] for row in cursor.fetchall()]

    if "user_id" not in expense_columns:
        cursor.execute("ALTER TABLE expenses ADD COLUMN user_id INTEGER")

    # Migrate an older single-user budget table.
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='budget'
    """)
    budget_exists = cursor.fetchone() is not None

    if budget_exists:
        cursor.execute("PRAGMA table_info(budget)")
        budget_columns = [row[1] for row in cursor.fetchall()]

        if "user_id" not in budget_columns:
            old_amount = 0

            try:
                cursor.execute("SELECT amount FROM budget LIMIT 1")
                row = cursor.fetchone()
                if row:
                    old_amount = float(row[0])
            except sqlite3.Error:
                pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS legacy_settings (
                    id INTEGER PRIMARY KEY,
                    old_budget REAL DEFAULT 0
                )
            """)

            cursor.execute(
                "INSERT OR REPLACE INTO legacy_settings(id, old_budget) VALUES(1, ?)",
                (old_amount,)
            )

            cursor.execute("ALTER TABLE budget RENAME TO budget_legacy")

            cursor.execute("""
                CREATE TABLE budget (
                    user_id INTEGER PRIMARY KEY,
                    amount REAL DEFAULT 0
                )
            """)
    else:
        cursor.execute("""
            CREATE TABLE budget (
                user_id INTEGER PRIMARY KEY,
                amount REAL DEFAULT 0
            )
        """)

    # Recurring expenses table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recurring_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            frequency TEXT NOT NULL,
            next_date TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# PASSWORD SECURITY
# ============================================================

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return password_hash, salt


def verify_password(password, stored_hash, salt):
    password_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(password_hash, stored_hash)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def clear_window():
    for widget in root.winfo_children():
        widget.destroy()


def set_status(message, color=MUTED):
    if status_label and status_label.winfo_exists():
        status_label.config(text=message, foreground=color)


def format_currency(value):
    return f"₹{value:,.2f}"


def validate_date(date_text):
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ============================================================
# REGISTRATION
# ============================================================

def register_user():
    username = reg_username_entry.get().strip()
    password = reg_password_entry.get()
    confirm_password = reg_confirm_entry.get()

    if len(username) < 3:
        messagebox.showwarning(
            "Invalid Username",
            "Username must contain at least 3 characters."
        )
        return

    if len(password) < 6:
        messagebox.showwarning(
            "Invalid Password",
            "Password must contain at least 6 characters."
        )
        return

    if password != confirm_password:
        messagebox.showerror(
            "Password Error",
            "Passwords do not match."
        )
        return

    password_hash, salt = hash_password(password)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO users(username, password_hash, salt)
            VALUES(?, ?, ?)
        """, (username, password_hash, salt))

        new_user_id = cursor.lastrowid

        # Transfer old single-user records to the first registered user.
        cursor.execute("""
            SELECT COUNT(*) FROM users
        """)
        user_count = cursor.fetchone()[0]

        if user_count == 1:
            cursor.execute("""
                UPDATE expenses
                SET user_id = ?
                WHERE user_id IS NULL
            """, (new_user_id,))

            try:
                cursor.execute("""
                    SELECT old_budget FROM legacy_settings
                    WHERE id = 1
                """)
                legacy_budget = cursor.fetchone()

                if legacy_budget and float(legacy_budget[0]) > 0:
                    cursor.execute("""
                        INSERT OR REPLACE INTO budget(user_id, amount)
                        VALUES(?, ?)
                    """, (new_user_id, float(legacy_budget[0])))
            except sqlite3.Error:
                pass

        conn.commit()

        messagebox.showinfo(
            "Registration Successful",
            "Account created successfully.\n\nYou can now log in."
        )

        register_window.destroy()

    except sqlite3.IntegrityError:
        messagebox.showerror(
            "Username Exists",
            "That username is already registered."
        )

    finally:
        conn.close()


def toggle_register_password():
    if show_reg_password_var.get():
        reg_password_entry.config(show="")
    else:
        reg_password_entry.config(show="*")


def toggle_confirm_password():
    if show_confirm_password_var.get():
        reg_confirm_entry.config(show="")
    else:
        reg_confirm_entry.config(show="*")


def show_register():
    global register_window
    global reg_username_entry
    global reg_password_entry
    global reg_confirm_entry
    global show_reg_password_var
    global show_confirm_password_var

    register_window = tk.Toplevel(root)
    register_window.title("Create Account")
    register_window.geometry("430x560")
    register_window.resizable(False, False)
    register_window.configure(bg=BG)
    register_window.transient(root)
    register_window.grab_set()

    container = tk.Frame(
        register_window,
        bg=CARD,
        highlightbackground=BORDER,
        highlightthickness=1
    )
    container.pack(fill="both", expand=True, padx=25, pady=25)

    tk.Label(
        container,
        text="Create Account",
        font=("Segoe UI", 24, "bold"),
        bg=CARD,
        fg=DARK
    ).pack(pady=(30, 5))

    tk.Label(
        container,
        text="Start managing your expenses securely",
        font=("Segoe UI", 10),
        bg=CARD,
        fg=MUTED
    ).pack(pady=(0, 25))

    tk.Label(
        container,
        text="Username",
        font=("Segoe UI", 10, "bold"),
        bg=CARD,
        fg=TEXT
    ).pack(anchor="w", padx=35)

    reg_username_entry = tk.Entry(
        container,
        font=("Segoe UI", 11),
        relief="solid",
        bd=1
    )
    reg_username_entry.pack(fill="x", padx=35, pady=(6, 18), ipady=8)

    tk.Label(
        container,
        text="Password",
        font=("Segoe UI", 10, "bold"),
        bg=CARD,
        fg=TEXT
    ).pack(anchor="w", padx=35)

    reg_password_entry = tk.Entry(
        container,
        font=("Segoe UI", 11),
        show="*",
        relief="solid",
        bd=1
    )
    reg_password_entry.pack(fill="x", padx=35, pady=(6, 6), ipady=8)

    show_reg_password_var = tk.BooleanVar(value=False)

    tk.Checkbutton(
        container,
        text="Show Password",
        variable=show_reg_password_var,
        command=toggle_register_password,
        bg=CARD,
        fg=MUTED,
        activebackground=CARD,
        font=("Segoe UI", 9)
    ).pack(anchor="w", padx=32, pady=(0, 14))

    tk.Label(
        container,
        text="Confirm Password",
        font=("Segoe UI", 10, "bold"),
        bg=CARD,
        fg=TEXT
    ).pack(anchor="w", padx=35)

    reg_confirm_entry = tk.Entry(
        container,
        font=("Segoe UI", 11),
        show="*",
        relief="solid",
        bd=1
    )
    reg_confirm_entry.pack(fill="x", padx=35, pady=(6, 6), ipady=8)

    # Enter / keypad Enter navigation
    enter_next(reg_username_entry, reg_password_entry)
    enter_next(reg_password_entry, reg_confirm_entry)
    enter_next(reg_confirm_entry, command=register_user)

    show_confirm_password_var = tk.BooleanVar(value=False)

    tk.Checkbutton(
        container,
        text="Show Confirm Password",
        variable=show_confirm_password_var,
        command=toggle_confirm_password,
        bg=CARD,
        fg=MUTED,
        activebackground=CARD,
        font=("Segoe UI", 9)
    ).pack(anchor="w", padx=32, pady=(0, 22))

    tk.Button(
        container,
        text="CREATE ACCOUNT",
        command=register_user,
        bg=BLUE,
        fg="white",
        activebackground=BLUE_DARK,
        activeforeground="white",
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0
    ).pack(fill="x", padx=35, ipady=10)


# ============================================================
# LOGIN
# ============================================================

def toggle_login_password():
    if show_login_password_var.get():
        password_entry.config(show="")
    else:
        password_entry.config(show="*")


def login_user(event=None):
    global current_user_id
    global current_username

    username = username_entry.get().strip()
    password = password_entry.get()

    if not username or not password:
        messagebox.showwarning(
            "Login Required",
            "Please enter both username and password."
        )
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, username, password_hash, salt
        FROM users
        WHERE username = ?
    """, (username,))

    user = cursor.fetchone()
    conn.close()

    if user and verify_password(password, user[2], user[3]):
        current_user_id = user[0]
        current_username = user[1]
        show_dashboard()
    else:
        messagebox.showerror(
            "Login Failed",
            "Invalid username or password."
        )


def show_login():
    global login_frame
    global username_entry
    global password_entry
    global show_login_password_var

    clear_window()

    process_recurring_expenses()
    root.configure(bg=BG)

    outer = tk.Frame(root, bg=BG)
    outer.pack(fill="both", expand=True)

    card = tk.Frame(
        outer,
        bg=CARD,
        highlightbackground=BORDER,
        highlightthickness=1
    )
    card.place(relx=0.5, rely=0.5, anchor="center", width=460, height=590)

    tk.Label(
        card,
        text="EXPENSE TRACKER",
        font=("Segoe UI", 25, "bold"),
        bg=CARD,
        fg=DARK
    ).pack(pady=(55, 6))

    tk.Label(
        card,
        text="Smart • Simple • Secure",
        font=("Segoe UI", 11),
        bg=CARD,
        fg=MUTED
    ).pack(pady=(0, 40))

    tk.Label(
        card,
        text="Username",
        font=("Segoe UI", 10, "bold"),
        bg=CARD,
        fg=TEXT
    ).pack(anchor="w", padx=50)

    username_entry = tk.Entry(
        card,
        font=("Segoe UI", 11),
        relief="solid",
        bd=1
    )
    username_entry.pack(fill="x", padx=50, pady=(7, 20), ipady=9)

    tk.Label(
        card,
        text="Password",
        font=("Segoe UI", 10, "bold"),
        bg=CARD,
        fg=TEXT
    ).pack(anchor="w", padx=50)

    password_entry = tk.Entry(
        card,
        font=("Segoe UI", 11),
        show="*",
        relief="solid",
        bd=1
    )
    password_entry.pack(fill="x", padx=50, pady=(7, 7), ipady=9)

    # Enter / keypad Enter navigation
    enter_next(username_entry, password_entry)
    enter_next(password_entry, command=login_user)

    show_login_password_var = tk.BooleanVar(value=False)

    tk.Checkbutton(
        card,
        text="Show Password",
        variable=show_login_password_var,
        command=toggle_login_password,
        bg=CARD,
        fg=MUTED,
        activebackground=CARD,
        font=("Segoe UI", 9)
    ).pack(anchor="w", padx=47, pady=(0, 25))

    tk.Button(
        card,
        text="LOGIN",
        command=login_user,
        bg=BLUE,
        fg="white",
        activebackground=BLUE_DARK,
        activeforeground="white",
        font=("Segoe UI", 11, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0
    ).pack(fill="x", padx=50, ipady=11)

    tk.Button(
        card,
        text="Create New Account",
        command=show_register,
        bg=CARD,
        fg=BLUE,
        activebackground=CARD,
        activeforeground=BLUE_DARK,
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0
    ).pack(pady=22)

    tk.Label(
        card,
        text="Your passwords are securely hashed before storage.",
        font=("Segoe UI", 8),
        bg=CARD,
        fg=MUTED
    ).pack(side="bottom", pady=25)

    username_entry.focus()


# ============================================================
# DASHBOARD
# ============================================================

def create_stat_card(parent, title, key, accent):
    frame = tk.Frame(
        parent,
        bg=CARD,
        highlightbackground=BORDER,
        highlightthickness=1
    )

    frame.grid_propagate(False)

    accent_bar = tk.Frame(frame, bg=accent, width=5)
    accent_bar.pack(side="left", fill="y")

    content = tk.Frame(frame, bg=CARD)
    content.pack(fill="both", expand=True, padx=14, pady=11)

    tk.Label(
        content,
        text=title,
        font=("Segoe UI", 9, "bold"),
        bg=CARD,
        fg=MUTED
    ).pack(anchor="w")

    value_label = tk.Label(
        content,
        text="₹0.00",
        font=("Segoe UI", 18, "bold"),
        bg=CARD,
        fg=DARK
    )
    value_label.pack(anchor="w", pady=(5, 0))

    card_values[key] = value_label

    return frame


def build_dashboard():
    global dashboard_frame
    global user_label
    global status_label
    global tree
    global amount_var
    global category_var
    global date_var
    global description_var
    global search_var
    global filter_category_var
    global budget_var
    global amount_entry
    global category_combo
    global date_entry
    global description_entry
    global budget_entry
    global search_entry
    global filter_combo

    clear_window()

    root.configure(bg=BG)

    # ---------------- HEADER ----------------
    header = tk.Frame(root, bg=DARK, height=76)
    header.pack(fill="x")
    header.pack_propagate(False)

    title_area = tk.Frame(header, bg=DARK)
    title_area.pack(side="left", padx=25)

    tk.Label(
        title_area,
        text="Expense Tracker",
        font=("Segoe UI", 22, "bold"),
        bg=DARK,
        fg="white"
    ).pack(anchor="w", pady=(10, 0))

    tk.Label(
        title_area,
        text="Personal finance dashboard",
        font=("Segoe UI", 9),
        bg=DARK,
        fg="#AAB6C8"
    ).pack(anchor="w")

    right_header = tk.Frame(header, bg=DARK)
    right_header.pack(side="right", padx=22)

    user_label = tk.Label(
        right_header,
        text=f"Logged in as: {current_username}",
        font=("Segoe UI", 10, "bold"),
        bg=DARK,
        fg="white"
    )
    user_label.pack(side="left", padx=(0, 18))

    tk.Button(
        right_header,
        text="Logout",
        command=logout,
        bg="#334155",
        fg="white",
        activebackground="#475569",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=15,
        pady=7
    ).pack(side="left")

    # ---------------- MAIN AREA ----------------
    dashboard_frame = tk.Frame(root, bg=BG)
    dashboard_frame.pack(fill="both", expand=True, padx=22, pady=18)

    # Statistics heading
    tk.Label(
        dashboard_frame,
        text="Overview",
        font=("Segoe UI", 17, "bold"),
        bg=BG,
        fg=DARK
    ).pack(anchor="w")

    tk.Label(
        dashboard_frame,
        text="A quick view of your current spending",
        font=("Segoe UI", 9),
        bg=BG,
        fg=MUTED
    ).pack(anchor="w", pady=(0, 12))

    cards_frame = tk.Frame(dashboard_frame, bg=BG)
    cards_frame.pack(fill="x")

    card_titles = [
        ("TOTAL EXPENSES", "total", BLUE),
        ("NUMBER OF EXPENSES", "count", PURPLE),
        ("AVERAGE EXPENSE", "average", GREEN),
        ("HIGHEST EXPENSE", "highest", RED),
        ("THIS MONTH", "month", ORANGE),
        ("MONTHLY BUDGET", "budget", BLUE),
        ("REMAINING BUDGET", "remaining", GREEN),
        ("BUDGET USED", "used", RED)
    ]

    for col in range(4):
        cards_frame.columnconfigure(col, weight=1)

    for index, (title, key, accent) in enumerate(card_titles):
        card = create_stat_card(
            cards_frame,
            title,
            key,
            accent
        )
        card.grid(
            row=index // 4,
            column=index % 4,
            sticky="nsew",
            padx=5,
            pady=5,
            ipady=2
        )

    # ---------------- BUDGET ----------------
    budget_section = tk.Frame(
        dashboard_frame,
        bg=CARD,
        highlightbackground=BORDER,
        highlightthickness=1
    )
    budget_section.pack(fill="x", pady=(14, 12))

    budget_top = tk.Frame(budget_section, bg=CARD)
    budget_top.pack(fill="x", padx=16, pady=(12, 5))

    tk.Label(
        budget_top,
        text="Monthly Budget",
        font=("Segoe UI", 11, "bold"),
        bg=CARD,
        fg=DARK
    ).pack(side="left")

    budget_var = tk.StringVar(value="0")

    budget_entry = tk.Entry(
        budget_top,
        textvariable=budget_var,
        font=("Segoe UI", 10),
        width=15,
        relief="solid",
        bd=1
    )
    budget_entry.pack(side="right", padx=(8, 0), ipady=4)
    enter_next(budget_entry, command=set_budget)

    tk.Button(
        budget_top,
        text="Set Budget",
        command=set_budget,
        bg=BLUE,
        fg="white",
        activebackground=BLUE_DARK,
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=14,
        pady=6
    ).pack(side="right")

    budget_progress = ttk.Progressbar(
        budget_section,
        orient="horizontal",
        mode="determinate"
    )
    budget_progress.pack(
        fill="x",
        padx=16,
        pady=(5, 5)
    )

    budget_hint = tk.Label(
        budget_section,
        text="",
        font=("Segoe UI", 8),
        bg=CARD,
        fg=MUTED
    )
    budget_hint.pack(anchor="w", padx=16, pady=(0, 10))

    # ---------------- EXPENSE ENTRY ----------------
    form_section = tk.Frame(
        dashboard_frame,
        bg=CARD,
        highlightbackground=BORDER,
        highlightthickness=1
    )
    form_section.pack(fill="x", pady=(0, 12))

    tk.Label(
        form_section,
        text="Add / Update Expense",
        font=("Segoe UI", 12, "bold"),
        bg=CARD,
        fg=DARK
    ).grid(row=0, column=0, columnspan=8, sticky="w", padx=16, pady=(13, 8))

    amount_var = tk.StringVar()
    category_var = tk.StringVar(value="Food")
    date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
    description_var = tk.StringVar()

    labels = [
        ("Amount", 0),
        ("Category", 2),
        ("Date (YYYY-MM-DD)", 4),
        ("Description", 6)
    ]

    for text, col in labels:
        tk.Label(
            form_section,
            text=text,
            font=("Segoe UI", 9, "bold"),
            bg=CARD,
            fg=TEXT
        ).grid(row=1, column=col, sticky="w", padx=(16, 5))

    amount_entry = tk.Entry(
        form_section,
        textvariable=amount_var,
        font=("Segoe UI", 10),
        relief="solid",
        bd=1
    )
    amount_entry.grid(
        row=2, column=0, columnspan=2,
        sticky="ew", padx=(16, 7), pady=(4, 14), ipady=6
    )

    category_combo = ttk.Combobox(
        form_section,
        textvariable=category_var,
        values=[
            "Food",
            "Transport",
            "Shopping",
            "Bills",
            "Education",
            "Health",
            "Entertainment",
            "Travel",
            "Other"
        ],
        state="readonly",
        font=("Segoe UI", 10)
    )
    category_combo.grid(
        row=2, column=2, columnspan=2,
        sticky="ew", padx=7, pady=(4, 14), ipady=4
    )

    date_entry = tk.Entry(
        form_section,
        textvariable=date_var,
        font=("Segoe UI", 10),
        relief="solid",
        bd=1
    )
    date_entry.grid(
        row=2, column=4, columnspan=2,
        sticky="ew", padx=7, pady=(4, 14), ipady=6
    )

    description_entry = tk.Entry(
        form_section,
        textvariable=description_var,
        font=("Segoe UI", 10),
        relief="solid",
        bd=1
    )
    description_entry.grid(
        row=2, column=6,
        sticky="ew", padx=7, pady=(4, 14), ipady=6
    )

    # Enter / keypad Enter navigation
    enter_next(amount_entry, category_combo)
    enter_next(category_combo, date_entry)
    enter_next(date_entry, description_entry)
    enter_next(description_entry, command=add_expense)

    for col in [1, 3, 5, 7]:
        form_section.columnconfigure(col, weight=1)

    form_section.columnconfigure(6, weight=2)

    button_area = tk.Frame(form_section, bg=CARD)
    button_area.grid(
        row=2, column=7,
        sticky="e",
        padx=(5, 16),
        pady=(4, 14)
    )

    tk.Button(
        button_area,
        text="ADD",
        command=add_expense,
        bg=GREEN,
        fg="white",
        activebackground="#15803D",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="left", padx=2)

    tk.Button(
        button_area,
        text="UPDATE",
        command=update_expense,
        bg=BLUE,
        fg="white",
        activebackground=BLUE_DARK,
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="left", padx=2)

    tk.Button(
        button_area,
        text="CLEAR",
        command=clear_form,
        bg="#64748B",
        fg="white",
        activebackground="#475569",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="left", padx=2)

    # ---------------- SEARCH / ACTIONS ----------------
    action_section = tk.Frame(dashboard_frame, bg=BG)
    action_section.pack(fill="x", pady=(0, 8))

    search_var = tk.StringVar()
    filter_category_var = tk.StringVar(value="All Categories")

    tk.Label(
        action_section,
        text="Search:",
        font=("Segoe UI", 9, "bold"),
        bg=BG,
        fg=TEXT
    ).pack(side="left")

    search_entry = tk.Entry(
        action_section,
        textvariable=search_var,
        font=("Segoe UI", 10),
        width=25,
        relief="solid",
        bd=1
    )
    search_entry.pack(side="left", padx=(7, 8), ipady=5)
    search_entry.bind("<KeyRelease>", lambda event: load_expenses())

    filter_combo = ttk.Combobox(
        action_section,
        textvariable=filter_category_var,
        values=[
            "All Categories",
            "Food",
            "Transport",
            "Shopping",
            "Bills",
            "Education",
            "Health",
            "Entertainment",
            "Travel",
            "Other"
        ],
        state="readonly",
        width=18,
        font=("Segoe UI", 9)
    )
    filter_combo.pack(side="left", padx=(0, 10))
    filter_combo.bind("<<ComboboxSelected>>", lambda event: load_expenses())

    enter_next(search_entry, filter_combo)
    enter_next(filter_combo, command=load_expenses)

    tk.Button(
        action_section,
        text="Recurring Expenses",
        command=show_recurring_expenses,
        bg=ORANGE,
        fg="white",
        activebackground="#C2410C",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="right", padx=3)

    tk.Button(
        action_section,
        text="Advanced Analytics",
        command=show_advanced_analytics,
        bg=BLUE_DARK,
        fg="white",
        activebackground=BLUE,
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="right", padx=3)

    tk.Button(
        action_section,
        text="Analytics & Charts",
        command=show_analytics,
        bg=PURPLE,
        fg="white",
        activebackground="#6D28D9",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="right", padx=3)

    tk.Button(
        action_section,
        text="Export CSV",
        command=export_csv,
        bg="#475569",
        fg="white",
        activebackground="#334155",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="right", padx=3)

    tk.Button(
        action_section,
        text="PDF Report",
        command=export_pdf,
        bg="#0F766E",
        fg="white",
        activebackground="#115E59",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="right", padx=3)

    tk.Button(
        action_section,
        text="Delete Selected",
        command=delete_expense,
        bg=RED,
        fg="white",
        activebackground="#B91C1C",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=13,
        pady=7
    ).pack(side="right", padx=3)

    # ---------------- TABLE ----------------
    table_section = tk.Frame(
        dashboard_frame,
        bg=CARD,
        highlightbackground=BORDER,
        highlightthickness=1
    )
    table_section.pack(fill="both", expand=True)

    tk.Label(
        table_section,
        text="Expense History",
        font=("Segoe UI", 12, "bold"),
        bg=CARD,
        fg=DARK
    ).pack(anchor="w", padx=15, pady=(12, 7))

    table_container = tk.Frame(table_section, bg=CARD)
    table_container.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    columns = ("ID", "Amount", "Category", "Date", "Description")

    tree = ttk.Treeview(
        table_container,
        columns=columns,
        show="headings",
        selectmode="browse"
    )

    headings = {
        "ID": "ID",
        "Amount": "Amount",
        "Category": "Category",
        "Date": "Date",
        "Description": "Description"
    }

    widths = {
        "ID": 55,
        "Amount": 120,
        "Category": 130,
        "Date": 120,
        "Description": 300
    }

    for col in columns:
        tree.heading(col, text=headings[col])
        tree.column(
            col,
            width=widths[col],
            anchor="center" if col != "Description" else "w"
        )

    scrollbar = ttk.Scrollbar(
        table_container,
        orient="vertical",
        command=tree.yview
    )
    tree.configure(yscrollcommand=scrollbar.set)

    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    tree.bind("<<TreeviewSelect>>", select_expense)

    # ---------------- STATUS ----------------
    status_label = tk.Label(
        dashboard_frame,
        text="Ready",
        font=("Segoe UI", 8),
        bg=BG,
        fg=MUTED
    )
    status_label.pack(anchor="w", pady=(5, 0))

    configure_styles()
    load_expenses()


def configure_styles():
    style = ttk.Style()

    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "Treeview",
        background=CARD,
        foreground=TEXT,
        rowheight=31,
        fieldbackground=CARD,
        borderwidth=0,
        font=("Segoe UI", 9)
    )

    style.configure(
        "Treeview.Heading",
        background="#E8EEF7",
        foreground=DARK,
        font=("Segoe UI", 9, "bold"),
        relief="flat"
    )

    style.map(
        "Treeview",
        background=[("selected", "#DBEAFE")],
        foreground=[("selected", DARK)]
    )

    style.configure(
        "TCombobox",
        padding=5
    )

    style.configure(
        "Horizontal.TProgressbar",
        thickness=10
    )


def show_dashboard():
    build_dashboard()


# ============================================================
# EXPENSE CRUD
# ============================================================

def add_expense():
    try:
        amount = float(amount_var.get().strip())
    except ValueError:
        messagebox.showerror(
            "Invalid Amount",
            "Please enter a valid numeric amount."
        )
        return

    if amount <= 0:
        messagebox.showerror(
            "Invalid Amount",
            "Amount must be greater than zero."
        )
        return

    category = category_var.get().strip()
    date_text = date_var.get().strip()
    description = description_var.get().strip()

    if not category:
        messagebox.showwarning(
            "Missing Category",
            "Please select a category."
        )
        return

    if not validate_date(date_text):
        messagebox.showerror(
            "Invalid Date",
            "Use the date format YYYY-MM-DD."
        )
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO expenses(amount, category, date, description, user_id)
        VALUES(?, ?, ?, ?, ?)
    """, (
        amount,
        category,
        date_text,
        description,
        current_user_id
    ))

    conn.commit()
    conn.close()

    clear_form()
    load_expenses()

    set_status(
        "Expense added successfully.",
        GREEN
    )


def update_expense():
    selected = tree.selection()

    if not selected:
        messagebox.showwarning(
            "No Selection",
            "Please select an expense from the table."
        )
        return

    item = tree.item(selected[0])
    expense_id = item["values"][0]

    try:
        amount = float(amount_var.get().strip())
    except ValueError:
        messagebox.showerror(
            "Invalid Amount",
            "Please enter a valid numeric amount."
        )
        return

    if amount <= 0:
        messagebox.showerror(
            "Invalid Amount",
            "Amount must be greater than zero."
        )
        return

    category = category_var.get().strip()
    date_text = date_var.get().strip()
    description = description_var.get().strip()

    if not validate_date(date_text):
        messagebox.showerror(
            "Invalid Date",
            "Use the date format YYYY-MM-DD."
        )
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE expenses
        SET amount = ?, category = ?, date = ?, description = ?
        WHERE id = ? AND user_id = ?
    """, (
        amount,
        category,
        date_text,
        description,
        expense_id,
        current_user_id
    ))

    conn.commit()
    conn.close()

    clear_form()
    load_expenses()

    set_status(
        "Expense updated successfully.",
        BLUE
    )


def delete_expense():
    selected = tree.selection()

    if not selected:
        messagebox.showwarning(
            "No Selection",
            "Please select an expense to delete."
        )
        return

    item = tree.item(selected[0])
    expense_id = item["values"][0]

    confirm = messagebox.askyesno(
        "Confirm Delete",
        "Are you sure you want to delete this expense?"
    )

    if not confirm:
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM expenses
        WHERE id = ? AND user_id = ?
    """, (expense_id, current_user_id))

    conn.commit()
    conn.close()

    clear_form()
    load_expenses()

    set_status(
        "Expense deleted successfully.",
        RED
    )


def select_expense(event=None):
    selected = tree.selection()

    if not selected:
        return

    item = tree.item(selected[0])
    values = item["values"]

    if not values:
        return

    amount_var.set(str(values[1]).replace("₹", "").replace(",", ""))
    category_var.set(values[2])
    date_var.set(values[3])
    description_var.set(values[4])


def clear_form():
    if amount_var:
        amount_var.set("")

    if category_var:
        category_var.set("Food")

    if date_var:
        date_var.set(datetime.now().strftime("%Y-%m-%d"))

    if description_var:
        description_var.set("")

    if tree:
        tree.selection_remove(tree.selection())


# ============================================================
# LOAD EXPENSES + DASHBOARD STATISTICS
# ============================================================

def load_expenses():
    if not tree:
        return

    for item in tree.get_children():
        tree.delete(item)

    search_text = search_var.get().strip() if search_var else ""
    filter_category = (
        filter_category_var.get()
        if filter_category_var
        else "All Categories"
    )

    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT id, amount, category, date, description
        FROM expenses
        WHERE user_id = ?
    """

    params = [current_user_id]

    if search_text:
        query += """
            AND (
                category LIKE ?
                OR description LIKE ?
                OR date LIKE ?
            )
        """
        like_text = f"%{search_text}%"
        params.extend([
            like_text,
            like_text,
            like_text
        ])

    if filter_category != "All Categories":
        query += " AND category = ?"
        params.append(filter_category)

    query += " ORDER BY date DESC, id DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    conn.close()

    for row in rows:
        tree.insert(
            "",
            "end",
            values=(
                row[0],
                format_currency(float(row[1])),
                row[2],
                row[3],
                row[4] or ""
            )
        )

    update_dashboard()


def update_dashboard():
    conn = get_connection()
    cursor = conn.cursor()

    # Total and basic statistics
    cursor.execute("""
        SELECT
            COALESCE(SUM(amount), 0),
            COUNT(*),
            COALESCE(AVG(amount), 0),
            COALESCE(MAX(amount), 0)
        FROM expenses
        WHERE user_id = ?
    """, (current_user_id,))

    total, count, average, highest = cursor.fetchone()

    # Current month
    current_month = datetime.now().strftime("%Y-%m")

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE user_id = ?
        AND substr(date, 1, 7) = ?
    """, (current_user_id, current_month))

    this_month = cursor.fetchone()[0]

    # Budget
    cursor.execute("""
        SELECT amount
        FROM budget
        WHERE user_id = ?
    """, (current_user_id,))

    budget_row = cursor.fetchone()
    budget = float(budget_row[0]) if budget_row else 0

    conn.close()

    remaining = max(budget - this_month, 0)

    if budget > 0:
        used_percent = (this_month / budget) * 100
    else:
        used_percent = 0

    card_values["total"].config(
        text=format_currency(total)
    )

    card_values["count"].config(
        text=str(count)
    )

    card_values["average"].config(
        text=format_currency(average)
    )

    card_values["highest"].config(
        text=format_currency(highest)
    )

    card_values["month"].config(
        text=format_currency(this_month)
    )

    card_values["budget"].config(
        text=format_currency(budget)
    )

    card_values["remaining"].config(
        text=format_currency(remaining)
    )

    if budget > 0:
        display_percent = min(used_percent, 100)
        card_values["used"].config(
            text=f"{used_percent:.1f}%"
        )
    else:
        display_percent = 0
        card_values["used"].config(
            text="0%"
        )

    # Find the progress bar and hint in the dashboard.
    if dashboard_frame:
        progressbars = [
            widget for widget in dashboard_frame.winfo_children()
            if isinstance(widget, tk.Frame)
        ]

    # Locate Progressbar recursively.
    def find_progressbar(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Progressbar):
                return child
            result = find_progressbar(child)
            if result:
                return result
        return None

    def find_budget_hint(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                if child.cget("font") == ("Segoe UI", 8):
                    return child
            result = find_budget_hint(child)
            if result:
                return result
        return None

    progress = find_progressbar(dashboard_frame)
    hint = find_budget_hint(dashboard_frame)

    if progress:
        progress["value"] = display_percent

    if hint:
        if budget <= 0:
            hint.config(
                text="Set a monthly budget to track your spending limit.",
                fg=MUTED
            )
        elif used_percent >= 100:
            hint.config(
                text=f"Over budget by {format_currency(this_month - budget)}",
                fg=RED
            )
        elif used_percent >= 80:
            hint.config(
                text=f"Budget warning: {used_percent:.1f}% of your budget has been used.",
                fg=ORANGE
            )
        else:
            hint.config(
                text=f"{format_currency(remaining)} remaining from your monthly budget.",
                fg=GREEN
            )


# ============================================================
# BUDGET
# ============================================================

def set_budget():
    try:
        budget_amount = float(budget_var.get().strip())
    except ValueError:
        messagebox.showerror(
            "Invalid Budget",
            "Please enter a valid numeric budget."
        )
        return

    if budget_amount < 0:
        messagebox.showerror(
            "Invalid Budget",
            "Budget cannot be negative."
        )
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO budget(user_id, amount)
        VALUES(?, ?)
    """, (current_user_id, budget_amount))

    conn.commit()
    conn.close()

    update_dashboard()

    if budget_amount > 0:
        set_status(
            "Monthly budget updated successfully.",
            GREEN
        )
    else:
        set_status(
            "Monthly budget reset.",
            MUTED
        )


# ============================================================
# RECURRING EXPENSES
# ============================================================

def add_months(date_obj, months):
    """Return a date moved forward by a number of calendar months."""
    month_index = date_obj.month - 1 + months
    year = date_obj.year + month_index // 12
    month = month_index % 12 + 1
    day = min(date_obj.day, calendar.monthrange(year, month)[1])
    return date_obj.replace(year=year, month=month, day=day)


def next_recurring_date(date_obj, frequency):
    if frequency == "Weekly":
        return date_obj + timedelta(days=7)
    if frequency == "Monthly":
        return add_months(date_obj, 1)
    if frequency == "Yearly":
        return add_months(date_obj, 12)
    return add_months(date_obj, 1)


def process_recurring_expenses():
    """Create due recurring expenses and advance their next dates."""
    if current_user_id is None:
        return 0

    today = datetime.now().date()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, amount, category, description, frequency, next_date
        FROM recurring_expenses
        WHERE user_id = ? AND active = 1 AND next_date <= ?
        ORDER BY next_date
    """, (current_user_id, today.isoformat()))
    rows = cursor.fetchall()

    created = 0
    for rid, amount, category, description, frequency, next_date_text in rows:
        try:
            due_date = datetime.strptime(next_date_text, "%Y-%m-%d").date()
        except ValueError:
            continue

        while due_date <= today:
            cursor.execute("""
                INSERT INTO expenses(amount, category, date, description, user_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                amount,
                category,
                due_date.isoformat(),
                description,
                current_user_id
            ))
            created += 1
            due_date = next_recurring_date(due_date, frequency)

        cursor.execute("""
            UPDATE recurring_expenses
            SET next_date = ?
            WHERE id = ? AND user_id = ?
        """, (due_date.isoformat(), rid, current_user_id))

    conn.commit()
    conn.close()
    return created


def show_recurring_expenses():
    process_recurring_expenses()

    window = tk.Toplevel(root)
    window.title("Recurring Expenses")
    window.geometry("1000x650")
    window.minsize(900, 580)
    window.configure(bg=BG)

    header = tk.Frame(window, bg=DARK, height=70)
    header.pack(fill="x")
    header.pack_propagate(False)

    tk.Label(
        header,
        text="Recurring Expenses",
        font=("Segoe UI", 21, "bold"),
        bg=DARK,
        fg="white"
    ).pack(side="left", padx=25, pady=18)

    tk.Label(
        window,
        text="Set regular expenses to be added automatically when they are due.",
        font=("Segoe UI", 9),
        bg=BG,
        fg=MUTED
    ).pack(anchor="w", padx=22, pady=(14, 8))

    form = tk.Frame(window, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    form.pack(fill="x", padx=22, pady=(0, 12))

    amount_v = tk.StringVar()
    category_v = tk.StringVar(value="Bills")
    desc_v = tk.StringVar()
    freq_v = tk.StringVar(value="Monthly")
    date_v = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))

    fields = tk.Frame(form, bg=CARD)
    fields.pack(fill="x", padx=14, pady=12)

    tk.Label(fields, text="Amount", font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).grid(row=0, column=0, sticky="w", padx=5)
    tk.Label(fields, text="Category", font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).grid(row=0, column=1, sticky="w", padx=5)
    tk.Label(fields, text="Description", font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).grid(row=0, column=2, sticky="w", padx=5)
    tk.Label(fields, text="Frequency", font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).grid(row=0, column=3, sticky="w", padx=5)
    tk.Label(fields, text="First Due Date", font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).grid(row=0, column=4, sticky="w", padx=5)

    amount_e = tk.Entry(fields, textvariable=amount_v, font=("Segoe UI", 10), relief="solid", bd=1)
    amount_e.grid(row=1, column=0, sticky="ew", padx=5, pady=(4, 4), ipady=5)
    cat_e = ttk.Combobox(fields, textvariable=category_v, values=["Food","Transport","Shopping","Bills","Education","Health","Entertainment","Travel","Other"], state="readonly", font=("Segoe UI", 9))
    cat_e.grid(row=1, column=1, sticky="ew", padx=5, pady=(4, 4), ipady=3)
    desc_e = tk.Entry(fields, textvariable=desc_v, font=("Segoe UI", 10), relief="solid", bd=1)
    desc_e.grid(row=1, column=2, sticky="ew", padx=5, pady=(4, 4), ipady=5)
    freq_e = ttk.Combobox(fields, textvariable=freq_v, values=["Weekly", "Monthly", "Yearly"], state="readonly", font=("Segoe UI", 9))
    freq_e.grid(row=1, column=3, sticky="ew", padx=5, pady=(4, 4), ipady=3)
    date_e = tk.Entry(fields, textvariable=date_v, font=("Segoe UI", 10), relief="solid", bd=1)
    date_e.grid(row=1, column=4, sticky="ew", padx=5, pady=(4, 4), ipady=5)

    for c in range(5):
        fields.columnconfigure(c, weight=1)

    def refresh():
        for item in recurring_tree.get_children():
            recurring_tree.delete(item)
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, amount, category, description, frequency, next_date,
                   CASE WHEN active = 1 THEN 'Active' ELSE 'Paused' END
            FROM recurring_expenses
            WHERE user_id = ?
            ORDER BY active DESC, next_date
        """, (current_user_id,))
        for row in cur.fetchall():
            recurring_tree.insert("", "end", values=row)
        conn.close()

    def add_recurring():
        try:
            amount = float(amount_v.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Amount", "Please enter a valid amount.", parent=window)
            return
        if amount <= 0:
            messagebox.showerror("Invalid Amount", "Amount must be greater than zero.", parent=window)
            return
        try:
            datetime.strptime(date_v.get().strip(), "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Invalid Date", "Use YYYY-MM-DD.", parent=window)
            return
        if not desc_v.get().strip():
            messagebox.showwarning("Missing Description", "Please enter a description.", parent=window)
            return

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recurring_expenses(user_id, amount, category, description, frequency, next_date, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (current_user_id, amount, category_v.get(), desc_v.get().strip(), freq_v.get(), date_v.get().strip()))
        conn.commit()
        conn.close()
        amount_v.set("")
        desc_v.set("")
        refresh()
        process_recurring_expenses()
        load_expenses()
        update_dashboard()
        set_status("Recurring expense added successfully.", GREEN)

    def toggle_selected():
        selected = recurring_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Select a recurring expense first.", parent=window)
            return
        rid = recurring_tree.item(selected[0])["values"][0]
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT active FROM recurring_expenses WHERE id = ? AND user_id = ?", (rid, current_user_id))
        row = cur.fetchone()
        if row is not None:
            cur.execute("UPDATE recurring_expenses SET active = ? WHERE id = ? AND user_id = ?", (0 if row[0] else 1, rid, current_user_id))
        conn.commit()
        conn.close()
        refresh()

    def delete_selected():
        selected = recurring_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Select a recurring expense first.", parent=window)
            return
        rid = recurring_tree.item(selected[0])["values"][0]
        if not messagebox.askyesno("Delete", "Delete this recurring expense?", parent=window):
            return
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM recurring_expenses WHERE id = ? AND user_id = ?", (rid, current_user_id))
        conn.commit()
        conn.close()
        refresh()

    buttons = tk.Frame(form, bg=CARD)
    buttons.pack(fill="x", padx=14, pady=(0, 12))
    tk.Button(buttons, text="ADD RECURRING", command=add_recurring, bg=GREEN, fg="white", activebackground="#15803D", font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=14, pady=7, cursor="hand2").pack(side="left", padx=4)
    tk.Button(buttons, text="PAUSE / RESUME", command=toggle_selected, bg=ORANGE, fg="white", activebackground="#C2410C", font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=14, pady=7, cursor="hand2").pack(side="left", padx=4)
    tk.Button(buttons, text="DELETE", command=delete_selected, bg=RED, fg="white", activebackground="#B91C1C", font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=14, pady=7, cursor="hand2").pack(side="left", padx=4)
    tk.Button(buttons, text="CLOSE", command=window.destroy, bg="#475569", fg="white", activebackground="#334155", font=("Segoe UI", 9, "bold"), relief="flat", bd=0, padx=14, pady=7, cursor="hand2").pack(side="right", padx=4)

    table_frame = tk.Frame(window, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    table_frame.pack(fill="both", expand=True, padx=22, pady=(0, 20))

    columns = ("ID", "Amount", "Category", "Description", "Frequency", "Next Due", "Status")
    recurring_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
    widths = {"ID":55, "Amount":95, "Category":110, "Description":240, "Frequency":100, "Next Due":105, "Status":90}
    for col in columns:
        recurring_tree.heading(col, text=col)
        recurring_tree.column(col, width=widths[col], anchor="center")
    recurring_tree.pack(fill="both", expand=True, padx=10, pady=10)

    enter_next(amount_e, cat_e)
    enter_next(cat_e, desc_e)
    enter_next(desc_e, freq_e)
    enter_next(freq_e, date_e)
    enter_next(date_e, command=add_recurring)
    refresh()


# ============================================================
# CSV EXPORT
# ============================================================

def export_csv():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, amount, category, date, description
        FROM expenses
        WHERE user_id = ?
        ORDER BY date DESC, id DESC
    """, (current_user_id,))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        messagebox.showinfo(
            "No Data",
            "There are no expenses to export."
        )
        return

    file_path = filedialog.asksaveasfilename(
        title="Save Expense Report",
        defaultextension=".csv",
        filetypes=[
            ("CSV files", "*.csv"),
            ("All files", "*.*")
        ]
    )

    if not file_path:
        return

    try:
        with open(
            file_path,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as file:
            writer = csv.writer(file)

            writer.writerow([
                "ID",
                "Amount",
                "Category",
                "Date",
                "Description"
            ])

            writer.writerows(rows)

        messagebox.showinfo(
            "Export Successful",
            f"Expense report saved successfully.\n\n{file_path}"
        )

        set_status(
            "CSV report exported successfully.",
            GREEN
        )

    except Exception as error:
        messagebox.showerror(
            "Export Error",
            f"Could not export the report.\n\n{error}"
        )



# ============================================================
# PDF EXPENSE REPORT
# ============================================================

def export_pdf():
    """Create a PDF report for the logged-in user's expenses."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT amount, category, date, description
        FROM expenses
        WHERE user_id = ?
        ORDER BY date DESC, id DESC
    """, (current_user_id,))
    rows = cursor.fetchall()

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0), COUNT(*), COALESCE(AVG(amount), 0),
               COALESCE(MAX(amount), 0)
        FROM expenses
        WHERE user_id = ?
    """, (current_user_id,))
    total, count, average, highest = cursor.fetchone()

    cursor.execute("""
        SELECT category, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    """, (current_user_id,))
    category_rows = cursor.fetchall()

    conn.close()

    if not rows:
        messagebox.showinfo(
            "No Data",
            "Add some expenses before creating a PDF report."
        )
        return

    file_path = filedialog.asksaveasfilename(
        title="Save PDF Expense Report",
        defaultextension=".pdf",
        filetypes=[
            ("PDF files", "*.pdf"),
            ("All files", "*.*")
        ],
        initialfile="Expense_Report.pdf"
    )

    if not file_path:
        return

    try:
        with PdfPages(file_path) as pdf:
            # Page 1: Summary
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.patch.set_facecolor("white")
            fig.text(0.08, 0.94, "EXPENSE TRACKER", fontsize=24, fontweight="bold")
            fig.text(0.08, 0.905, "Personal Expense Report", fontsize=13)
            fig.text(0.08, 0.875, f"User: {current_username}", fontsize=10)
            fig.text(0.08, 0.855,
                     f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     fontsize=10)

            summary = [
                ("Total Expenses", format_currency(float(total))),
                ("Number of Expenses", str(count)),
                ("Average Expense", format_currency(float(average))),
                ("Highest Expense", format_currency(float(highest))),
            ]

            y = 0.76
            for label, value in summary:
                fig.text(0.10, y, label, fontsize=12, fontweight="bold")
                fig.text(0.55, y, value, fontsize=12)
                y -= 0.07

            if category_rows:
                labels = [str(r[0]) for r in category_rows]
                values = [float(r[1]) for r in category_rows]
                ax = fig.add_axes([0.12, 0.12, 0.76, 0.38])
                ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
                ax.set_title("Spending by Category")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

            # Remaining pages: expense details, 25 rows per page
            page_size = 25
            for start in range(0, len(rows), page_size):
                page_rows = rows[start:start + page_size]

                fig = plt.figure(figsize=(11.69, 8.27))
                ax = fig.add_axes([0.04, 0.08, 0.92, 0.82])
                ax.axis("off")

                table_data = [["Amount", "Category", "Date", "Description"]]
                for amount, category, date_text, description in page_rows:
                    table_data.append([
                        format_currency(float(amount)),
                        str(category),
                        str(date_text),
                        str(description)[:55]
                    ])

                table = ax.table(
                    cellText=table_data,
                    colWidths=[0.15, 0.18, 0.16, 0.51],
                    loc="center",
                    cellLoc="left"
                )
                table.auto_set_font_size(False)
                table.set_fontsize(8)
                table.scale(1, 1.6)

                for col in range(4):
                    table[(0, col)].set_text_props(fontweight="bold")

                ax.set_title(
                    f"Expense Details — {start + 1} to "
                    f"{min(start + page_size, len(rows))}",
                    fontsize=15,
                    fontweight="bold",
                    pad=20
                )

                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)

        messagebox.showinfo(
            "PDF Created",
            f"PDF expense report created successfully.\n\n{file_path}"
        )
        set_status("PDF report created successfully.", GREEN)

    except Exception as error:
        messagebox.showerror(
            "PDF Error",
            f"Could not create the PDF report.\n\n{error}"
        )


# ============================================================
# ADVANCED ANALYTICS
# ============================================================

def show_advanced_analytics():
    """Show deeper spending analysis for the logged-in user."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT amount, category, date, description
        FROM expenses
        WHERE user_id = ?
        ORDER BY date ASC, id ASC
    """, (current_user_id,))
    rows = cursor.fetchall()

    cursor.execute("""
        SELECT category, SUM(amount), COUNT(*)
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    """, (current_user_id,))
    category_rows = cursor.fetchall()

    cursor.execute("""
        SELECT substr(date, 1, 7), SUM(amount), COUNT(*)
        FROM expenses
        WHERE user_id = ?
        GROUP BY substr(date, 1, 7)
        ORDER BY substr(date, 1, 7) DESC
        LIMIT 6
    """, (current_user_id,))
    month_rows = cursor.fetchall()

    cursor.execute("""
        SELECT date, SUM(amount), COUNT(*)
        FROM expenses
        WHERE user_id = ?
        GROUP BY date
        ORDER BY SUM(amount) DESC
        LIMIT 5
    """, (current_user_id,))
    top_days = cursor.fetchall()

    cursor.execute("""
        SELECT id, amount, category, date, description
        FROM expenses
        WHERE user_id = ?
        ORDER BY amount DESC
        LIMIT 5
    """, (current_user_id,))
    top_expenses = cursor.fetchall()

    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(amount), 0)
        FROM recurring_expenses
        WHERE user_id = ? AND active = 1
    """, (current_user_id,))
    recurring_count, recurring_total = cursor.fetchone()

    conn.close()

    if not rows:
        messagebox.showinfo("No Data", "Add some expenses before opening Advanced Analytics.")
        return

    amounts = [float(r[0]) for r in rows]
    total = sum(amounts)
    average = total / len(amounts)
    highest = max(amounts)
    lowest = min(amounts)

    try:
        dates = [datetime.strptime(r[2], "%Y-%m-%d").date() for r in rows]
        days_span = max((max(dates) - min(dates)).days + 1, 1)
        daily_average = total / days_span
    except Exception:
        daily_average = average

    top_category = category_rows[0][0] if category_rows else "N/A"
    top_category_amount = float(category_rows[0][1]) if category_rows else 0
    top_category_pct = (top_category_amount / total * 100) if total else 0

    # Month-on-month change using the two latest available months.
    mom_text = "Not enough monthly data"
    if len(month_rows) >= 2:
        latest_amount = float(month_rows[0][1])
        previous_amount = float(month_rows[1][1])
        if previous_amount == 0:
            mom_text = "New spending this month"
        else:
            change = (latest_amount - previous_amount) / previous_amount * 100
            direction = "increase" if change >= 0 else "decrease"
            mom_text = f"{abs(change):.1f}% {direction}"

    analytics = tk.Toplevel(root)
    analytics.title("Advanced Expense Analytics")
    analytics.geometry("1180x820")
    analytics.minsize(1000, 700)
    analytics.configure(bg=BG)

    header = tk.Frame(analytics, bg=DARK, height=70)
    header.pack(fill="x")
    header.pack_propagate(False)

    tk.Label(
        header,
        text="Advanced Expense Analytics",
        font=("Segoe UI", 21, "bold"),
        bg=DARK,
        fg="white"
    ).pack(side="left", padx=25, pady=18)

    tk.Button(
        header,
        text="Back to Dashboard",
        command=analytics.destroy,
        bg="#334155",
        fg="white",
        activebackground="#475569",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=14,
        pady=7
    ).pack(side="right", padx=22)

    content = tk.Frame(analytics, bg=BG)
    content.pack(fill="both", expand=True, padx=18, pady=15)

    stats = tk.Frame(content, bg=BG)
    stats.pack(fill="x", pady=(0, 12))

    stat_items = [
        ("TOTAL SPENDING", format_currency(total)),
        ("AVG. EXPENSE", format_currency(average)),
        ("HIGHEST EXPENSE", format_currency(highest)),
        ("DAILY AVG.", format_currency(daily_average)),
        ("TOP CATEGORY", top_category),
        ("MONTH CHANGE", mom_text),
    ]

    for i, (title, value) in enumerate(stat_items):
        box = tk.Frame(stats, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        box.grid(row=0, column=i, sticky="nsew", padx=3)
        stats.columnconfigure(i, weight=1)
        tk.Label(box, text=title, font=("Segoe UI", 7, "bold"), bg=CARD, fg=MUTED).pack(anchor="w", padx=9, pady=(9, 2))
        tk.Label(box, text=value, font=("Segoe UI", 11, "bold"), bg=CARD, fg=DARK, wraplength=145).pack(anchor="w", padx=9, pady=(0, 9))

    middle = tk.Frame(content, bg=BG)
    middle.pack(fill="both", expand=True)

    chart_box = tk.Frame(middle, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    chart_box.pack(side="left", fill="both", expand=True, padx=(0, 7))

    fig = plt.Figure(figsize=(7.4, 5.0), dpi=100)
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212)

    if category_rows:
        cats = [r[0] for r in category_rows]
        cat_amounts = [float(r[1]) for r in category_rows]
        ax1.barh(cats[::-1], cat_amounts[::-1])
        ax1.set_title("Spending by Category", fontsize=10, fontweight="bold")
        ax1.set_xlabel("Amount")

    if month_rows:
        months = [r[0] for r in reversed(month_rows)]
        month_amounts = [float(r[1]) for r in reversed(month_rows)]
        ax2.plot(months, month_amounts, marker="o")
        ax2.set_title("Last 6 Available Months", fontsize=10, fontweight="bold")
        ax2.set_ylabel("Amount")
        ax2.tick_params(axis="x", rotation=35)

    fig.tight_layout(pad=2)
    canvas = FigureCanvasTkAgg(fig, master=chart_box)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

    side = tk.Frame(middle, bg=BG, width=365)
    side.pack(side="right", fill="y")
    side.pack_propagate(False)

    # Category breakdown
    cat_box = tk.Frame(side, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    cat_box.pack(fill="x", pady=(0, 8))
    tk.Label(cat_box, text="CATEGORY BREAKDOWN", font=("Segoe UI", 10, "bold"), bg=CARD, fg=DARK).pack(anchor="w", padx=13, pady=(10, 6))
    for category, amount, count in category_rows[:8]:
        pct = float(amount) / total * 100 if total else 0
        tk.Label(
            cat_box,
            text=f"{category:<15} {format_currency(float(amount))}  ({pct:.1f}%)",
            font=("Consolas", 8), bg=CARD, fg=TEXT, anchor="w"
        ).pack(fill="x", padx=13, pady=1)
    tk.Label(cat_box, text=f"Top category: {top_category} ({top_category_pct:.1f}%)", font=("Segoe UI", 8, "bold"), bg=CARD, fg=PURPLE).pack(anchor="w", padx=13, pady=(7, 10))

    # Top expenses
    top_box = tk.Frame(side, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    top_box.pack(fill="x", pady=(0, 8))
    tk.Label(top_box, text="TOP 5 EXPENSES", font=("Segoe UI", 10, "bold"), bg=CARD, fg=DARK).pack(anchor="w", padx=13, pady=(10, 6))
    for _, amount, category, date_text, description in top_expenses:
        desc = description or "No description"
        if len(desc) > 25:
            desc = desc[:22] + "..."
        tk.Label(top_box, text=f"{format_currency(float(amount))}  •  {category}\n{date_text}  •  {desc}", font=("Segoe UI", 8), bg=CARD, fg=TEXT, justify="left", anchor="w").pack(fill="x", padx=13, pady=3)

    # Highest spending days
    day_box = tk.Frame(side, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    day_box.pack(fill="x", pady=(0, 8))
    tk.Label(day_box, text="HIGHEST SPENDING DAYS", font=("Segoe UI", 10, "bold"), bg=CARD, fg=DARK).pack(anchor="w", padx=13, pady=(10, 6))
    for date_text, amount, count in top_days[:5]:
        tk.Label(day_box, text=f"{date_text}   {format_currency(float(amount))}   ({count} expense{'s' if count != 1 else ''})", font=("Segoe UI", 8), bg=CARD, fg=TEXT, anchor="w").pack(fill="x", padx=13, pady=2)
    tk.Label(day_box, text=f"Lowest single expense: {format_currency(lowest)}", font=("Segoe UI", 8, "bold"), bg=CARD, fg=MUTED).pack(anchor="w", padx=13, pady=(6, 10))

    recurring_box = tk.Frame(content, bg="#EEF4FF", highlightbackground=BORDER, highlightthickness=1)
    recurring_box.pack(fill="x", pady=(12, 0))
    recurring_message = (
        f"Active recurring expenses: {recurring_count}   •   "
        f"Scheduled amount: {format_currency(float(recurring_total))}   •   "
        f"Month-to-month: {mom_text}"
    )
    tk.Label(recurring_box, text="FINANCIAL SUMMARY", font=("Segoe UI", 10, "bold"), bg="#EEF4FF", fg=DARK).pack(anchor="w", padx=14, pady=(9, 2))
    tk.Label(recurring_box, text=recurring_message, font=("Segoe UI", 9), bg="#EEF4FF", fg=TEXT, wraplength=1080, justify="left").pack(anchor="w", padx=14, pady=(0, 9))


# ============================================================
# ANALYTICS
# ============================================================

def show_analytics():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT category, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        ORDER BY SUM(amount) DESC
    """, (current_user_id,))

    category_data = cursor.fetchall()

    cursor.execute("""
        SELECT substr(date, 1, 7), SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY substr(date, 1, 7)
        ORDER BY substr(date, 1, 7)
    """, (current_user_id,))

    monthly_data = cursor.fetchall()

    conn.close()

    if not category_data:
        messagebox.showinfo(
            "No Data",
            "Add some expenses before opening analytics."
        )
        return

    analytics = tk.Toplevel(root)
    analytics.title("Expense Analytics")
    analytics.geometry("1100x760")
    analytics.configure(bg=BG)

    header = tk.Frame(analytics, bg=DARK, height=70)
    header.pack(fill="x")
    header.pack_propagate(False)

    tk.Label(
        header,
        text="Expense Analytics",
        font=("Segoe UI", 21, "bold"),
        bg=DARK,
        fg="white"
    ).pack(side="left", padx=25, pady=18)

    tk.Button(
        header,
        text="Back to Dashboard",
        command=analytics.destroy,
        bg="#334155",
        fg="white",
        activebackground="#475569",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=14,
        pady=7
    ).pack(side="right", padx=22)

    content = tk.Frame(analytics, bg=BG)
    content.pack(fill="both", expand=True, padx=20, pady=18)

    total_spending = sum(float(row[1]) for row in category_data)

    highest_category = category_data[0][0]
    highest_category_amount = float(category_data[0][1])

    highest_category_percent = (
        highest_category_amount / total_spending * 100
        if total_spending > 0 else 0
    )

    monthly_values = [float(row[1]) for row in monthly_data]

    average_monthly = (
        sum(monthly_values) / len(monthly_values)
        if monthly_values else 0
    )

    if highest_category_percent >= 50:
        insight = (
            f"Most of your spending is in {highest_category}. "
            f"Consider reviewing this category."
        )
    elif highest_category_percent >= 30:
        insight = (
            f"{highest_category} is your highest spending category. "
            f"Keep monitoring it."
        )
    else:
        insight = (
            "Your spending is distributed across multiple categories."
        )

    stats = tk.Frame(content, bg=BG)
    stats.pack(fill="x", pady=(0, 12))

    stat_items = [
        ("TOTAL SPENDING", format_currency(total_spending)),
        ("TOP CATEGORY", highest_category),
        ("TOP CATEGORY %", f"{highest_category_percent:.1f}%"),
        ("AVG. MONTHLY", format_currency(average_monthly))
    ]

    for i, (title, value) in enumerate(stat_items):
        box = tk.Frame(
            stats,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        box.grid(
            row=0,
            column=i,
            sticky="nsew",
            padx=5
        )
        stats.columnconfigure(i, weight=1)

        tk.Label(
            box,
            text=title,
            font=("Segoe UI", 8, "bold"),
            bg=CARD,
            fg=MUTED
        ).pack(anchor="w", padx=13, pady=(11, 2))

        tk.Label(
            box,
            text=value,
            font=("Segoe UI", 14, "bold"),
            bg=CARD,
            fg=DARK
        ).pack(anchor="w", padx=13, pady=(0, 11))

    chart_frame = tk.Frame(
        content,
        bg=CARD,
        highlightbackground=BORDER,
        highlightthickness=1
    )
    chart_frame.pack(fill="both", expand=True)

    fig = plt.Figure(figsize=(10, 5.3), dpi=100)
    ax1 = fig.add_subplot(121)
    ax2 = fig.add_subplot(122)

    categories = [row[0] for row in category_data]
    category_amounts = [float(row[1]) for row in category_data]

    ax1.pie(
        category_amounts,
        labels=categories,
        autopct="%1.1f%%",
        startangle=90
    )
    ax1.set_title(
        "Category-wise Spending",
        fontsize=11,
        fontweight="bold"
    )

    if monthly_data:
        months = [row[0] for row in monthly_data]
        amounts = [float(row[1]) for row in monthly_data]

        ax2.bar(months, amounts)
        ax2.set_title(
            "Monthly Spending",
            fontsize=11,
            fontweight="bold"
        )
        ax2.set_xlabel("Month")
        ax2.set_ylabel("Amount")
        ax2.tick_params(axis="x", rotation=45)

    fig.tight_layout(pad=2)

    canvas = FigureCanvasTkAgg(
        fig,
        master=chart_frame
    )
    canvas.draw()
    canvas.get_tk_widget().pack(
        fill="both",
        expand=True,
        padx=10,
        pady=10
    )

    insight_frame = tk.Frame(
        content,
        bg="#EEF4FF",
        highlightbackground=BORDER,
        highlightthickness=1
    )
    insight_frame.pack(fill="x", pady=(12, 0))

    tk.Label(
        insight_frame,
        text="Spending Insight",
        font=("Segoe UI", 10, "bold"),
        bg="#EEF4FF",
        fg=DARK
    ).pack(anchor="w", padx=14, pady=(9, 2))

    tk.Label(
        insight_frame,
        text=insight,
        font=("Segoe UI", 9),
        bg="#EEF4FF",
        fg=TEXT,
        wraplength=950,
        justify="left"
    ).pack(anchor="w", padx=14, pady=(0, 9))


# ============================================================
# LOGOUT
# ============================================================

def logout():
    global current_user_id
    global current_username

    answer = messagebox.askyesno(
        "Logout",
        "Are you sure you want to logout?"
    )

    if not answer:
        return

    current_user_id = None
    current_username = None

    show_login()


# ============================================================
# APPLICATION-WIDE ENTER KEY SUPPORT
# ============================================================

def application_enter_handler(event):
    """Application-wide fallback for Enter and numeric keypad Enter."""
    widget = event.widget

    mapping = {
        username_entry: password_entry,
        reg_username_entry: reg_password_entry,
        reg_password_entry: reg_confirm_entry,
        amount_entry: category_combo,
        category_combo: date_entry,
        date_entry: description_entry,
        budget_entry: None,
        search_entry: amount_entry,
        filter_combo: search_entry,
    }

    if widget in mapping and mapping[widget] is not None:
        mapping[widget].focus_set()
        return "break"

    if widget == password_entry:
        login_user()
        return "break"
    if widget == reg_confirm_entry:
        register_user()
        return "break"
    if widget == description_entry:
        add_expense()
        return "break"
    if widget == budget_entry:
        set_budget()
        return "break"

    return None


# ============================================================
# APPLICATION STARTUP
# ============================================================
# Create the Tkinter root BEFORE showing the login screen.
# This is essential because clear_window() and all widgets use root.
initialize_database()

root = tk.Tk()
root.title("Expense Tracker")
root.geometry("1250x850")
root.minsize(1000, 700)
root.configure(bg=BG)

# Directly handle Enter at the application level as an extra safeguard.
# The field-specific enter_next() bindings above remain active.
root.bind_all("<Return>", application_enter_handler, add="+")
root.bind_all("<KP_Enter>", application_enter_handler, add="+")

show_login()
root.mainloop()
