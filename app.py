import os, sqlite3, secrets, json\
from pathlib import Path\
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, abort\
from werkzeug.utils import secure_filename\
\
BASE = Path(\_\_file\_\_).resolve().parent\
UPLOAD_DIR = BASE / "uploads"\
UPLOAD_DIR.mkdir(exist_ok=True)\
DB = BASE / "wedding.db"\
ALLOWED = {"jpg", "jpeg", "png", "webp"}\
\
app = Flask(\_\_name\_\_)\
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deploying")\
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me")\
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")\
\
def db():\
&#x20;   conn = sqlite3.connect(DB)\
&#x20;   conn.row_factory = sqlite3.Row\
&#x20;   return conn\
\
def init_db():\
&#x20;   with db() as con:\
&#x20;       con.execute("""CREATE TABLE IF NOT EXISTS events (\
&#x20;           id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,\
&#x20;           title TEXT NOT NULL, couple TEXT DEFAULT '', date TEXT DEFAULT '',\
&#x20;           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")\
&#x20;       con.execute("""CREATE TABLE IF NOT EXISTS photos (\
&#x20;           id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL,\
&#x20;           filename TEXT NOT NULL, descriptors TEXT DEFAULT '[]',\
&#x20;           FOREIGN KEY(event_id) REFERENCES events(id))""")\
\
init_db()\
\
def allowed(name):\
&#x20;   return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED\
\
@app.route("/")\
def home():\
&#x20;   with db() as con:\
&#x20;       events = con.execute("SELECT \* FROM events ORDER BY id DESC").fetchall()\
&#x20;   return render_template("home.html", events=events)\
\
@app.route("/admin", methods=["GET", "POST"])\
def admin():\
&#x20;   if request.method == "POST":\
&#x20;       if request.form.get("password") != ADMIN_PASSWORD:\
&#x20;           flash("Incorrect admin password.", "error")\
&#x20;           return redirect(url_for("admin"))\
&#x20;       \# Lightweight sessionless admin gate for a starter project.\
&#x20;       from flask import session\
&#x20;       session["admin_ok"] = True\
&#x20;       return redirect(url_for("dashboard"))\
&#x20;   return render_template("admin_login.html")\
\
@app.route("/dashboard")\
def dashboard():\
&#x20;   from flask import session\
&#x20;   if not session.get("admin_ok"):\
&#x20;       return redirect(url_for("admin"))\
&#x20;   with db() as con:\
&#x20;       events = con.execute("""SELECT e.\*, COUNT(p.id) AS photo_count\
&#x20;           FROM events e LEFT JOIN photos p ON p.event_id=e.id\
&#x20;           GROUP BY e.id ORDER BY e.id DESC""").fetchall()\
&#x20;   return render_template("dashboard.html", events=events, site_url=SITE_URL)\
\
@app.route("/events/new", methods=["POST"])\
def create_event():\
&#x20;   from flask import session\
&#x20;   if not session.get("admin_ok"):\
&#x20;       abort(403)\
&#x20;   title = request.form.get("title", "").strip()\
&#x20;   if not title:\
&#x20;       flash("Please enter an event title.", "error")\
&#x20;       return redirect(url_for("dashboard"))\
&#x20;   slug = secrets.token_urlsafe(6).replace("-", "").replace("\_", "")[:9].lower()\
&#x20;   with db() as con:\
&#x20;       con.execute("INSERT INTO events(slug,title,couple,date) VALUES(?,?,?,?)",\
&#x20;                   (slug, title, request.form.get("couple","").strip(), request.form.get("date","")))\
&#x20;   flash("Wedding event created. Upload photos to begin indexing.", "success")\
&#x20;   return redirect(url_for("event_admin", slug=slug))\
\
@app.route("/admin/event/\<slug>/edit", methods=["POST"])\
def edit_event(slug):\
&#x20;   from flask import session\
&#x20;   if not session.get("admin_ok"):\
&#x20;       abort(403)\
&#x20;   title = request.form.get("title", "").strip()\
&#x20;   couple = request.form.get("couple", "").strip()\
&#x20;   date = request.form.get("date", "").strip()\
&#x20;   if not title:\
&#x20;       flash("Wedding title cannot be empty.", "error")\
&#x20;       return redirect(url_for("event_admin", slug=slug))\
&#x20;   with db() as con:\
&#x20;       cur = con.execute(\
&#x20;           "UPDATE events SET title=?, couple=?, date=? WHERE slug=?",\
&#x20;           (title, couple, date, slug)\
&#x20;       )\
&#x20;       if cur.rowcount == 0:\
&#x20;           abort(404)\
&#x20;   flash("Wedding details updated successfully.", "success")\
&#x20;   return redirect(url_for("event_admin", slug=slug))\
\
@app.route("/admin/event/\<slug>", methods=["GET", "POST"])\
def event_admin(slug):\
&#x20;   from flask import session\
&#x20;   if not session.get("admin_ok"):\
&#x20;       abort(403)\
&#x20;   with db() as con:\
&#x20;       event = con.execute("SELECT \* FROM events WHERE slug=?", (slug,)).fetchone()\
&#x20;       photos = con.execute("SELECT \* FROM photos WHERE event_id=? ORDER BY id DESC", (event["id"],)).fetchall() if event else []\
&#x20;   if not event:\
&#x20;       abort(404)\
&#x20;   if request.method == "POST":\
&#x20;       count = 0\
&#x20;       for f in request.files.getlist("photos"):\
&#x20;           if not f or not f.filename or not allowed(f.filename):\
&#x20;               continue\
&#x20;           ext = f.filename.rsplit(".", 1)[1].lower()\
&#x20;           filename = secure_filename(f"{secrets.token_hex(8)}.{ext}")\
&#x20;           f.save(UPLOAD_DIR / filename)\
&#x20;           with db() as con:\
&#x20;               con.execute("INSERT INTO photos(event_id,filename) VALUES(?,?)", (event["id"], filename))\
&#x20;           count += 1\
&#x20;       flash(f"Uploaded {count} photo(s). Open the event page and use Index photos on this device to prepare face matches.", "success")\
&#x20;       return redirect(url_for("event_admin", slug=slug))\
&#x20;   public_url = (SITE_URL or request.url_root.rstrip("/")) + url_for("guest_event", slug=slug)\
&#x20;   return render_template("event_admin.html", event=event, photos=photos, public_url=public_url)\
\
@app.route("/api/event/\<slug>/photos")\
def photo_data(slug):\
&#x20;   with db() as con:\
&#x20;       event = con.execute("SELECT \* FROM events WHERE slug=?", (slug,)).fetchone()\
&#x20;       if not event:\
&#x20;           return jsonify({"error":"Event not found"}), 404\
&#x20;       photos = con.execute("SELECT id,filename,descriptors FROM photos WHERE event_id=?", (event["id"],)).fetchall()\
&#x20;   return jsonify({"event": dict(event), "photos":[{"id":p["id"],"url":url_for("uploaded_file", filename=p["filename"]),"descriptors":json.loads(p["descriptors"] or "[]")} for p in photos]})\
\
@app.route("/api/photo/\<int:photo_id>/descriptors", methods=["POST"])\
def save_descriptors(photo_id):\
&#x20;   data = request.get_json(silent=True) or {}\
&#x20;   descriptors = data.get("descriptors")\
&#x20;   if not isinstance(descriptors, list) or len(descriptors) > 30:\
&#x20;       return jsonify({"error":"Invalid descriptors"}), 400\
&#x20;   \# Each descriptor is a 128-number face embedding generated by face-api.js.\
&#x20;   clean = []\
&#x20;   for d in descriptors:\
&#x20;       if isinstance(d, list) and len(d) == 128 and all(isinstance(x,(int,float)) for x in d):\
&#x20;           clean.append([float(x) for x in d])\
&#x20;   with db() as con:\
&#x20;       cur = con.execute("UPDATE photos SET descriptors=? WHERE id=?", (json.dumps(clean), photo_id))\
&#x20;       if cur.rowcount == 0:\
&#x20;           return jsonify({"error":"Photo not found"}), 404\
&#x20;   return jsonify({"saved":len(clean)})\
\
@app.route("/event/\<slug>")\
def guest_event(slug):\
&#x20;   with db() as con:\
&#x20;       event = con.execute("SELECT \* FROM events WHERE slug=?", (slug,)).fetchone()\
&#x20;   if not event:\
&#x20;       abort(404)\
&#x20;   return render_template("guest.html", event=event)\
\
@app.route("/uploads/\<path:filename>")\
def uploaded_file(filename):\
&#x20;   return send_from_directory(UPLOAD_DIR, filename)\
\
@app.route("/logout")\
def logout():\
&#x20;   from flask import session\
&#x20;   session.clear()\
&#x20;   return redirect(url_for("home"))\
\
if \_\_name\_\_ == "\_\_main\_\_":\
&#x20;   app.run(debug=True, host="127.0.0.1", port=5000)
