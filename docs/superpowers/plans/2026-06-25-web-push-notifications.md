# Web Push 消息提醒 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给导师组 PWA 加 Web Push，使 app 关闭/锁屏时也能弹出"某人给你发了消息"的系统通知，点击跳转对应会话。

**Architecture:** 在现有 Flask-SocketIO 红点机制旁并行加一套 Web Push。后端用 `pywebpush`+VAPID 在消息扇出中枢 `_notify_conversation()` 给收件人所有已订阅设备发推送；前端在 `sw.js` 加 push/notificationclick 事件，设置页加"消息提醒"开关（含 iPhone 智能引导）。订阅凭证存新表 `PushSubscription`。

**Tech Stack:** Flask + Flask-SQLAlchemy + SQLite + pywebpush + Web Push API + Service Worker + Bootstrap。

## Global Constraints

- 项目位置 `D:\Claudework\daoshi_app`，本地 Python 3.14.5，线上 3.10。
- 服务器**不走 git pull**（私有仓库+无代理 TLS 失败），部署靠文件直传 → `sudo systemctl restart daoshi`。本地照常 commit+push（git 走代理 http://127.0.0.1:10808）。
- 新表靠启动 `create_all()` + `auto_add_missing_columns()` 建。**部署后必须停服务用 Python 确认表已建**。
- 手动跑脚本务必带 `DATA_DIR=...` 前缀。真库永远是 `data/app.db`（线上）/ 本地 `app.db`。
- VAPID **私钥绝不进 git**，走环境变量（同 INVITE_CODE 方式，systemd 配置）。公钥可进代码。
- 通知内容：发送者名 + 内容前 30 字；群聊带群名。尊重现有 `notify_on` 字段（关了就不发）。
- 现有 SocketIO 红点/提示音逻辑**一律不动**，只新增、不改写。
- 本地开发用 HTTP（`http://localhost:5000`）即可测 Service Worker 与推送——`localhost` 被浏览器视为安全上下文，例外于 HTTPS 要求。

---

### Task 1: 加 PushSubscription 数据模型

**Files:**
- Modify: `app.py`（在 `ConversationPin` 类后、约 app.py:294 之后插入新模型）
- Test: 临时脚本 `_t_push_model.py`（验证后删除）

**Interfaces:**
- Produces: `PushSubscription` 模型，字段 `id, user_id(int FK), endpoint(Text), p256dh(str), auth(str), created_at(datetime)`；`endpoint` 唯一约束 `uq_push_endpoint`。

- [ ] **Step 1: 写模型**

在 app.py 的 `ConversationPin` 类定义之后插入：

```python
# ── Web Push 订阅表：每个用户每台设备一条 ──
# 浏览器订阅推送后会给一组凭证（endpoint + 两把密钥），存下来后端才能给这台设备发推送。
# 一个人可多设备（手机+电脑各一条）。endpoint 唯一：同设备重订阅时更新而非重复插入。
class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    endpoint = db.Column(db.Text, nullable=False)          # 浏览器推送端点 URL
    p256dh = db.Column(db.String(200), nullable=False)     # 加密公钥（base64）
    auth = db.Column(db.String(100), nullable=False)       # 认证密钥（base64）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("endpoint", name="uq_push_endpoint"),)

    user = db.relationship("User")
```

- [ ] **Step 2: 写验证脚本**

创建 `_t_push_model.py`：

```python
import os
os.environ.setdefault("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
from app import db, app, PushSubscription
with app.app_context():
    from sqlalchemy import inspect
    cols = {c["name"] for c in inspect(db.engine).get_columns("push_subscription")}
    print("push_subscription 列:", cols)
    assert {"id", "user_id", "endpoint", "p256dh", "auth", "created_at"} <= cols
    print("OK: 模型与表正常")
```

- [ ] **Step 3: 跑验证，确认表建成**

Run: `cd /d/Claudework/daoshi_app && python _t_push_model.py`
Expected: 打印 `push_subscription 列: {...}` 且 `OK: 模型与表正常`

- [ ] **Step 4: 删除临时脚本**

