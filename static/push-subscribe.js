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
  // base64url 公钥 → Uint8Array（PushManager.subscribe 要求这个格式）
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
