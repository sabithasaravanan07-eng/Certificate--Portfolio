"""End-to-end checks. Run:  python test_app.py
Uses a temporary data folder, so your real database and certificates are never touched."""
import base64, io, os, re, tempfile

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, DATABASE_URL="", ADMIN_USERNAME="admin", ADMIN_PASSWORD="correct-horse-battery",
                  SECRET_KEY="test-key", OWNER_FOCUS="I design and learn through practical projects.",
                  OWNER_ABOUT="I value curiosity, teamwork, and learning through practice.",
                  OWNER_EDUCATION="B.Tech in Information Technology — Example College, Full Stack certificate — Example",
                  OWNER_SPECIALTIES="HTML5, Python, Flask",
                  OWNER_HIGHLIGHTS="My Brain Battle team won two prizes, Participated in a code-debugging event",
                  OWNER_LOCATION="Open to collaboration")
import app as portfolio  # noqa: E402

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
checks = []
def check(name, cond):
    checks.append(cond); print(("PASS  " if cond else "FAIL  ") + name)

def csrf(c, path="/admin/login"):
    return re.search(r'name="_csrf" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)

c = portfolio.app.test_client()
anon = portfolio.app.test_client()

# --- public site works with no certificates
for path in ["/", "/about", "/certificates", "/certificates/major", "/certificates/workshops",
             "/certificates/courses", "/certificates/achievements", "/sitemap.xml", "/robots.txt"]:
    check(f"public {path} loads (empty)", c.get(path).status_code == 200)
check("unknown section is 404", c.get("/certificates/nope").status_code == 404)

# --- admin is protected
for path in ["/admin", "/admin/certificates", "/admin/certificates/new", "/admin/profile",
             "/admin/backup", "/admin/password"]:
    r = anon.get(path); check(f"anonymous blocked from {path}", r.status_code == 302 and "/admin/login" in r.location)
check("anonymous cannot POST delete (CSRF/auth)", anon.post("/admin/certificates/1/delete").status_code == 400)

# --- login
r = c.post("/admin/login", data={"_csrf": csrf(c), "username": "admin", "password": "wrong"})
check("wrong password rejected", b"incorrect" in r.data and not r.headers.get("Location"))
r = c.post("/admin/login", data={"_csrf": csrf(c), "username": "admin", "password": "correct-horse-battery"})
check("login succeeds", r.status_code == 302)
check("dashboard loads", c.get("/admin").status_code == 200)
check("password stored hashed", "pbkdf2" in portfolio.sqlite3.connect(portfolio.DB_PATH).execute("select password_hash from admins").fetchone()[0] or "scrypt" in portfolio.sqlite3.connect(portfolio.DB_PATH).execute("select password_hash from admins").fetchone()[0])

def add(title, cat, data, name, year="2024-05-10", featured=True, extra=None):
    t = csrf(c, "/admin/certificates/new")
    form = {"_csrf": t, "title": title, "category": cat, "issuer": "Test Org", "completion_date": year,
            "duration": "3 hours", "skills": "Python, Flask", "description": "Desc",
            "verification_url": "https://example.com/verify", "file": (io.BytesIO(data), name)}
    if featured: form["is_featured"] = "1"
    form.update(extra or {})
    return c.post("/admin/certificates/new", data=form, content_type="multipart/form-data")

# --- upload
check("upload PDF as Major Certification", add("Full Stack Development", "Major Certification", PDF, "a.pdf").status_code == 302)
check("upload PNG as Participation", add("Brain Battle Second Prize", "Participation", PNG, "b.png", "2023-02-01", False).status_code == 302)
check("upload Short-Term Course", add("Git in 2 Hours", "Short-Term Course", PDF, "c.pdf", "2022-01-01", False).status_code == 302)
check("upload Workshop", add("AI Masterclass", "Masterclass / Workshop", PNG, "d.png", "2025-03-03", False).status_code == 302)

# --- validation
check("fake .pdf (really text) rejected", add("Bad", "Achievement", b"hello", "x.pdf").status_code == 400)
check("disallowed .exe rejected", add("Bad", "Achievement", b"MZ", "x.exe").status_code == 400)
check("missing file rejected", c.post("/admin/certificates/new", data={"_csrf": csrf(c, "/admin/certificates/new"), "title": "x", "category": "Achievement", "issuer": "y", "completion_date": "2024-01-01"}).status_code == 400)
check("bad URL rejected", add("Bad", "Achievement", PDF, "x.pdf", extra={"verification_url": "javascript:alert(1)"}).status_code == 400)
check("only 4 certificates stored", portfolio.sqlite3.connect(portfolio.DB_PATH).execute("select count(*) from certificates").fetchone()[0] == 4)
check("only 4 files on disk", len(list(portfolio.UPLOAD_DIR.iterdir())) == 4)

# --- public display in the right sections (no login)
check("Major section shows Full Stack", b"Full Stack Development" in anon.get("/certificates/major").data)
check("Major section hides others", b"Brain Battle" not in anon.get("/certificates/major").data)
check("Achievements shows Brain Battle", b"Brain Battle Second Prize" in anon.get("/certificates/achievements").data)
check("Courses shows short course", b"Git in 2 Hours" in anon.get("/certificates/courses").data)
check("Workshops shows masterclass", b"AI Masterclass" in anon.get("/certificates/workshops").data)
home = anon.get("/").get_data(as_text=True)
check("Home shows portfolio intro and certificate image cards",
      all(text in home for text in ("Every Achievement Has a Story.", "About me",
                                    "Major Certifications", "Full Stack Development", 'class="cert"')))
check("About is a separate page with extra profile details",
      all(text in anon.get("/about").get_data(as_text=True)
          for text in ("I value curiosity, teamwork", "I design and learn", "HTML5",
                       "B.Tech in Information Technology", "Full Stack certificate — Example",
                       "Kavery Chatbot", "New Drop Taxi", "My Brain Battle team won two prizes",
                       "Open to collaboration")))
collection = anon.get("/certificates").get_data(as_text=True)
check("All certificates page shows uploaded certificates",
      all(text in collection for text in ("All Certificates", "Full Stack Development", "4 certificates")))
check("Public certificate pages have no search/filter bar",
      'class="filters"' not in collection and 'type="search"' not in collection and "Search by name" not in collection)
check("search by name", b"Git in 2 Hours" in anon.get("/certificates?q=git").data and b"Brain Battle" not in anon.get("/certificates?q=git").data)
check("filter by year", b"Brain Battle" in anon.get("/certificates?year=2023").data and b"Git in 2" not in anon.get("/certificates?year=2023").data)
check("filter by category", b"AI Masterclass" not in anon.get("/certificates?category=Participation").data)
check("filter by issuer", b"AI Masterclass" in anon.get("/certificates?issuer=Test+Org").data)
html = anon.get("/certificates?sort=oldest").get_data(as_text=True)
check("sort oldest first", html.index("Git in 2 Hours") < html.index("AI Masterclass"))
html = anon.get("/certificates?sort=newest").get_data(as_text=True)
check("sort newest first", html.index("AI Masterclass") < html.index("Git in 2 Hours"))
check("preview data + dialog present", 'id="cert-data"' in html and 'id="preview"' in html)
check("sitemap lists About and certificate sections",
      b"/about" in anon.get("/sitemap.xml").data and b"/certificates/major" in anon.get("/sitemap.xml").data)

# --- file preview + download (public)
row = portfolio.sqlite3.connect(portfolio.DB_PATH).execute("select id,file_path from certificates where title='Full Stack Development'").fetchone()
cid, fname = row
r = anon.get(f"/files/{fname}"); check("PDF preview serves inline", r.status_code == 200 and r.data == PDF and "attachment" not in r.headers.get("Content-Disposition", ""))
r = anon.get(f"/files/{fname}?download=1"); check("download forces attachment with readable name", "attachment" in r.headers["Content-Disposition"] and "Full-Stack-Development.pdf" in r.headers["Content-Disposition"])
check("unknown file 404", anon.get("/files/nothing.pdf").status_code == 404)
check("path traversal blocked", anon.get("/files/..%2Fportfolio.db").status_code == 404)

# --- edit (details + category + replace file)
t = csrf(c, f"/admin/certificates/{cid}/edit")
r = c.post(f"/admin/certificates/{cid}/edit", data={"_csrf": t, "title": "Full Stack Development (Updated)", "category": "Short-Term Course",
    "issuer": "New Org", "completion_date": "2024-06-01", "duration": "6 months", "skills": "A, B", "description": "x",
    "verification_url": "", "file": (io.BytesIO(PNG), "new.png")}, content_type="multipart/form-data")
check("edit saves", r.status_code == 302)
check("edited cert moved to Courses section", b"Full Stack Development (Updated)" in anon.get("/certificates/courses").data)
check("edited cert left Major section", b"Full Stack Development" not in anon.get("/certificates/major").data)
check("old file removed, new file stored", not (portfolio.UPLOAD_DIR / fname).exists() and len(list(portfolio.UPLOAD_DIR.iterdir())) == 4)
t = csrf(c, f"/admin/certificates/{cid}/edit")
r = c.post(f"/admin/certificates/{cid}/edit", data={"_csrf": t, "title": "Keep file", "category": "Major Certification", "issuer": "o", "completion_date": "2024-06-01"}, content_type="multipart/form-data")
check("edit without new file keeps existing file", r.status_code == 302 and len(list(portfolio.UPLOAD_DIR.iterdir())) == 4)

# --- feature toggle
t = csrf(c, "/admin/certificates")
c.post(f"/admin/certificates/{cid}/feature", data={"_csrf": t})
check("feature toggle works", portfolio.sqlite3.connect(portfolio.DB_PATH).execute("select is_featured from certificates where id=?", (cid,)).fetchone()[0] == 1)

# --- admin search/list, backup
check("admin search", b"Keep file" in c.get("/admin/certificates?q=keep").data)
r = c.get("/admin/backup"); check("backup zip downloads", r.status_code == 200 and r.data[:2] == b"PK")

# --- delete
r = c.post(f"/admin/certificates/{cid}/delete", data={"_csrf": csrf(c, "/admin/certificates")})
check("delete works", r.status_code == 302 and b"Keep file" not in anon.get("/certificates").data)
check("delete removed the file", len(list(portfolio.UPLOAD_DIR.iterdir())) == 3)

# --- password change + logout
t = csrf(c, "/admin/password")
r = c.post("/admin/password", data={"_csrf": t, "current": "correct-horse-battery", "new": "another-long-password", "confirm": "another-long-password"})
check("password change works", r.status_code == 302)
c.post("/admin/logout", data={"_csrf": csrf(c, "/admin")})
check("logout blocks admin", c.get("/admin").status_code == 302)
r = c.post("/admin/login", data={"_csrf": csrf(c), "username": "admin", "password": "another-long-password"})
check("login with new password", r.status_code == 302)

# --- XSS escaping
add("<script>alert(1)</script>", "Achievement", PDF, "z.pdf")
check("titles are HTML-escaped", b"<script>alert(1)</script>" not in anon.get("/certificates").data.replace(b'type="application/json"', b''))
check("security headers set", anon.get("/").headers.get("X-Content-Type-Options") == "nosniff")

# --- database configuration adapter
class ExecuteRecorder:
    def cursor(self):
        return self

    def execute(self, query, params):
        self.query, self.params = query, params
        return self

recorder = ExecuteRecorder()
portfolio.PostgresDatabase(recorder).execute(
    "SELECT * FROM certificates WHERE id=? AND title=?", (7, "Example"))
check("PostgreSQL adapter converts SQLite-style placeholders",
      recorder.query == "SELECT * FROM certificates WHERE id=%s AND title=%s"
      and recorder.params == (7, "Example"))

# --- website profile management
check("admin dashboard links to profile editor", b"Edit website profile" in c.get("/admin").data)
with portfolio.app.app_context():
    profile = portfolio.get_site_profile()
profile_data = {
    "_csrf": csrf(c, "/admin/profile"),
    "name": profile["name"],
    "owner": "Updated Owner",
    "tagline": "A new portfolio heading",
    "description": "A saved profile description",
    "intro": "A new homepage introduction",
    "about": "A new About page biography",
    "focus": "Learning through practical projects",
    "location": "Salem",
    "email": "owner@example.com",
    "linkedin": "https://linkedin.com/in/example",
    "github": "https://github.com/example",
    "portfolio": "https://example.com",
    "education": "B.Tech in Information Technology",
    "specialties": "Python, Flask",
    "highlights": "Built a portfolio",
    "projects": "Portfolio | A personal project | https://example.com/project",
}
profile_data["photo"] = (io.BytesIO(PNG), "portrait.png")
r = c.post("/admin/profile", data=profile_data, content_type="multipart/form-data")
check("profile editor saves text and redirects", r.status_code == 302)
check("updated profile appears on public pages",
      b"A new portfolio heading" in anon.get("/").data
      and b"A new About page biography" in anon.get("/about").data
      and b"Portfolio" in anon.get("/about").data)
with portfolio.app.app_context():
    saved_profile = portfolio.get_site_profile()
check("profile persists in the database with uploaded photo",
      saved_profile["owner"] == "Updated Owner" and saved_profile["photo"]
      and anon.get("/profile-photo").data == PNG)
invalid_profile = dict(profile_data)
invalid_profile.pop("photo")
invalid_profile["_csrf"] = csrf(c, "/admin/profile")
invalid_profile["linkedin"] = "javascript:alert(1)"
r = c.post("/admin/profile", data=invalid_profile)
with portfolio.app.app_context():
    unchanged_profile = portfolio.get_site_profile()
check("invalid profile URL is rejected without replacing saved content",
      r.status_code == 400 and unchanged_profile["owner"] == "Updated Owner")
portfolio.set_admin_password("bootstrap-check", "first-bootstrap-password")
portfolio.set_admin_password("bootstrap-check", "second-bootstrap-password")
bootstrap_hash = portfolio.sqlite3.connect(portfolio.DB_PATH).execute(
    "SELECT password_hash FROM admins WHERE username='bootstrap-check'"
).fetchone()[0]
check("admin bootstrap can safely rerun without duplicate usernames",
      portfolio.check_password_hash(bootstrap_hash, "second-bootstrap-password"))

print(f"\n{sum(checks)}/{len(checks)} checks passed")
raise SystemExit(0 if all(checks) else 1)