Run: `rm /d/Claudework/daoshi_app/_t_push_model.py`

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat(push): 加 PushSubscription 订阅表模型"
```

---

### Task 2: 装 pywebpush 并生成 VAPID 密钥对

**Files:**
- Modify: `requirements.txt`
- Create: 本地临时 `_gen_vapid.py`（生成密钥后删除，密钥另存安全处）

**Interfaces:**
- Produces: 本地已装 `pywebpush`；一对 VAPID 密钥（applicationServerKey 公钥串 + 私钥 PEM）。公钥后续写入 app.py，私钥后续走环境变量。

- [ ] **Step 1: requirements.txt 加依赖**

在 `requirements.txt` 末尾追加一行：

```
pywebpush
```

- [ ] **Step 2: 本地安装**

Run: `cd /d/Claudework/daoshi_app && pip install pywebpush`
Expected: 成功安装 pywebpush 及其依赖（py-vapid、http-ecdsa、cryptography 等）。

- [ ] **Step 3: 写密钥生成脚本**

创建 `_gen_vapid.py`：

```python
# 生成一对 VAPID 密钥。公钥（base64url）给前端做 applicationServerKey；
# 私钥（PEM）后端发推送时用。两者一次生成、永久使用。
from py_vapid import Vapid01
from cryptography.hazmat.primitives import serialization
import base64

v = Vapid01()
v.generate_keys()

# 公钥：未压缩点 → base64url（前端 applicationServerKey 用这个格式）
pub_raw = v.public_key.public_bytes(
    serialization.Encoding.X962,
    serialization.PublicFormat.UncompressedPoint,
)
pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()

# 私钥：PEM 文本
priv_pem = v.private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()

print("=== VAPID 公钥（写进 app.py 的 VAPID_PUBLIC_KEY）===")
print(pub_b64)
print()
print("=== VAPID 私钥（存安全处，部署时走环境变量 VAPID_PRIVATE_KEY，单行）===")
# 转单行：换行替换为 \n 字面，便于放进 systemd Environment=
print(priv_pem.replace("\n", "\\n"))
```

- [ ] **Step 4: 生成并保存密钥**

Run: `cd /d/Claudework/daoshi_app && python _gen_vapid.py`
Expected: 打印公钥串和私钥（单行带 `\n`）。**把这两个值复制保存到本机一个安全的私人文件**（如 `我提供的材料\vapid_keys.txt`，该目录已被 git 排除）。公钥下个 Task 写进代码；私钥本地测试和部署都要用。

- [ ] **Step 5: 删除生成脚本**

Run: `rm /d/Claudework/daoshi_app/_gen_vapid.py`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt
git commit -m "build(push): 加 pywebpush 依赖"
```

注：本 Task 不 commit 密钥。公钥在 Task 3 随代码提交，私钥永不进 git。

---

### Task 3: 后端推送核心 + 两个接口

**Files:**
- Modify: `app.py`（顶部 import 区约 app.py:24 后加 import；配置区约 app.py:65 后加 VAPID 常量；`_notify_conversation` 约 app.py:88 改；新增接口和 `send_web_push` 函数放在 `_notify_conversation` 附近）
- Test: 临时脚本 `_t_push_send.py`（验证后删除）

**Interfaces:**
- Consumes: `PushSubscription` 模型（Task 1）；VAPID 公私钥（Task 2）。
- Produces:
  - 常量 `VAPID_PUBLIC_KEY`（str）、`VAPID_PRIVATE_KEY`（从环境变量读，str）、`VAPID_CLAIMS`（dict）。
  - `send_web_push(user_id: int, title: str, body: str, url: str) -> None`：给该用户所有订阅设备发推送，失效订阅（404/410）自动删。
  - 路由 `GET /api/vapid-public-key` → `{"key": VAPID_PUBLIC_KEY}`。
  - 路由 `POST /api/push/subscribe`（登录态）→ body JSON `{endpoint, keys:{p256dh, auth}}`，upsert by endpoint，返回 `{"ok": True}`。
  - `_notify_conversation` 内对每个收件人（除发送者、且 `notify_on` 为真）调 `send_web_push`。

- [ ] **Step 1: 顶部加 import**

