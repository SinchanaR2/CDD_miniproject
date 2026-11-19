import os, sqlite3, uuid
from functools import wraps
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
    UPLOAD_FOLDER=os.path.join(BASE, "static", "uploads"),
    DATABASE=os.environ.get("DATABASE_PATH", os.path.join(BASE, "roadraksh.db")),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
ISSUE_TYPES = ["Pothole", "Cracked Road", "Waterlogging", "Broken Footpath",
               "Missing Signage", "Other"]
STATUSES = ["Pending", "In Progress", "Resolved"]
REASONS = ["Duplicate report", "Spam / fake report", "Wrong or invalid location", "Issue already fixed", "Other"]
ALLOWED = {"png", "jpg", "jpeg", "webp"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, is_admin INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, issue_type TEXT NOT NULL,
  description TEXT NOT NULL, address TEXT, lat REAL NOT NULL, lng REAL NOT NULL,
  photo TEXT, status TEXT DEFAULT 'Pending', admin_note TEXT, archived INTEGER DEFAULT 0, archive_reason TEXT, archived_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript(SCHEMA)
    have = [c[1] for c in db.execute("PRAGMA table_info(reports)")]
    for col, ddl in (("archived", "INTEGER DEFAULT 0"), ("archive_reason", "TEXT"), ("archived_at", "TEXT")):
        if col not in have:  # upgrade an older database safely
            db.execute(f"ALTER TABLE reports ADD COLUMN {col} {ddl}")
    if not db.execute("SELECT 1 FROM users").fetchone():
        db.execute("INSERT INTO users(name,email,password,is_admin) VALUES(?,?,?,1)",
                   ("Admin", "admin@roadraksh.com", generate_password_hash("admin123")))
        demo = [
            ("Pothole", "Deep pothole near the signal, dangerous for two-wheelers.", "MG Road, Bengaluru", 12.9756, 77.6068, "Pending"),
            ("Waterlogging", "Road floods after every rain.", "Silk Board Junction", 12.9177, 77.6233, "In Progress"),
            ("Cracked Road", "Long cracks across the lane.", "Indiranagar 100ft Road", 12.9784, 77.6408, "Resolved"),
            ("Broken Footpath", "Footpath slabs broken, unsafe for pedestrians.", "Jayanagar 4th Block", 12.9250, 77.5938, "Pending"),
        ]
        db.executemany("INSERT INTO reports(user_id,issue_type,description,address,lat,lng,status) VALUES(1,?,?,?,?,?,?)", demo)
    db.commit()
    db.close()

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if "uid" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("is_admin"):
            flash("Admin access only.", "danger")
            return redirect(url_for("login"))
        return f(*a, **k)
    return w

@app.route("/")
def index():
    db = get_db()
    stats = {s: db.execute("SELECT COUNT(*) c FROM reports WHERE archived=0 AND status=?", (s,)).fetchone()["c"] for s in STATUSES}
    stats["Total"] = sum(stats.values())
    recent = db.execute("SELECT * FROM reports WHERE archived=0 ORDER BY id DESC LIMIT 3").fetchall()
    return render_template("index.html", stats=stats, recent=recent)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        n, e, p = (request.form.get(x, "").strip() for x in ("name", "email", "password"))
        if not (n and e and len(p) >= 6):
            flash("Fill all fields (password min 6 characters).", "danger")
        else:
            try:
                db = get_db()
                db.execute("INSERT INTO users(name,email,password) VALUES(?,?,?)",
                           (n, e.lower(), generate_password_hash(p)))
                db.commit()
                flash("Account created! Please log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Email already registered.", "danger")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = get_db().execute("SELECT * FROM users WHERE email=?",
                             (request.form.get("email", "").strip().lower(),)).fetchone()
        if u and check_password_hash(u["password"], request.form.get("password", "")):
            session.update(uid=u["id"], name=u["name"], is_admin=bool(u["is_admin"]))
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("admin" if u["is_admin"] else "index"))
        flash("Invalid email or password.", "danger")
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/report", methods=["GET", "POST"])
@login_required
def report():
    if request.method == "POST":
        f = request.form
        try:
            lat, lng = float(f["lat"]), float(f["lng"])
        except (KeyError, ValueError):
            flash("Please pin the location on the map.", "danger")
            return render_template("report.html", types=ISSUE_TYPES)
        file = request.files.get("photo")
        if (f.get("issue_type") not in ISSUE_TYPES or not f.get("description", "").strip()
                or not f.get("address", "").strip() or not (file and file.filename)):
            flash("Complaint type, description, address and photo are all required.", "danger")
            return render_template("report.html", types=ISSUE_TYPES)
        photo = None
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in ALLOWED:
                photo = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(photo)))
        db = get_db()
        cur = db.execute(
            "INSERT INTO reports(user_id,issue_type,description,address,lat,lng,photo) VALUES(?,?,?,?,?,?,?)",
            (session["uid"], f["issue_type"], f["description"].strip(), f.get("address", "").strip(), lat, lng, photo))
        db.commit()
        flash(f"Report #{cur.lastrowid} submitted. Thank you for making roads safer!", "success")
        return redirect(url_for("my_reports"))
    return render_template("report.html", types=ISSUE_TYPES)

