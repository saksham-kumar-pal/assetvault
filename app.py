import os, uuid
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_from_directory, abort)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func
from PIL import Image

BASE = os.path.abspath(os.path.dirname(__file__))
UPLOADS = os.path.join(BASE, "static", "uploads")
THUMBS = os.path.join(BASE, "static", "thumbs")
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(THUMBS, exist_ok=True)

ALLOWED = {"png", "jpg", "jpeg", "bmp", "tga", "fbx", "obj", "blend",
           "glb", "gltf", "uasset", "sbsar", "zip"}
IMAGES = {"png", "jpg", "jpeg", "bmp"}
CATEGORIES = ["Environment", "Prop", "Character", "Texture", "Material",
              "Brush/Alpha", "Blueprint/Script", "Other"]

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE, "assetvault.db"),
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(10), default="user")  # admin or user


class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(40))
    tags = db.Column(db.String(200), default="")
    description = db.Column(db.Text, default="")
    file_type = db.Column(db.String(10))
    file_size = db.Column(db.Integer, default=0)
    poly_count = db.Column(db.Integer)
    version = db.Column(db.Integer, default=1)
    filename = db.Column(db.String(200))
    thumb = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    uploader = db.relationship("User")

    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


@app.template_filter("filesize")
def filesize(n):
    n = n or 0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def save_file(f):
    """Save upload, make thumbnail for images. Returns (stored, ext, size, thumb)."""
    ext = f.filename.rsplit(".", 1)[-1].lower()
    stored = uuid.uuid4().hex + "_" + secure_filename(f.filename)
    path = os.path.join(UPLOADS, stored)
    f.save(path)
    thumb = None
    if ext in IMAGES:
        try:
            img = Image.open(path)
            img.thumbnail((300, 300))
            thumb = stored.rsplit(".", 1)[0] + "_t.png"
            img.convert("RGBA").save(os.path.join(THUMBS, thumb))
        except Exception:
            thumb = None
    return stored, ext, os.path.getsize(path), thumb


def remove_files(a):
    for folder, name in ((UPLOADS, a.filename), (THUMBS, a.thumb)):
        if name and os.path.exists(os.path.join(folder, name)):
            os.remove(os.path.join(folder, name))


def allowed(f):
    return f and "." in f.filename and f.filename.rsplit(".", 1)[-1].lower() in ALLOWED


def can_edit(a):
    return current_user.role == "admin" or a.uploader_id == current_user.id


# ---------- auth ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u, p = request.form["username"].strip(), request.form["password"]
        if len(u) < 3 or len(p) < 4:
            flash("Username min 3 chars, password min 4 chars.", "danger")
        elif User.query.filter_by(username=u).first():
            flash("Username already taken.", "danger")
        else:
            role = "admin" if User.query.count() == 0 else "user"  # first user = admin
            db.session.add(User(username=u, password_hash=generate_password_hash(p), role=role))
            db.session.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"].strip()).first()
        if user and check_password_hash(user.password_hash, request.form["password"]):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("auth.html", mode="login")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------- pages ----------
@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user.is_authenticated else url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    total = Asset.query.count()
    storage = db.session.query(func.coalesce(func.sum(Asset.file_size), 0)).scalar()
    by_cat = db.session.query(Asset.category, func.count(Asset.id)).group_by(Asset.category).all()
    recent = Asset.query.order_by(Asset.created_at.desc()).limit(5).all()
    users = User.query.count()
    return render_template("dashboard.html", total=total, storage=storage,
                           by_cat=by_cat, recent=recent, users=users)


@app.route("/assets")
@login_required
def assets():
    q = Asset.query
    s = request.args.get("q", "").strip()
    cat = request.args.get("category", "")
    ftype = request.args.get("type", "")
    sort = request.args.get("sort", "new")
    if s:
        like = f"%{s}%"
        q = q.filter(db.or_(Asset.name.ilike(like), Asset.tags.ilike(like),
                            Asset.description.ilike(like)))
    if cat:
        q = q.filter_by(category=cat)
    if ftype:
        q = q.filter_by(file_type=ftype)
    order = {"new": Asset.created_at.desc(), "name": Asset.name.asc(),
             "size": Asset.file_size.desc()}.get(sort, Asset.created_at.desc())
    items = q.order_by(order).all()
    types = [t[0] for t in db.session.query(Asset.file_type).distinct() if t[0]]
    return render_template("assets.html", items=items, categories=CATEGORIES,
                           types=types, s=s, cat=cat, ftype=ftype, sort=sort)


