# 导师组 App — Web Push 消息提醒设计

日期：2026-06-25
项目：daoshi-app（导师组通讯录+相册+聊天 web app，已上腾讯云北京、备案成功、HTTPS 齐全）

## 背景与目标

备案成功后，用户希望：
1. **可下载到本地的 app 形式** —— 经分析，最优解是继续走 **PWA**（已实现"添加到主屏幕"装桌面），**不打包原生 app**（iOS 上架要 99 美元/年+审核，安卓侧载各品牌拦截，且每次改码都要重新打包，对几十人内部使用不值得）。
2. **消息提醒** —— 用 **Web Push** 实现：即使 app 没打开、手机锁屏、电脑只开桌面，也能弹出"张三给你发了消息"，点通知跳到对应聊天。

**关键认知**：原生 app 能做的"装桌面 + 锁屏推送"PWA 现在都能做到，且零成本。原生 app 的额外能力（底层硬件、上架商店）本场景用不上。YAGNI。

## 整体架构：SocketIO 与 Web Push 并行

保留现有一切（SocketIO 红点、提示音都不动），并行加一套 Web Push。两者分工：

| 场景 | SocketIO（已有） | Web Push（新增） |
|---|---|---|
| app 开着 | ✅ 红点+响铃 | 静默（不重复打扰） |
| app 关着/锁屏 | ❌ 收不到 | ✅ 弹系统通知 |

接入点已确认：`app.py` 的 `_notify_conversation(conv, exclude_user_id)`（app.py:88）是消息扇出中枢，现有 `push_unread()` 走 SocketIO；只需在此并行加一行 `send_web_push()`。两套互不干扰。

## 新增组件（3 部分）

### 1. 数据库：PushSubscription 表

存每个用户每台设备的推送订阅凭证（一人可多设备）：

```python
class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    endpoint = db.Column(db.Text, nullable=False)          # 浏览器推送端点 URL（唯一标识一台设备订阅）
    p256dh = db.Column(db.String(200), nullable=False)      # 加密公钥
    auth = db.Column(db.String(100), nullable=False)        # 认证密钥
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # endpoint 唯一约束：同一设备重复订阅时更新而非重复插入
```

靠现有 `auto_add_missing_columns()` / 启动 `create_all()` 建表。**部署后务必停服务用 Python 确认表已建**（记忆中 `message_hide` 曾重启多次未建，停服务 import 一次才建成）。

### 2. 后端：pywebpush + VAPID + 2 个接口

- 依赖：`pywebpush`（requirements.txt 新增）。
- **VAPID 密钥对**：本地生成一次，公钥写入代码/环境变量，**私钥走 systemd 环境变量**（同 INVITE_CODE/DATA_DIR 方式），绝不进 git。
- 新增接口：
  - `GET /api/vapid-public-key` —— 前端取公钥用于订阅。
  - `POST /api/push/subscribe` —— 前端把订阅凭证存进 PushSubscription 表（登录态，upsert by endpoint）。
- `send_web_push(user_id, title, body, url)`：给该用户所有已订阅设备发推送。
- 在 `_notify_conversation()` 内调用：给收件人发"发送者名：内容前30字（群聊带群名）"。

### 3. 前端：sw.js + 开启引导

- `sw.js` 新增 `push` 事件（弹通知）和 `notificationclick` 事件（打开/聚焦 app 并跳转会话）。
- **设置页新增"消息提醒"开关**，点开启时智能引导：
  - 安卓/桌面 Chrome/Edge → 直接弹浏览器授权 → 注册订阅。
  - iPhone/iPad：
    - 未装 PWA（在 Safari）→ 引导"先 [分享]→添加到主屏幕，从图标打开后再来开启"。
    - 已装 PWA（standalone）→ 同安卓流程。
  - 检测用 `display-mode: standalone` / `navigator.standalone`。

## 三个稳妥性细节（Web Push 实战必处理）

1. **失效订阅自动清理**：发推送返回 404/410（用户卸载/换设备）→ 后端自动从表删除该订阅，避免堆积。
2. **尊重"关提醒"设置**：复用现有 `notify_on` 字段；用户关了提醒就不发 Web Push，与红点逻辑统一。
3. **消息内容隐私**：通知只显示发送者名 + 内容前 30 字（群聊显示群名）。锁屏可见，符合聊天 app 习惯。

## 数据流

**开启提醒（前端）**：点"开启" → 检测设备 → (iPhone 未装 PWA 则引导先装) → 弹浏览器授权 → 拿到订阅 → POST /api/push/subscribe 存库。

**发推送（后端）**：张三发消息 → add message → `_notify_conversation(conv)` → `push_unread()`（SocketIO 红点，不动）+ `send_web_push()`（新增）→ 收件人各设备 sw.js 收 push → 弹通知 → 点击打开/聚焦 app 跳会话。

## 开发顺序（已与用户确认）

**先本地全做完并跑通**（本机写完所有代码 + 装 pywebpush + 本地启动验证推送真能弹出 + 零 bug），**再一次性部署服务器**（装包 + 文件直传 + 配私钥）。部署失败风险最低。

⚠️ 服务器风险点：该服务器私有仓库+无代理，pip 连 pypi 可能 TLS 失败。部署时若 `pip install pywebpush` 失败，备选：离线 whl 上传 / 临时代理 / 国内镜像源（如 `-i https://pypi.tuna.tsinghua.edu.cn/simple`）。

## 部署运维要点（沿用项目既定方式）

- 服务器**不走 git pull**（私有仓库+无代理 TLS 失败），改文件直传 `/home/ubuntu/daoshi-app` → `sudo systemctl restart daoshi` → 看 journalctl 无报错 + curl /login 200。
- 手动跑脚本务必带 `DATA_DIR=/home/ubuntu/daoshi-app/data` 前缀，否则连错根目录废弃库报 readonly。
- 改 systemd 环境变量后 `sudo systemctl daemon-reload && sudo systemctl restart daoshi`。
- 真库永远是 `data/app.db`。

## 不做的事（YAGNI）

- 不打包原生 app（apk / iOS 包 / App Store）。
- 不做离线缓存（sw.js 维持直连网络拿最新，避免缓存挡更新）。
- 不替换现有 SocketIO（它负责 app 开着时的实时红点，与 Web Push 互补）。
- 推送不做"已读回执""通知分组折叠"等高级特性（几十人内部用不上）。
