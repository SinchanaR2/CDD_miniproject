import io, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as a

def client():
    a.app.config["DATABASE"] = os.path.join(tempfile.mkdtemp(), "t.db")
    a.init_db()
    a.app.config["TESTING"] = True
    return a.app.test_client()

def test_home_and_api():
    c = client()
    assert c.get("/").status_code == 200
    assert len(c.get("/api/reports").get_json()) == 4

def test_report_requires_login():
    assert client().get("/report").status_code == 302

def test_register_login_report():
    c = client()
    c.post("/register", data={"name": "T", "email": "t@t.com", "password": "secret1"})
    c.post("/login", data={"email": "t@t.com", "password": "secret1"})
    r = c.post("/report", data={"issue_type": "Pothole", "description": "big", "address": "MG Road", "lat": "12.9", "lng": "77.6", "photo": (io.BytesIO(b"fake"), "a.jpg")})
    assert r.status_code == 302
    assert len(c.get("/api/reports").get_json()) == 5

def test_admin_update():
    c = client()
    c.post("/login", data={"email": "admin@roadraksh.com", "password": "admin123"})
    assert c.get("/admin").status_code == 200
    c.post("/admin/update/1", data={"status": "Resolved"})
    assert c.get("/api/reports").get_json()[0]["status"] == "Resolved"

def test_report_needs_photo_and_address():
    c = client()
    c.post("/login", data={"email": "admin@roadraksh.com", "password": "admin123"})
    c.post("/report", data={"issue_type": "Pothole", "description": "x", "lat": "1", "lng": "2"})
    assert len(c.get("/api/reports").get_json()) == 4

def test_profile_tracker_admin_search():
    c = client()
    c.post("/login", data={"email": "admin@roadraksh.com", "password": "admin123"})
    assert c.get("/profile").status_code == 200
    assert c.get("/my-reports?status=Pending&q=pothole").status_code == 200
    assert b"Showing 1 of 4" in c.get("/admin?q=%231").data

def admin_client():
    c = client()
    c.post("/login", data={"email": "admin@roadraksh.com", "password": "admin123"})
    return c

def test_archive_hides_and_restore_brings_back():
    c = admin_client()
    c.post("/admin/archive/1", data={"reason": "Duplicate report", "detail": "same as #2"})
    assert len(c.get("/api/reports").get_json()) == 3
    assert b"Duplicate report: same as #2" in c.get("/admin?view=archived").data
    assert b"Duplicate report: same as #2" in c.get("/my-reports").data
    assert b"Showing 3 of 3" in c.get("/admin").data
    c.post("/admin/restore/1")
    assert len(c.get("/api/reports").get_json()) == 4

def test_archive_requires_valid_reason():
    c = admin_client()
    c.post("/admin/archive/1", data={"reason": "bogus"})
    assert len(c.get("/api/reports").get_json()) == 4

def test_citizen_cannot_archive():
    c = client()
    assert c.post("/admin/archive/1", data={"reason": "Duplicate report"}).status_code == 302
    assert len(c.get("/api/reports").get_json()) == 4

def test_old_database_is_upgraded():
    import sqlite3
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,email TEXT UNIQUE,password TEXT,is_admin INTEGER DEFAULT 0);"
                     "CREATE TABLE reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,issue_type TEXT,description TEXT,address TEXT,lat REAL,lng REAL,photo TEXT,status TEXT DEFAULT 'Pending',admin_note TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);"
                     "INSERT INTO users(name,email,password,is_admin) VALUES('A','a@a.com','x',1);"
                     "INSERT INTO reports(user_id,issue_type,description,address,lat,lng) VALUES(1,'Pothole','old','x',1,2);")
    db.commit(); db.close()
    a.app.config["DATABASE"] = path
    a.init_db(); a.app.config["TESTING"] = True
    assert len(a.app.test_client().get("/api/reports").get_json()) == 1
