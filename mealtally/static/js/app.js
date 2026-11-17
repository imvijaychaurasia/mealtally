/* SPDX-License-Identifier: AGPL-3.0-only */
/* Mealtally front-end glue. No inline scripts anywhere (CSP script-src 'self'); Alpine runs in its CSP build. */
(function () {
  "use strict";

  function beep() {
    if (localStorage.getItem("mealtally.beep") === "off") return;
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      var ctx = new Ctx();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.value = 0.15;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.18);
    } catch (e) { /* audio is best effort */ }
  }
  document.addEventListener("mealtally:redeemed", beep);

  document.addEventListener("alpine:init", function () {
    var Alpine = window.Alpine;

    // Ring/countdown. data-seconds on the element; restarts whenever HTMX swaps a new element in.
    Alpine.data("countdown", function () {
      return {
        n: 30, total: 30, timer: null,
        init: function () {
          this.total = parseInt(this.$el.dataset.seconds || "30", 10);
          this.n = this.total;
          var self = this;
          this.timer = setInterval(function () { if (self.n > 0) self.n--; }, 1000);
        },
        destroy: function () { clearInterval(this.timer); },
        get offset() { return 100 - (100 * this.n) / this.total; },
        get expired() { return this.n <= 0; },
        get active() { return this.n > 0; },
      };
    });

    // Undo bar: visible for 30 s after a redemption.
    Alpine.data("undoBar", function () {
      return {
        n: 30, timer: null,
        init: function () {
          var self = this;
          this.timer = setInterval(function () { if (self.n > 0) self.n--; }, 1000);
        },
        destroy: function () { clearInterval(this.timer); },
        get active() { return this.n > 0; },
      };
    });

    // Keep the screen awake while the QR is open (best effort).
    Alpine.data("qrScreen", function () {
      return {
        lock: null,
        async init() {
          try { if (navigator.wakeLock) this.lock = await navigator.wakeLock.request("screen"); } catch (e) { /* ignore */ }
        },
        destroy: function () { if (this.lock) this.lock.release(); },
      };
    });

    Alpine.data("beepToggle", function () {
      return {
        on: localStorage.getItem("mealtally.beep") !== "off",
        toggle: function () { this.on = !this.on; localStorage.setItem("mealtally.beep", this.on ? "on" : "off"); },
        get label() { return this.on ? this.$el.dataset.on : this.$el.dataset.off; },
      };
    });

    Alpine.data("copyBtn", function () {
      return {
        done: false,
        async copy() {
          try { await navigator.clipboard.writeText(this.$el.dataset.text); this.done = true; } catch (e) { this.done = false; }
        },
        print: function () { window.print(); },
      };
    });

    // Plan form: live "₹50 per meal", and the days field only for fixed-day plans.
    Alpine.data("planForm", function () {
      return {
        price: "", meals: "", mode: "ROLLING_DAYS",
        init: function () {
          this.price = this.$el.dataset.price; this.meals = this.$el.dataset.meals; this.mode = this.$el.dataset.mode;
        },
        get isCalendar() { return this.mode === "CALENDAR_MONTH"; },
        get showDays() { return this.mode !== "CALENDAR_MONTH"; },
        get perMeal() {
          var p = parseFloat(this.price), m = parseInt(this.meals, 10);
          if (!(p > 0) || !(m > 0)) { return ""; }
          var each = p / m;
          return "\u20b9" + (Math.abs(each - Math.round(each)) < 0.005 ? String(Math.round(each)) : each.toFixed(2)) + " per meal";
        },
      };
    });

    Alpine.data("toggle", function () {
      return { open: false, toggle: function () { this.open = !this.open; }, close: function () { this.open = false; }, get closed() { return !this.open; } };
    });

    // QR scanner overlay (zxing, vendored). Starts only from the tap; falls back to the manual box, which opens on any failure.
    Alpine.data("scanner", function () {
      return {
        open: false, error: "", controls: null, cfg: {},
        init: function () { this.cfg = this.$el.dataset; },  // $el is the component root only here (not inside click handlers)
        async start() {
          this.open = true; this.error = "";
          var video = this.$refs.video;
          video.muted = true; video.setAttribute("playsinline", ""); video.setAttribute("autoplay", "");  // iOS Safari needs all three
          try {
            var reader = new window.ZXingBrowser.BrowserQRCodeReader();
            var self = this;
            this.controls = await reader.decodeFromConstraints({ video: { facingMode: { ideal: "environment" } } }, video, function (result) {
              if (result) {
                self.$refs.token.value = result.getText();
                self.stop();
                self.$refs.form.requestSubmit();
              }
            });
          } catch (e) {
            var d = this.cfg, name = e && e.name;
            this.error = name === "NotAllowedError" || name === "SecurityError" ? d.errDenied : name === "NotFoundError" || name === "OverconstrainedError" ? d.errNone : d.cameraError;
            this.openManual();
          }
        },
        openManual: function () {
          var box = this.$refs.manual || document.querySelector("[data-testid=manual-box]");
          if (box) { box.open = true; var f = box.querySelector("input"); if (f) f.focus({ preventScroll: true }); }
        },
        stop: function () {
          if (this.controls) { this.controls.stop(); this.controls = null; }
          this.open = false;
        },
        get closed() { return !this.open; },
        get hasError() { return this.error !== ""; },
      };
    });
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  }
})();

