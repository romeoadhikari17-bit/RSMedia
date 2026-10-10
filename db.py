import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DB  = os.path.join(BASE_DIR, "users.db")
POSTS_DB  = os.path.join(BASE_DIR, "posts.db")


# ─────────────────────────────────────────────
#  Initialise both databases
# ─────────────────────────────────────────────

def init_db():
    # users.db  →  users + follows
    with sqlite3.connect(USERS_DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                follower TEXT NOT NULL,
                followee TEXT NOT NULL,
                PRIMARY KEY (follower, followee),
                FOREIGN KEY (follower) REFERENCES users(username),
                FOREIGN KEY (followee) REFERENCES users(username)
            )
        """)
        con.commit()

    # posts.db  →  posts
    with sqlite3.connect(POSTS_DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                timestamp DATETIME DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()

    # users.db  →  messages
    with sqlite3.connect(USERS_DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sender     TEXT    NOT NULL,
                recipient  TEXT    NOT NULL,
                body       TEXT    NOT NULL,
                timestamp  DATETIME DEFAULT (datetime('now','localtime')),
                read       INTEGER DEFAULT 0,
                FOREIGN KEY (sender)    REFERENCES users(username),
                FOREIGN KEY (recipient) REFERENCES users(username)
            )
        """)
        con.commit()


# ─────────────────────────────────────────────
#  User helpers
# ─────────────────────────────────────────────

def register_user(username: str, password: str) -> tuple[bool, str]:
    """Returns (success, message)."""
    with sqlite3.connect(USERS_DB) as con:
        try:
            con.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            con.commit()
            return True, f"Account '{username}' created!"
        except sqlite3.IntegrityError:
            return False, "Username already taken."


def login_user(username: str, password: str) -> tuple[bool, str]:
    with sqlite3.connect(USERS_DB) as con:
        row = con.execute(
            "SELECT password FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return False, "User not found."
    if row[0] != password:
        return False, "Wrong password."
    return True, "Login successful!"


def get_all_usernames() -> list[str]:
    with sqlite3.connect(USERS_DB) as con:
        rows = con.execute("SELECT username FROM users ORDER BY username").fetchall()
    return [r[0] for r in rows]


# ─────────────────────────────────────────────
#  Follow helpers
# ─────────────────────────────────────────────

def follow_user(follower: str, followee: str) -> tuple[bool, str]:
    if follower == followee:
        return False, "You can't follow yourself!"
    with sqlite3.connect(USERS_DB) as con:
        existing = con.execute(
            "SELECT 1 FROM follows WHERE follower=? AND followee=?",
            (follower, followee)
        ).fetchone()
        if existing:
            return False, f"You already follow {followee}."
        con.execute(
            "INSERT INTO follows (follower, followee) VALUES (?, ?)",
            (follower, followee)
        )
        con.commit()
    return True, f"You are now following {followee}!"


def unfollow_user(follower: str, followee: str) -> tuple[bool, str]:
    with sqlite3.connect(USERS_DB) as con:
        con.execute(
            "DELETE FROM follows WHERE follower=? AND followee=?",
            (follower, followee)
        )
        con.commit()
    return True, f"You unfollowed {followee}."


def get_followers(username: str) -> list[str]:
    with sqlite3.connect(USERS_DB) as con:
        rows = con.execute(
            "SELECT follower FROM follows WHERE followee=?", (username,)
        ).fetchall()
    return [r[0] for r in rows]


def get_following(username: str) -> list[str]:
    with sqlite3.connect(USERS_DB) as con:
        rows = con.execute(
            "SELECT followee FROM follows WHERE follower=?", (username,)
        ).fetchall()
    return [r[0] for r in rows]


def is_following(follower: str, followee: str) -> bool:
    with sqlite3.connect(USERS_DB) as con:
        row = con.execute(
            "SELECT 1 FROM follows WHERE follower=? AND followee=?",
            (follower, followee)
        ).fetchone()
    return row is not None


# ─────────────────────────────────────────────
#  Post helpers
# ─────────────────────────────────────────────

def add_post(username: str, content: str) -> None:
    with sqlite3.connect(POSTS_DB) as con:
        con.execute(
            "INSERT INTO posts (username, content) VALUES (?, ?)",
            (username, content)
        )
        con.commit()


def get_posts(username: str) -> list[dict]:
    """Return posts for one user, newest first."""
    with sqlite3.connect(POSTS_DB) as con:
        rows = con.execute(
            "SELECT id, content, timestamp FROM posts WHERE username=? ORDER BY id DESC",
            (username,)
        ).fetchall()
    return [{"id": r[0], "content": r[1], "timestamp": r[2]} for r in rows]


def get_feed(username: str) -> list[dict]:
    """Posts from people the user follows + their own, newest first."""
    following = get_following(username)
    following.append(username)
    placeholders = ",".join("?" * len(following))
    with sqlite3.connect(POSTS_DB) as con:
        rows = con.execute(
            f"""SELECT username, content, timestamp
                FROM posts
                WHERE username IN ({placeholders})
                ORDER BY id DESC""",
            following
        ).fetchall()
    return [{"username": r[0], "content": r[1], "timestamp": r[2]} for r in rows]


# ─────────────────────────────────────────────
#  Message helpers
# ─────────────────────────────────────────────

def send_message(sender: str, recipient: str, body: str) -> None:
    with sqlite3.connect(USERS_DB) as con:
        con.execute(
            "INSERT INTO messages (sender, recipient, body) VALUES (?, ?, ?)",
            (sender, recipient, body)
        )
        con.commit()


def get_conversation(user_a: str, user_b: str) -> list[dict]:
    """All messages between two users, oldest first."""
    with sqlite3.connect(USERS_DB) as con:
        rows = con.execute(
            """SELECT sender, recipient, body, timestamp
               FROM messages
               WHERE (sender=? AND recipient=?)
                  OR (sender=? AND recipient=?)
               ORDER BY id ASC""",
            (user_a, user_b, user_b, user_a)
        ).fetchall()
        # Mark messages sent to user_a as read
        con.execute(
            "UPDATE messages SET read=1 WHERE sender=? AND recipient=?",
            (user_b, user_a)
        )
        con.commit()
    return [{"sender": r[0], "recipient": r[1],
             "body": r[2], "timestamp": r[3]} for r in rows]


def get_inbox(username: str) -> list[dict]:
    """Latest message per conversation partner, newest first."""
    with sqlite3.connect(USERS_DB) as con:
        rows = con.execute(
            """SELECT partner, body, timestamp, unread FROM (
                SELECT
                    CASE WHEN sender=? THEN recipient ELSE sender END AS partner,
                    body,
                    timestamp,
                    SUM(CASE WHEN recipient=? AND read=0 THEN 1 ELSE 0 END) AS unread,
                    MAX(id) AS last_id
                FROM messages
                WHERE sender=? OR recipient=?
                GROUP BY partner
               ) ORDER BY last_id DESC""",
            (username, username, username, username)
        ).fetchall()
    return [{"partner": r[0], "body": r[1],
             "timestamp": r[2], "unread": r[3]} for r in rows]


def unread_count(username: str) -> int:
    with sqlite3.connect(USERS_DB) as con:
        row = con.execute(
            "SELECT COUNT(*) FROM messages WHERE recipient=? AND read=0",
            (username,)
        ).fetchone()
    return row[0] if row else 0
