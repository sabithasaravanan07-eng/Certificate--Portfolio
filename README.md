# Sabitha's Certificate Portfolio

A Flask website for showing every certificate in one place, with a private admin panel for uploading and managing them. Visitors need no login. One permanent URL for your resume, LinkedIn and portfolio.

## What each file does

| File / folder | Purpose |
|---|---|
| `app.py` | The whole backend: settings, database, public pages, admin pages and security. |
| `templates/base.html` | Page shell: header, menu, footer, SEO tags. |
| `templates/index.html` | Home: portfolio intro and certificate image cards grouped by category. |
| `templates/about.html` | Separate About page with biography, education, skills, projects and achievements. |
| `templates/listing.html` | Category pages with certificate cards and previews. |
| `templates/_macros.html`, `_preview.html` | The certificate card and the preview window. |
| `templates/admin/` | Login, dashboard, website profile editor, certificate management and password change. |
| `static/css/style.css` | All styling. Colours and fonts are at the top (`:root`). |
| `static/js/main.js` | Mobile menu, preview window, share and copy-link. |
| `data/` | Created at runtime: `portfolio.db` and `uploads/`, including your profile photo. Your real data. Not in Git. |
| `test_app.py` | Automated test of upload, edit, delete, display, download and security. |
| `requirements.txt`, `Procfile`, `wsgi.py`, `render.yaml` | Deployment files. |

The site uses a modern forest-green and cream theme. Adjust the color variables at the top of `static/css/style.css` to customize it.

## Run it on your computer

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

export ADMIN_USERNAME=sabitha      # Windows PowerShell: $env:ADMIN_USERNAME="sabitha"
export ADMIN_PASSWORD="a-strong-password-10+-chars"
export OWNER_NAME="Sabitha S"
export OWNER_FOCUS="I’m curious and driven, and I enjoy building clean, functional web experiences."
export OWNER_EDUCATION="B.Tech in Information Technology — The Kavery Engineering College, Full Stack Development certification — Novi Tech, HDCA six-month course — TCDS"
export OWNER_SPECIALTIES="HTML5, CSS3, JavaScript, Python, Flask, MySQL, Git, GitHub"
export OWNER_HIGHLIGHTS="My Brain Battle team won two prizes, Participated in a code-debugging event"
export OWNER_LOCATION="Salem, Tamil Nadu, India"
export CONTACT_EMAIL=you@example.com
python app.py
```

Copy `.env.example` to `.env` and set your values there. Leave `DATABASE_URL` blank for local SQLite. To use Supabase, paste the PostgreSQL connection URI from **Supabase → Project Settings → Database → Connect** into `DATABASE_URL`; use its session-pooler URI if your host cannot connect directly. Keep this URI private. `sslmode=require` encrypts traffic but does not verify the server; for server identity verification, download the root certificate from **Supabase → Project Settings → Database → SSL Configuration**, set its path in `DATABASE_SSLROOTCERT`, and use `sslmode=verify-full`. Install dependencies with `pip install -r requirements.txt`, then run `python app.py`.

When connecting to a new Supabase database, set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env` before the first start; the app creates the initial admin account automatically. Choose a password of at least 10 characters. To create or reset an admin later: `flask --app app create-admin`.

After signing in, use **Dashboard → Edit website profile** to update the homepage and About-page text, website name, skills, education, achievements, projects, profile photo, location and contact links. Project entries use one line each in the format `Name | Description | https://project-link`. These edits are saved in the database and remain after an app restart.

Run the tests any time with `python test_app.py` (uses a temporary folder, never your real data).

## Where your data lives, and why hosting matters

With local SQLite, the database and uploaded files are stored in `DATA_DIR` (default `./data`), kept **outside the code**. With Supabase configured, database records use Supabase PostgreSQL while uploaded certificate and profile image files remain in `DATA_DIR/uploads`. Updating the code never changes this folder.

**Do not use Vercel for this app as written.** Vercel is serverless: its filesystem is temporary, so uploaded certificate files would disappear. Use a host with persistent file storage:

**Option A: PythonAnywhere (has a free tier, persistent disk, permanent `yourname.pythonanywhere.com` URL)**
1. Create an account, open a Bash console, `git clone` your GitHub repo.
2. `cd` into it, then `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
3. Web tab → Add a new web app → Manual configuration (pick the Python version you used). Set the virtualenv path.
4. Edit the WSGI file so it contains:
   ```python
   import os, sys
   sys.path.insert(0, "/home/YOURNAME/certificate-portfolio")
   os.environ["DATA_DIR"] = "/home/YOURNAME/portfolio-data"
   os.environ["SECRET_KEY"] = "paste-a-long-random-string"
   os.environ["COOKIE_SECURE"] = "1"
   os.environ["ADMIN_USERNAME"] = "sabitha"
   os.environ["ADMIN_PASSWORD"] = "your-strong-password"
   os.environ["CONTACT_EMAIL"] = "you@example.com"
   from app import app as application
   ```
5. Reload the web app. Remove `ADMIN_PASSWORD` from the WSGI file after the first start, and change your password in the admin panel.

**Option B: Render with a persistent disk (paid instance)**
Push to GitHub, then Render → New → Blueprint and select the repo. `render.yaml` mounts a disk at `/var/data` and sets `DATA_DIR`. Enter `ADMIN_USERNAME` and `ADMIN_PASSWORD` when asked. Railway and Fly.io work the same way: attach a volume and point `DATA_DIR` at it. Check each provider's current pricing and limits.

## Push to GitHub

```bash
git init && git add . && git commit -m "Certificate portfolio"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/certificate-portfolio.git
git push -u origin main
```
`.gitignore` keeps `data/`, `.env` and your passwords out of the repository.

## Updating the site safely

Change code, push to GitHub, pull/redeploy. Never delete or overwrite `DATA_DIR`. Before bigger changes, open **Admin → Dashboard → Download backup** (a zip of the database and every certificate). The backup contains your password hash, so keep it private.

## Security summary

Hashed passwords; session login (8 hours, HttpOnly, SameSite); CSRF token on every POST; login lockout after 5 failures; uploads limited to PDF/JPG/JPEG/PNG, checked by real file content, 10 MB max, saved under random names; parameterised SQL; HTML auto-escaped; security headers and CSP; all admin routes require login.
