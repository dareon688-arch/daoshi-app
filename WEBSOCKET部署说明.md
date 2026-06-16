# WebSocket（实时红点）部署说明

加了 Flask-SocketIO 实时推送后，服务器的**启动方式**和 **nginx** 都要改。
按下面步骤在服务器上操作。

## 第 1 步：装新依赖

```bash
cd ~/daoshi-app
source venv/bin/activate
pip install -r requirements.txt
```

## 第 2 步：改 systemd 启动命令（关键）

SocketIO 不能再用普通 `gunicorn app:app`，要用 **gthread worker + 单 worker**
（threading 模式要求单 worker，否则 WebSocket 连接会乱）。

编辑服务文件：
```bash
sudo nano /etc/systemd/system/daoshi.service
```

把 `ExecStart` 那行改成：
```
ExecStart=/home/ubuntu/daoshi-app/venv/bin/gunicorn --worker-class gthread --workers 1 --threads 8 --bind 127.0.0.1:5000 app:app
```

保存（Ctrl+O 回车，Ctrl+X 退出），然后：
```bash
sudo systemctl daemon-reload
sudo systemctl restart daoshi
sudo systemctl status daoshi --no-pager | grep Active
```

## 第 3 步：改 nginx 支持 WebSocket（关键）

```bash
sudo nano /etc/nginx/sites-available/daoshi
```

在 `location / { ... }` 里加上 WebSocket 升级头（加这 4 行）：
```
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    # ↓↓↓ WebSocket 支持（新增）
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400;
}
```

保存，检查并重启：
```bash
sudo nginx -t
sudo systemctl restart nginx
```

## 第 4 步：验证

打开两个浏览器（不同账号），一个发消息，另一个的底部「消息」红点应**立刻**出现；
点开看完消息，红点应**立刻**消失。

## 出问题怎么回退

如果新启动方式起不来，临时回退到旧的（不带实时，但能用）：
```bash
sudo systemctl stop daoshi
# 把 ExecStart 改回： gunicorn app:app --bind 127.0.0.1:5000 --workers 2
sudo systemctl daemon-reload && sudo systemctl start daoshi
```