@app.route("/asset/<int:aid>")
@login_required
def detail(aid):
    return render_template("detail.html", a=db.get_or_404(Asset, aid), can_edit=can_edit)


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        if not allowed(f):
            flash("Please choose a valid file (" + ", ".join(sorted(ALLOWED)) + ").", "danger")
            return render_template("form.html", a=None, categories=CATEGORIES)
        stored, ext, size, thumb = save_file(f)
        a = Asset(name=request.form["name"].strip() or f.filename,
                  category=request.form["category"], tags=request.form["tags"],
                  description=request.form["description"],
                  poly_count=int(request.form["poly_count"]) if request.form["poly_count"].isdigit() else None,
                  file_type=ext, file_size=size, filename=stored, thumb=thumb,
                  uploader_id=current_user.id)
        db.session.add(a)
        db.session.commit()
        flash("Asset uploaded.", "success")
        return redirect(url_for("detail", aid=a.id))
    return render_template("form.html", a=None, categories=CATEGORIES)


@app.route("/asset/<int:aid>/edit", methods=["GET", "POST"])
@login_required
def edit(aid):
    a = db.get_or_404(Asset, aid)
    if not can_edit(a):
        abort(403)
    if request.method == "POST":
        a.name = request.form["name"].strip() or a.name
        a.category = request.form["category"]
        a.tags = request.form["tags"]
        a.description = request.form["description"]
        a.poly_count = int(request.form["poly_count"]) if request.form["poly_count"].isdigit() else None
        f = request.files.get("file")
        if f and f.filename:
            if not allowed(f):
                flash("Invalid file type.", "danger")
                return render_template("form.html", a=a, categories=CATEGORIES)
            remove_files(a)
            a.filename, a.file_type, a.file_size, a.thumb = save_file(f)
            a.version += 1  # new file = new version
        db.session.commit()
        flash("Asset updated.", "success")
        return redirect(url_for("detail", aid=a.id))
    return render_template("form.html", a=a, categories=CATEGORIES)


@app.route("/asset/<int:aid>/delete", methods=["POST"])
@login_required
def delete(aid):
    a = db.get_or_404(Asset, aid)
    if not can_edit(a):
        abort(403)
    remove_files(a)
    db.session.delete(a)
    db.session.commit()
    flash("Asset deleted.", "info")
    return redirect(url_for("assets"))


@app.route("/download/<int:aid>")
@login_required
def download(aid):
    a = db.get_or_404(Asset, aid)
    return send_from_directory(UPLOADS, a.filename, as_attachment=True,
                               download_name=a.name + "." + a.file_type)


@app.route("/admin/users")
@login_required
def users():
    if current_user.role != "admin":
        abort(403)
    return render_template("users.html", users=User.query.all())


def seed_demo():
    """Fill an empty database with a demo admin and sample assets."""
    if User.query.count():
        return
    db.session.add(User(username="demo", password_hash=generate_password_hash("demo123"), role="admin"))
    db.session.commit()
    uid = User.query.filter_by(username="demo").first().id
    samples = [
        ("Mossy Stone Wall", "Texture", "stone,moss,medieval,tileable", (88, 110, 84)),
        ("Weathered Oak Planks", "Texture", "wood,planks,medieval", (120, 86, 52)),
        ("Rusted Iron Plate", "Material", "metal,rust,pbr", (140, 82, 50)),
        ("Cobblestone Path", "Texture", "stone,ground,tileable", (112, 112, 118)),
        ("Castle Brick Tile", "Texture", "brick,wall,medieval", (150, 84, 72)),
        ("Dry Mud Ground", "Texture", "mud,ground,terrain", (104, 80, 58)),
        ("Forest Moss Mix", "Material", "moss,nature,vr-ready", (64, 104, 58)),
        ("Aged Plaster", "Texture", "plaster,wall,interior", (186, 176, 154)),
        ("Slate Roof Tiles", "Texture", "roof,slate,tileable", (70, 78, 96)),
        ("Worn Leather", "Material", "leather,prop,pbr", (110, 66, 44)),
        ("Torch Fire Alpha", "Brush/Alpha", "fire,vfx,alpha", (220, 120, 30)),
        ("Cracked Marble", "Texture", "marble,floor,castle", (206, 208, 214)),
    ]
    for i, (name, cat, tags, col) in enumerate(samples):
        noise = Image.effect_noise((256, 256), 60).convert("RGB")
        img = Image.blend(Image.new("RGB", (256, 256), col), noise, 0.22)
        stored, thumb = f"seed{i}.png", f"seed{i}_t.png"
        img.save(os.path.join(UPLOADS, stored))
        img.resize((200, 200)).save(os.path.join(THUMBS, thumb))
        db.session.add(Asset(name=name, category=cat, tags=tags, file_type="png",
            description="Sample placeholder asset for demo purposes.",
            file_size=os.path.getsize(os.path.join(UPLOADS, stored)),
            filename=stored, thumb=thumb, uploader_id=uid,
            created_at=datetime.utcnow()))
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_demo()


if __name__ == "__main__":
    app.run(debug=True)