在 app.py 的 `from flask_socketio import SocketIO, join_room`（app.py:24）下一行加：

```python
import json
from pywebpush import webpush, WebPushException
```

- [ ] **Step 2: 加 VAPID 配置常量**

在 `socketio = SocketIO(...)`（app.py:65）之后加：

```python
# ── Web Push（VAPID）配置 ──
# 公钥可公开（前端要用）；私钥保密，走环境变量。本地测试时也需设 VAPID_PRIVATE_KEY 环境变量。
VAPID_PUBLIC_KEY = "在此粘贴 Task2 生成的公钥串"
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
# VAPID 声明里的联系方式（出问题时推送服务联系用），随便一个本站邮箱即可
VAPID_CLAIMS = {"sub": "mailto:admin@daoshi.local"}
```

把 `在此粘贴 Task2 生成的公钥串` 换成 Task 2 实际生成的公钥。

- [ ] **Step 3: 写 send_web_push 函数**

在 `_notify_conversation`（app.py:88）之前插入：

```python
def send_web_push(user_id, title, body, url):
    """给某用户的所有已订阅设备发一条 Web Push 系统通知。
    失效订阅（对方卸载/换设备，推送服务返回 404/410）自动从库里删掉。
    没配私钥（本地没设环境变量）时静默跳过，不影响主流程。"""
    if not VAPID_PRIVATE_KEY:
        return
    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=dict(VAPID_CLAIMS),
            )
        except WebPushException as e:
            # 404/410 = 订阅失效，删掉；其它错误（网络等）忽略，下次再试
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                db.session.delete(sub)
                db.session.commit()
        except Exception:
            pass
```

- [ ] **Step 4: 改 _notify_conversation 加推送扇出**

把 `_notify_conversation`（app.py:88-92）整体替换为：

```python
def _notify_conversation(conv, exclude_user_id=None):
    """给会话里的成员（除发送者）推送未读更新。
    SocketIO 负责 app 开着时的红点+响铃；Web Push 负责 app 关着/锁屏时的系统通知。"""
    # 取最新一条消息做推送正文
    last = (Message.query.filter_by(conversation_id=conv.id)
            .order_by(Message.id.desc()).first())
    sender_name = last.sender.name if (last and last.sender) else "有人"
    if last and last.msg_type == "image":
        snippet = "[图片]"
    else:
        snippet = (last.content or "")[:30] if last else ""
    # 群聊标题带群名，私聊标题就是发送者名
    if conv.is_group:
        title = conv.name or "群聊"
        body = f"{sender_name}：{snippet}"
    else:
        title = sender_name
        body = snippet
    push_url = url_for("conversation_page", conv_id=conv.id, _external=False)

    for m in conv.memberships:
        if m.user_id == exclude_user_id:
            continue
        push_unread(m.user_id, is_new=True)        # 现有：SocketIO 红点+响铃（不动）
        if m.user and m.user.notify_on:            # 新增：尊重“关提醒”设置
            send_web_push(m.user_id, title, body, push_url)  # 新增：系统通知
```

注：`conversation_page` 是会话页路由的 endpoint 名。**实现时先确认实际名**——用 `grep -n "def conversation" app.py` 查；若不是这个名（如 `conversation` / `chat_conversation`），把 `url_for("conversation_page", ...)` 换成真实 endpoint。

- [ ] **Step 5: 加两个接口**

在 `send_web_push` 函数之后加：

```python
@app.route("/api/vapid-public-key")
def vapid_public_key():
    """前端订阅前来取公钥。"""
    return {"key": VAPID_PUBLIC_KEY}


@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    """前端拿到浏览器订阅后调这个存库。按 endpoint upsert（同设备重订阅则更新）。"""
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not (endpoint and p256dh and auth):
        return {"ok": False, "error": "订阅信息不完整"}, 400
    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if sub:
        sub.user_id = current_user.id
        sub.p256dh = p256dh
        sub.auth = auth
    else:
        sub = PushSubscription(user_id=current_user.id, endpoint=endpoint,
                               p256dh=p256dh, auth=auth)
        db.session.add(sub)
    db.session.commit()
    return {"ok": True}
```

