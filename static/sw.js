// sw.js —— Service Worker
// 作用：让这个网页可以“被安装”成 App。这里做最简单的安装即可，
// 暂不做复杂的离线缓存，避免缓存把更新挡住（小站每次都拿最新内容更省心）。

self.addEventListener("install", (event) => {
  self.skipWaiting(); // 新版本立刻生效
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// fetch 事件：直接走网络（不拦截、不缓存），保证内容总是最新。
self.addEventListener("fetch", (event) => {
  // 不做任何处理，浏览器照常请求。
});

// ── 收到推送：弹系统通知 ──
// 后端 send_web_push 发的 payload 是 { title, body, url }。
self.addEventListener("push", (event) => {
  let data = { title: "新消息", body: "", url: "/" };
  try { if (event.data) data = event.data.json(); } catch (e) {}
  const options = {
    body: data.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    data: { url: data.url || "/" },
    tag: "daoshi-msg",          // 同 tag 的通知会合并，避免连发刷屏
    renotify: true,             // 合并时仍再次提醒（响一下/震一下）
  };
  event.waitUntil(self.registration.showNotification(data.title || "新消息", options));
});

// ── 点通知：聚焦已开的 app 标签并跳转；没开就新开一个 ──
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) {
          client.focus();
          if ("navigate" in client) {
            // navigate 在个别环境可能抛错，失败就保持当前页并已聚焦，不影响
            client.navigate(target).catch(function () {});
          }
          return;
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