/* After the console card resets: clear the search box and focus it again. */
document.addEventListener("htmx:afterSwap", function (e) {
  if (e.target && e.target.querySelector && e.target.querySelector("[data-reset]")) {
    var q = document.getElementById("q");
    var results = document.getElementById("results");
    if (q) { q.value = ""; q.focus(); }
    if (results) { results.innerHTML = ""; }
  }
});
/* Theme cards save at once (HTMX POST); the server answers with an HX-Trigger so the whole page swaps theme in place. */
function applyTheme(theme, color) {
  document.documentElement.setAttribute("data-theme", theme);
  var meta = document.querySelector("meta[name=theme-color]");
  if (meta && color) { meta.setAttribute("content", color); }
  var radio = document.querySelector("[data-theme-option][value=" + theme + "]");
  if (radio) { radio.checked = true; }
}
function showToast(text, undo) {
  var old = document.querySelector("[data-testid=toast]");
  if (old) { old.remove(); }
  var el = document.createElement("div");
  el.className = "toast";
  el.setAttribute("role", "status");
  el.setAttribute("data-testid", "toast");
  var span = document.createElement("span");
  span.textContent = text;
  el.appendChild(span);
  if (undo) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "toast-action";
    b.setAttribute("data-testid", "toast-undo");
    b.textContent = undo.label;
    b.addEventListener("click", undo.run);
    el.appendChild(b);
  }
  document.body.appendChild(el);
  window.setTimeout(function () { if (el.parentNode) { el.remove(); } }, 10000);
}
document.addEventListener("themeSaved", function (e) {
  var d = e.detail || {};
  applyTheme(d.theme, d.color);
  var form = document.querySelector("[data-theme-option]");
  form = form && form.closest("form");
  showToast(d.message + " ·", {
    label: "Undo",
    run: function () {
      var body = new URLSearchParams({ theme: d.previous });
      var token = document.body.getAttribute("hx-headers");
      var csrf = token ? JSON.parse(token)["X-CSRFToken"] : "";
      fetch(form.getAttribute("hx-post"), { method: "POST", body: body, headers: { "X-CSRFToken": csrf } }).then(function (r) {
        if (r.ok) {
          applyTheme(d.previous, null);
          var m = document.querySelector("meta[name=theme-color]");
          var c = window.getComputedStyle(document.documentElement).getPropertyValue("--primary").trim();
          if (m && c) { m.setAttribute("content", c); }
          showToast(d.previousLabel + " restored.");
        } else { showToast("Could not undo."); }
      });
    },
  });
});
/* Unsaved-changes warning for the profile form only (not the theme cards, which save themselves). */
(function () {
  var form = document.querySelector("form[data-dirty-guard]");
  if (!form) { return; }
  var dirty = false;
  form.addEventListener("input", function () { dirty = true; });
  form.addEventListener("change", function () { dirty = true; });
  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
})();
document.addEventListener("click", function (e) {
  if (e.target.closest && e.target.closest("[data-back]")) { window.history.back(); return; }
  var t = e.target.closest && e.target.closest("[data-print]");
  if (t) { window.print(); }
});

/* ---- D03.8 Show QR button: icon-only while scrolling down, label back on scroll up or at rest ---- */
(function () {
  var fab = document.querySelector("[data-fab]");
  if (!fab) { return; }
  var last = window.scrollY, rest = null;
  window.addEventListener("scroll", function () {
    var y = window.scrollY;
    if (y > last + 6 && y > 40) { fab.classList.add("cust-fab-mini"); }
    else if (y < last - 6 || y <= 40) { fab.classList.remove("cust-fab-mini"); }
    last = y;
    window.clearTimeout(rest);
    rest = window.setTimeout(function () { fab.classList.remove("cust-fab-mini"); }, 1200);
  }, { passive: true });
})();

/* ---- D03.7 station shell: live clock, auto-refresh (skipped while something is ticked), delivered group from the bar ---- */
(function () {
  function clock() { document.querySelectorAll("[data-clock]").forEach(function (el) { el.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }); }
  clock(); window.setInterval(clock, 30000);
  var ar = document.querySelector("[data-autorefresh]");
  if (ar) {
    window.setInterval(function () { if (!document.querySelector("#packing input:checked")) { window.location.reload(); } }, parseInt(ar.getAttribute("data-autorefresh"), 10) * 1000);
  }
  function openDelivered() { var d = document.getElementById("delivered-group"); if (d && window.location.hash === "#delivered-group") { d.open = true; d.scrollIntoView(); } }
  window.addEventListener("hashchange", openDelivered); openDelivered();
})();