- [ ] **Step 6: 确认 conversation 路由 endpoint 名并修正 Step 4**

Run: `cd /d/Claudework/daoshi_app && grep -n "def conversation\|/chat/<int:conv_id>\"" app.py`
Expected: 找到会话页路由的函数名。若与 Step 4 里 `conversation_page` 不符，立即改 Step 4 写入的代码为真实 endpoint 名。

- [ ] **Step 7: 写推送发送验证脚本**

创建 `_t_push_send.py`（验证 VAPID 配置和函数不报错——无真实订阅时应静默返回）：

```python
import os
os.environ.setdefault("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
# 模拟设私钥：用 Task2 保存的私钥单行串
os.environ.setdefault("VAPID_PRIVATE_KEY", "在此粘贴Task2私钥单行串")
from app import app, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, send_web_push
with app.app_context():
    assert VAPID_PUBLIC_KEY and "粘贴" not in VAPID_PUBLIC_KEY, "公钥没填"
    assert VAPID_PRIVATE_KEY, "私钥环境变量没读到"
    # 给不存在的用户发：无订阅，应静默返回，不抛异常
    send_web_push(999999, "测试标题", "测试正文", "/chat/1")
    print("OK: VAPID 配置正确，send_web_push 无订阅时安全返回")
```

- [ ] **Step 8: 跑验证**

Run: `cd /d/Claudework/daoshi_app && python _t_push_send.py`
Expected: 打印 `OK: VAPID 配置正确...`。若报 `公钥没填`→回 Step 2 填公钥；若报私钥没读到→检查 Step 7 私钥串。

- [ ] **Step 9: 删除临时脚本**

Run: `rm /d/Claudework/daoshi_app/_t_push_send.py`

- [ ] **Step 10: Commit**

```bash
git add app.py
git commit -m "feat(push): 后端 Web Push 发送 + 订阅接口，扇出接入消息通知"
```

注：commit 含 VAPID 公钥（可公开），不含私钥。

---

### Task 4: Service Worker 加 push / notificationclick

**Files:**
- Modify: `static/sw.js`

**Interfaces:**
- Consumes: 后端推送 payload `{title, body, url}`（Task 3 send_web_push 发的格式）。
- Produces: sw 收到 push 弹通知；点通知聚焦/打开 app 并导航到 `url`。

- [ ] **Step 1: sw.js 末尾加 push 与 notificationclick 处理**

在 `static/sw.js` 末尾追加：

```javascript
// ── 收到推送：弹系统通知 ──
self.addEventListener("push", (event) => {
  let data = { title: "新消息", body: "", url: "/" };
  try { if (event.data) data = event.data.json(); } catch (e) {}
  const options = {
    body: data.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    data: { url: data.url || "/" },
    tag: "daoshi-msg",          // 同 tag 的通知会合并，避免刷屏
    renotify: true,
  };
  event.waitUntil(self.registration.showNotification(data.title || "新消息", options));
});

// ── 点通知：聚焦已开的 app 标签并跳转；没开就新开 ──
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) {
          client.focus();
          if ("navigate" in client) client.navigate(target);
          return;
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
```

- [ ] **Step 2: 语法自检**

Run: `cd /d/Claudework/daoshi_app && node --check static/sw.js`
Expected: 无输出（语法正确）。若本机无 node，跳过此步，靠浏览器实测验证。

- [ ] **Step 3: Commit**

```bash
git add static/sw.js
git commit -m "feat(push): SW 处理 push 弹通知 + 点击跳转会话"
```

---

### Task 5: 前端订阅逻辑（push-subscribe.js）

**Files:**
- Create: `static/push-subscribe.js`

**Interfaces:**
- Consumes: `GET /api/vapid-public-key`、`POST /api/push/subscribe`（Task 3）；已注册的 service worker（`_pwa_head.html` 已注册 `/sw.js`）。
- Produces: 全局函数：
  - `window.daoshiPush.isIOS()` → bool
  - `window.daoshiPush.isStandalone()` → bool（是否已装成 PWA）
  - `window.daoshiPush.permission()` → "granted"/"denied"/"default"/"unsupported"
  - `window.daoshiPush.enable()` → Promise，返回 `{ok: bool, reason?: string}`；reason 取值 `"need-install"`（iPhone 要先装 PWA）/ `"denied"` / `"unsupported"` / `"error"`。

