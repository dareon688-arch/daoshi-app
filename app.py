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
from datetime import datetime, date
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
from flask_socketio import SocketIO, join_room

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

# 实时推送：用 threading 模式（不依赖 eventlet/gevent，兼容性最好，几十人够用）
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")


@socketio.on("connect")
def _on_connect(auth=None):
    # 每个登录用户连上后，加入“以自己 user id 命名的房间”，
    # 这样给某人推送时，emit 到 user_<id> 房间即可。
    if current_user.is_authenticated:
        join_room(f"user_{current_user.id}")


def push_unread(user_id, is_new=False):
    """给某个用户推送一次‘未读数变化’事件，让前端实时更新红点。
    is_new=True 表示这次是“真的来了新消息”（对方发来），前端据此决定是否响提示音；
    is_new=False 是“读了消息让红点消失”这类变化，不该响铃。"""
    try:
        u = db.session.get(User, user_id)
        total = _total_unread(u) if u else 0
        socketio.emit("unread_update", {"total": total, "is_new": is_new}, room=f"user_{user_id}")
    except Exception:
        pass


def _notify_conversation(conv, exclude_user_id=None):
    """给会话里的成员（除发送者）推送未读更新，让红点实时出现并响提示音。"""
    for m in conv.memberships:
        if m.user_id != exclude_user_id:
            push_unread(m.user_id, is_new=True)   # 来新消息 → 前端响铃


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
    status = db.Column(db.String(20), default="approved") # approved=正常 / pending=待管理员审核
    theme = db.Column(db.String(20), default="bamboo")    # 主题：bamboo竹青 / ink墨黑 / azure淡蓝
    notify_on = db.Column(db.Boolean, default=True)       # 是否显示未读提醒红点
    sound = db.Column(db.String(20), default="dingdong")  # 消息提示音：dingdong叮咚/water水滴/crisp清脆/off关闭

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


# ── 活动日历：一条 = 一个（未来）活动安排 ──
class CalendarEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)       # 活动标题
    event_date = db.Column(db.Date, nullable=False)         # 活动日期
    location = db.Column(db.String(100), nullable=True)     # 地点（选填）
    note = db.Column(db.Text, nullable=True)                # 说明（选填）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── 活动足迹：一条 = 一次办过的活动（图文档案） ──
class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)       # 活动标题
    content = db.Column(db.Text, nullable=True)             # 文案/记述
    cover = db.Column(db.String(200), nullable=True)        # 封面图文件名
    happened_on = db.Column(db.Date, nullable=True)         # 活动发生日期（选填）
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship("User")
    photos = db.relationship("ActivityPhoto", back_populates="activity",
                             cascade="all, delete-orphan")


