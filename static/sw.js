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
