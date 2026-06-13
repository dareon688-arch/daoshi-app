# app.py —— 导师组小应用 · 第 3 步：成员名片 + 个人信息编辑
#
# 已有：登录系统、密码哈希
# 新增：
#   1. 名片字段（入学年份、培养方式、工作单位、籍贯、微信、邮箱、照片）
#   2. 成员列表页（所有人，只读）
#   3. 编辑“我的信息”（只能改自己）
#   4. 上传个人照片

import os
import uuid
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_from_directory,
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ──────────────────────────────────────────────────────────────
# 1. 基本配置
# ──────────────────────────────────────────────────────────────
app = Flask(__name__)

# DATA_DIR：数据（数据库 + 上传的照片）存放的根目录。
#   - 本地运行：不设环境变量，默认就是项目文件夹，跟以前完全一样。
#   - 云上运行：把环境变量 DATA_DIR 设成持久磁盘路径（如 /var/data），
#     数据就存到持久磁盘上，重启也不会丢。
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)

# SECRET_KEY 用来给登录状态签名，必须保密。
#   - 本地：用占位值即可。
#   - 云上：设环境变量 SECRET_KEY 为一串随机值（部署那步我会教你生成）。
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me-later")

# 数据库文件放在 DATA_DIR 下的 app.db
# 注意：SQLite 的 URI 必须用正斜杠 /，Windows 的反斜杠 \ 会出错，所以这里转换一下。
db_path = os.path.join(DATA_DIR, "app.db").replace("\\", "/")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

# 上传的照片放在 DATA_DIR/uploads/ 下
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
# 限制上传大小为 5MB，防止有人传超大文件
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
# 只允许这些图片格式
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


db = SQLAlchemy(app)

# 登录管理器：负责“记住谁登录了”
login_manager = LoginManager(app)
login_manager.login_view = "login"          # 没登录时自动跳到登录页
login_manager.login_message = "请先登录"


# ──────────────────────────────────────────────────────────────
# 2. 数据模型：一张用户表
#    每个师兄师姐 = 表里的一行
# ──────────────────────────────────────────────────────────────
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)          # 自动编号
    username = db.Column(db.String(50), unique=True, nullable=False)  # 登录用户名
    name = db.Column(db.String(50), nullable=False)       # 姓名（必填）
    password_hash = db.Column(db.String(256), nullable=False)  # 加密后的密码

    # ↓↓↓ 第 3 步新增的名片字段 ↓↓↓
    enroll_year = db.Column(db.Integer, nullable=True)    # 入学年份，如 2023，显示为“2023 级”（必填，建账号时给）
    program = db.Column(db.String(20), nullable=True)     # 培养方式：full（全日制）/ mem（非全日制MEM）
    work_unit = db.Column(db.String(100), nullable=True)  # 工作单位（选填）
    hometown = db.Column(db.String(50), nullable=True)    # 籍贯（选填）
    wechat = db.Column(db.String(50), nullable=True)      # 微信号（选填）
    email = db.Column(db.String(100), nullable=True)      # 邮箱（选填）
    photo = db.Column(db.String(200), nullable=True)      # 个人照片的文件名（选填）
    is_admin = db.Column(db.Boolean, default=False)       # 是否管理员（能删任意相册照片）

    # 把 program 代码转成中文显示用
    @property
    def program_label(self):
        return {"full": "全日制", "mem": "非全日制（MEM）"}.get(self.program, "")

    # 设置密码：自动加密，绝不存明文
    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    # 校验密码：用哈希比对
    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


# ── 相册照片表：每张合照 = 一行 ──
class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)   # 存在 static/uploads/ 的文件名
    caption = db.Column(db.String(200), nullable=True)     # 说明文字（选填）
    uploader_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # 谁传的
    created_at = db.Column(db.DateTime, default=datetime.utcnow)   # 上传时间

    # 方便在页面上拿到上传者对象（uploader.name）
    uploader = db.relationship("User")


# Flask-Login 需要这个函数，用来根据 id 找回用户
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ──────────────────────────────────────────────────────────────
# 3. 页面路由
# ──────────────────────────────────────────────────────────────
@app.route("/")
@login_required                      # 加了这行：没登录会被挡在外面
def home():
    # 打开网站直接看到成员列表（通讯录就是主界面）
    return redirect(url_for("members"))


# Service Worker 必须从根路径提供，才能控制整个站点（这是 PWA 的要求）
@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")


# 提供上传的图片（照片存在 DATA_DIR/uploads，不在 static 里，所以需要这个路由）
# 加了 @login_required：未登录的人无法直接拿到照片，进一步防泄露。
@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/login", methods=["GET", "POST"])
def login():
    # GET：显示登录表单；POST：处理提交的用户名密码
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)                 # 登录成功，记住他
            return redirect(url_for("home"))
        else:
            flash("用户名或密码错误")          # 失败提示
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        if not current_user.check_password(old):
            flash("当前密码不对")
        elif len(new) < 6:
            flash("新密码至少 6 位")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("密码已修改 ✅")
            return redirect(url_for("members"))
    return render_template("change_password.html")


# ── 成员列表：所有人都能看，按入学年份排序 ──
@app.route("/members")
@login_required
def members():
    all_users = User.query.order_by(User.enroll_year, User.name).all()
    return render_template("members.html", users=all_users)