# ── 活动足迹照片：成员往某则活动里上传的照片（谁传谁删，管理员删任意） ──
class ActivityPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activity.id"))
    filename = db.Column(db.String(200), nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    activity = db.relationship("Activity", back_populates="photos")
    uploader = db.relationship("User")


# ──────────────────────────────────────────────────────────────
# 聊天相关：会话 / 会话成员 / 消息（私聊=2人会话，群聊=多人会话）
# ──────────────────────────────────────────────────────────────

# ── 会话表：一个聊天窗口（一个私聊或一个群） ──
class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_group = db.Column(db.Boolean, default=False)          # True=群聊，False=私聊
    name = db.Column(db.String(80), nullable=True)           # 群名（群聊才有）
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # 谁建的（=群主）
    group_photo = db.Column(db.String(200), nullable=True)   # 群头像文件名（群聊可选）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def can_manage(self, user):
        """谁能管理这个群：群主（建群人）或系统管理员。"""
        return self.is_group and (self.creator_id == user.id or user.is_admin)

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
        # 私聊：取对方名字；对方账号可能已被删，做好兜底
        others = [m.user for m in self.memberships if m.user_id != viewer.id and m.user]
        return others[0].name if others else "（对方已退出）"

    def is_orphan_private(self, viewer):
        """私聊且对方账号已不存在（被移除）→ 这是个空壳会话，列表里应隐藏。"""
        if self.is_group:
            return False
        others = [m.user for m in self.memberships if m.user_id != viewer.id and m.user]
        return not others


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
    recalled = db.Column(db.Boolean, default=False)         # 是否已撤回
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    conversation = db.relationship("Conversation", back_populates="messages")
    sender = db.relationship("User")


# ── 消息隐藏表：记录“某用户删除（隐藏）了某条消息” ──
# 删除只对自己生效，不影响对方——所以不真删 Message 行，只记一条隐藏记录。
class MessageHide(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    message_id = db.Column(db.Integer, db.ForeignKey("message.id"))
    __table_args__ = (db.UniqueConstraint("user_id", "message_id", name="uq_hide"),)


# 某用户在某会话里隐藏了哪些消息 id（集合，过滤显示用）
def _hidden_ids(user, conv_id):
    rows = (db.session.query(MessageHide.message_id)
            .join(Message, Message.id == MessageHide.message_id)
            .filter(MessageHide.user_id == user.id,
                    Message.conversation_id == conv_id).all())
    return {r[0] for r in rows}


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
            if user.status == "pending":
                flash("你的账号还在等管理员审核，通过后才能登录")
                return render_template("login.html")
            login_user(user)                 # 登录成功，记住他
            return redirect(url_for("home"))
        else:
            flash("用户名或密码错误")          # 失败提示
    return render_template("login.html")


# 申请账号的邀请码（师门内部约定，可在服务器用环境变量 INVITE_CODE 改）
INVITE_CODE = os.environ.get("INVITE_CODE", "laoxing2024")


@app.route("/register", methods=["GET", "POST"])
def register():
    # 注意：不拦已登录用户——点了“申请加入”就该看到注册页，
    # 直接弹回主页会让人以为链接坏了（提交的是 status=pending 的新账号，不影响当前登录会话）
    if request.method == "POST":
        invite = request.form.get("invite", "").strip()
        username = request.form.get("username", "").strip()
        name = request.form.get("name", "").strip()
        year = request.form.get("enroll_year", "").strip()
        password = request.form.get("password", "")

        if invite != INVITE_CODE:
            flash("邀请码不对，请向师门管理员索取")
            return render_template("register.html")
        if not username or not name or not year or not password:
            flash("用户名、姓名、入学年份、密码都要填")
            return render_template("register.html")
        if len(password) < 6:
            flash("密码至少 6 位")
            return render_template("register.html")
        if User.query.filter_by(username=username).first():
            flash("这个用户名已被占用，换一个")
            return render_template("register.html")
        try:
            year_int = int(year)
        except ValueError:
            flash("入学年份要填数字")
            return render_template("register.html")

        u = User(username=username, name=name, enroll_year=year_int,
                 is_admin=False, status="pending")   # 待审核
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash("申请已提交，等管理员通过后就能登录啦")
        return redirect(url_for("login"))
    return render_template("register.html")


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
            return redirect(url_for("settings"))
    return render_template("change_password.html")


# ── 设置页：改密码入口 + 消息提醒开关 + 主题颜色 ──
@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/settings/theme", methods=["POST"])
@login_required
def set_theme():
    theme = request.form.get("theme", "bamboo")
    if theme in ("bamboo", "ink", "azure"):
        current_user.theme = theme
        db.session.commit()
        flash("主题已更新 ✅")
    return redirect(url_for("settings"))


@app.route("/settings/sound", methods=["POST"])
@login_required
def set_sound():
    sound = request.form.get("sound", "dingdong")
    if sound in ("dingdong", "water", "crisp", "off"):
        current_user.sound = sound
        db.session.commit()
        flash("提示音已更新 ✅")
    return redirect(url_for("settings"))


# ── 成员列表：所有人都能看，按入学年份排序 ──
@app.route("/members")
@login_required
def members():
    q = (request.args.get("q") or "").strip()

    if q:
        # 搜索模式：在多个字段里模糊匹配
        like = f"%{q}%"
        results = User.query.filter(
            db.or_(
                User.name.like(like),
                User.work_unit.like(like),
                User.hometown.like(like),
                User.wechat.like(like),
                User.email.like(like),
            )
        ).order_by(User.enroll_year, User.name).all()
        return render_template("members.html", search_results=results, q=q, groups=None)

    # 分组模式：按 “入学年份 + 培养方式” 分组
    all_users = User.query.order_by(User.enroll_year.desc(), User.name).all()
    groups = {}   # key: (year, program) -> 显示标签 + 成员列表
    for u in all_users:
        year = u.enroll_year or 0
        prog = u.program or ""
        key = (year, prog)
        if key not in groups:
            year_label = f"{year} 级" if year else "未填年份"
            prog_label = u.program_label or "未填方式"
            groups[key] = {"label": f"{year_label} · {prog_label}", "users": []}
        groups[key]["users"].append(u)
    # 按年份倒序、方式排，转成有序列表
    group_list = [groups[k] for k in sorted(groups.keys(), key=lambda k: (-k[0], k[1]))]
    return render_template("members.html", groups=group_list, q="", search_results=None)


# ── 成员详情：看某一个人的完整名片 ──
@app.route("/member/<int:user_id>")
@login_required
def member_detail(user_id):
    user = db.get_or_404(User, user_id)
    return render_template("member_detail.html", user=user)


# ──────────────────────────────────────────────────────────────
# 管理员后台：管理成员（加人 / 重置密码 / 删除 / 设管理员）
# ──────────────────────────────────────────────────────────────
@app.route("/admin/members")
@login_required
def admin_members():
    if not current_user.is_admin:
        flash("仅管理员可进入")
        return redirect(url_for("members"))
    pending = User.query.filter_by(status="pending").order_by(User.id.desc()).all()
    users = (User.query.filter(User.status != "pending")
             .order_by(User.enroll_year.desc(), User.name).all())
    return render_template("admin_members.html", users=users, pending=pending)


@app.route("/admin/members/<int:user_id>/approve", methods=["POST"])
@login_required
def admin_approve_member(user_id):
    if not current_user.is_admin:
        flash("仅管理员可操作")
        return redirect(url_for("members"))
    u = db.get_or_404(User, user_id)
    u.status = "approved"
    db.session.commit()
    flash(f"已通过 {u.name} 的申请")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/<int:user_id>/reject", methods=["POST"])
@login_required
def admin_reject_member(user_id):
    if not current_user.is_admin:
        flash("仅管理员可操作")
        return redirect(url_for("members"))
    u = db.get_or_404(User, user_id)
    name = u.name
    db.session.delete(u)
    db.session.commit()
    flash(f"已拒绝并删除申请：{name}")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/add", methods=["POST"])
@login_required
def admin_add_member():
    if not current_user.is_admin:
        flash("仅管理员可操作")
        return redirect(url_for("members"))
    username = request.form.get("username", "").strip()
    name = request.form.get("name", "").strip()
    year = request.form.get("enroll_year", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not name or not year or not password:
        flash("用户名、姓名、入学年份、初始密码都要填")
        return redirect(url_for("admin_members"))
    if User.query.filter_by(username=username).first():
        flash(f"用户名 {username} 已存在")
        return redirect(url_for("admin_members"))
    try:
        year_int = int(year)
    except ValueError:
        flash("入学年份要填数字")
        return redirect(url_for("admin_members"))
    u = User(username=username, name=name, enroll_year=year_int, is_admin=False)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    flash(f"已添加 {name}（用户名 {username}，初始密码 {password}），把它发给本人")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/<int:user_id>/reset", methods=["POST"])
@login_required
def admin_reset_password(user_id):
    if not current_user.is_admin:
        flash("仅管理员可操作")
        return redirect(url_for("members"))
    u = db.get_or_404(User, user_id)
    new_pwd = request.form.get("new_password", "").strip()
    if len(new_pwd) < 6:
        flash("新密码至少 6 位")
        return redirect(url_for("admin_members"))
    u.set_password(new_pwd)
    db.session.commit()
    flash(f"已把 {u.name} 的密码重置为 {new_pwd}，发给本人")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
def admin_toggle_admin(user_id):
    if not current_user.is_admin:
        flash("仅管理员可操作")
        return redirect(url_for("members"))
    u = db.get_or_404(User, user_id)
    if u.id == current_user.id:
        flash("不能改自己的管理员身份")
        return redirect(url_for("admin_members"))
    u.is_admin = not u.is_admin
    db.session.commit()
    flash(f"{u.name} {'已设为管理员' if u.is_admin else '已取消管理员'}")
    return redirect(url_for("admin_members"))


@app.route("/admin/members/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_delete_member(user_id):
    if not current_user.is_admin:
        flash("仅管理员可操作")
        return redirect(url_for("members"))
    u = db.get_or_404(User, user_id)
    if u.id == current_user.id:
        flash("不能删除自己")
        return redirect(url_for("admin_members"))
    name = u.name
    _cleanup_user_relations(u)   # 先清理他的会话/成员记录/消息，避免留下“（对方已退出）”空壳
    db.session.delete(u)
    db.session.commit()
    flash(f"已删除成员 {name}")
    return redirect(url_for("admin_members"))


def _cleanup_user_relations(u):
    """删一个用户前，清理他在聊天里留下的关联，避免产生孤儿会话/消息。
    - 私聊会话（只有两个人）：直接整条删掉，对方列表里就不会再看到他
    - 群聊：只把他从群里移除（删 Membership），群和别人发的消息都保留
    - 他发过的消息：sender_id 置空（显示为匿名），不破坏群里的聊天记录
    """
    for mem in Membership.query.filter_by(user_id=u.id).all():
        conv = mem.conversation
        if conv and not conv.is_group:
            db.session.delete(conv)   # 私聊整条删（会级联删掉其消息和两条成员记录）
        else:
            db.session.delete(mem)    # 群聊只把他踢出
    # 群聊里他发过的消息：作者置空，保留内容不留孤儿外键
    for msg in Message.query.filter_by(sender_id=u.id).all():
        msg.sender_id = None


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
# 活动日历：看未来活动（所有人）；管理员可增删改
# ──────────────────────────────────────────────────────────────
@app.route("/calendar")
@login_required
def calendar():
    # 按日期升序，今天及以后的在前；过去的也列出但靠后
    today = date.today()
    upcoming = (CalendarEvent.query.filter(CalendarEvent.event_date >= today)
                .order_by(CalendarEvent.event_date.asc()).all())
    past = (CalendarEvent.query.filter(CalendarEvent.event_date < today)
            .order_by(CalendarEvent.event_date.desc()).all())
    return render_template("calendar.html", upcoming=upcoming, past=past, today=today)


@app.route("/calendar/new", methods=["GET", "POST"])
@login_required
def new_event():
    if not current_user.is_admin:
        flash("只有管理员能添加活动")
        return redirect(url_for("calendar"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("event_date", "").strip()
        location = request.form.get("location", "").strip()
        note = request.form.get("note", "").strip()
        if not title or not date_str:
            flash("标题和日期必填")
            return render_template("new_event.html")
        try:
            ev_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("日期格式不对")
            return render_template("new_event.html")
        ev = CalendarEvent(title=title, event_date=ev_date,
                           location=location or None, note=note or None)
        db.session.add(ev)
        db.session.commit()
        flash("活动已添加 ✅")
        return redirect(url_for("calendar"))
    return render_template("new_event.html")


@app.route("/calendar/delete/<int:event_id>", methods=["POST"])
@login_required
def delete_event(event_id):
    if not current_user.is_admin:
        flash("只有管理员能删除活动")
        return redirect(url_for("calendar"))
    ev = db.get_or_404(CalendarEvent, event_id)
    db.session.delete(ev)
    db.session.commit()
    flash("活动已删除")
    return redirect(url_for("calendar"))


# ──────────────────────────────────────────────────────────────
# 活动足迹：办过的活动图文档案；管理员发布，成员可往里补照片
# ──────────────────────────────────────────────────────────────
@app.route("/footprint")
@login_required
def footprint():
    items = Activity.query.order_by(Activity.created_at.desc()).all()
    return render_template("footprint.html", items=items)


@app.route("/footprint/new", methods=["GET", "POST"])
@login_required
def new_activity():
    if not current_user.is_admin:
        flash("只有管理员能发布活动足迹")
        return redirect(url_for("footprint"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        date_str = request.form.get("happened_on", "").strip()
        if not title:
            flash("标题必填")
            return render_template("new_activity.html")
        happened = None
        if date_str:
            try:
                happened = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                happened = None
        # 封面图（选填）
        cover_name = None
        file = request.files.get("cover")
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit(".", 1)[1].lower()
            cover_name = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], cover_name))
        act = Activity(title=title, content=content or None, cover=cover_name,
                       happened_on=happened, author_id=current_user.id)
        db.session.add(act)
        db.session.commit()
        flash("活动足迹已发布 🎉")
        return redirect(url_for("activity_detail", activity_id=act.id))
    return render_template("new_activity.html")


@app.route("/footprint/<int:activity_id>")
@login_required
def activity_detail(activity_id):
    act = db.get_or_404(Activity, activity_id)
    photos = (ActivityPhoto.query.filter_by(activity_id=act.id)
              .order_by(ActivityPhoto.created_at.asc()).all())
    return render_template("activity_detail.html", act=act, photos=photos)


@app.route("/footprint/<int:activity_id>/add-photo", methods=["POST"])
@login_required
def add_activity_photo(activity_id):
    # 所有成员都能往活动里补照片
    act = db.get_or_404(Activity, activity_id)
    file = request.files.get("photo")
    if not file or not file.filename:
        flash("请选择照片")
        return redirect(url_for("activity_detail", activity_id=act.id))
    if not allowed_file(file.filename):
        flash("照片格式不支持")
        return redirect(url_for("activity_detail", activity_id=act.id))
    ext = file.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))
    photo = ActivityPhoto(activity_id=act.id, filename=fname, uploader_id=current_user.id)
    db.session.add(photo)
    db.session.commit()
    flash("照片已添加 ✅")
    return redirect(url_for("activity_detail", activity_id=act.id))


@app.route("/footprint/photo/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_activity_photo(photo_id):
    photo = db.get_or_404(ActivityPhoto, photo_id)
    aid = photo.activity_id
    # 谁传谁能删，管理员能删任意
    if photo.uploader_id != current_user.id and not current_user.is_admin:
        flash("你没有权限删除这张照片")
        return redirect(url_for("activity_detail", activity_id=aid))
    filename = photo.filename
    db.session.delete(photo)
    db.session.commit()
    try:
        os.remove(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    except OSError:
        pass
    flash("照片已删除")
    return redirect(url_for("activity_detail", activity_id=aid))


@app.route("/footprint/<int:activity_id>/delete", methods=["POST"])
@login_required
def delete_activity(activity_id):
    if not current_user.is_admin:
        flash("只有管理员能删除活动足迹")
        return redirect(url_for("footprint"))
    act = db.get_or_404(Activity, activity_id)
    db.session.delete(act)   # 关联照片记录会级联删除
    db.session.commit()
    flash("活动足迹已删除")
    return redirect(url_for("footprint"))


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


# 让所有模板都能拿到当前用户的未读总数（导航栏红点用）+ 管理员的待审核申请数（同门页“管理”红点用）
@app.context_processor
def inject_unread():
    if current_user.is_authenticated:
        try:
            unread = _total_unread(current_user)
        except Exception:
            unread = 0
        # 只有管理员才需要待审核数；普通成员恒为 0，不浪费查询
        pending = 0
        if current_user.is_admin:
            try:
                pending = User.query.filter_by(status="pending").count()
            except Exception:
                pending = 0
        return {"unread_total": unread, "pending_count": pending}
    return {"unread_total": 0, "pending_count": 0}


# ── 查询当前用户未读总数（前端在页面重新可见时主动拉，兜底实时推送漏掉的情况）──
@app.route("/api/unread")
@login_required
def api_unread():
    try:
        return {"total": _total_unread(current_user)}
    except Exception:
        return {"total": 0}


# ── 会议引导页：一键打开腾讯会议 ──
@app.route("/meeting")
@login_required
def meeting():
    return render_template("meeting.html")


def _build_chat_items():
    """构建当前用户的会话列表数据（标题、最后一条消息、未读数）。"""
    items = []
    for c in _my_conversations():
        # 私聊对方已被移除 → 空壳会话，不显示在列表里（避免“（对方已退出）”刷屏）
        if c.is_orphan_private(current_user):
            continue
        # 取最近一条“我没删过的”消息当列表预览
        hidden = _hidden_ids(current_user, c.id)
        last = (Message.query.filter_by(conversation_id=c.id)
                .filter(~Message.id.in_(hidden) if hidden else True)
                .order_by(Message.created_at.desc()).first())
        # 私聊：取对方头像照片（群聊用'群'字圆圈，不取）
        other_photo = None
        if not c.is_group:
            others = [m.user for m in c.memberships if m.user_id != current_user.id and m.user]
            if others and others[0].photo:
                other_photo = others[0].photo
        items.append({
            "conv": c,
            "title": c.title_for(current_user),
            "last": last,
            "unread": _unread_count(c, current_user),
            "other_photo": other_photo,   # 对方头像文件名（无则 None → 模板用首字圆圈）
        })
    return items


# ── 聊天首页：我的会话列表 ──
@app.route("/chat")
@login_required
def chat():
    others = User.query.filter(User.id != current_user.id).all()
    return render_template("chat.html", items=_build_chat_items(), others=others)


# ── 会话列表片段：消息页收到实时推送时，用它局部刷新列表（不整页刷新）──
@app.route("/chat/list")
@login_required
def chat_list():
    return render_template("_chat_list.html", items=_build_chat_items())


# ── 全局搜索聊天记录：跨所有会话，找含关键词的文字消息 ──
@app.route("/chat/search")
@login_required
def chat_search():
    q = (request.args.get("q") or "").strip()
    results = []
    if q:
        # 我所在的会话 id 列表
        my_conv_ids = [c.id for c in _my_conversations()]
        if my_conv_ids:
            hits = (Message.query
                    .filter(Message.conversation_id.in_(my_conv_ids),
                            Message.recalled == False,
                            Message.msg_type == "text",
                            Message.content.ilike(f"%{q}%"))
                    .order_by(Message.created_at.desc()).all())
            for m in hits:
                # 跳过我已删除（隐藏）的
                if MessageHide.query.filter_by(user_id=current_user.id, message_id=m.id).first():
                    continue
                conv = m.conversation
                if conv and not conv.is_orphan_private(current_user):
                    results.append({
                        "conv_id": conv.id,
                        "conv_title": conv.title_for(current_user),
                        "sender": m.sender.name if m.sender else "?",
                        "content": m.content or "",
                        "msg_id": m.id,
                        "time": m.created_at.strftime("%Y-%m-%d %H:%M"),
                    })
    return render_template("chat_search.html", q=q, results=results)


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

    hidden = _hidden_ids(current_user, conv.id)   # 我删除（隐藏）过的消息
    msgs = [m for m in (Message.query.filter_by(conversation_id=conv.id)
            .order_by(Message.created_at.asc()).all())
            if m.id not in hidden]

    # 关键字搜索（会话内查找）：有 q 时只保留命中的文字消息，并标记给前端高亮
    search_q = (request.args.get("q") or "").strip()

    # 更新“读到哪了”
    mem = Membership.query.filter_by(conversation_id=conv.id, user_id=current_user.id).first()
    if mem:
        mem.last_read_at = datetime.utcnow()
        db.session.commit()
        push_unread(current_user.id)   # 读了消息，实时让自己的红点消失

    # 私聊时，找出对方（点头像看资料用）
    other = None
    if not conv.is_group:
        others = [m.user for m in conv.memberships if m.user_id != current_user.id]
        other = others[0] if others else None

    return render_template("conversation.html", conv=conv, msgs=msgs,
                           title=conv.title_for(current_user), other=other,
                           search_q=search_q)


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
        "recalled": bool(m.recalled),
        # 发送者头像：有照片给 url，没有给 None（前端用名字首字圆圈兜底）
        "avatar_url": url_for("uploaded_file", filename=m.sender.photo) if (m.sender and m.sender.photo) else None,
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
    _notify_conversation(conv, exclude_user_id=current_user.id)
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
    _notify_conversation(conv, exclude_user_id=current_user.id)
    return {"ok": True, "id": msg.id}


# ── 撤回消息：自己发的随时撤；管理员/群主能撤任意 ──
@app.route("/chat/<int:conv_id>/recall/<int:msg_id>", methods=["POST"])
@login_required
def recall_message(conv_id, msg_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        return {"ok": False, "error": "你不在这个会话里"}, 403
    msg = db.get_or_404(Message, msg_id)
    if msg.conversation_id != conv.id:
        return {"ok": False, "error": "消息不属于这个会话"}, 400

    # 权限：自己发的，或系统管理员，或（群聊里）群主
    is_mine = msg.sender_id == current_user.id
    can_manage = current_user.is_admin or (conv.is_group and conv.creator_id == current_user.id)
    if not (is_mine or can_manage):
        return {"ok": False, "error": "你没有权限撤回这条消息"}, 403

    msg.recalled = True
    db.session.commit()
    # 实时通知会话里所有人：这条消息被撤回了
    for m in conv.memberships:
        socketio.emit("message_recalled",
                      {"conv_id": conv.id, "msg_id": msg.id},
                      room=f"user_{m.user_id}")
    return {"ok": True}


# ── 删除单条消息（只对自己隐藏，不影响对方）──
@app.route("/chat/<int:conv_id>/delete-msg/<int:msg_id>", methods=["POST"])
@login_required
def delete_message_for_me(conv_id, msg_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        return {"ok": False, "error": "你不在这个会话里"}, 403
    msg = db.get_or_404(Message, msg_id)
    if msg.conversation_id != conv.id:
        return {"ok": False, "error": "消息不属于这个会话"}, 400
    # 已经隐藏过就不重复加
    exists = MessageHide.query.filter_by(user_id=current_user.id, message_id=msg.id).first()
    if not exists:
        db.session.add(MessageHide(user_id=current_user.id, message_id=msg.id))
        db.session.commit()
    return {"ok": True}


# ── 清空整条会话的聊天记录（只清自己这边，对方不受影响）──
@app.route("/chat/<int:conv_id>/clear", methods=["POST"])
@login_required
def clear_conversation(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        flash("你不在这个会话里")
        return redirect(url_for("chat"))
    # 把该会话当前所有消息，对我隐藏（已隐藏的跳过）
    already = _hidden_ids(current_user, conv.id)
    msgs = Message.query.filter_by(conversation_id=conv.id).all()
    for m in msgs:
        if m.id not in already:
            db.session.add(MessageHide(user_id=current_user.id, message_id=m.id))
    db.session.commit()
    # 不弹提示，直接回到（已清空的）会话页
    return redirect(url_for("conversation", conv_id=conv.id))


# ── 私聊设置页：看对方资料入口 + 删除聊天记录（像微信点右上角进来）──
@app.route("/chat/<int:conv_id>/settings")
@login_required
def chat_settings(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if conv.is_group or not _is_member(conv, current_user):
        flash("无权查看")
        return redirect(url_for("chat"))
    others = [m.user for m in conv.memberships if m.user_id != current_user.id and m.user]
    other = others[0] if others else None
    return render_template("chat_settings.html", conv=conv, other=other)


# ── 群信息页：看成员、改名、改头像、加人、移除、退群、解散 ──
@app.route("/chat/<int:conv_id>/info")
@login_required
def group_info(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.is_group or not _is_member(conv, current_user):
        flash("无权查看")
        return redirect(url_for("chat"))
    members = [m.user for m in conv.memberships]
    # 可加入的人：同门里还不在群的
    member_ids = {u.id for u in members}
    candidates = User.query.filter(
        User.id.notin_(member_ids), User.status == "approved"
    ).order_by(User.name).all()
    return render_template("group_info.html", conv=conv, members=members,
                           candidates=candidates,
                           can_manage=conv.can_manage(current_user))


@app.route("/chat/<int:conv_id>/rename", methods=["POST"])
@login_required
def rename_group(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.can_manage(current_user):
        flash("只有群主或管理员能改群名")
        return redirect(url_for("group_info", conv_id=conv.id))
    name = (request.form.get("name") or "").strip()
    if name:
        conv.name = name[:80]
        db.session.commit()
        flash("群名已修改 ✅")
    return redirect(url_for("group_info", conv_id=conv.id))


@app.route("/chat/<int:conv_id>/photo", methods=["POST"])
@login_required
def group_photo(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.can_manage(current_user):
        flash("只有群主或管理员能改群头像")
        return redirect(url_for("group_info", conv_id=conv.id))
    file = request.files.get("photo")
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        fname = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))
        conv.group_photo = fname
        db.session.commit()
        flash("群头像已更新 ✅")
    return redirect(url_for("group_info", conv_id=conv.id))


@app.route("/chat/<int:conv_id>/add-members", methods=["POST"])
@login_required
def add_group_members(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.can_manage(current_user):
        flash("只有群主或管理员能加人")
        return redirect(url_for("group_info", conv_id=conv.id))
    ids = request.form.getlist("user_ids")
    added = 0
    for uid in ids:
        uid = int(uid)
        if not Membership.query.filter_by(conversation_id=conv.id, user_id=uid).first():
            db.session.add(Membership(conversation_id=conv.id, user_id=uid))
            added += 1
    db.session.commit()
    if added:
        flash(f"已加入 {added} 人 ✅")
    return redirect(url_for("group_info", conv_id=conv.id))


@app.route("/chat/<int:conv_id>/remove/<int:user_id>", methods=["POST"])
@login_required
def remove_group_member(conv_id, user_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.can_manage(current_user):
        flash("只有群主或管理员能移除成员")
        return redirect(url_for("group_info", conv_id=conv.id))
    if user_id == conv.creator_id:
        flash("不能移除群主")
        return redirect(url_for("group_info", conv_id=conv.id))
    mem = Membership.query.filter_by(conversation_id=conv.id, user_id=user_id).first()
    if mem:
        db.session.delete(mem)
        db.session.commit()
        flash("已移除该成员")
    return redirect(url_for("group_info", conv_id=conv.id))


@app.route("/chat/<int:conv_id>/leave", methods=["POST"])
@login_required
def leave_group(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.is_group:
        return redirect(url_for("chat"))
    # 群主退群=解散；普通成员退群=只移除自己
    if conv.creator_id == current_user.id:
        db.session.delete(conv)
        db.session.commit()
        flash("群已解散")
    else:
        mem = Membership.query.filter_by(conversation_id=conv.id, user_id=current_user.id).first()
        if mem:
            db.session.delete(mem)
            db.session.commit()
        flash("已退出群聊")
    return redirect(url_for("chat"))


@app.route("/chat/<int:conv_id>/dissolve", methods=["POST"])
@login_required
def dissolve_group(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.can_manage(current_user):
        flash("只有群主或管理员能解散群")
        return redirect(url_for("group_info", conv_id=conv.id))
    db.session.delete(conv)
    db.session.commit()
    flash("群已解散")
    return redirect(url_for("chat"))


# ── 轮询：拉取某会话里 id 大于 after 的新消息（前端每隔几秒调一次） ──
@app.route("/chat/<int:conv_id>/poll")
@login_required
def poll_messages(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not _is_member(conv, current_user):
        return {"ok": False}, 403
    after = request.args.get("after", 0, type=int)
    hidden = _hidden_ids(current_user, conv.id)   # 我删除（隐藏）过的不再推给前端
    msgs = [m for m in (Message.query
            .filter(Message.conversation_id == conv.id, Message.id > after)
            .order_by(Message.created_at.asc()).all())
            if m.id not in hidden]
    # 同时返回本会话里已被撤回的消息 id（让前端把已显示的消息标记成撤回）
    recalled_ids = [m.id for m in Message.query
                    .filter(Message.conversation_id == conv.id, Message.recalled == True).all()]
    return {"ok": True,
            "messages": [_msg_to_dict(m) for m in msgs],
            "recalled": recalled_ids}


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

    # 旧主题 coral（朱砂）已下线，改为 azure（淡蓝）。把选过朱砂的人平滑迁过去。
    moved = User.query.filter_by(theme="coral").update({"theme": "azure"})
    if moved:
        db.session.commit()
        print(f"已把 {moved} 个用户的主题从 coral 迁移到 azure")

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
    # 本地开发：用 socketio.run 启动（支持 WebSocket）
    socketio.run(app, host="0.0.0.0", port=5000, debug=True,
                 allow_unsafe_werkzeug=True)