- [ ] **Step 1: 写 push-subscribe.js**

创建 `static/push-subscribe.js`：

```javascript
// push-subscribe.js —— 前端开启消息提醒（Web Push）
// 暴露 window.daoshiPush.{isIOS,isStandalone,permission,enable}
(function () {
  function isIOS() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent)
      || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); // iPadOS 伪装桌面
  }
  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches
      || window.navigator.standalone === true; // iOS Safari 的私有标志
  }
  function permission() {
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      return "unsupported";
    }
    return Notification.permission; // granted / denied / default
  }
  // base64url 公钥 → Uint8Array（PushManager.subscribe 要求）
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const arr = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
  }

  async function enable() {
    if (permission() === "unsupported") return { ok: false, reason: "unsupported" };
    // iPhone/iPad：必须先装成 PWA 才能订阅推送（苹果限制）
    if (isIOS() && !isStandalone()) return { ok: false, reason: "need-install" };

    const perm = await Notification.requestPermission();
    if (perm !== "granted") return { ok: false, reason: "denied" };

    try {
      const reg = await navigator.serviceWorker.ready;
      const res = await fetch("/api/vapid-public-key");
      const { key } = await res.json();
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(key),
        });
      }
      const r = await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub.toJSON()),
      });
      const data = await r.json();
      return data.ok ? { ok: true } : { ok: false, reason: "error" };
    } catch (e) {
      console.log("订阅失败:", e);
      return { ok: false, reason: "error" };
    }
  }

  window.daoshiPush = { isIOS, isStandalone, permission, enable };
})();
```

- [ ] **Step 2: 语法自检**

Run: `cd /d/Claudework/daoshi_app && node --check static/push-subscribe.js`
Expected: 无输出。无 node 则跳过，靠浏览器实测。

- [ ] **Step 3: Commit**

```bash
git add static/push-subscribe.js
git commit -m "feat(push): 前端订阅逻辑，含 iPhone 设备检测"
```

---

### Task 6: 设置页加"消息提醒"开关 + 引导

**Files:**
- Modify: `templates/settings.html`（在"消息提示音"卡片后、约 settings.html:85 之后插入新卡片）

**Interfaces:**
- Consumes: `window.daoshiPush.{permission,enable,isIOS,isStandalone}`（Task 5）。
- Produces: 设置页一张"消息提醒"卡片，按当前状态显示不同 UI；点开启走 `daoshiPush.enable()`，按 reason 给中文提示。

- [ ] **Step 1: 插入"消息提醒"卡片**

在 settings.html 的"消息提示音"卡片 `</div>`（约第 85 行，"账号安全"卡片之前）之后插入：

```html
        <!-- 消息提醒（系统推送通知）-->
        <div class="gf-card mb-3">
            <div class="p-3">
                <div class="brush mb-2" style="font-size:18px;">消息提醒</div>
                <p class="small mb-2" style="color:var(--muted);">
                    开启后，即使没打开本应用、手机锁屏，也能收到"有人给你发消息"的系统通知。
                </p>
                <button type="button" class="btn btn-ink w-100" id="pushEnableBtn">开启消息提醒</button>
                <div class="small mt-2" id="pushHint" style="color:var(--muted);"></div>
            </div>
        </div>
```

- [ ] **Step 2: 在页面脚本区引入 push-subscribe.js 并加交互**

把 settings.html 末尾的 `<script src="{{ url_for('static', filename='sound.js') }}"></script>`（约第 99 行）替换为：

