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


# ── 公告表：每条公告 = 一行 ──
class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)        # 公告标题
    content = db.Column(db.Text, nullable=False)             # 公告内容
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # 谁发的
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 发布时间
    pinned = db.Column(db.Boolean, default=False)            # 是否置顶（管理员设置）

    author = db.relationship("User")


# ──────────────────────────────────────────────────────────────
# 聊天相关：会话 / 会话成员 / 消息（私聊=2人会话，群聊=多人会话）
# ──────────────────────────────────────────────────────────────

# ── 会话表：一个聊天窗口（一个私聊或一个群） ──
class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_group = db.Column(db.Boolean, default=False)          # True=群聊，False=私聊
    name = db.Column(db.String(80), nullable=True)           # 群名（群聊才有）
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # 谁建的
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 这个会话里的成员（通过 Membership 关联）
    memberships = db.relationship("Membership", back_populates="conversation",
                                  cascade="all, delete-orphan")
    messages = db.relationship("Message", back_populates="conversation",
                               cascade="all, delete-orphan")

    def members(self):
        """返回这个会话里的所有用户对象。"""
        return [m.user for m in self.memberships]

    def title_for(self, viewer):
        """给某个查看者显示的会话标题：
        群聊显示群名；私聊显示“对方的名字”。"""
        if self.is_group:
            return self.name or "群聊"
        others = [m.user for m in self.memberships if m.user_id != viewer.id]
        return others[0].name if others else "（空会话）"


# ── 会话成员表：谁在哪个会话里 ──
class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow)  # 读到哪了（算未读用）

    conversation = db.relationship("Conversation", back_populates="memberships")
    user = db.relationship("User")


# ── 消息表：每条聊天消息 = 一行 ──
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"))
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    content = db.Column(db.Text, nullable=True)              # 文字内容（图片消息可为空）
    msg_type = db.Column(db.String(10), default="text")     # text / image（以后可加 voice）
    image = db.Column(db.String(200), nullable=True)        # 图片文件名（图片消息才有）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    conversation = db.relationship("Conversation", back_populates="messages")
    sender = db.relationship("User")


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


# ── 公告：所有人可看，置顶的排最前，其余按时间倒序 ──
@app.route("/announcements")
@login_required
def announcements():
    items = Announcement.query.order_by(
        Announcement.pinned.desc(),        # 置顶（True）排在前面
        Announcement.created_at.desc(),    # 其次按时间，新的在上
    ).all()
    return render_template("announcements.html", items=items)


# ── 公告：置顶 / 取消置顶（仅管理员） ──
@app.route("/announcements/pin/<int:item_id>", methods=["POST"])
@login_required
def toggle_pin_announcement(item_id):
    if not current_user.is_admin:
        flash("只有管理员能置顶公告")
        return redirect(url_for("announcements"))
    item = db.get_or_404(Announcement, item_id)
    item.pinned = not item.pinned          # 反转：置顶↔取消置顶
    db.session.commit()
    flash("已置顶 📌" if item.pinned else "已取消置顶")
    return redirect(url_for("announcements"))


