"""Sabitha's Certificate Portfolio: Flask application.

Everything the site does lives in this file:
  1. Settings (edit SITE below to change your name, intro and links)
  2. Database helpers (SQLite)
  3. Public pages (home, sections, certificate files, sitemap, robots)
  4. Admin pages (login, dashboard, add / edit / delete, password, backup)
"""
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import ssl
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import warnings
import zipfile
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit

import click
from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

# ----------------------------------------------------------------------------
# 1. Settings
# ----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET") or "certificate-uploads"
SUPABASE_STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
IS_VERCEL = os.environ.get("VERCEL") == "1"
if any((SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)) and not SUPABASE_STORAGE_ENABLED:
    raise RuntimeError("Set both SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to enable Supabase Storage.")
if IS_VERCEL:
    missing = []
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not SUPABASE_STORAGE_ENABLED:
        missing.extend(["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
    if not os.environ.get("SECRET_KEY"):
        missing.append("SECRET_KEY")
    if missing:
        raise RuntimeError("Vercel requires these environment variables: " + ", ".join(missing))
# SQLite and local uploads live in DATA_DIR, outside the code.
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "portfolio.db"
if not DATABASE_URL:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
if not SUPABASE_STORAGE_ENABLED:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def parse_list_setting(value, default):
    if value is None:
        return default
    items = [item.strip() for item in str(value).split(",")]
    return [item for item in items if item]


# Edit these values to personalise the site (or set the matching environment variables).
SITE = {
    "name": "Sabitha's Certificate Portfolio",
    "owner": os.environ.get("OWNER_NAME", "Sabitha S"),
    "tagline": "Every Achievement Has a Story.",
    "description": ("Sabitha S is a B.Tech Information Technology student and full-stack "
                    "developer sharing her certificates, projects and learning journey."),
    "intro": os.environ.get(
        "OWNER_INTRO",
        "I’m Sabitha S, a B.Tech Information Technology student interested in web and "
        "full-stack development. This portfolio brings together my certificates and projects."),
    "about": os.environ.get(
        "OWNER_ABOUT",
        "I’m studying Information Technology at The Kavery Engineering College. I enjoy "
        "building useful web experiences, solving problems, and learning by working on projects."),
    "focus": os.environ.get(
        "OWNER_FOCUS",
        "I’m curious, driven, and interested in full-stack development. I like turning ideas "
        "into clean, functional digital experiences and exploring new technologies."),
    "education": parse_list_setting(
        os.environ.get("OWNER_EDUCATION"),
        [
            "B.Tech in Information Technology — The Kavery Engineering College (currently pursuing)",
            "Full Stack Development certification — Novi Tech",
            "HDCA six-month course — TCDS",
        ],
    ),
    "specialties": parse_list_setting(
        os.environ.get("OWNER_SPECIALTIES", "HTML5, CSS3, JavaScript, Python, Flask, MySQL, Git, GitHub"),
        ["HTML5", "CSS3", "JavaScript", "Python", "Flask", "MySQL", "Git", "GitHub"],
    ),
    "highlights": parse_list_setting(
        os.environ.get("OWNER_HIGHLIGHTS", "My Brain Battle team won two prizes, Participated in a code-debugging event"),
        ["My Brain Battle team won two prizes", "Participated in a code-debugging event"],
    ),
    "projects": [
        {
            "name": "Kavery Chatbot",
            "description": "A chatbot project built for The Kavery Engineering College.",
            "url": "https://kavery-chat-ai.vercel.app",
        },
        {
            "name": "New Drop Taxi",
            "description": "A full-stack travel-booking website for exploring and booking taxi trips.",
            "url": "https://new-drop-taxi-fd38.vercel.app",
        },
    ],
    "location": os.environ.get("OWNER_LOCATION", "Salem, Tamil Nadu, India"),
    "email": os.environ.get("CONTACT_EMAIL", ""),
    "linkedin": os.environ.get("LINKEDIN_URL", ""),
    "github": os.environ.get("GITHUB_URL", ""),
    "portfolio": os.environ.get("PORTFOLIO_URL", ""),
}

CATEGORIES = ["Major Certification", "Masterclass / Workshop", "Short-Term Course",
              "Participation", "Achievement"]

# slug -> (page title, short description, categories shown)
SECTIONS = {
    "major": ("Major Certifications", "Professional certifications that took sustained effort.",
              ["Major Certification"]),
    "workshops": ("Masterclasses & Workshops",
                  "Masterclasses, online workshops, guest lectures and skill programs.",
                  ["Masterclass / Workshop"]),
    "courses": ("Short-Term Courses",
                "Courses of any length, from two hours to a few weeks.",
                ["Short-Term Course"]),
    "achievements": ("Participation & Achievements",
                     "Competitions, hackathons, college events and prizes.",
                     ["Participation", "Achievement"]),
    "all": ("All Certificates", "Every certificate in one searchable list.", CATEGORIES),
}

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
MAX_UPLOAD_MB = 10

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1" if IS_VERCEL else "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)


def load_secret_key():
    """Use SECRET_KEY from the environment; otherwise create one and keep it in DATA_DIR."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    if IS_VERCEL:
        raise RuntimeError("Set SECRET_KEY in the Vercel project environment variables.")
    key_file = DATA_DIR / ".secret_key"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


app.secret_key = load_secret_key()


# ----------------------------------------------------------------------------
# 2. Database
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    issuer TEXT NOT NULL,
    completion_date TEXT NOT NULL,
    duration TEXT,
    skills TEXT,
    description TEXT,
    file_path TEXT NOT NULL,
    verification_url TEXT,
    is_featured INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS site_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PostgresDatabase:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=()):
        cursor = self.connection.cursor()
        cursor.execute(query.replace("?", "%s"), params)
        return PostgresCursor(cursor)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


class PostgresCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def _as_dict(self, row):
        if row is None:
            return None
        columns = [column[0] for column in self.cursor.description]
        return dict(zip(columns, row))

    def fetchone(self):
        return self._as_dict(self.cursor.fetchone())

    def fetchall(self):
        return [self._as_dict(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        for row in self.cursor:
            yield self._as_dict(row)


def connect_db():
    if DATABASE_URL:
        parsed = urlsplit(DATABASE_URL)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URI from Supabase.")
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        sslmode = query.get("sslmode", "require")
        if sslmode not in {"require", "verify-ca", "verify-full"}:
            raise RuntimeError("Supabase database connections must use TLS (sslmode=require).")
        root_cert = query.get("sslrootcert") or os.environ.get("DATABASE_SSLROOTCERT", "")
        cert_path = Path(root_cert).expanduser() if root_cert and root_cert != "system" else None
        if cert_path and not cert_path.is_file():
            raise RuntimeError("DATABASE_SSLROOTCERT does not point to an existing certificate file.")
        if cert_path or root_cert == "system" or sslmode != "require":
            ssl_context = ssl.create_default_context(
                cafile=str(cert_path) if cert_path else None
            )
        else:
            warnings.warn(
                "Supabase TLS encrypts traffic, but the server certificate is not verified. "
                "Set DATABASE_SSLROOTCERT and sslmode=verify-full to verify the server.",
                RuntimeWarning,
            )
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        try:
            import pg8000.dbapi
        except ImportError as exc:
            raise RuntimeError("Install the project dependencies to use Supabase PostgreSQL.") from exc
        if not parsed.hostname or not parsed.path.strip("/") or not parsed.username:
            raise RuntimeError("DATABASE_URL must include a PostgreSQL host, database, and username.")
        connection = pg8000.dbapi.connect(
            user=unquote(parsed.username),
            password=unquote(parsed.password or ""),
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=unquote(parsed.path.lstrip("/")),
            ssl_context=ssl_context,
            timeout=10,
        )
        return PostgresDatabase(connection)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def get_db():
    if "db" not in g:
        g.db = connect_db()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def set_admin_password(username, password):
    db = connect_db()
    pw = generate_password_hash(password)
    db.execute(
        "INSERT INTO admins (username, password_hash, created_at) VALUES (?,?,?) "
        "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash",
        (username, pw, now_iso()),
    )
    db.commit()
    db.close()


def init_db():
    db = connect_db()
    schema = SCHEMA.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"
    ) if DATABASE_URL else SCHEMA
    if DATABASE_URL:
        for statement in schema.split(";"):
            if statement.strip():
                db.execute(statement)
        db.commit()
    else:
        db.executescript(schema)
    has_admin = db.execute("SELECT 1 FROM admins LIMIT 1").fetchone()
    db.close()
    # First start: create the admin from environment variables (never hard-coded in the code).
    user, pw = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
    if not has_admin and user and pw:
        set_admin_password(user.strip(), pw)


init_db()


@app.cli.command("create-admin")
@click.option("--username", prompt=True)
@click.password_option()
def create_admin_command(username, password):
    """Create the admin account, or reset its password."""
    if len(password) < 10:
        raise click.ClickException("Use a password with at least 10 characters.")
    set_admin_password(username.strip(), password)
    click.echo("Admin saved.")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def fmt_date(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.day} {d:%b %Y}"
    except (TypeError, ValueError):
        return iso or ""


def cert_dict(row):
    ext = row["file_path"].rsplit(".", 1)[-1].lower()
    return {
        "id": row["id"], "title": row["title"], "category": row["category"],
        "issuer": row["issuer"], "completion_date": row["completion_date"],
        "date_display": fmt_date(row["completion_date"]),
        "duration": row["duration"] or "",
        "skills": [s.strip() for s in (row["skills"] or "").split(",") if s.strip()],
        "description": row["description"] or "",
        "verification_url": row["verification_url"] or "",
        "is_featured": bool(row["is_featured"]),
        "is_pdf": ext == "pdf",
        "file_url": url_for("uploaded_file", filename=row["file_path"]),
        "download_url": url_for("uploaded_file", filename=row["file_path"], download=1),
    }


def query_certs(categories=None, q="", issuer="", year="", sort="newest",
                featured_only=False, limit=None):
    sql, params = "SELECT * FROM certificates WHERE 1=1", []
    if categories:
        sql += " AND category IN (%s)" % ",".join("?" * len(categories))
        params += list(categories)
    if q:
        sql += " AND (title LIKE ? OR issuer LIKE ? OR skills LIKE ?)"
        params += [f"%{q}%"] * 3
    if issuer:
        sql += " AND issuer = ?"
        params.append(issuer)
    if year:
        sql += " AND substr(completion_date,1,4) = ?"
        params.append(year)
    if featured_only:
        sql += " AND is_featured = 1"
    sql += " ORDER BY completion_date %s, id DESC" % ("ASC" if sort == "oldest" else "DESC")
    if limit:
        sql += " LIMIT %d" % int(limit)
    return [cert_dict(r) for r in get_db().execute(sql, params).fetchall()]


def get_site_profile():
    row = get_db().execute("SELECT data FROM site_profile WHERE id=1").fetchone()
    return {**SITE, **(json.loads(row["data"]) if row else {})}


PROFILE_FIELDS = (
    "name", "owner", "tagline", "description", "intro", "about", "focus",
    "location", "email", "linkedin", "github", "portfolio",
)
PROFILE_LIMITS = {
    "name": 120, "owner": 100, "tagline": 180, "description": 500,
    "intro": 2000, "about": 2000, "focus": 2000, "location": 200,
    "email": 254, "linkedin": 500, "github": 500, "portfolio": 500,
}


def profile_form_values(profile):
    return {
        **profile,
        "education_text": "\n".join(profile["education"]),
        "specialties_text": ", ".join(profile["specialties"]),
        "highlights_text": "\n".join(profile["highlights"]),
        "projects_text": "\n".join(
            f'{project["name"]} | {project["description"]} | {project["url"]}'
            for project in profile["projects"]
        ),
    }


def parse_profile_form(form):
    profile = {field: form.get(field, "").strip() for field in PROFILE_FIELDS}
    profile["education"] = [line.strip() for line in form.get("education", "").splitlines()
                            if line.strip()]
    profile["specialties"] = [item.strip() for item in form.get("specialties", "").split(",")
                              if item.strip()]
    profile["highlights"] = [line.strip() for line in form.get("highlights", "").splitlines()
                             if line.strip()]
    profile["projects"] = []
    errors = []

    if not profile["owner"]:
        errors.append("Enter your name.")
    for field, limit in PROFILE_LIMITS.items():
        if len(profile[field]) > limit:
            errors.append(f"{field.replace('_', ' ').capitalize()} is too long (maximum {limit} characters).")
    for field in ("linkedin", "github", "portfolio"):
        if profile[field] and not re.match(r"^https?://", profile[field], re.I):
            errors.append(f"{field.capitalize()} link must start with http:// or https://.")
    if profile["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", profile["email"]):
        errors.append("Enter a valid email address.")

    for number, line in enumerate(form.get("projects", "").splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) != 3 or not all(parts):
            errors.append(f"Project line {number} needs a name, description, and URL separated by |.")
            continue
        name, description, url = parts
        if len(name) > 120 or len(description) > 500 or len(url) > 500:
            errors.append(f"Project line {number} is too long.")
        elif not re.match(r"^https?://", url, re.I):
            errors.append(f"Project line {number} URL must start with http:// or https://.")
        else:
            profile["projects"].append({"name": name, "description": description, "url": url})

    return profile, errors


def get_counts():
    rows = get_db().execute("SELECT category, COUNT(*) n FROM certificates GROUP BY category")
    c = {r["category"]: r["n"] for r in rows}
    return {
        "total": sum(c.values()),
        "major": c.get("Major Certification", 0),
        "workshops": c.get("Masterclass / Workshop", 0),
        "courses": c.get("Short-Term Course", 0),
        "achievements": c.get("Participation", 0) + c.get("Achievement", 0),
    }


def supabase_storage_request(method, filename, data=None, content_type=None):
    bucket = quote(SUPABASE_STORAGE_BUCKET, safe="")
    object_name = quote(Path(filename).name, safe="")
    if method == "DELETE":
        url = f"{SUPABASE_URL}/storage/v1/object/{bucket}"
        data = json.dumps({"prefixes": [Path(filename).name]}).encode("utf-8")
        content_type = "application/json"
    else:
        url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{object_name}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
    }
    if content_type:
        headers["Content-Type"] = content_type
    if method == "POST":
        headers["x-upsert"] = "false"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(
            f"Supabase Storage {method} failed with HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Supabase Storage {method} request failed: {exc.reason}") from exc


def read_upload(filename):
    if SUPABASE_STORAGE_ENABLED:
        return supabase_storage_request("GET", filename)
    file_path = UPLOAD_DIR / Path(filename).name
    if not file_path.is_file():
        raise FileNotFoundError(filename)
    return file_path.read_bytes()


def save_upload(file_storage):
    """Validate the type AND the real file content, then store under a random name."""
    name = file_storage.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Upload a PDF, JPG, JPEG or PNG file.")
    head = file_storage.stream.read(8)
    file_storage.stream.seek(0)
    signatures = {"pdf": b"%PDF", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff",
                  "png": b"\x89PNG\r\n\x1a\n"}
    if not head.startswith(signatures[ext]):
        raise ValueError("That file's content does not match its type. Upload a real PDF, JPG or PNG.")
    filename = f"{uuid.uuid4().hex}.{ext}"
    if SUPABASE_STORAGE_ENABLED:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        supabase_storage_request("POST", filename, file_storage.stream.read(), content_type)
    else:
        file_storage.stream.seek(0)
        file_storage.save(UPLOAD_DIR / filename)
    return filename


def remove_file(filename):
    if not filename:
        return
    if SUPABASE_STORAGE_ENABLED:
        supabase_storage_request("DELETE", filename)
        return
    target = UPLOAD_DIR / Path(filename).name
    for attempt in range(6):
        try:
            target.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 5:
                return
            time.sleep(0.1 * (attempt + 1))


FIELD_LIMITS = {"title": 200, "issuer": 150, "duration": 60, "skills": 400,
                "description": 2000, "verification_url": 500}


def parse_form(form):
    d = {k: form.get(k, "").strip() for k in
         ("title", "category", "issuer", "completion_date", "duration", "skills",
          "description", "verification_url")}
    d["is_featured"] = 1 if form.get("is_featured") else 0
    errors = []
    if not d["title"]:
        errors.append("Enter a certificate title.")
    if not d["issuer"]:
        errors.append("Enter the issuing organization.")
    if d["category"] not in CATEGORIES:
        errors.append("Choose a category.")
    try:
        datetime.strptime(d["completion_date"], "%Y-%m-%d")
    except ValueError:
        errors.append("Enter a valid completion date.")
    if d["verification_url"] and not re.match(r"^https?://", d["verification_url"], re.I):
        errors.append("The verification link must start with http:// or https://")
    for field, limit in FIELD_LIMITS.items():
        if len(d[field]) > limit:
            errors.append(f"{field.replace('_', ' ').capitalize()} is too long (maximum {limit} characters).")
    return d, errors


# ----------------------------------------------------------------------------
# Security: CSRF protection, headers, login throttling
# ----------------------------------------------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def csrf_protect():
    if request.method == "POST":
        expected = session.get("_csrf", "")
        sent = request.form.get("_csrf") or ""
        # An empty token must never match, even when the session has none yet.
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            abort(400)


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "frame-src 'self'; object-src 'self'; base-uri 'self'; form-action 'self'")
    if request.path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


FAILED_LOGINS = {}  # ip -> (count, first_failure_time)


def login_locked(ip):
    count, first = FAILED_LOGINS.get(ip, (0, 0))
    if time.time() - first > 300:
        FAILED_LOGINS.pop(ip, None)
        return False
    return count >= 5


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return {"site": get_site_profile(), "csrf_token": csrf_token, "categories": CATEGORIES,
            "sections": SECTIONS, "year_now": datetime.now().year,
            "is_admin": bool(session.get("admin_id")), "max_mb": MAX_UPLOAD_MB}


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
def show_error(err):
    messages = {400: "That request could not be verified. Go back, refresh the page and try again.",
                404: "We couldn't find that page.",
                413: f"That file is too large. The limit is {MAX_UPLOAD_MB} MB."}
    return render_template("error.html", code=err.code, message=messages[err.code]), err.code


# ----------------------------------------------------------------------------
# 3. Public pages
# ----------------------------------------------------------------------------
@app.route("/")
def home():
    site = get_site_profile()
    certs = query_certs()
    cert_groups = {
        slug: [cert for cert in certs if cert["category"] in SECTIONS[slug][2]]
        for slug in ("major", "workshops", "courses", "achievements")
    }
    return render_template("index.html", certs=certs, cert_groups=cert_groups,
                           has_photo=bool(site.get("photo")))


@app.route("/profile-photo")
def profile_photo():
    filename = get_site_profile().get("photo", "")
    if not filename or Path(filename).name != filename:
        abort(404)
    try:
        data = read_upload(filename)
    except FileNotFoundError:
        abort(404)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return send_file(io.BytesIO(data), mimetype=mime)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/certificates", defaults={"slug": "all"})
@app.route("/certificates/<slug>")
def listing(slug):
    if slug not in SECTIONS:
        abort(404)
    title, blurb, cats = SECTIONS[slug]
    f = {"q": request.args.get("q", "").strip()[:100],
         "category": request.args.get("category", ""),
         "issuer": request.args.get("issuer", ""),
         "year": request.args.get("year", ""),
         "sort": "oldest" if request.args.get("sort") == "oldest" else "newest"}
    shown = [f["category"]] if f["category"] in cats else cats
    certs = query_certs(shown, f["q"], f["issuer"], f["year"], f["sort"])
    ph = ",".join("?" * len(cats))
    db = get_db()
    issuers = [r[0] for r in db.execute(
        f"SELECT DISTINCT issuer FROM certificates WHERE category IN ({ph}) "
        "ORDER BY issuer COLLATE NOCASE", cats)]
    years = [r[0] for r in db.execute(
        f"SELECT DISTINCT substr(completion_date,1,4) y FROM certificates "
        f"WHERE category IN ({ph}) ORDER BY y DESC", cats)]
    filtered = bool(f["q"] or f["category"] in cats or f["issuer"] or f["year"])
    return render_template("listing.html", slug=slug, title=title, blurb=blurb, cats=cats,
                           certs=certs, f=f, issuers=issuers, years=years, filtered=filtered)


@app.route("/files/<path:filename>")
def uploaded_file(filename):
    """Serve a certificate file. Add ?download=1 to force a download."""
    row = get_db().execute("SELECT title FROM certificates WHERE file_path=?",
                           (filename,)).fetchone()
    if row is None:
        abort(404)
    try:
        data = read_upload(filename)
    except FileNotFoundError:
        abort(404)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if request.args.get("download"):
        ext = filename.rsplit(".", 1)[-1]
        safe = re.sub(r"[^A-Za-z0-9]+", "-", row["title"]).strip("-")[:80] or "certificate"
        return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True,
                        download_name=f"{safe}.{ext}")
    return send_file(io.BytesIO(data), mimetype=mime)


@app.route("/robots.txt")
def robots():
    body = f"User-agent: *\nDisallow: /admin\nSitemap: {request.url_root}sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    base = request.url_root.rstrip("/")
    paths = [url_for("home"), url_for("about")] + [url_for("listing", slug=s) for s in SECTIONS]
    items = "".join(f"<url><loc>{base}{p}</loc></url>" for p in paths)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>')
    return Response(xml, mimetype="application/xml")


# ----------------------------------------------------------------------------
# 4. Admin
# ----------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if login_locked(ip):
            error = "Too many failed attempts. Try again in a few minutes."
        else:
            row = get_db().execute("SELECT * FROM admins WHERE username=?",
                                   (request.form.get("username", "").strip(),)).fetchone()
            # Always run a hash check so response time doesn't reveal valid usernames.
            hashed = row["password_hash"] if row else generate_password_hash("not-a-real-password")
            ok = check_password_hash(hashed, request.form.get("password", "")) and row
            if ok:
                FAILED_LOGINS.pop(ip, None)
                session.clear()
                session.permanent = True
                session["admin_id"] = row["id"]
                return redirect(url_for("admin_dashboard"))
            count, first = FAILED_LOGINS.get(ip, (0, time.time()))
            FAILED_LOGINS[ip] = (count + 1, first)
            error = "Username or password is incorrect."
    return render_template("admin/login.html", error=error)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    flash("You are signed out.")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    recent = query_certs(limit=5)
    return render_template("admin/dashboard.html", counts=get_counts(), recent=recent)


@app.route("/admin/profile", methods=["GET", "POST"])
@login_required
def admin_profile():
    current = get_site_profile()
    errors = []
    if request.method == "POST":
        profile, errors = parse_profile_form(request.form)
        upload = request.files.get("photo")
        remove_photo = bool(request.form.get("remove_photo"))
        current_photo = current.get("photo", "")
        new_photo = None

        if not profile["name"]:
            errors.append("Enter a website name.")
        if not profile["tagline"]:
            errors.append("Enter a homepage heading.")
        if upload and upload.filename and remove_photo:
            errors.append("Choose either a new profile photo or remove the current photo, not both.")
        elif upload and upload.filename:
            extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
            upload.stream.seek(0, os.SEEK_END)
            size = upload.stream.tell()
            upload.stream.seek(0)
            if extension not in {"jpg", "jpeg", "png"}:
                errors.append("Profile photo must be a JPG, JPEG, or PNG image.")
            elif size > 5 * 1024 * 1024:
                errors.append("Profile photo must be 5 MB or smaller.")
            elif not errors:
                try:
                    new_photo = save_upload(upload)
                except ValueError as e:
                    errors.append(str(e))
                finally:
                    upload.close()

        if errors:
            if upload and not upload.closed:
                upload.close()
            form = profile_form_values(current)
            form.update({field: request.form.get(field, "") for field in PROFILE_FIELDS})
            form.update({
                "education_text": request.form.get("education", ""),
                "specialties_text": request.form.get("specialties", ""),
                "highlights_text": request.form.get("highlights", ""),
                "projects_text": request.form.get("projects", ""),
            })
            return render_template(
                "admin/profile.html",
                form=form,
                errors=errors,
            ), 400

        profile["photo"] = new_photo or ("" if remove_photo else current_photo)
        get_db().execute(
            "INSERT INTO site_profile (id, data) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (json.dumps(profile, ensure_ascii=False),),
        )
        get_db().commit()
        if new_photo or remove_photo:
            remove_file(current_photo)
        flash("Website profile saved. Your public pages are updated.")
        return redirect(url_for("admin_profile"))

    return render_template("admin/profile.html", form=profile_form_values(current), errors=errors)


@app.route("/admin/certificates")
@login_required
def admin_list():
    q = request.args.get("q", "").strip()[:100]
    cat = request.args.get("category", "")
    certs = query_certs([cat] if cat in CATEGORIES else None, q)
    return render_template("admin/list.html", certs=certs, q=q, cat=cat)


def render_form(cert_id, form, errors, current_file=None, status=200):
    return render_template("admin/form.html", cert_id=cert_id, form=form, errors=errors,
                           current_file=current_file), status


@app.route("/admin/certificates/new", methods=["GET", "POST"])
@login_required
def admin_new():
    if request.method == "GET":
        return render_form(None, {"category": CATEGORIES[0]}, [])
    data, errors = parse_form(request.form)
    upload = request.files.get("file")
    filename = None
    if not upload or not upload.filename:
        errors.append("Choose a certificate file (PDF, JPG, JPEG or PNG).")
    elif not errors:
        try:
            filename = save_upload(upload)
        except ValueError as e:
            errors.append(str(e))
        finally:
            upload.close()
    if errors:
        return render_form(None, request.form, errors, status=400)
    db = get_db()
    db.execute(
        "INSERT INTO certificates (title,category,issuer,completion_date,duration,skills,"
        "description,file_path,verification_url,is_featured,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (data["title"], data["category"], data["issuer"], data["completion_date"],
         data["duration"], data["skills"], data["description"], filename,
         data["verification_url"], data["is_featured"], now_iso()))
    db.commit()
    flash(f"Added “{data['title']}”. It now appears on the public site.")
    return redirect(url_for("admin_list"))


@app.route("/admin/certificates/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def admin_edit(cid):
    db = get_db()
    row = db.execute("SELECT * FROM certificates WHERE id=?", (cid,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "GET":
        return render_form(cid, dict(row), [], row["file_path"])
    data, errors = parse_form(request.form)
    upload = request.files.get("file")
    new_file = None
    if upload and upload.filename and not errors:
        try:
            new_file = save_upload(upload)
        except ValueError as e:
            errors.append(str(e))
        finally:
            upload.close()
    if errors:
        return render_form(cid, request.form, errors, row["file_path"], 400)
    db.execute(
        "UPDATE certificates SET title=?,category=?,issuer=?,completion_date=?,duration=?,"
        "skills=?,description=?,file_path=?,verification_url=?,is_featured=? WHERE id=?",
        (data["title"], data["category"], data["issuer"], data["completion_date"],
         data["duration"], data["skills"], data["description"], new_file or row["file_path"],
         data["verification_url"], data["is_featured"], cid))
    db.commit()
    if new_file:
        remove_file(row["file_path"])  # only after the database points at the new file
    flash("Changes saved.")
    return redirect(url_for("admin_list"))


@app.route("/admin/certificates/<int:cid>/delete", methods=["POST"])
@login_required
def admin_delete(cid):
    db = get_db()
    row = db.execute("SELECT * FROM certificates WHERE id=?", (cid,)).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM certificates WHERE id=?", (cid,))
    db.commit()
    remove_file(row["file_path"])
    flash(f"Deleted “{row['title']}”.")
    return redirect(url_for("admin_list"))


@app.route("/admin/certificates/<int:cid>/feature", methods=["POST"])
@login_required
def admin_feature(cid):
    db = get_db()
    db.execute("UPDATE certificates SET is_featured = 1 - is_featured WHERE id=?", (cid,))
    db.commit()
    return redirect(request.referrer or url_for("admin_list"))


@app.route("/admin/password", methods=["GET", "POST"])
@login_required
def admin_password():
    errors = []
    if request.method == "POST":
        db = get_db()
        row = db.execute("SELECT * FROM admins WHERE id=?", (session["admin_id"],)).fetchone()
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        if not check_password_hash(row["password_hash"], request.form.get("current", "")):
            errors.append("Your current password is incorrect.")
        if len(new) < 10:
            errors.append("The new password needs at least 10 characters.")
        if new != confirm:
            errors.append("The new passwords don't match.")
        if not errors:
            db.execute("UPDATE admins SET password_hash=? WHERE id=?",
                       (generate_password_hash(new), row["id"]))
            db.commit()
            flash("Password changed.")
            return redirect(url_for("admin_dashboard"))
    return render_template("admin/password.html", errors=errors)


@app.route("/admin/backup")
@login_required
def admin_backup():
    """Download a zip of the database and every uploaded certificate."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if DATABASE_URL:
            snapshot = {
                table: [dict(row) for row in get_db().execute(f"SELECT * FROM {table}").fetchall()]
                for table in ("certificates", "admins", "site_profile")
            }
            z.writestr("database.json", json.dumps(snapshot, ensure_ascii=False, default=str))
        else:
            with tempfile.TemporaryDirectory() as tmp:
                snap = Path(tmp) / "portfolio.db"
                src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(snap)
                try:
                    src.backup(dst)
                finally:
                    src.close()
                    dst.close()
                z.write(snap, "portfolio.db")
        if SUPABASE_STORAGE_ENABLED:
            filenames = {
                row["file_path"]
                for row in get_db().execute("SELECT file_path FROM certificates").fetchall()
            }
            photo = get_site_profile().get("photo", "")
            if photo:
                filenames.add(photo)
            for filename in filenames:
                z.writestr(f"uploads/{Path(filename).name}", read_upload(filename))
        else:
            for p in UPLOAD_DIR.iterdir():
                if p.is_file():
                    z.write(p, f"uploads/{p.name}")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"portfolio-backup-{datetime.now():%Y-%m-%d}.zip")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