/* ---- D03.7 counter keyboard shortcuts: / focuses search, Enter redeems (or opens the first result), Esc clears ---- */
document.addEventListener("keydown", function (e) {
  var q = document.getElementById("q");
  if (!q || !document.querySelector("[data-testid=counter-panes]")) { return; }
  var typing = e.target.matches && e.target.matches("input, textarea, select, [contenteditable]");
  if (e.key === "/" && !typing) { e.preventDefault(); q.focus(); q.select(); return; }
  if (e.key === "Escape") {
    q.value = "";
    var res = document.getElementById("results"); if (res) { res.innerHTML = ""; }
    var card = document.querySelector("[data-testid=customer-card]");
    if (card && window.htmx) { window.htmx.ajax("GET", document.querySelector("[data-card-reset]") ? document.querySelector("[data-card-reset]").getAttribute("data-card-reset") : "", "#console-card"); }
    q.focus();
    return;
  }
  if (e.key === "Enter" && (e.target === q || e.target === document.body)) {
    var redeem = document.querySelector("[data-testid=redeem]");
    var first = document.querySelector("[data-testid=result]");
    if (redeem) { e.preventDefault(); redeem.click(); } else if (first) { e.preventDefault(); first.click(); }
  }
});

/* ---- D03.6 sign-in screens: PIN cells, show/hide, double-submit guard, remembered choice ---------------------- */
(function () {
  document.querySelectorAll("[data-pin]").forEach(function (box) {
    var input = box.querySelector("input");
    var cells = box.querySelector("[data-pin-cells]");
    var len = parseInt(box.getAttribute("data-len"), 10) || 6;
    var shown = false;
    box.classList.add("pin-js");
    for (var i = 0; i < len; i++) { var c = document.createElement("span"); c.className = "pin-cell"; cells.appendChild(c); }
    function paint() {
      var v = input.value;
      var focused = document.activeElement === input;
      for (var k = 0; k < cells.children.length; k++) {
        var cell = cells.children[k];
        cell.textContent = k < v.length ? (shown ? v.charAt(k) : "•") : "";
        cell.setAttribute("data-on", focused && k === Math.min(v.length, len - 1) ? "1" : "0");
      }
    }
    input.addEventListener("input", function () { input.value = input.value.replace(/\D/g, "").slice(0, len); paint(); });
    input.addEventListener("focus", paint);
    input.addEventListener("blur", paint);
    box.addEventListener("pin-visibility", function (e) { shown = e.detail; paint(); });
    paint();
  });
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-reveal]");
    if (!btn) { return; }
    var input = document.getElementById(btn.getAttribute("data-reveal"));
    var show = input.type === "password" && !input.closest("[data-pin]");
    var pinBox = input.closest("[data-pin]");
    if (pinBox) { show = btn.getAttribute("aria-pressed") !== "true"; pinBox.dispatchEvent(new CustomEvent("pin-visibility", { detail: show })); }
    else { input.type = show ? "text" : "password"; }
    btn.setAttribute("aria-pressed", show ? "true" : "false");
    btn.textContent = show ? btn.getAttribute("data-hide") || "Hide" : btn.getAttribute("data-show") || "Show";
  });
  document.querySelectorAll("form[data-submit-once]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.getAttribute("data-busy") === "1") { e.preventDefault(); return; }
      form.setAttribute("data-busy", "1");
      var b = form.querySelector("button[type=submit]");
      if (b) { b.classList.add("opacity-80"); b.setAttribute("aria-disabled", "true"); var sp = b.querySelector(".btn-spinner"); if (sp) { sp.classList.remove("hidden"); } }
    });
  });
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-submit-once]").forEach(function (f) {
      f.removeAttribute("data-busy");
      var b = f.querySelector("button[type=submit]");
      if (b) { b.classList.remove("opacity-80"); b.removeAttribute("aria-disabled"); var sp = b.querySelector(".btn-spinner"); if (sp) { sp.classList.add("hidden"); } }
    });
  });
  var choices = document.querySelector("[data-choices]");
  if (choices) {
    var last = "";
    try { last = window.localStorage.getItem("mealtally.choice") || ""; } catch (err) { last = ""; }
    choices.querySelectorAll("[data-choice]").forEach(function (a) {
      if (a.getAttribute("data-choice") === last) {
        a.classList.add("border-primary", "bg-soft");
        var chip = a.querySelector("[data-last-chip]"); if (chip) { chip.classList.remove("hidden"); }
      }
      a.addEventListener("click", function () {
        try { window.localStorage.setItem("mealtally.choice", a.getAttribute("data-choice")); } catch (err) { /* private mode */ }
      });
    });
  }
})();

// language picker (and any other select marked data-autosubmit) submits its form on change; a noscript button covers no-JS
document.addEventListener("change", function (e) {
  var el = e.target;
  if (el && el.matches && el.matches("[data-autosubmit]") && el.form) { el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); }
});