```html
    <script src="{{ url_for('static', filename='sound.js') }}"></script>
    <script src="{{ url_for('static', filename='push-subscribe.js') }}"></script>
    <script>
      (function () {
        var btn = document.getElementById("pushEnableBtn");
        var hint = document.getElementById("pushHint");
        if (!btn) return;

        function render() {
          var perm = daoshiPush.permission();
          if (perm === "unsupported") {
            btn.disabled = true;
            btn.textContent = "当前浏览器不支持";
            hint.textContent = "建议用 Chrome / Edge / Safari 打开。";
          } else if (perm === "granted") {
            btn.disabled = true;
            btn.textContent = "✓ 已开启消息提醒";
            hint.textContent = "如需关闭，请在系统/浏览器的通知设置里操作。";
          } else if (daoshiPush.isIOS() && !daoshiPush.isStandalone()) {
            btn.textContent = "开启消息提醒";
            hint.innerHTML = "iPhone/iPad 需先把本应用装到主屏幕：点底部 <b>分享</b> → <b>添加到主屏幕</b>，再从主屏幕图标打开本页开启。";
          } else {
            btn.textContent = "开启消息提醒";
            hint.textContent = "";
          }
        }

        btn.addEventListener("click", function () {
          btn.disabled = true;
          btn.textContent = "正在开启…";
          daoshiPush.enable().then(function (r) {
            if (r.ok) {
              btn.textContent = "✓ 已开启消息提醒";
              hint.textContent = "成功！以后有新消息会弹系统通知。";
            } else if (r.reason === "need-install") {
              btn.disabled = false;
              btn.textContent = "开启消息提醒";
              hint.innerHTML = "请先把本应用装到主屏幕：点底部 <b>分享</b> → <b>添加到主屏幕</b>，再从主屏幕图标打开本页开启。";
            } else if (r.reason === "denied") {
              btn.disabled = false;
              btn.textContent = "重新开启";
              hint.textContent = "你拒绝了通知权限。如想开启，请到系统/浏览器通知设置里允许本站。";
            } else if (r.reason === "unsupported") {
              btn.disabled = true;
              btn.textContent = "当前浏览器不支持";
            } else {
              btn.disabled = false;
              btn.textContent = "重试";
              hint.textContent = "开启失败，请稍后再试。";
            }
          });
        });

        render();
      })();
    </script>
```

- [ ] **Step 3: 本地启动手测（关键验证）**

Run: `cd /d/Claudework/daoshi_app && DATA_DIR=. VAPID_PRIVATE_KEY="$(cat 我提供的材料/vapid_keys_private_oneline.txt 2>/dev/null)" python app.py`（私钥单行串放进该文件，或直接内联）

然后在浏览器（Chrome/Edge）开 `http://localhost:5000`：
1. 登录 → 进设置页 → 看到"消息提醒"卡片。
2. 点"开启消息提醒" → 浏览器弹授权框 → 允许 → 按钮变"✓ 已开启"。
3. 开两个账号（一个隐身窗口），互发消息；给**没聚焦那个标签**发消息时，桌面应弹出系统通知"发送者名：内容"。
4. 点通知 → 跳到对应会话。

Expected: 系统通知能弹出，点击能跳转。**这是整个功能的核心验收点，必须亲眼确认通过。**

- [ ] **Step 4: Commit**

```bash
git add templates/settings.html
git commit -m "feat(push): 设置页加消息提醒开关与 iPhone 引导"
```

---

### Task 7: 部署到服务器

**Files:**
- 无代码改动；操作服务器。

**Interfaces:**
- Consumes: 前面所有改动 + Task 2 的 VAPID 私钥单行串。

- [ ] **Step 1: 服务器装 pywebpush**

SSH 到服务器，在项目 venv 装包：

```bash
cd ~/daoshi-app
./venv/bin/pip install pywebpush -i https://pypi.tuna.tsinghua.edu.cn/simple
```
Expected: 成功安装。**若 TLS/网络失败**（该服务器历史上连外网不稳）：备选 a) 换镜像源 `https://mirrors.aliyun.com/pypi/simple/`；b) 本地 `pip download pywebpush -d ./wheels` 下好 whl 传到服务器再 `./venv/bin/pip install --no-index --find-links=./wheels pywebpush`。

- [ ] **Step 2: 配 VAPID 私钥环境变量**

编辑 systemd 配置（先备份）：

