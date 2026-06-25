// install-prompt.js —— 登录页"安装到桌面"提示条（仅安卓 Chrome 等支持 beforeinstallprompt 的浏览器）
// 逻辑：抓住浏览器的可安装信号 → 没装且没关过 → 滑出底部提示条 → 点安装走原生安装框。
// iPhone/已装/不支持的浏览器不会触发 beforeinstallprompt，提示条自然不出现。
(function () {
  var DISMISS_KEY = "daoshi_install_dismissed";   // 记住用户关过，不再自动弹
  var deferredPrompt = null;                        // 浏览器给的安装事件，留着点按钮时用

  // 已经装成 PWA 了就别提示
  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches
      || window.navigator.standalone === true;
  }

  function bar() { return document.getElementById("installBar"); }

  function showBar() {
    var el = bar();
    if (el) el.classList.add("show");
  }
  function hideBar() {
    var el = bar();
    if (el) el.classList.remove("show");
  }

  // 浏览器判定本站可安装时会触发此事件；拦下它、自己决定何时弹
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();              // 阻止浏览器自带的迷你提示，改用我们自己的
    deferredPrompt = e;
    if (isStandalone()) return;                              // 已装，不弹
    if (localStorage.getItem(DISMISS_KEY) === "1") return;   // 关过，不弹
    showBar();
  });

  // 装成功后隐藏提示（清掉，避免重复）
  window.addEventListener("appinstalled", function () {
    deferredPrompt = null;
    hideBar();
  });

  document.addEventListener("DOMContentLoaded", function () {
    var installBtn = document.getElementById("installBtn");
    var closeBtn = document.getElementById("installClose");

    if (installBtn) {
      installBtn.addEventListener("click", function () {
        if (!deferredPrompt) { hideBar(); return; }
        deferredPrompt.prompt();                  // 弹出浏览器原生安装框
        deferredPrompt.userChoice.finally(function () {
          deferredPrompt = null;                  // 一次性，用完即弃
          hideBar();
        });
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        localStorage.setItem(DISMISS_KEY, "1");   // 记住，以后不再自动弹
        hideBar();
      });
    }
  });
})();
