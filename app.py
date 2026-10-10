# -*- coding: utf-8 -*-
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from functools import wraps
import db

app = Flask(__name__)
app.secret_key = "rsmedia-secret-key-change-in-production"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Initialise databases on startup
with app.app_context():
    db.init_db()


# ── Auth guard ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ── Context processor: unread badge ──────────────────────────────────────────

@app.context_processor
def inject_unread():
    count = 0
    if "username" in session:
        count = db.unread_count(session["username"])
    return {"unread_count": count}


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "username" in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Please fill in all fields.", "error")
            return render_template("login.html")
        ok, msg = db.login_user(username, password)
        if ok:
            session["username"] = username
            return redirect(url_for("home"))
        flash(msg, "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "username" in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Please fill in all fields.", "error")
            return render_template("register.html")
        ok, msg = db.register_user(username, password)
        if ok:
            flash(msg, "success")
            return redirect(url_for("login"))
        flash(msg, "error")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ── Feed ──────────────────────────────────────────────────────────────────────

@app.route("/home")
@login_required
def home():
    posts = db.get_feed(session["username"])
    return render_template("home.html", posts=posts)


# ── New post ──────────────────────────────────────────────────────────────────

@app.route("/post/new", methods=["GET", "POST"])
@login_required
def new_post():
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if not content:
            flash("Post cannot be empty.", "error")
            return render_template("new_post.html")
        if len(content) > 280:
            flash("Post must be 280 characters or fewer.", "error")
            return render_template("new_post.html")
        db.add_post(session["username"], content)
        flash("Post published!", "success")
        return redirect(url_for("home"))
    return render_template("new_post.html")


# ── Profile ───────────────────────────────────────────────────────────────────

@app.route("/profile/<username>")
@login_required
def profile(username):
    if username not in db.get_all_usernames():
        flash("User not found.", "error")
        return redirect(url_for("home"))
    posts           = db.get_posts(username)
    follower_count  = len(db.get_followers(username))
    following_count = len(db.get_following(username))
    is_following    = db.is_following(session["username"], username)
    return render_template(
        "profile.html",
        owner           = username,
        posts           = posts,
        post_count      = len(posts),
        follower_count  = follower_count,
        following_count = following_count,
        is_following    = is_following,
    )


# ── Find people ───────────────────────────────────────────────────────────────

@app.route("/find")
@login_required
def find_people():
    me = session["username"]
    users = [
        {"username": u, "is_following": db.is_following(me, u)}
        for u in db.get_all_usernames() if u != me
    ]
    return render_template("find_people.html", users=users)


# ── Follow / Unfollow ─────────────────────────────────────────────────────────

@app.route("/follow/<username>", methods=["POST"])
@login_required
def follow(username):
    ok, msg = db.follow_user(session["username"], username)
    flash(msg, "success" if ok else "error")
    return redirect(request.referrer or url_for("find_people"))


@app.route("/unfollow/<username>", methods=["POST"])
@login_required
def unfollow(username):
    ok, msg = db.unfollow_user(session["username"], username)
    flash(msg, "success" if ok else "error")
    return redirect(request.referrer or url_for("find_people"))


# ── Inbox ─────────────────────────────────────────────────────────────────────

@app.route("/inbox")
@login_required
def inbox():
    conversations = db.get_inbox(session["username"])
    return render_template("inbox.html", conversations=conversations)


# ── Chat room ─────────────────────────────────────────────────────────────────

@app.route("/chat/<partner>")
@login_required
def chat(partner):
    if partner not in db.get_all_usernames():
        flash("User not found.", "error")
        return redirect(url_for("inbox"))
    if partner == session["username"]:
        flash("You can't chat with yourself.", "error")
        return redirect(url_for("inbox"))
    messages = db.get_conversation(session["username"], partner)
    return render_template("chat.html", partner=partner, messages=messages)


# ── Call ──────────────────────────────────────────────────────────────────────

@app.route("/call/<partner>")
@login_required
def call(partner):
    if partner not in db.get_all_usernames():
        flash("User not found.", "error")
        return redirect(url_for("inbox"))
    if partner == session["username"]:
        flash("You can't call yourself.", "error")
        return redirect(url_for("inbox"))
    return render_template("call.html", partner=partner,
                           me=session["username"])


# ── SocketIO — Chat ───────────────────────────────────────────────────────────

def chat_room(a, b):
    """Deterministic room name for two users."""
    return "chat_" + "_".join(sorted([a, b]))


@socketio.on("join_chat")
def on_join_chat(data):
    me      = session.get("username")
    partner = data.get("partner")
    if not me or not partner:
        return
    join_room(chat_room(me, partner))


@socketio.on("send_message")
def on_send_message(data):
    me      = session.get("username")
    partner = data.get("partner")
    body    = data.get("body", "").strip()
    if not me or not partner or not body:
        return
    db.send_message(me, partner, body)
    room = chat_room(me, partner)
    emit("new_message", {
        "sender":    me,
        "body":      body,
        "timestamp": "just now",
    }, to=room)


# ── SocketIO — WebRTC signaling ───────────────────────────────────────────────

def call_room(a, b):
    return "call_" + "_".join(sorted([a, b]))


@socketio.on("join_call")
def on_join_call(data):
    me      = session.get("username")
    partner = data.get("partner")
    if not me or not partner:
        return
    room = call_room(me, partner)
    join_room(room)
    # Notify the other peer that someone joined
    emit("peer_joined", {"from": me}, to=room, skip_sid=request.sid)


@socketio.on("webrtc_offer")
def on_offer(data):
    me      = session.get("username")
    partner = data.get("partner")
    emit("webrtc_offer", {"from": me, "sdp": data["sdp"]},
         to=call_room(me, partner), skip_sid=request.sid)


@socketio.on("webrtc_answer")
def on_answer(data):
    me      = session.get("username")
    partner = data.get("partner")
    emit("webrtc_answer", {"from": me, "sdp": data["sdp"]},
         to=call_room(me, partner), skip_sid=request.sid)


@socketio.on("webrtc_ice")
def on_ice(data):
    me      = session.get("username")
    partner = data.get("partner")
    emit("webrtc_ice", {"from": me, "candidate": data["candidate"]},
         to=call_room(me, partner), skip_sid=request.sid)


@socketio.on("call_ended")
def on_call_ended(data):
    me      = session.get("username")
    partner = data.get("partner")
    room    = call_room(me, partner)
    emit("call_ended", {"from": me}, to=room, skip_sid=request.sid)
    leave_room(room)


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    socketio.run(app, debug=True, port=5000)