```bash
sudo cp /etc/systemd/system/daoshi.service /etc/systemd/system/daoshi.service.bak.$(date +%s)
sudo nano /etc/systemd/system/daoshi.service
```
在 `[Service]` 段加一行（私钥用 Task 2 保存的单行串，含字面 `\n`）：

```
Environment="VAPID_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
```
保存后：

```bash
sudo systemctl daemon-reload
```

- [ ] **Step 3: 传改动文件到服务器**

把这些文件直传到 `/home/ubuntu/daoshi-app/`（覆盖）：`app.py`、`requirements.txt`、`static/sw.js`、`static/push-subscribe.js`、`templates/settings.html`。

- [ ] **Step 4: 重启服务**

```bash
sudo systemctl restart daoshi
```

- [ ] **Step 5: 确认 push_subscription 表已建**

```bash
sudo systemctl stop daoshi
cd ~/daoshi-app
DATA_DIR=/home/ubuntu/daoshi-app/data ./venv/bin/python -c "
from app import db, app
with app.app_context():
    from sqlalchemy import inspect
    print('SQLALCHEMY_DATABASE_URI:', app.config['SQLALCHEMY_DATABASE_URI'])
    print('push_subscription 在表里:' , 'push_subscription' in inspect(db.engine).get_table_names())
"
sudo systemctl start daoshi
```
Expected: 打印的 URI 是 `sqlite:///.../data/app.db`，且 `push_subscription 在表里: True`。若为 False，重复 stop→import→start 一次（记忆里新表偶发首次没建成）。

- [ ] **Step 6: 线上验收**

```bash
sudo journalctl -u daoshi -n 50 --no-pager
curl -so /dev/null -w "%{http_code}" https://<你的域名>/login
curl -s https://<你的域名>/api/vapid-public-key
```
Expected: journalctl 无报错；/login 返回 200；vapid-public-key 返回 `{"key":"..."}` 且 key 非空。

然后手机/电脑实测：装 PWA → 设置页开启提醒 → 让别人发消息 → 收到系统通知。

- [ ] **Step 7: push 留存历史**

本地把所有 commit 推到 GitHub（git 走代理 http://127.0.0.1:10808）：

```bash
cd /d/Claudework/daoshi_app && git push
```

---

## Self-Review

**1. Spec coverage（逐条对 spec）：**
- PWA 装桌面（已实现，不重做）✅ 沿用，无需任务。
- PushSubscription 表 ✅ Task 1。
- pywebpush + VAPID ✅ Task 2。
- 2 个接口（vapid-public-key / push/subscribe）✅ Task 3 Step 5。
- send_web_push 接入 _notify_conversation ✅ Task 3 Step 4。
- sw.js push + notificationclick ✅ Task 4。
- 设置页开关 + iPhone 智能引导 ✅ Task 5（检测）+ Task 6（UI）。
- 失效订阅自动清理（404/410）✅ Task 3 Step 3 send_web_push。
- 尊重 notify_on ✅ Task 3 Step 4。
- 隐私（名+30字，群带群名）✅ Task 3 Step 4。
- 先本地跑通再部署 ✅ Task 6 Step 3 本地验收 → Task 7 部署。
- 服务器不走 git pull / DATA_DIR / 停服务验表 ✅ Task 7。
- VAPID 私钥不进 git ✅ Task 2/3 注明。

**2. Placeholder scan：** Task 3 Step 2 公钥、Task 3 Step 7 / Task 6 Step 3 私钥串、Task 7 域名为**用户运行时填入的真实机密/环境值**，非占位逻辑——已在步骤里明确指出从何处取得，符合"机密不写进 plan"原则。其余无 TBD/TODO。

**3. Type consistency：** `send_web_push(user_id, title, body, url)` 签名在 Task 3 定义、Task 3 Step 4 调用一致；前端 `daoshiPush.enable()` 返回 `{ok, reason}` 在 Task 5 定义、Task 6 消费一致，reason 取值（need-install/denied/unsupported/error）两处吻合；payload `{title, body, url}` 后端发（Task 3）与 sw.js 收（Task 4）一致。`conversation_page` endpoint 名在 Task 3 Step 6 强制实测校正，避免错名。
