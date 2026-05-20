"""
AgroMind Flask Web Server
"""

import os
import sqlite3
import requests
import re
from functools import wraps
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash, check_password_hash
from rag_pipeline import RAGPipeline

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "agromind-dev-secret")
oauth = OAuth(app)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
CLERK_PUBLISHABLE_KEY = (os.getenv("CLERK_PUBLISHABLE_KEY") or "").strip()
CLERK_SECRET_KEY = (os.getenv("CLERK_SECRET_KEY") or "").strip()
CLERK_ENABLED = bool(CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY)
CLERK_ENABLE_APPLE = (os.getenv("CLERK_ENABLE_APPLE") or "").strip().lower() in {"1", "true", "yes"}
CLERK_FREE_PLAN_KEY = (os.getenv("CLERK_FREE_PLAN_KEY") or "free_daily_ten").strip()
CLERK_FARMER_PLAN_KEY = (os.getenv("CLERK_FARMER_PLAN_KEY") or "farmer_plus").strip()
CLERK_PRO_PLAN_KEY = (os.getenv("CLERK_PRO_PLAN_KEY") or "agri_pro_new").strip()
FREE_DAILY_QUERY_LIMIT = int(os.getenv("FREE_DAILY_QUERY_LIMIT", "10"))
SKIP_RAG_INIT = (os.getenv("SKIP_RAG_INIT") or "").strip().lower() in {"1", "true", "yes"}

BILLING_PLANS = [
    {
        "key": CLERK_FREE_PLAN_KEY,
        "name": "Free",
        "price": "₹0",
        "period": "forever",
        "description": "Basic access for trying AgroMind.",
        "features": [
            f"{FREE_DAILY_QUERY_LIMIT} questions per day",
            "Basic crop, soil, pest, and irrigation guidance",
            "Limited chat history",
            "Community support",
        ],
    },
    {
        "key": CLERK_FARMER_PLAN_KEY,
        "name": "Farmer Plus",
        "price": "$3.00",
        "period": "month",
        "description": "For farmers who need daily agricultural support.",
        "features": [
            "Unlimited questions",
            "Crop image upload support",
            "Saved chat history",
            "Personalized AgroMind settings",
            "Faster responses",
        ],
    },
    {
        "key": CLERK_PRO_PLAN_KEY,
        "name": "Agri Pro",
        "price": "$20.91",
        "period": "month",
        "description": "For agronomists, advisors, students, and agri-business users.",
        "features": [
            "Everything in Farmer Plus",
            "Advanced document-grounded answers",
            "Export/report workflows",
            "Priority support",
            "Early access to new capabilities",
        ],
    },
]
PLAN_ORDER = {
    CLERK_FREE_PLAN_KEY: 0,
    CLERK_FARMER_PLAN_KEY: 1,
    CLERK_PRO_PLAN_KEY: 2,
}

def _mask(val: str) -> str:
    if not val:
        return "(missing)"
    if len(val) <= 8:
        return val[:2] + ".." + val[-2:]
    return val[:4] + ".." + val[-4:]

print(f"[AgroMind] CLERK_PUBLISHABLE_KEY={_mask(CLERK_PUBLISHABLE_KEY)} CLERK_SECRET_KEY={_mask(CLERK_SECRET_KEY)} CLERK_ENABLED={CLERK_ENABLED}")

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