@app.route("/reports")
def reports():
    status = request.args.get("status", "")
    q, a = "SELECT * FROM reports WHERE archived=0", ()
    if status in STATUSES:
        q, a = q + " AND status=?", (status,)
    rows = get_db().execute(q + " ORDER BY id DESC", a).fetchall()
    return render_template("reports.html", reports=rows, statuses=STATUSES, current=status)

def matches(r, q, fields):
    return not q or q in " ".join(str(r[f] or "") for f in fields).lower()

@app.route("/my-reports")
@login_required
def my_reports():
    status = request.args.get("status", "")
    q = request.args.get("q", "").strip().lower()
    rows = get_db().execute("SELECT * FROM reports WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    active = [r for r in rows if not r["archived"]]
    removed = [r for r in rows if r["archived"]]
    base = removed if status == "Archived" else [r for r in active if status not in STATUSES or r["status"] == status]
    if status not in STATUSES and status != "Archived":
        base = rows
    shown = [r for r in base if matches(r, q, ("id", "issue_type", "description", "address", "admin_note", "archive_reason"))]
    counts = {s: sum(1 for r in active if r["status"] == s) for s in STATUSES}
    return render_template("my_reports.html", reports=shown, total=len(active), statuses=STATUSES,
                           counts=counts, removed=len(removed), current=status, q=q)

@app.route("/profile")
@login_required
def profile():
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    total = db.execute("SELECT COUNT(*) c FROM reports WHERE archived=0 AND user_id=?", (session["uid"],)).fetchone()["c"]
    done = db.execute("SELECT COUNT(*) c FROM reports WHERE archived=0 AND user_id=? AND status='Resolved'", (session["uid"],)).fetchone()["c"]
    return render_template("profile.html", user=user, total=total, done=done)

@app.route("/api/reports")
def api_reports():
    rows = get_db().execute("SELECT id,issue_type,description,address,lat,lng,status,photo,created_at FROM reports WHERE archived=0").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/admin")
@admin_required
def admin():
    rows = get_db().execute("SELECT r.*, u.name AS reporter FROM reports r LEFT JOIN users u ON u.id=r.user_id ORDER BY r.id DESC").fetchall()
    active = [r for r in rows if not r["archived"]]
    archived = [r for r in rows if r["archived"]]
    counts = {s: sum(1 for r in active if r["status"] == s) for s in STATUSES}
    by_type = {}
    for r in active:
        by_type[r["issue_type"]] = by_type.get(r["issue_type"], 0) + 1
    view = "archived" if request.args.get("view") == "archived" else ""
    status = "" if view else request.args.get("status", "")
    q = request.args.get("q", "").strip()
    shown = archived if view else active
    if status in STATUSES:
        shown = [r for r in shown if r["status"] == status]
    if q.startswith("#") and q[1:].isdigit():
        shown = [r for r in shown if r["id"] == int(q[1:])]
    else:
        shown = [r for r in shown if matches(r, q.lstrip("#").lower(), ("id", "issue_type", "description", "address", "reporter", "admin_note", "status", "archive_reason"))]
    return render_template("admin.html", reports=active, shown=shown, statuses=STATUSES, counts=counts,
                           by_type=by_type, q=q, current=status, view=view,
                           archived_count=len(archived), reasons=REASONS)

@app.route("/admin/update/<int:rid>", methods=["POST"])
@admin_required
def update(rid):
    st = request.form.get("status")
    if st in STATUSES:
        db = get_db()
        db.execute("UPDATE reports SET status=?, admin_note=? WHERE id=?", (st, request.form.get("note", "").strip(), rid))
        db.commit()
        flash(f"Report #{rid} updated to {st}.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/archive/<int:rid>", methods=["POST"])
@admin_required
def archive(rid):
    reason = request.form.get("reason", "")
    if reason not in REASONS:
        flash("Please choose a reason before archiving.", "danger")
        return redirect(url_for("admin"))
    detail = request.form.get("detail", "").strip()
    full = reason + (": " + detail if detail else "")
    db = get_db()
    db.execute("UPDATE reports SET archived=1, archive_reason=?, archived_at=CURRENT_TIMESTAMP WHERE id=?", (full, rid))
    db.commit()
    flash(f"Report #{rid} archived. You can restore it from the Archived tab.", "info")
    return redirect(url_for("admin"))

@app.route("/admin/restore/<int:rid>", methods=["POST"])
@admin_required
def restore(rid):
    db = get_db()
    db.execute("UPDATE reports SET archived=0, archive_reason=NULL, archived_at=NULL WHERE id=?", (rid,))
    db.commit()
    flash(f"Report #{rid} restored.", "success")
    return redirect(url_for("admin", view="archived"))

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
