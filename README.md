# AssetVault - Digital Asset Management System
A web app to catalog, tag, search and version 3D/game assets (textures, materials, models).
**Stack:** Python, Flask, SQLite (SQLAlchemy), Flask-Login, Pillow, Bootstrap 5.
**Features:** role-based login, asset CRUD, tags and categories, metadata, thumbnails, versioning, search/filter/sort, dashboard.
**Run locally:** `pip install -r requirements.txt` then `python app.py`. Demo login: demo / demo123.
**Deploy (Render):** build `pip install -r requirements.txt`, start `gunicorn app:app`, env var SECRET_KEY.
**Future scope (major project):** auto metadata extraction, Blender add-on, 3D web preview, cloud storage.
