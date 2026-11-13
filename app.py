import os, sqlite3, secrets, json
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, abort
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
UPLOAD_DIR = BASE / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DB = BASE / "wedding.db"
ALLOWED = {"jpg", "jpeg", "png", "webp"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deploying")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me")
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, couple TEXT DEFAULT '', date TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("""CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL,
            filename TEXT NOT NULL, descriptors TEXT DEFAULT '[]',
            FOREIGN KEY(event_id) REFERENCES events(id))""")

init_db()

def allowed(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED

@app.route("/")
def home():
    with db() as con:
        events = con.execute("SELECT * FROM events ORDER BY id DESC").fetchall()
    return render_template("home.html", events=events)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("password") != ADMIN_PASSWORD:
            flash("Incorrect admin password.", "error")
            return redirect(url_for("admin"))
        # Lightweight sessionless admin gate for a starter project.
        from flask import session
        session["admin_ok"] = True
        return redirect(url_for("dashboard"))
    return render_template("admin_login.html")

@app.route("/dashboard")
def dashboard():
    from flask import session
    if not session.get("admin_ok"):
        return redirect(url_for("admin"))
    with db() as con:
        events = con.execute("""SELECT e.*, COUNT(p.id) AS photo_count
            FROM events e LEFT JOIN photos p ON p.event_id=e.id
            GROUP BY e.id ORDER BY e.id DESC""").fetchall()
    return render_template("dashboard.html", events=events, site_url=SITE_URL)

@app.route("/events/new", methods=["POST"])
def create_event():
    from flask import session
    if not session.get("admin_ok"):
        abort(403)
    title = request.form.get("title", "").strip()
    if not title:
        flash("Please enter an event title.", "error")
        return redirect(url_for("dashboard"))
    slug = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:9].lower()
    with db() as con:
        con.execute("INSERT INTO events(slug,title,couple,date) VALUES(?,?,?,?)",
                    (slug, title, request.form.get("couple","").strip(), request.form.get("date","")))
    flash("Wedding event created. Upload photos to begin indexing.", "success")
    return redirect(url_for("event_admin", slug=slug))

@app.route("/admin/event/<slug>/edit", methods=["POST"])
def edit_event(slug):
    from flask import session
    if not session.get("admin_ok"):
        abort(403)
    title = request.form.get("title", "").strip()
    couple = request.form.get("couple", "").strip()
    date = request.form.get("date", "").strip()
    if not title:
        flash("Wedding title cannot be empty.", "error")
        return redirect(url_for("event_admin", slug=slug))
    with db() as con:
        cur = con.execute(
            "UPDATE events SET title=?, couple=?, date=? WHERE slug=?",
            (title, couple, date, slug)
        )
        if cur.rowcount == 0:
            abort(404)
    flash("Wedding details updated successfully.", "success")
    return redirect(url_for("event_admin", slug=slug))

@app.route("/admin/event/<slug>", methods=["GET", "POST"])
def event_admin(slug):
    from flask import session
    if not session.get("admin_ok"):
        abort(403)
    with db() as con:
        event = con.execute("SELECT * FROM events WHERE slug=?", (slug,)).fetchone()
        photos = con.execute("SELECT * FROM photos WHERE event_id=? ORDER BY id DESC", (event["id"],)).fetchall() if event else []
    if not event:
        abort(404)
    if request.method == "POST":
        count = 0
        for f in request.files.getlist("photos"):
            if not f or not f.filename or not allowed(f.filename):
                continue
            ext = f.filename.rsplit(".", 1)[1].lower()
            filename = secure_filename(f"{secrets.token_hex(8)}.{ext}")
            f.save(UPLOAD_DIR / filename)
            with db() as con:
                con.execute("INSERT INTO photos(event_id,filename) VALUES(?,?)", (event["id"], filename))
            count += 1
        flash(f"Uploaded {count} photo(s). Open the event page and use Index photos on this device to prepare face matches.", "success")
        return redirect(url_for("event_admin", slug=slug))
    public_url = (SITE_URL or request.url_root.rstrip("/")) + url_for("guest_event", slug=slug)
    return render_template("event_admin.html", event=event, photos=photos, public_url=public_url)

@app.route("/api/event/<slug>/photos")
def photo_data(slug):
    with db() as con:
        event = con.execute("SELECT * FROM events WHERE slug=?", (slug,)).fetchone()
        if not event:
            return jsonify({"error":"Event not found"}), 404
        photos = con.execute("SELECT id,filename,descriptors FROM photos WHERE event_id=?", (event["id"],)).fetchall()
    return jsonify({"event": dict(event), "photos":[{"id":p["id"],"url":url_for("uploaded_file", filename=p["filename"]),"descriptors":json.loads(p["descriptors"] or "[]")} for p in photos]})

@app.route("/api/photo/<int:photo_id>/descriptors", methods=["POST"])
def save_descriptors(photo_id):
    data = request.get_json(silent=True) or {}
    descriptors = data.get("descriptors")
    if not isinstance(descriptors, list) or len(descriptors) > 30:
        return jsonify({"error":"Invalid descriptors"}), 400
    # Each descriptor is a 128-number face embedding generated by face-api.js.
    clean = []
    for d in descriptors:
        if isinstance(d, list) and len(d) == 128 and all(isinstance(x,(int,float)) for x in d):
            clean.append([float(x) for x in d])
    with db() as con:
        cur = con.execute("UPDATE photos SET descriptors=? WHERE id=?", (json.dumps(clean), photo_id))
        if cur.rowcount == 0:
            return jsonify({"error":"Photo not found"}), 404
    return jsonify({"saved":len(clean)})

@app.route("/event/<slug>")
def guest_event(slug):
    with db() as con:
        event = con.execute("SELECT * FROM events WHERE slug=?", (slug,)).fetchone()
    if not event:
        abort(404)
    return render_template("guest.html", event=event)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/logout")
def logout():
    from flask import session
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
