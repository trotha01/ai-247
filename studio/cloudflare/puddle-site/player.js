(function () {
  "use strict";
  var STALL_MS = 15000;      // no playback progress for this long while "playing" => stalled
  var RETRY_MS = 10000;      // reload attempt interval while offline/stalled
  var video = document.getElementById("video");
  var statusEl = document.getElementById("status");
  var stateEl = document.getElementById("state");
  var hls = null, lastTime = -1, lastProgress = Date.now(), url = "", started = false;

  function setState(s, msg) {
    stateEl.textContent = s;
    document.body.dataset.state = s;
    if (msg) { statusEl.textContent = msg; statusEl.hidden = false; }
    else { statusEl.hidden = true; }
  }
  var OFFLINE_MSG = "The channel is offline or temporarily stalled. We will keep retrying automatically. No AI-generated content is shown while it is down.";

  function renderSources() {
    if (!document.getElementById("sources")) return;
    fetch("sources.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(function (d) {
      var ul = document.getElementById("sources");
      ul.textContent = "";
      d.sources.forEach(function (s) {
        var li = document.createElement("li"), a = document.createElement("a");
        a.href = s.url; a.textContent = s.name; a.rel = "noopener noreferrer"; a.target = "_blank";
        li.appendChild(a); ul.appendChild(li);
      });
    }).catch(function () {
      document.getElementById("sources").textContent = "Source list unavailable.";
    });
  }

  function teardown() { if (hls) { hls.destroy(); hls = null; } }

  var retryTimer = null;
  function fail(reason) {
    teardown();
    // report a stall once: until start() runs again the stall check must not fire, and only one retry is pending
    started = false; lastProgress = Date.now();
    setState(reason === "stalled" ? "stalled" : "offline", OFFLINE_MSG);
    if (retryTimer) clearTimeout(retryTimer);
    retryTimer = setTimeout(function () { retryTimer = null; start(); }, RETRY_MS);
  }

  function start() {
    if (!url) { setState("offline", OFFLINE_MSG); return; }
    teardown();
    setState("connecting");
    lastTime = -1; lastProgress = Date.now(); started = false;
    if (window.Hls && Hls.isSupported()) {
      hls = new Hls({ lowLatencyMode: false, manifestLoadingMaxRetry: 2, levelLoadingMaxRetry: 2, fragLoadingMaxRetry: 2 });
      hls.on(Hls.Events.ERROR, function (_e, data) { if (data.fatal) fail("offline"); });
      hls.loadSource(url);
      hls.attachMedia(video);
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;   // Safari / iOS native HLS
      video.onerror = function () { fail("offline"); };
    } else {
      setState("offline", "This browser cannot play HLS video.");
      return;
    }
    video.play().catch(function () {});
  }

  video.addEventListener("playing", function () { started = true; lastProgress = Date.now(); setState("live"); });
  video.addEventListener("timeupdate", function () {
    if (video.currentTime !== lastTime) { lastTime = video.currentTime; lastProgress = Date.now(); }
  });
  setInterval(function () {
    if (!url || video.paused || document.hidden) { lastProgress = Date.now(); return; }
    if (Date.now() - lastProgress > STALL_MS && (started || stateEl.textContent === "connecting")) fail("stalled");
  }, 1000);

  var q = new URLSearchParams(location.search);
  renderSources();
  if (q.get("stall")) { STALL_MS = +q.get("stall"); }   // test hook (ms)
  if (q.get("retry")) { RETRY_MS = +q.get("retry"); }
  fetch("config.json", { cache: "no-cache" }).then(function (r) { return r.json(); })
    .catch(function () { return {}; })
    .then(function (c) { url = q.get("src") || c.streamUrl || ""; start(); });
})();