# ── 成员详情：看某一个人的完整名片 ──
@app.route("/member/<int:user_id>")
@login_required
def member_detail(user_id):
    user = db.get_or_404(User, user_id)
    return render_template("member_detail.html", user=user)


# ── 编辑“我的信息”：只能改自己 ──
@app.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        # 姓名、入学年份是必填
        name = request.form.get("name", "").strip()
        enroll_year = request.form.get("enroll_year", "").strip()

        if not name:
            flash("姓名不能为空")
            return render_template("edit_profile.html", user=current_user)
        if not enroll_year.isdigit():
            flash("入学年份要填数字，比如 2023")
            return render_template("edit_profile.html", user=current_user)

        current_user.name = name
        current_user.enroll_year = int(enroll_year)
        # 以下都是选填，直接读取（空就是空）
        current_user.program = request.form.get("program", "") or None
        current_user.work_unit = request.form.get("work_unit", "").strip() or None
        current_user.hometown = request.form.get("hometown", "").strip() or None
        current_user.wechat = request.form.get("wechat", "").strip() or None
        current_user.email = request.form.get("email", "").strip() or None

        # 处理照片上传（选填）
        file = request.files.get("photo")
        if file and file.filename:
            if allowed_file(file.filename):
                # 用随机文件名，避免中文名/重名/覆盖问题
                ext = file.filename.rsplit(".", 1)[1].lower()
                fname = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))
                current_user.photo = fname
            else:
                flash("照片格式不支持（只能 png/jpg/jpeg/gif/webp）")
                return render_template("edit_profile.html", user=current_user)

        db.session.commit()
        flash("信息已保存 ✅")
        return redirect(url_for("member_detail", user_id=current_user.id))

    return render_template("edit_profile.html", user=current_user)


# ── 相册：浏览所有合照（按时间倒序） ──
@app.route("/album")
@login_required
def album():
    photos = Photo.query.order_by(Photo.created_at.desc()).all()
    return render_template("album.html", photos=photos)


# ── 相册：下载某张照片（用友好的文件名“另存为”） ──
@app.route("/album/download/<int:photo_id>")
@login_required
def download_photo(photo_id):
    photo = db.get_or_404(Photo, photo_id)
    ext = photo.filename.rsplit(".", 1)[1].lower()
    # 下载时显示的文件名：有说明就用说明+日期，否则用日期
    date_str = photo.created_at.strftime("%Y%m%d")
    nice_name = f"{photo.caption}_{date_str}.{ext}" if photo.caption else f"导师组合照_{date_str}.{ext}"
    # as_attachment=True 让浏览器“下载”而不是直接打开；download_name 是另存为的名字
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], photo.filename,
        as_attachment=True, download_name=nice_name,
    )


# ── 相册：上传合照 ──
@app.route("/album/upload", methods=["GET", "POST"])
@login_required
def upload_photo():
    if request.method == "POST":
        file = request.files.get("photo")
        caption = request.form.get("caption", "").strip()

        if not file or not file.filename:
            flash("请选择一张照片")
            return render_template("upload_photo.html")
        if not allowed_file(file.filename):
            flash("照片格式不支持（只能 png/jpg/jpeg/gif/webp）")
            return render_template("upload_photo.html")

        ext = file.filename.rsplit(".", 1)[1].lower()
        fname = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))

        photo = Photo(filename=fname, caption=caption or None,
                      uploader_id=current_user.id)
        db.session.add(photo)
        db.session.commit()
        flash("照片已上传 ✅")
        return redirect(url_for("album"))

    return render_template("upload_photo.html")


# ── 相册：删除照片（谁传谁能删，管理员能删任意） ──
@app.route("/album/delete/<int:photo_id>", methods=["POST"])
@login_required
def delete_photo(photo_id):
    photo = db.get_or_404(Photo, photo_id)
    # 权限检查：只有上传者本人或管理员能删
    if photo.uploader_id != current_user.id and not current_user.is_admin:
        flash("你没有权限删除这张照片")
        return redirect(url_for("album"))

    # 先删数据库记录（让照片从相册消失，这是关键），再尝试删磁盘文件。
    filename = photo.filename
    db.session.delete(photo)
    db.session.commit()

    # 删磁盘文件：删不掉也不让整个操作失败（文件不存在 / Windows 上偶发的占用都忽略）
    try:
        os.remove(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    except OSError:
        pass

    flash("照片已删除")
    return redirect(url_for("album"))


# ──────────────────────────────────────────────────────────────
# 4. 启动时：建表 + 确保有一个初始管理员
# ──────────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

    # 如果数据库里一个用户都没有（比如刚部署到云上、库是空的），
    # 就用环境变量创建一个初始管理员，方便第一次登录进去。
    # 在 Render 后台设置这两个环境变量：ADMIN_USERNAME、ADMIN_PASSWORD。
    if User.query.count() == 0:
        admin_user = os.environ.get("ADMIN_USERNAME")
        admin_pass = os.environ.get("ADMIN_PASSWORD")
        if admin_user and admin_pass:
            admin = User(username=admin_user, name="管理员",
                         enroll_year=2020, is_admin=True)
            admin.set_password(admin_pass)
            db.session.add(admin)
            db.session.commit()
            print(f"已创建初始管理员账号：{admin_user}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
