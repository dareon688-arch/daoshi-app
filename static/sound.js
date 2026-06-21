/* 消息提示音：用 Web Audio API 当场合成，不依赖任何音频文件。
   暴露：
     window.playSound(type)  播放提示音（dingdong/water/crisp/off）
     window.unlockSound()    在用户手势里调用，提前“解锁”音频，之后才能稳定出声

   为什么要 unlock：浏览器（尤其手机）规定 AudioContext 必须在一次真实用户
   手势里被创建/恢复才会解锁。否则等收到消息时才创建，那一刻没有手势，
   声音放不出来 → 表现为“时响时不响”。所以页面一加载就监听首次点击/触摸，
   立刻解锁并保持常驻，之后任何时刻来消息都能稳定播放。 */
(function () {
    var ctx = null;
    var unlocked = false;

    function ensureCtx() {
        if (!ctx) {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return null;
            ctx = new AC();
        }
        return ctx;
    }

    // 在“用户手势”里调用：创建 + resume + 播一个 0 音量的哑音，彻底解锁
    function unlock() {
        var c = ensureCtx();
        if (!c) return;
        if (c.state === 'suspended') { try { c.resume(); } catch (e) {} }
        if (!unlocked) {
            try {
                // 播一个听不见的哑音，把音频管线“踢活”，iOS 上尤其需要
                var osc = c.createOscillator(), g = c.createGain();
                g.gain.value = 0;
                osc.connect(g).connect(c.destination);
                osc.start(0);
                osc.stop(c.currentTime + 0.02);
                unlocked = true;
            } catch (e) {}
        }
    }
    window.unlockSound = unlock;

    // 页面任何一次点击/触摸都顺手解锁（捕获阶段，确保最早触发）
    ['touchstart', 'mousedown', 'click', 'keydown'].forEach(function (evt) {
        document.addEventListener(evt, unlock, { capture: true, passive: true });
    });

    /* 播放一个柔和的音：freq 基频, start 相对开始(秒), dur 时长(秒), vol 峰值音量 */
    function soft(c, freq, start, dur, vol) {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        var t0 = c.currentTime + start;
        gain.gain.setValueAtTime(0.0001, t0);
        gain.gain.exponentialRampToValueAtTime(vol, t0 + 0.04);
        gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
        osc.connect(gain).connect(c.destination);
        osc.start(t0);
        osc.stop(t0 + dur + 0.05);
    }

    window.playSound = function (type) {
        if (type === 'off' || !type) return;
        var c = ensureCtx();
        if (!c) return;
        // 每次播放前都确保是 running（切后台回来可能又被挂起）
        if (c.state === 'suspended') { try { c.resume(); } catch (e) {} }
        try {
            if (type === 'dingdong') {
                soft(c, 784, 0,    0.5, 0.18);
                soft(c, 659, 0.18, 0.7, 0.16);
            } else if (type === 'water') {
                var osc = c.createOscillator(), gain = c.createGain();
                osc.type = 'sine';
                var t0 = c.currentTime;
                osc.frequency.setValueAtTime(740, t0);
                osc.frequency.exponentialRampToValueAtTime(520, t0 + 0.16);
                gain.gain.setValueAtTime(0.0001, t0);
                gain.gain.exponentialRampToValueAtTime(0.18, t0 + 0.04);
                gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.6);
                osc.connect(gain).connect(c.destination);
                osc.start(t0); osc.stop(t0 + 0.65);
            } else if (type === 'crisp') {
                soft(c, 880, 0, 0.6, 0.16);
                soft(c, 440, 0, 0.6, 0.07);
            }
        } catch (e) { /* 静默失败，不打扰用户 */ }
    };
})();
