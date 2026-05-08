"""
AgroMind Flask Web Server
"""

import os
import sqlite3
from functools import wraps
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash, check_password_hash
from rag_pipeline import RAGPipeline

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "agromind-dev-secret")
oauth = OAuth(app)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

DB_PATH = "agromind.db"


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


pipeline = RAGPipeline()
init_db()

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
            return render_template("login.html", error=error)

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()
        if user is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (email, generate_password_hash(email), datetime.utcnow().isoformat()),
            )
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()

        conn.close()

        if user:
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
            return redirect(url_for("chat_page"))

        error = "Unable to create or load account"

    return render_template("login.html", error=error)


@app.route("/login/google")
def login_google():
    google_client = oauth.create_client("google")
    if google_client is None:
        return render_template(
            "login.html",
            error="Google sign-in is not configured yet. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    redirect_uri = url_for("login_google_callback", _external=True)
    return google_client.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def login_google_callback():
    google_client = oauth.create_client("google")
    if google_client is None:
        return render_template(
            "login.html",
            error="Google sign-in is not configured yet. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    token = google_client.authorize_access_token()
    user_info_response = google_client.get("userinfo", token=token)
    user_info = user_info_response.json()

    email = (user_info.get("email") or "").strip()
    if not email:
        return render_template("login.html", error="Google did not return an email address.")

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()
    if user is None:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(user_info.get("sub", email)), datetime.utcnow().isoformat()),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()
    conn.close()

    if not user:
        return render_template("login.html", error="Unable to create or load your Google account.")

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    default_thread = get_or_create_default_thread(user["id"])
    session["current_thread_id"] = default_thread["id"]
    session["anon_query_count"] = 0
    session.pop("anon_history", None)
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
    payload = request.json or {}
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

@app.route("/api/chat", methods=["POST"])
def chat_api():
    data = request.json or {}
    query = (data.get("query") or "").strip()
    image_b64 = data.get("image", None)

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

    if image_b64:
        query = f"[Farmer uploaded a crop image] {query}"

    # Enforce anonymous query limit (3)
    if "user_id" not in session:
        session.setdefault("anon_query_count", 0)
        count = int(session.get("anon_query_count", 0))
        if count >= 3:
            return jsonify({"error": "auth_required", "message": "Please login to continue using AgroMind.", "remaining": 0}), 403

    # Run the pipeline (may be slow) and produce answer
    answer = pipeline.run(query)

    # Persist result: if logged in -> DB, else -> session temp history
    if "user_id" in session:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO chats (user_id, thread_id, query, answer, created_at) VALUES (?, ?, ?, ?, ?)",
            (session["user_id"], thread_id, query, answer, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
    else:
        # store in session for potential migration after login
        anon_history = session.get("anon_history", [])
        anon_history.append({"query": query, "answer": answer, "created_at": datetime.utcnow().isoformat()})
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