DB_PATH = os.getenv("AGROMIND_DB_PATH", "agromind.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            clerk_user_id TEXT UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            thread_id INTEGER,
            query TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (thread_id) REFERENCES threads(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            preferred_name TEXT,
            work_type TEXT,
            instructions TEXT,
            appearance TEXT NOT NULL DEFAULT 'system',
            chat_font TEXT NOT NULL DEFAULT 'dm-sans',
            voice TEXT NOT NULL DEFAULT 'clear',
            response_notifications INTEGER NOT NULL DEFAULT 1,
            dispatch_messages INTEGER NOT NULL DEFAULT 0,
            language TEXT NOT NULL DEFAULT 'en',
            plan_key TEXT NOT NULL DEFAULT 'free_daily_ten',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    user_cols = [row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "clerk_user_id" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN clerk_user_id TEXT")

    settings_cols = [row["name"] for row in conn.execute("PRAGMA table_info(user_settings)").fetchall()]
    if "plan_key" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN plan_key TEXT NOT NULL DEFAULT 'free_daily_ten'"
        )

    cols = [row["name"] for row in conn.execute("PRAGMA table_info(chats)").fetchall()]
    if "thread_id" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN thread_id INTEGER")

    # Backfill existing chats into a default thread for each user.
    users_with_chats = conn.execute("SELECT DISTINCT user_id FROM chats").fetchall()
    for row in users_with_chats:
        user_id = row["user_id"]
        thread = conn.execute(
            "SELECT id FROM threads WHERE user_id = ? ORDER BY id ASC LIMIT 1",
            (user_id,),
        ).fetchone()
        if thread is None:
            conn.execute(
                "INSERT INTO threads (user_id, title, created_at) VALUES (?, ?, ?)",
                (user_id, "General", datetime.utcnow().isoformat()),
            )
            thread = conn.execute(
                "SELECT id FROM threads WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

        conn.execute(
            "UPDATE chats SET thread_id = ? WHERE user_id = ? AND thread_id IS NULL",
            (thread["id"], user_id),
        )

    conn.commit()
    conn.close()


def get_user_settings(user_id: int):
    conn = get_db_connection()
    settings = conn.execute(
        "SELECT * FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if settings is None:
        user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        fallback_name = user["username"] if user else ""
        conn.execute(
            """
            INSERT INTO user_settings (
                user_id, full_name, preferred_name, work_type, instructions,
                appearance, chat_font, voice, response_notifications,
                dispatch_messages, language, plan_key, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                fallback_name,
                fallback_name.split("@")[0] if fallback_name else "",
                "",
                "",
                "system",
                "dm-sans",
                "clear",
                1,
                0,
                "en",
                CLERK_FREE_PLAN_KEY,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        settings = conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    conn.close()
    data = dict(settings)
    if data.get("plan_key") not in PLAN_ORDER:
        data["plan_key"] = CLERK_FREE_PLAN_KEY
    return data


def update_user_plan(user_id: int, plan_key: str):
    if plan_key not in PLAN_ORDER:
        plan_key = CLERK_FREE_PLAN_KEY
    get_user_settings(user_id)
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO user_settings (
            user_id, full_name, preferred_name, work_type, instructions,
            appearance, chat_font, voice, response_notifications,
            dispatch_messages, language, plan_key, updated_at
        ) VALUES (?, '', '', '', '', 'system', 'dm-sans', 'clear', 1, 0, 'en', ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            plan_key = excluded.plan_key,
            updated_at = excluded.updated_at
        """,
        (user_id, plan_key, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return get_user_settings(user_id)


def get_plan_by_key(plan_key: str):
    for plan in BILLING_PLANS:
        if plan["key"] == plan_key:
            return plan
    return BILLING_PLANS[0]


def has_plan(user_id: int, required_plan_key: str):
    current = get_user_settings(user_id).get("plan_key", CLERK_FREE_PLAN_KEY)
    return PLAN_ORDER.get(current, 0) >= PLAN_ORDER.get(required_plan_key, 0)


def get_today_chat_count(user_id: int):
    today_prefix = datetime.utcnow().date().isoformat()
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM chats WHERE user_id = ? AND created_at LIKE ?",
        (user_id, f"{today_prefix}%"),
    ).fetchone()
    conn.close()
    return int(row["count"] if row else 0)


def extract_plan_key_from_subscription(subscription):
    if not isinstance(subscription, dict):
        return ""

    candidates = [
        subscription.get("plan"),
        subscription.get("planKey"),
        subscription.get("plan_key"),
        subscription.get("slug"),
        subscription.get("key"),
    ]
    for item in subscription.get("items", []) or []:
        candidates.extend(
            [
                item.get("plan"),
                item.get("planKey"),
                item.get("plan_key"),
                item.get("slug"),
                item.get("key"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate in PLAN_ORDER:
            return candidate
        if isinstance(candidate, dict):
            for key in ("key", "slug", "name"):
                value = candidate.get(key)
                if isinstance(value, str) and value in PLAN_ORDER:
                    return value

    return ""


def sync_clerk_billing_for_user(user_id: int):
    if not CLERK_ENABLED:
        return get_user_settings(user_id)

    conn = get_db_connection()
    user = conn.execute("SELECT clerk_user_id FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    clerk_user_id = user["clerk_user_id"] if user else ""
    if not clerk_user_id:
        return get_user_settings(user_id)

    headers = {"Authorization": f"Bearer {CLERK_SECRET_KEY}"}
    try:
        response = requests.get(
            f"https://api.clerk.com/v1/users/{clerk_user_id}/billing/subscription",
            headers=headers,
            timeout=12,
        )
    except requests.RequestException:
        return get_user_settings(user_id)

    if not response.ok:
        return get_user_settings(user_id)

    plan_key = extract_plan_key_from_subscription(response.json())
    if plan_key:
        return update_user_plan(user_id, plan_key)
    return get_user_settings(user_id)


def get_or_create_default_thread(user_id: int):
    conn = get_db_connection()
    thread = conn.execute(
        "SELECT id, title FROM threads WHERE user_id = ? ORDER BY id ASC LIMIT 1",
        (user_id,),
    ).fetchone()
    if thread is None:
        conn.execute(
            "INSERT INTO threads (user_id, title, created_at) VALUES (?, ?, ?)",
            (user_id, "General", datetime.utcnow().isoformat()),
        )
        conn.commit()
        thread = conn.execute(
            "SELECT id, title FROM threads WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    conn.close()
    return thread


def get_valid_thread_id(user_id: int, requested_thread_id):
    if requested_thread_id is not None:
        conn = get_db_connection()
        thread = conn.execute(
            "SELECT id FROM threads WHERE id = ? AND user_id = ?",
            (requested_thread_id, user_id),
        ).fetchone()
        conn.close()
        if thread:
            return thread["id"]

    default_thread = get_or_create_default_thread(user_id)
    return default_thread["id"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def render_login(error=None):
    return render_template(
        "login.html",
        error=error,
        clerk_enabled=CLERK_ENABLED,
        clerk_publishable_key=CLERK_PUBLISHABLE_KEY,
        clerk_enable_apple=CLERK_ENABLE_APPLE,
    )


def complete_login(user):
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    default_thread = get_or_create_default_thread(user["id"])
    session["current_thread_id"] = default_thread["id"]
    anon_history = session.pop("anon_history", []) if session.get("anon_history") else []
    try:
        if anon_history:
            conn = get_db_connection()
            for item in anon_history:
                q = item.get("query")
                a = item.get("answer")
                conn.execute(
                    "INSERT INTO chats (user_id, thread_id, query, answer, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user["id"], default_thread["id"], q, a, datetime.utcnow().isoformat()),
                )
            conn.commit()
            conn.close()
    except Exception:
        pass
    session["anon_query_count"] = 0
    session.pop("anon_history", None)


def get_or_create_user_by_email(email, password_seed, clerk_user_id=None):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()
    if user is None:
        conn.execute(
            "INSERT INTO users (username, password_hash, clerk_user_id, created_at) VALUES (?, ?, ?, ?)",
            (
                email,
                generate_password_hash(password_seed),
                clerk_user_id,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()
    elif clerk_user_id and not user["clerk_user_id"]:
        conn.execute(
            "UPDATE users SET clerk_user_id = ? WHERE id = ?",
            (clerk_user_id, user["id"]),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()
    conn.close()
    return user


pipeline = None
init_db()
if not SKIP_RAG_INIT:
    try:
        pipeline = RAGPipeline()
    except Exception:
        app.logger.exception("Failed to initialize RAG pipeline")
        pipeline = None
else:
    app.logger.info("SKIP_RAG_INIT is set; skipping heavy RAG pipeline initialization")

@app.route("/")
def index():
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()

        if not email:
            error = "Email is required"
            return render_login(error=error)

        user = get_or_create_user_by_email(email, email)

        if user:
            complete_login(user)
            return redirect(url_for("chat_page"))

        error = "Unable to create or load account"

    return render_login(error=error)


@app.route("/sso-callback")
def clerk_sso_callback():
    if not CLERK_ENABLED:
        return redirect(url_for("login"))

    return render_template(
        "sso_callback.html",
        clerk_publishable_key=CLERK_PUBLISHABLE_KEY,
    )


@app.route("/login/clerk", methods=["POST"])
def login_clerk():
    if not CLERK_ENABLED:
        return jsonify({"error": "Clerk sign-in is not configured yet."}), 400

    payload = request.json or {}
    clerk_session_id = (payload.get("session_id") or "").strip()
    if not clerk_session_id:
        return jsonify({"error": "Missing Clerk session id."}), 400

    headers = {"Authorization": f"Bearer {CLERK_SECRET_KEY}"}
    try:
        session_res = requests.get(
            f"https://api.clerk.com/v1/sessions/{clerk_session_id}",
            headers=headers,
            timeout=12,
        )
    except requests.RequestException:
        return jsonify({"error": "Unable to reach Clerk."}), 502

    if not session_res.ok:
        return jsonify({"error": "Invalid Clerk session."}), 401

    clerk_session = session_res.json()
    if clerk_session.get("status") != "active":
        return jsonify({"error": "Clerk session is not active."}), 401

    clerk_user_id = clerk_session.get("user_id")
    if not clerk_user_id:
        return jsonify({"error": "Missing Clerk user id."}), 401

    try:
        user_res = requests.get(
            f"https://api.clerk.com/v1/users/{clerk_user_id}",
            headers=headers,
            timeout=12,
        )
    except requests.RequestException:
        return jsonify({"error": "Unable to fetch Clerk user profile."}), 502

    if not user_res.ok:
        return jsonify({"error": "Could not load Clerk user profile."}), 401

    clerk_user = user_res.json()
    primary_email_id = clerk_user.get("primary_email_address_id")
    email = ""
    for item in clerk_user.get("email_addresses", []):
        if item.get("id") == primary_email_id:
            email = (item.get("email_address") or "").strip()
            break
    if not email and clerk_user.get("email_addresses"):
        email = (clerk_user["email_addresses"][0].get("email_address") or "").strip()

    if not email:
        return jsonify({"error": "Clerk did not provide an email address."}), 400

    user = get_or_create_user_by_email(email, clerk_user_id, clerk_user_id=clerk_user_id)
    if not user:
        return jsonify({"error": "Unable to create or load account."}), 500

    complete_login(user)
    sync_clerk_billing_for_user(user["id"])
    return jsonify({"ok": True, "redirect": url_for("chat_page")})


@app.route("/login/google")
def login_google():
    google_client = oauth.create_client("google")
    if google_client is None:
        return render_login(error="Google sign-in is not configured yet. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")

    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI") or url_for("login_google_callback", _external=True)
    return google_client.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def login_google_callback():
    google_client = oauth.create_client("google")
    if google_client is None:
        return render_login(error="Google sign-in is not configured yet. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")

    token = google_client.authorize_access_token()
    user_info_response = google_client.get("userinfo", token=token)
    user_info = user_info_response.json()

    email = (user_info.get("email") or "").strip()
    if not email:
        return render_login(error="Google did not return an email address.")

    user = get_or_create_user_by_email(email, user_info.get("sub", email))

    if not user:
        return render_login(error="Unable to create or load your Google account.")

    complete_login(user)
    return redirect(url_for("chat_page"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/chat")
def chat_page():
    # Allow anonymous users to view the chat UI; they can ask up to 3 queries before
    # being required to log in. If logged in, provide username and thread context.
    username = session.get("username")
    current_thread = session.get("current_thread_id")
    # ensure anon counters exist
    if "anon_query_count" not in session:
        session["anon_query_count"] = 0
    if "anon_history" not in session:
        session["anon_history"] = []

    return render_template(
        "index.html",
        username=username or "",
        current_thread_id=current_thread,
        anon_remaining=max(0, 3 - int(session.get("anon_query_count", 0))),
        settings=get_user_settings(session["user_id"]) if username else {},
        billing_plans=BILLING_PLANS,
    )


@app.route("/api/threads", methods=["GET"])
@login_required
def list_threads():
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            t.id,
            t.title,
            t.created_at,
            COUNT(c.id) AS message_count,
            MAX(c.created_at) AS last_message_at
        FROM threads t
        LEFT JOIN chats c ON c.thread_id = t.id
        WHERE t.user_id = ?
        GROUP BY t.id, t.title, t.created_at
        ORDER BY COALESCE(MAX(c.created_at), t.created_at) DESC
        """,
        (session["user_id"],),
    ).fetchall()
    conn.close()

    if not rows:
        thread = get_or_create_default_thread(session["user_id"])
        rows = [
            {
                "id": thread["id"],
                "title": thread["title"],
                "created_at": datetime.utcnow().isoformat(),
                "message_count": 0,
                "last_message_at": None,
            }
        ]

    threads = [
        {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "message_count": row["message_count"],
            "last_message_at": row["last_message_at"],
        }
        for row in rows
    ]

    return jsonify(
        {
            "threads": threads,
            "current_thread_id": session.get("current_thread_id"),
        }
    )


@app.route("/api/threads", methods=["POST"])
@login_required
def create_thread():
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        title = f"Chat {datetime.utcnow().strftime('%b %d, %H:%M')}"

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO threads (user_id, title, created_at) VALUES (?, ?, ?)",
        (session["user_id"], title[:80], datetime.utcnow().isoformat()),
    )
    conn.commit()
    thread = conn.execute(
        "SELECT id, title, created_at FROM threads WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (session["user_id"],),
    ).fetchone()
    conn.close()

    session["current_thread_id"] = thread["id"]

    return jsonify(
        {
            "thread": {
                "id": thread["id"],
                "title": thread["title"],
                "created_at": thread["created_at"],
                "message_count": 0,
                "last_message_at": None,
            }
        }
    )


@app.route("/api/threads/rename", methods=["POST"])
@login_required
def rename_thread():
    payload = request.json or {}
    requested_thread_id = payload.get("thread_id")
    title = (payload.get("title") or "").strip()

    if not title:
        return jsonify({"error": "Title cannot be empty"}), 400

    thread_id = get_valid_thread_id(session["user_id"], requested_thread_id)

    conn = get_db_connection()
    conn.execute(
        "UPDATE threads SET title = ? WHERE id = ? AND user_id = ?",
        (title[:80], thread_id, session["user_id"]),
    )
    conn.commit()
    thread = conn.execute(
        "SELECT id, title, created_at FROM threads WHERE id = ? AND user_id = ?",
        (thread_id, session["user_id"]),
    ).fetchone()
    conn.close()

    return jsonify(
        {
            "thread": {
                "id": thread["id"],
                "title": thread["title"],
                "created_at": thread["created_at"],
            }
        }
    )


@app.route("/api/threads/delete", methods=["POST"])
@login_required
def delete_thread():
    payload = request.json or {}
    requested_thread_id = payload.get("thread_id")
    thread_id = get_valid_thread_id(session["user_id"], requested_thread_id)

    conn = get_db_connection()
    conn.execute(
        "DELETE FROM chats WHERE user_id = ? AND thread_id = ?",
        (session["user_id"], thread_id),
    )
    conn.execute(
        "DELETE FROM threads WHERE id = ? AND user_id = ?",
        (thread_id, session["user_id"]),
    )
    conn.commit()

    next_thread = conn.execute(
        """
        SELECT t.id, t.title, t.created_at
        FROM threads t
        LEFT JOIN chats c ON c.thread_id = t.id
        WHERE t.user_id = ?
        GROUP BY t.id, t.title, t.created_at
        ORDER BY COALESCE(MAX(c.created_at), t.created_at) DESC
        LIMIT 1
        """,
        (session["user_id"],),
    ).fetchone()
    conn.close()

    if next_thread is None:
        next_thread = get_or_create_default_thread(session["user_id"])

    session["current_thread_id"] = next_thread["id"]

    return jsonify(
        {
            "ok": True,
            "current_thread_id": next_thread["id"],
            "thread": {
                "id": next_thread["id"],
                "title": next_thread["title"],
                "created_at": next_thread["created_at"],
            },
        }
    )


@app.route("/api/select-thread", methods=["POST"])
@login_required
def select_thread():
    payload = request.json or {}
    requested_thread_id = payload.get("thread_id")
    thread_id = get_valid_thread_id(session["user_id"], requested_thread_id)
    session["current_thread_id"] = thread_id
    return jsonify({"thread_id": thread_id})


@app.route("/api/history", methods=["GET"])
@login_required
def chat_history():
    requested_thread_id = request.args.get("thread_id", type=int)
    thread_id = get_valid_thread_id(session["user_id"], requested_thread_id or session.get("current_thread_id"))
    session["current_thread_id"] = thread_id

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT query, answer, created_at
        FROM chats
        WHERE user_id = ? AND thread_id = ?
        ORDER BY id ASC
        """,
        (session["user_id"], thread_id),
    ).fetchall()
    conn.close()

    history = [
        {
            "query": row["query"],
            "answer": row["answer"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]

    grouped = {}
    for item in history:
        try:
            dt = datetime.fromisoformat(item["created_at"])
            date_label = dt.strftime("%b %d, %Y")
        except ValueError:
            date_label = "Unknown Date"
        grouped.setdefault(date_label, []).append(item)

    groups = [{"date": date_label, "messages": msgs} for date_label, msgs in grouped.items()]
    return jsonify({"thread_id": thread_id, "groups": groups})


@app.route("/api/history/clear", methods=["POST"])
@login_required
def clear_history():
    payload = request.json or {}
    scope = (payload.get("scope") or "thread").strip().lower()
    requested_thread_id = payload.get("thread_id")

    conn = get_db_connection()
    if scope == "all":
        conn.execute("DELETE FROM chats WHERE user_id = ?", (session["user_id"],))
    else:
        thread_id = get_valid_thread_id(session["user_id"], requested_thread_id or session.get("current_thread_id"))
        conn.execute(
            "DELETE FROM chats WHERE user_id = ? AND thread_id = ?",
            (session["user_id"], thread_id),
        )
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/api/anon-status", methods=["GET"])
def anon_status():
    # returns how many anonymous queries remain (if not logged in)
    if "user_id" in session:
        return jsonify({"logged_in": True, "remaining": None})
    remaining = max(0, 3 - int(session.get("anon_query_count", 0)))
    return jsonify({"logged_in": False, "remaining": remaining})


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "GET":
        return redirect(url_for("settings_page"))

    error = None
    if request.method == "POST":
        new_username = (request.form.get("username") or "").strip()
        if not new_username or len(new_username) < 3:
            error = "Username must be at least 3 characters"
        else:
            conn = get_db_connection()
            exists = conn.execute("SELECT id FROM users WHERE username = ? AND id != ?", (new_username, session["user_id"])).fetchone()
            if exists:
                error = "Username already taken"
            else:
                conn.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, session["user_id"]))
                conn.commit()
                conn.close()
                session["username"] = new_username
                return redirect(url_for("chat_page"))
            conn.close()

    return render_template("profile.html", username=session.get("username"), error=error)


@app.route("/settings")
@login_required
def settings_page():
    settings = sync_clerk_billing_for_user(session["user_id"])
    return render_template(
        "settings/index.html",
        username=session.get("username"),
        settings=settings,
        billing_plans=BILLING_PLANS,
        current_plan=get_plan_by_key(settings.get("plan_key", CLERK_FREE_PLAN_KEY)),
        clerk_enabled=CLERK_ENABLED,
        clerk_publishable_key=CLERK_PUBLISHABLE_KEY,
    )


@app.route("/settings/billing/checkout")
@login_required
def billing_checkout_page():
    settings = sync_clerk_billing_for_user(session["user_id"])
    return render_template(
        "settings/billing_checkout.html",
        username=session.get("username"),
        settings=settings,
        billing_plans=BILLING_PLANS,
        current_plan=get_plan_by_key(settings.get("plan_key", CLERK_FREE_PLAN_KEY)),
        clerk_enabled=CLERK_ENABLED,
        clerk_publishable_key=CLERK_PUBLISHABLE_KEY,
    )


@app.route("/learn-more")
def learn_more_doc():
    return render_template("learn_more.html")


@app.route("/terms")
def terms_page():
    return render_template("terms.html")


@app.route("/api/settings", methods=["GET", "POST"])
@login_required
def settings_api():
    if request.method == "GET":
        return jsonify({"settings": get_user_settings(session["user_id"])})

    data = request.json or {}
    allowed_appearance = {"system", "light", "dark"}
    allowed_fonts = {"dm-sans", "serif", "mono"}
    allowed_voices = {"clear", "warm", "brief", "detailed"}
    allowed_languages = {"en", "fr", "de", "hi", "id", "it", "ja", "ko", "pt", "es_419", "es", "ta", "mr", "te", "bn"}

    full_name = (data.get("full_name") or "").strip()[:120]
    preferred_name = (data.get("preferred_name") or "").strip()[:80]
    work_type = (data.get("work_type") or "").strip()[:80]
    instructions = (data.get("instructions") or "").strip()[:2000]
    appearance = (data.get("appearance") or "system").strip()
    chat_font = (data.get("chat_font") or "dm-sans").strip()
    voice = (data.get("voice") or "clear").strip()
    language = (data.get("language") or "en").strip()

    if appearance not in allowed_appearance:
        appearance = "system"
    if chat_font not in allowed_fonts:
        chat_font = "dm-sans"
    if voice not in allowed_voices:
        voice = "clear"
    if language not in allowed_languages:
        language = "en"

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO user_settings (
            user_id, full_name, preferred_name, work_type, instructions,
            appearance, chat_font, voice, response_notifications,
            dispatch_messages, language, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            full_name = excluded.full_name,
            preferred_name = excluded.preferred_name,
            work_type = excluded.work_type,
            instructions = excluded.instructions,
            appearance = excluded.appearance,
            chat_font = excluded.chat_font,
            voice = excluded.voice,
            response_notifications = excluded.response_notifications,
            dispatch_messages = excluded.dispatch_messages,
            language = excluded.language,
            updated_at = excluded.updated_at
        """,
        (
            session["user_id"],
            full_name,
            preferred_name,
            work_type,
            instructions,
            appearance,
            chat_font,
            voice,
            1 if data.get("response_notifications") else 0,
            1 if data.get("dispatch_messages") else 0,
            language,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "settings": get_user_settings(session["user_id"])})


@app.route("/api/settings/account", methods=["POST"])
@login_required
def settings_account_api():
    data = request.json or {}
    new_username = (data.get("username") or "").strip()
    if len(new_username) < 3:
        return jsonify({"error": "Username must be at least 3 characters."}), 400

    conn = get_db_connection()
    exists = conn.execute(
        "SELECT id FROM users WHERE username = ? AND id != ?",
        (new_username, session["user_id"]),
    ).fetchone()
    if exists:
        conn.close()
        return jsonify({"error": "Username already taken."}), 409

    conn.execute(
        "UPDATE users SET username = ? WHERE id = ?",
        (new_username, session["user_id"]),
    )
    conn.commit()
    conn.close()
    session["username"] = new_username
    return jsonify({"ok": True, "username": new_username})


@app.route("/api/settings/export", methods=["GET"])
@login_required
def export_settings_data():
    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, username, created_at FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()
    threads = conn.execute(
        "SELECT id, title, created_at FROM threads WHERE user_id = ? ORDER BY id ASC",
        (session["user_id"],),
    ).fetchall()
    chats = conn.execute(
        "SELECT thread_id, query, answer, created_at FROM chats WHERE user_id = ? ORDER BY id ASC",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return jsonify(
        {
            "user": dict(user) if user else {},
            "settings": get_user_settings(session["user_id"]),
            "threads": [dict(row) for row in threads],
            "chats": [dict(row) for row in chats],
            "exported_at": datetime.utcnow().isoformat(),
        }
    )


@app.route("/api/settings/delete-account", methods=["POST"])
@login_required
def delete_account_api():
    user_id = session["user_id"]
    conn = get_db_connection()
    conn.execute("DELETE FROM chats WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM threads WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    session.clear()
    return jsonify({"ok": True, "redirect": url_for("login")})


@app.route("/api/billing", methods=["GET"])
@login_required
def billing_api():
    settings = sync_clerk_billing_for_user(session["user_id"])
    return jsonify(
        {
            "clerk_enabled": CLERK_ENABLED,
            "plans": BILLING_PLANS,
            "current_plan": get_plan_by_key(settings.get("plan_key", CLERK_FREE_PLAN_KEY)),
            "current_plan_key": settings.get("plan_key", CLERK_FREE_PLAN_KEY),
            "limits": {"free_daily_queries": FREE_DAILY_QUERY_LIMIT},
        }
    )


@app.route("/api/billing/sync", methods=["POST"])
@login_required
def billing_sync_api():
    settings = sync_clerk_billing_for_user(session["user_id"])
    return jsonify(
        {
            "ok": True,
            "current_plan": get_plan_by_key(settings.get("plan_key", CLERK_FREE_PLAN_KEY)),
            "current_plan_key": settings.get("plan_key", CLERK_FREE_PLAN_KEY),
        }
    )


@app.route("/api/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    """Create a Clerk checkout/checkout session for the current user and plan.

    This endpoint returns a JSON object with a `url` field the client should
    redirect the browser to. It expects `plan_key` in the JSON body.
    """
    app.logger.info("/api/create-checkout-session invoked by user_id=%s", session.get("user_id"))
    app.logger.debug("Request headers: %s", dict(request.headers))
    try:
        app.logger.debug("Request body: %s", request.get_data(as_text=True))
    except Exception:
        pass

    if not CLERK_ENABLED:
        app.logger.warning("Clerk not enabled - request rejected")
        return jsonify({"error": "Billing not configured"}), 400

    data = request.json or {}
    plan_key = (data.get("plan_key") or "").strip()
    if plan_key not in PLAN_ORDER:
        return jsonify({"error": "Invalid plan"}), 400

    # find clerk_user_id for this user if available
    conn = get_db_connection()
    row = conn.execute("SELECT clerk_user_id, username FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()
    clerk_user_id = row["clerk_user_id"] if row else None
    username = row["username"] if row else None

    headers = {
        "Authorization": f"Bearer {CLERK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    # Clerk billing API shapes vary; attempt a reasonable payload that Clerk accepts.
    payload = {
        "plan": plan_key,
        "success_url": url_for("settings_page", _external=True) + "?billing=success",
        "cancel_url": url_for("settings_page", _external=True) + "?billing=cancel",
    }
    if clerk_user_id:
        payload["customer"] = {"id": clerk_user_id}
    elif username:
        payload["customer"] = {"email": username}

    try:
        res = requests.post(
            "https://api.clerk.com/v1/billing/checkout_sessions",
            json=payload,
            headers=headers,
            timeout=12,
        )
    except requests.RequestException:
        app.logger.exception("Error creating Clerk checkout session")
        return jsonify({"error": "Unable to create checkout session"}), 502

    if not res.ok:
        # Log Clerk response to help debugging
        app.logger.error("Clerk checkout creation failed: %s %s", res.status_code, res.text)
        detail = res.text
        # Attempt to include JSON error message if available
        try:
            j = res.json()
            # prefer explicit message fields
            detail = j.get("error") or j.get("message") or j.get("detail") or str(j)
        except Exception:
            pass
        return jsonify({"error": "Checkout creation failed", "detail": detail, "status_code": res.status_code}), 400

    j = res.json()
    checkout_url = j.get("url") or j.get("checkout_url") or j.get("redirect_url")
    if not checkout_url:
        return jsonify({"error": "No redirect URL returned by billing provider"}), 500

    return jsonify({"url": checkout_url})


@app.route("/webhook/clerk", methods=["POST"])
def clerk_webhook():
    """Simple Clerk webhook receiver to update user plan on subscription changes.

    For basic security the request should include an `Authorization: Bearer <CLERK_SECRET_KEY>` header.
    """
    app.logger.info("/webhook/clerk received")
    app.logger.debug("Webhook headers: %s", dict(request.headers))
    try:
        app.logger.debug("Webhook body: %s", request.get_data(as_text=True))
    except Exception:
        pass
    if not CLERK_ENABLED:
        app.logger.warning("Clerk not enabled - webhook rejected")
        return jsonify({"error": "Billing not configured"}), 400

    # optional bearer check
    auth = request.headers.get("Authorization", "")
    if CLERK_SECRET_KEY and auth != f"Bearer {CLERK_SECRET_KEY}":
        # If secret exists, require the same secret in Authorization header.
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.json or {}

    # Attempt to extract clerk_user_id from common webhook shapes
    clerk_user_id = None
    if isinstance(payload.get("data"), dict):
        d = payload.get("data")
        clerk_user_id = d.get("user_id") or d.get("user") or d.get("id")
        subscription = d.get("subscription") or d.get("billing") or d.get("plan") or d
    else:
        clerk_user_id = payload.get("user_id") or payload.get("user") or payload.get("id")
        subscription = payload.get("subscription") or payload.get("billing") or payload.get("plan") or payload

    # normalize clerk_user_id if it's a dict
    if isinstance(clerk_user_id, dict):
        clerk_user_id = clerk_user_id.get("id")

    # If subscription is nested, try to find plan key
    plan_key = extract_plan_key_from_subscription(subscription or {})

    if not clerk_user_id:
        return jsonify({"error": "Missing clerk user id"}), 400

    # find our user
    conn = get_db_connection()
    row = conn.execute("SELECT id FROM users WHERE clerk_user_id = ?", (clerk_user_id,)).fetchone()
    conn.close()
    if not row:
        # Nothing to do for unknown users
        return jsonify({"ok": True, "note": "user not found locally"}), 200

    user_id = row["id"]
    if plan_key:
        update_user_plan(user_id, plan_key)
        return jsonify({"ok": True, "plan": plan_key}), 200

    # No plan found; leave as-is
    return jsonify({"ok": True, "note": "no-plan-detected"}), 200


@app.route('/api/_diag', methods=['GET'])
def _diag():
    """Local diagnostic route to show masked Clerk env and status.

    Accessible only from localhost to avoid exposing secrets.
    """
    remote = request.remote_addr
    if remote not in ("127.0.0.1", "::1", "localhost"):
        return jsonify({"error": "forbidden"}), 403

    def mask(s: str | None) -> str | None:
        if not s:
            return None
        s = str(s)
        if len(s) <= 10:
            return s[:2] + ".." + s[-2:]
        return s[:6] + ".." + s[-4:]

    return jsonify(
        {
            "clerk_publishable_key": mask(CLERK_PUBLISHABLE_KEY),
            "clerk_secret_key": mask(CLERK_SECRET_KEY),
            "clerk_enabled": CLERK_ENABLED,
            "skip_rag_init": SKIP_RAG_INIT,
        }
    )


@app.route("/api/chat", methods=["POST"])
def chat_api():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    image_b64 = data.get("image", None)

    # If the RAG pipeline wasn't initialized (SKIP_RAG_INIT), return service unavailable
    if pipeline is None:
        return (
            jsonify({"error": "service_unavailable", "message": "The RAG pipeline is not available. Try again later or set SKIP_RAG_INIT=0."}),
            503,
        )

    # If user is logged in, resolve thread against their threads
    if "user_id" in session:
        user_id = session["user_id"]
        thread_id = get_valid_thread_id(user_id, data.get("thread_id") or session.get("current_thread_id"))
        session["current_thread_id"] = thread_id
    else:
        # anonymous: no DB thread, just keep thread_id as None
        thread_id = None

    if not query:
        return jsonify({"error": "Empty query"}), 400

    display_query = query
    pipeline_query = query

    if image_b64:
        if "user_id" in session and not has_plan(session["user_id"], CLERK_FARMER_PLAN_KEY):
            return jsonify(
                {
                    "error": "billing_required",
                    "message": "Image uploads are available on Farmer Plus and Agri Pro.",
                    "upgrade_url": url_for("settings_page") + "#billing",
                }
            ), 402
        pipeline_query = f"[Farmer uploaded a crop image] {pipeline_query}"

    if "user_id" in session:
        settings = get_user_settings(session["user_id"])
        guidance = []
        if settings.get("preferred_name"):
            guidance.append(f"Call the user {settings['preferred_name']}.")
        if settings.get("work_type"):
            guidance.append(f"The user's work type is {settings['work_type']}.")
        if settings.get("voice") == "brief":
            guidance.append("Keep the answer brief and action-focused.")
        elif settings.get("voice") == "detailed":
            guidance.append("Include careful detail and reasoning.")
        elif settings.get("voice") == "warm":
            guidance.append("Use a warm, supportive tone.")
        if settings.get("instructions"):
            guidance.append(settings["instructions"])
        if guidance:
            pipeline_query = "[User settings: " + " ".join(guidance) + "] " + pipeline_query

    # Enforce anonymous query limit (3)
    if "user_id" not in session:
        session.setdefault("anon_query_count", 0)
        count = int(session.get("anon_query_count", 0))
        if count >= 3:
            return jsonify({"error": "auth_required", "message": "Please login to continue using AgroMind.", "remaining": 0}), 403
    elif not has_plan(session["user_id"], CLERK_FARMER_PLAN_KEY):
        used_today = get_today_chat_count(session["user_id"])
        if used_today >= FREE_DAILY_QUERY_LIMIT:
            return jsonify(
                {
                    "error": "billing_required",
                    "message": f"You have reached the Free plan limit of {FREE_DAILY_QUERY_LIMIT} questions today.",
                    "upgrade_url": url_for("settings_page") + "#billing",
                }
            ), 402

    # Run the pipeline (may be slow) and produce answer
    answer = pipeline.run(pipeline_query)

    # Persist result: if logged in -> DB, else -> session temp history
    if "user_id" in session:
        conn = get_db_connection()

        # If this is the first message in a newly-created thread with a default title,
        # update the thread title to a short summary derived from the user's first query.
        try:
            thread_row = conn.execute(
                "SELECT title FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, session["user_id"]),
            ).fetchone()
            if thread_row:
                # Count existing messages in the thread.
                count_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM chats WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
                msg_count = int(count_row["cnt"] if count_row else 0)
                title = thread_row["title"] or ""
                if msg_count == 0 and (title.startswith("Chat ") or title == "General"):
                    # Derive a short title from the first query: strip punctuation, remove stopwords,
                    # take the first 6 meaningful words and Title Case them (max 80 chars).
                    STOPWORDS = {
                        'the','a','an','and','or','of','in','on','for','to','with','is','are','was','were','be','by','my','your','i','you'
                    }
                    cleaned = re.sub(r"[^\w\s]", "", display_query).lower()
                    words = [w for w in cleaned.split() if w and w not in STOPWORDS]
                    if not words:
                        # fallback to raw words if removal left nothing
                        words = [w for w in re.sub(r"[^\w\s]", "", display_query).split() if w]
                    new_title = " ".join(words[:6]) if words else "Chat"
                    new_title = new_title.strip()
                    # Title case and enforce length
                    new_title = new_title.title()
                    if len(new_title) > 80:
                        new_title = new_title[:80].rsplit(" ", 1)[0]
                    if not new_title:
                        new_title = "Chat"
                    conn.execute(
                        "UPDATE threads SET title = ? WHERE id = ? AND user_id = ?",
                        (new_title, thread_id, session["user_id"]),
                    )

        except Exception:
            # If anything goes wrong here, don't block saving the chat.
            app.logger.exception("Error updating thread title from first message")

        conn.execute(
            "INSERT INTO chats (user_id, thread_id, query, answer, created_at) VALUES (?, ?, ?, ?, ?)",
            (session["user_id"], thread_id, display_query, answer, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
    else:
        # store in session for potential migration after login
        anon_history = session.get("anon_history", [])
        anon_history.append({"query": display_query, "answer": answer, "created_at": datetime.utcnow().isoformat()})
        session["anon_history"] = anon_history
        session["anon_query_count"] = int(session.get("anon_query_count", 0)) + 1

    remaining = None
    if "user_id" not in session:
        remaining = max(0, 3 - int(session.get("anon_query_count", 0)))

    resp = {"answer": answer}
    if remaining is not None:
        resp["remaining"] = remaining

    return jsonify(resp)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
