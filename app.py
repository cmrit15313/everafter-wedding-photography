from supabase import create_client
import mimetypes
import os, sqlite3, secrets, json
from pathlib import Path
from io import BytesIO
import qrcode
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, send_file, abort
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
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_BUCKET = "wedding-photos"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the Render environment.")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def storage_signed_url(path, expires_in=86400):
    """Return a time-limited URL for an object in the private Supabase bucket."""
    result = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, expires_in)
    if isinstance(result, dict):
        signed = result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
    else:
        signed = getattr(result, "signed_url", None) or getattr(result, "signedURL", None)
    if not signed:
        raise RuntimeError("Supabase did not return a signed download URL.")
    if signed.startswith("/"):
        signed = SUPABASE_URL.rstrip("/") + "/storage/v1" + signed
    return signed

def photo_url(filename):
    # Keep compatibility with older files that still exist on the local disk.
    local_file = UPLOAD_DIR / filename
    if "/" not in filename and local_file.is_file():
        return url_for("uploaded_file", filename=filename)
    return storage_signed_url(filename)

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
        abort(405)
    public_url = (SITE_URL or request.url_root.rstrip("/")) + url_for("guest_event", slug=slug)
    gallery_photos = []
    for p in photos:
        try:
            gallery_photos.append({"filename": p["filename"], "url": photo_url(p["filename"])})
        except Exception:
            app.logger.exception("Could not create photo URL for %s", p["filename"])
    return render_template("event_admin.html", event=event, photos=gallery_photos, public_url=public_url, supabase_anon_key=SUPABASE_ANON_KEY, supabase_url=SUPABASE_URL)

@app.route("/api/event/<slug>/photos")
def photo_data(slug):
    with db() as con:
        event = con.execute("SELECT * FROM events WHERE slug=?", (slug,)).fetchone()
        if not event:
            return jsonify({"error":"Event not found"}), 404
        photos = con.execute("SELECT id,filename,descriptors FROM photos WHERE event_id=?", (event["id"],)).fetchall()
    result = []
    for p in photos:
        try:
            result.append({"id": p["id"], "url": photo_url(p["filename"]), "descriptors": json.loads(p["descriptors"] or "[]")})
        except Exception:
            app.logger.exception("Could not create photo URL for %s", p["filename"])
    return jsonify({"event": dict(event), "photos": result})

@app.route("/api/admin/event/<slug>/upload-token", methods=["POST"])
def create_photo_upload_token(slug):
    from flask import session
    if not session.get("admin_ok"):
        abort(403)
    if not SUPABASE_ANON_KEY:
        return jsonify({"error": "SUPABASE_ANON_KEY is missing from the Render environment."}), 503
    with db() as con:
        event = con.execute("SELECT id FROM events WHERE slug=?", (slug,)).fetchone()
    if not event:
        abort(404)
    # Unique path per upload: never overwrite an existing wedding photo.
    object_path = f"{slug}/{secrets.token_hex(16)}.jpg"
    signed = supabase.storage.from_(SUPABASE_BUCKET).create_signed_upload_url(object_path)
    token = getattr(signed, "token", None)
    if isinstance(signed, dict):
        token = signed.get("token", token)
    if not token:
        return jsonify({"error": "Supabase did not return an upload token."}), 502
    return jsonify({"path": object_path, "token": token, "bucket": SUPABASE_BUCKET})

@app.route("/api/admin/event/<slug>/photos/import-root", methods=["POST"])
def import_existing_root_photos(slug):
    from flask import session
    if not session.get("admin_ok"):
        abort(403)
    with db() as con:
        event = con.execute("SELECT id FROM events WHERE slug=?", (slug,)).fetchone()
        if not event:
            abort(404)
    try:
        objects = supabase.storage.from_(SUPABASE_BUCKET).list()
        imported = 0
        with db() as con:
            for item in objects:
                name = item.get("name", "") if isinstance(item, dict) else ""
                if not name or "/" in name or not allowed(name):
                    continue
                # Only import actual image objects, not folder placeholders.
                if isinstance(item, dict) and item.get("id") is None and item.get("metadata") is None:
                    continue
                exists = con.execute(
                    "SELECT id FROM photos WHERE event_id=? AND filename=?",
                    (event["id"], name)
                ).fetchone()
                if not exists:
                    con.execute("INSERT INTO photos(event_id,filename) VALUES(?,?)", (event["id"], name))
                    imported += 1
        return jsonify({"success": True, "imported": imported})
    except Exception as exc:
        app.logger.exception("Could not import existing root photos from Supabase")
        return jsonify({"error": "Could not read the existing bucket files: " + str(exc)}), 502

@app.route("/api/admin/event/<slug>/photos/complete", methods=["POST"])
def complete_photo_upload(slug):
    from flask import session
    import re
    if not session.get("admin_ok"):
        abort(403)
    data = request.get_json(silent=True) or {}
    object_path = data.get("path", "")
    if not isinstance(object_path, str) or not re.fullmatch(re.escape(slug) + r"/[a-f0-9]{32}\.jpg", object_path):
        return jsonify({"error": "Invalid upload path."}), 400
    with db() as con:
        event = con.execute("SELECT id FROM events WHERE slug=?", (slug,)).fetchone()
        if not event:
            abort(404)
        existing = con.execute("SELECT id FROM photos WHERE event_id=? AND filename=?", (event["id"], object_path)).fetchone()
        if not existing:
            con.execute("INSERT INTO photos(event_id,filename) VALUES(?,?)", (event["id"], object_path))
        photo = con.execute("SELECT id FROM photos WHERE event_id=? AND filename=?", (event["id"], object_path)).fetchone()
    return jsonify({"success": True, "id": photo["id"], "url": storage_signed_url(object_path)})

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
@app.route("/admin/event/<slug>/qr.png")
def event_qr(slug):
    from flask import session

    if not session.get("admin_ok"):
        abort(403)

    with db() as con:
        event = con.execute(
            "SELECT slug FROM events WHERE slug=?", (slug,)
        ).fetchone()

    if not event:
        abort(404)

    public_url = (
        SITE_URL or request.url_root.rstrip("/")
    ) + url_for("guest_event", slug=slug)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4
    )

    qr.add_data(public_url)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)

    return send_file(output, mimetype="image/png")
@app.route("/event/<slug>")
def guest_event(slug):
    with db() as con:
        event = con.execute("SELECT * FROM events WHERE slug=?", (slug,)).fetchone()
    if not event:
        abort(404)
    return render_template("guest.html", event=event)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Older local uploads remain readable; Supabase objects use short-lived signed URLs.
    local_file = UPLOAD_DIR / filename
    if local_file.is_file():
        return send_from_directory(UPLOAD_DIR, filename)
    return redirect(storage_signed_url(filename))

@app.route("/logout")
def logout():
    from flask import session
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