# ── 公告：发布（仅管理员） ──
@app.route("/announcements/new", methods=["GET", "POST"])
@login_required
def new_announcement():
    # 权限：只有管理员能发公告
    if not current_user.is_admin:
        flash("只有管理员能发布公告")
        return redirect(url_for("announcements"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        if not title or not content:
            flash("标题和内容都要填")
            return render_template("new_announcement.html")

        item = Announcement(title=title, content=content,
                            author_id=current_user.id)
        db.session.add(item)
        db.session.commit()
        flash("公告已发布 ✅")
        return redirect(url_for("announcements"))

    return render_template("new_announcement.html")


# ── 公告：删除（仅管理员） ──
@app.route("/announcements/delete/<int:item_id>", methods=["POST"])
@login_required
def delete_announcement(item_id):
    if not current_user.is_admin:
        flash("只有管理员能删除公告")
        return redirect(url_for("announcements"))
    item = db.get_or_404(Announcement, item_id)
    db.session.delete(item)
    db.session.commit()
    flash("公告已删除")
    return redirect(url_for("announcements"))


# ──────────────────────────────────────────────────────────────
# 聊天功能（阶段一：私聊 + 建群 + 轮询拉消息）
# ──────────────────────────────────────────────────────────────

def _my_conversations():
    """当前用户所在的所有会话，按最近有消息的排在前面。"""
    convs = (Conversation.query
             .join(Membership)
             .filter(Membership.user_id == current_user.id)
             .all())
    # 按最后一条消息时间倒序（没消息的用创建时间）
    def last_time(c):
        last = (Message.query.filter_by(conversation_id=c.id)
                .order_by(Message.created_at.desc()).first())
        return last.created_at if last else c.created_at
    return sorted(convs, key=last_time, reverse=True)


def _is_member(conv, user):
    return Membership.query.filter_by(conversation_id=conv.id, user_id=user.id).first() is not None


def _unread_count(conv, user):
    """某用户在某会话里的未读消息数：
    比 last_read_at 晚、且不是自己发的消息。"""
    mem = Membership.query.filter_by(conversation_id=conv.id, user_id=user.id).first()
    if not mem:
        return 0
    return (Message.query
            .filter(Message.conversation_id == conv.id,
                    Message.sender_id != user.id,
                    Message.created_at > (mem.last_read_at or datetime.min))
            .count())


def _total_unread(user):
    """某用户所有会话的未读总数（用于导航栏红点）。"""
    convs = (Conversation.query.join(Membership)
             .filter(Membership.user_id == user.id).all())
    return sum(_unread_count(c, user) for c in convs)


# 让所有模板都能拿到当前用户的未读总数（导航栏红点用）
@app.context_processor
def inject_unread():
    if current_user.is_authenticated:
        try:
            return {"unread_total": _total_unread(current_user)}
        except Exception:
            return {"unread_total": 0}
    return {"unread_total": 0}


# ── 会议引导页：一键打开腾讯会议 ──
@app.route("/meeting")
@login_required
def meeting():
    return render_template("meeting.html")


# ── 聊天首页：我的会话列表 ──
@app.route("/chat")
@login_required
def chat():
    convs = _my_conversations()
    # 给每个会话准备：标题、最后一条消息预览
    items = []
    for c in convs:
        last = (Message.query.filter_by(conversation_id=c.id)
                .order_by(Message.created_at.desc()).first())
        items.append({
            "conv": c,
            "title": c.title_for(current_user),
            "last": last,
            "unread": _unread_count(c, current_user),
        })
    # 可选私聊对象：除自己外的所有成员
    others = User.query.filter(User.id != current_user.id).all()
    return render_template("chat.html", items=items, others=others)


# ── 开始（或打开）和某人的私聊 ──
@app.route("/chat/private/<int:user_id>", methods=["POST"])
@login_required
def open_private(user_id):
    other = db.get_or_404(User, user_id)
    if other.id == current_user.id:
        flash("不能和自己私聊")
        return redirect(url_for("chat"))

    # 找有没有已存在的、只含这两人的私聊会话
    my_convs = (Conversation.query.join(Membership)
                .filter(Membership.user_id == current_user.id,
                        Conversation.is_group == False).all())
    existing = None
    for c in my_convs:
        member_ids = {m.user_id for m in c.memberships}
        if member_ids == {current_user.id, other.id}:
            existing = c
            break

    if existing:
        return redirect(url_for("conversation", conv_id=existing.id))

    # 没有就新建一个私聊会话
    conv = Conversation(is_group=False, creator_id=current_user.id)
    db.session.add(conv)
    db.session.flush()
    db.session.add(Membership(conversation_id=conv.id, user_id=current_user.id))
    db.session.add(Membership(conversation_id=conv.id, user_id=other.id))
    db.session.commit()
    return redirect(url_for("conversation", conv_id=conv.id))


# ── 建群：选若干成员 ──
@app.route("/chat/new-group", methods=["GET", "POST"])
@login_required
def new_group():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        member_ids = request.form.getlist("members")  # 选中的成员 id 列表
        if not name:
            flash("请填群名")
            return redirect(url_for("new_group"))
        if not member_ids:
            flash("至少选一个成员")
            return redirect(url_for("new_group"))

        conv = Conversation(is_group=True, name=name, creator_id=current_user.id)
        db.session.add(conv)
        db.session.flush()
        # 建群者自己一定在群里
        ids = set(int(i) for i in member_ids) | {current_user.id}
        for uid in ids:
            db.session.add(Membership(conversation_id=conv.id, user_id=uid))
        db.session.commit()
        flash("群聊已创建 🎉")
        return redirect(url_for("conversation", conv_id=conv.id))

    others = User.query.filter(User.id != current_user.id).all()
    return render_template("new_group.html", others=others)


# ── 打开某个会话，看消息 ──
@app.route("/chat/<int:conv_id>")
@login_required
def conversation(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        flash("你不在这个会话里")
        return redirect(url_for("chat"))

    msgs = (Message.query.filter_by(conversation_id=conv.id)
            .order_by(Message.created_at.asc()).all())

    # 更新“读到哪了”
    mem = Membership.query.filter_by(conversation_id=conv.id, user_id=current_user.id).first()
    if mem:
        mem.last_read_at = datetime.utcnow()
        db.session.commit()

    # 私聊时，找出对方（点头像看资料用）
    other = None
    if not conv.is_group:
        others = [m.user for m in conv.memberships if m.user_id != current_user.id]
        other = others[0] if others else None

    return render_template("conversation.html", conv=conv, msgs=msgs,
                           title=conv.title_for(current_user), other=other)


def _msg_to_dict(m):
    """把一条消息转成前端要的字典（文字/图片通用）。"""
    return {
        "id": m.id,
        "sender_id": m.sender_id,
        "sender_name": m.sender.name if m.sender else "?",
        "type": m.msg_type or "text",
        "content": m.content or "",
        "image_url": url_for("uploaded_file", filename=m.image) if m.image else None,
        "time": m.created_at.strftime("%H:%M"),
        "mine": m.sender_id == current_user.id,
    }


# ── 发文字消息 ──
@app.route("/chat/<int:conv_id>/send", methods=["POST"])
@login_required
def send_message(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        return {"ok": False, "error": "你不在这个会话里"}, 403
    content = (request.form.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "消息不能为空"}, 400

    msg = Message(conversation_id=conv.id, sender_id=current_user.id,
                  content=content, msg_type="text")
    db.session.add(msg)
    db.session.commit()
    return {"ok": True, "id": msg.id}


# ── 发图片消息 ──
@app.route("/chat/<int:conv_id>/send-image", methods=["POST"])
@login_required
def send_image(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        return {"ok": False, "error": "你不在这个会话里"}, 403
    file = request.files.get("image")
    if not file or not file.filename:
        return {"ok": False, "error": "没有选择图片"}, 400
    if not allowed_file(file.filename):
        return {"ok": False, "error": "图片格式不支持"}, 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))

    # content 给空字符串而非 None：兼容老库里 content 列的 NOT NULL 约束
    msg = Message(conversation_id=conv.id, sender_id=current_user.id,
                  content="", msg_type="image", image=fname)
    db.session.add(msg)
    db.session.commit()
    return {"ok": True, "id": msg.id}


# ── 轮询：拉取某会话里 id 大于 after 的新消息（前端每隔几秒调一次） ──
@app.route("/chat/<int:conv_id>/poll")
@login_required
def poll_messages(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        return {"ok": False}, 403
    after = request.args.get("after", 0, type=int)
    msgs = (Message.query
            .filter(Message.conversation_id == conv.id, Message.id > after)
            .order_by(Message.created_at.asc()).all())
    return {"ok": True, "messages": [_msg_to_dict(m) for m in msgs]}


# ──────────────────────────────────────────────────────────────
# 4. 启动时：建表 + 自动补缺失的列 + 确保有一个初始管理员
# ──────────────────────────────────────────────────────────────
def auto_add_missing_columns():
    """自动给已存在的表补上“模型里有、但数据库里还没有”的列。

    作用：以后给某张表加了新字段（如给 Announcement 加 pinned），
    重新部署时不必手动跑 ALTER TABLE —— 启动时自动检测并补齐，
    避免出现 “no such column” 报错。只处理简单的加列，安全无损。
    """
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()

    # 自动遍历所有已定义的模型（以后加任何表/字段都不会漏）
    for mapper in db.Model.registry.mappers:
        model = mapper.class_
        table = model.__tablename__
        if table not in existing_tables:
            continue
        db_cols = {c["name"] for c in inspector.get_columns(table)}
        for col in model.__table__.columns:
            if col.name in db_cols:
                continue
            # 拼出列的类型和默认值，补这一列
            col_type = col.type.compile(dialect=db.engine.dialect)
            default_sql = ""
            if col.default is not None and getattr(col.default, "arg", None) is not None:
                val = col.default.arg
                if isinstance(val, bool):
                    default_sql = f" DEFAULT {1 if val else 0}"
                elif isinstance(val, (int, float)):
                    default_sql = f" DEFAULT {val}"
                elif isinstance(val, str):
                    default_sql = f" DEFAULT '{val}'"
            sql = f'ALTER TABLE {table} ADD COLUMN {col.name} {col_type}{default_sql}'
            with db.engine.begin() as conn:
                conn.execute(text(sql))
            print(f"自动补列：{table}.{col.name}")


with app.app_context():
    db.create_all()
    auto_add_missing_columns()        # ← 自动补齐缺失的列

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
