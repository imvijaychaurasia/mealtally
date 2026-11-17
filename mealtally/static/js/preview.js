/* Preview-mode interactions (D03). Vanilla + event delegation; no inline script/style (CSP), no network, no writes. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var DEFAULT_MSG = "Preview — saved in demo mode only";

  function toast(msg) {
    var host = $("#pv-toast");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "pointer-events-auto rounded-xl bg-ink px-4 py-3 text-sm font-medium text-on-primary shadow-lg";
    el.textContent = msg || DEFAULT_MSG;
    host.appendChild(el);
    setTimeout(function () { el.remove(); }, 3200);
  }
  function beep() {
    try {
      var C = window.AudioContext || window.webkitAudioContext, c = new C(), o = c.createOscillator(), g = c.createGain();
      o.frequency.value = 784; g.gain.value = 0.15; o.connect(g); g.connect(c.destination); o.start(); o.stop(c.currentTime + 0.25);
    } catch (e) { /* best effort */ }
  }
  function inr(paise) {  /* Indian digit grouping, same as the server's |inr */
    var neg = paise < 0, v = Math.abs(Math.round(paise)), rupees = Math.floor(v / 100), p = String(v % 100);
    var s = String(rupees), last3 = s.slice(-3), rest = s.slice(0, -3);
    if (rest) last3 = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3;
    return (neg ? "-" : "") + "\u20b9" + last3 + "." + (p.length < 2 ? "0" + p : p);
  }
  function cls(el, add, remove) {
    (remove || "").split(" ").forEach(function (c) { if (c) el.classList.remove(c); });
    (add || "").split(" ").forEach(function (c) { if (c) el.classList.add(c); });
  }

  /* progressive visuals that would otherwise need inline styles */
  function paint() {
    $$("[data-w]").forEach(function (el) { el.style.width = el.dataset.w + "%"; });
    $$("[data-bg]").forEach(function (el) { el.style.backgroundColor = el.dataset.bg; });
    $$("[data-gridcols]").forEach(function (el) { el.style.gridTemplateColumns = "repeat(" + el.dataset.gridcols + ", minmax(0, 1fr))"; });
  }

  document.addEventListener("click", function (e) {
    var vd = e.target.closest && e.target.closest("[data-validate-days]");
    if (vd) {  /* every selected delivery day must have a dish */
      var missing = [];
      $$("[data-day]").forEach(function (d) { var on = $("[data-daybox]", d).checked, sel = $("select", d); if (on && !sel.value) missing.push($("label", d).textContent.trim()); });
      var err = $(vd.dataset.validateDays);
      if (missing.length) { err.textContent = missing.join(", ") + " " + (missing.length > 1 ? "have" : "has") + " no dish yet \u2014 add at least one dish to every delivery day before saving."; err.classList.remove("hidden"); }
      else { err.classList.add("hidden"); toast(DEFAULT_MSG); }
      return;
    }
    var t = e.target.closest && e.target.closest("[data-pv]");
    if (t) {
      if (t.tagName === "A" || t.type === "submit") e.preventDefault();
      var row = t.closest("[data-row]");
      var chipText = t.dataset.chip;
      if (chipText && row) {
        var chip = $("[data-chip]", row);
        if (chip) { chip.textContent = chipText; cls(chip, t.dataset.chipClass || "chip-active", "chip-slate chip-amber chip-red chip-green chip-active chip-soon chip-void chip-expired"); }
        $$("[data-pv]", row).forEach(function (b) { if (b !== t && b.dataset.chip !== undefined) b.disabled = true; });
        t.disabled = true;
      }
      if (t.dataset.dec) { var kd = $(t.dataset.dec); if (kd) kd.textContent = Math.max(0, parseInt(kd.textContent, 10) - 1); }
      if (t.dataset.addMoney) {  /* "#selector|paise": keep a money KPI in step with the action */
        var am = t.dataset.addMoney.split("|"), km = $(am[0]);
        if (km) { var np = parseInt(km.dataset.amt, 10) + parseInt(am[1], 10); km.dataset.amt = np; km.textContent = inr(np); }
      }
      var hide = t.dataset.hide;
      if (hide) { var h = $(hide); if (h) h.classList.add("hidden"); }
      var show = t.dataset.show;
      if (show) { var s = $(show); if (s) s.classList.remove("hidden"); }
      var setText = t.dataset.setText;  // "selector|text"
      if (setText) { var parts = setText.split("|"), el = $(parts[0]); if (el) el.textContent = parts[1]; }
      var step = t.dataset.advance;  // order progress: advance the stepper in the same card
      if (step) { advance($(step)); }
      if (t.dataset.chime !== undefined) beep();
      toast(t.dataset.pv || DEFAULT_MSG);
      return;
    }
    var wz = e.target.closest && e.target.closest("[data-wiz]");
    if (wz) {  /* sign-up wizard */
      var root = wz.closest("[data-wizard]"), panes = $$("[data-wiz-pane]", root), bars = $$("[data-wiz-bar]", root);
      var cur = panes.findIndex(function (p) { return !p.classList.contains("hidden"); });
      var nxt = Math.max(0, Math.min(panes.length - 1, cur + (wz.dataset.wiz === "next" ? 1 : -1)));
      panes.forEach(function (p, i) { p.classList.toggle("hidden", i !== nxt); });
      bars.forEach(function (b, i) { cls(b, i <= nxt ? "bg-primary" : "bg-track", i <= nxt ? "bg-track" : "bg-primary"); });
      $("[data-wiz=next]", root).textContent = nxt === panes.length - 1 ? "Finish (demo)" : "Next";
      if (wz.dataset.wiz === "next" && cur === panes.length - 1) toast("Demo mode — no account created");
      return;
    }
    var tab = e.target.closest && e.target.closest("[data-tab]");
    if (tab) {
      var group = tab.closest("[data-tabs]");
      var name = tab.dataset.tab;
      $$("[data-tab]", group).forEach(function (b) { var on = b === tab; b.setAttribute("aria-selected", on ? "true" : "false"); cls(b, on ? "border-primary text-primary" : "border-transparent text-ink-soft", on ? "border-transparent text-ink-soft" : "border-primary text-primary"); });
      $$("[data-pane]", group).forEach(function (p) { p.classList.toggle("hidden", p.dataset.pane !== name); });
      return;
    }
    var st = e.target.closest && e.target.closest("[data-step]");
    if (st) {
      var box = st.closest("[data-stepper]"), val = $("[data-val]", box);
      var min = parseInt(box.dataset.min || "0", 10), max = parseInt(box.dataset.max || "99", 10);
      var n = Math.max(min, Math.min(max, parseInt(val.textContent, 10) + parseInt(st.dataset.step, 10)));
      val.textContent = n; var hid = $("input[type=hidden]", box); if (hid) hid.value = n;
      box.dispatchEvent(new CustomEvent("pv:change", { bubbles: true }));
      return;
    }
    var mv = e.target.closest && e.target.closest("[data-move]");
    if (mv) {
      var item = mv.closest("[data-sort-item]"), list = item.parentNode;
      if (mv.dataset.move === "up" && item.previousElementSibling) list.insertBefore(item, item.previousElementSibling);
      if (mv.dataset.move === "down" && item.nextElementSibling) list.insertBefore(item.nextElementSibling, item);
      renumber(list); toast("Stop order changed — " + DEFAULT_MSG.toLowerCase());
      return;
    }
    var cp = e.target.closest && e.target.closest("[data-copy]");
    if (cp) { try { navigator.clipboard.writeText(cp.dataset.copy); } catch (err) { /* ignore */ } toast("Link copied"); return; }
    var tg = e.target.closest && e.target.closest("[data-toggle]");
    if (tg) { var tgt = $(tg.dataset.toggle); if (tgt) tgt.classList.toggle("hidden"); return; }
    var lang = e.target.closest && e.target.closest("[data-closeable]");
    if (lang) { lang.closest("[data-closable-root]").classList.add("hidden"); }
  });

  /* order progress stepper */
  function advance(card) {
    if (!card) return;
    var steps = $$("[data-stepdot]", card), cur = steps.findIndex(function (s) { return s.dataset.state === "now"; });
    if (cur < 0 || cur >= steps.length - 1) return;
    steps[cur].dataset.state = "done"; cls(steps[cur], "bg-primary text-on-primary", "bg-card text-primary ring-2 ring-primary");
    steps[cur + 1].dataset.state = "now"; cls(steps[cur + 1], "bg-card text-primary ring-2 ring-primary", "bg-track text-ink-soft");
    var btn = $("[data-advance]", card), labels = (card.dataset.next || "").split("|");
    if (btn) { var l = labels[cur + 1]; if (l) btn.textContent = l; else btn.disabled = true; }
    var chip = $("[data-order-chip]");
    if (chip) chip.textContent = steps[cur + 1].dataset.label;
  }

  function renumber(list) { $$("[data-seq]", list).forEach(function (el, i) { el.textContent = i + 1; }); }

  /* drag to reorder (HTML5 DnD) */
  var dragging = null;
  document.addEventListener("dragstart", function (e) { var i = e.target.closest && e.target.closest("[data-sort-item]"); if (i) { dragging = i; i.classList.add("opacity-50"); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", "x"); } catch (err) { /* ignore */ } } });
  document.addEventListener("dragover", function (e) {
    var over = e.target.closest && e.target.closest("[data-sort-item]");
    if (!dragging || !over || over === dragging || over.parentNode !== dragging.parentNode) return;
    e.preventDefault();
    var r = over.getBoundingClientRect();
    over.parentNode.insertBefore(dragging, e.clientY < r.top + r.height / 2 ? over : over.nextSibling);
  });
  document.addEventListener("dragend", function () { if (dragging) { dragging.classList.remove("opacity-50"); renumber(dragging.parentNode); toast("Stop order changed — " + DEFAULT_MSG.toLowerCase()); dragging = null; } });

  /* live text filter + status chips */
  document.addEventListener("input", function (e) {
    var f = e.target.closest && e.target.closest("[data-filter]");
    if (f) {
      var q = f.value.toLowerCase();
      $$("[data-row]", $(f.dataset.filter)).forEach(function (r) { r.classList.toggle("hidden", (r.dataset.text || r.textContent).toLowerCase().indexOf(q) < 0); });
    }
    var rate = e.target.closest && e.target.closest("[data-rate]");
    if (rate) { /* daily rate auto-fills weekly (x7) and monthly (x30) unless edited */
      var v = parseFloat(rate.value);
      $$("[data-rate-to]").forEach(function (o) { if (o.dataset.touched !== "1") o.value = isNaN(v) ? "" : String(Math.round(v * parseFloat(o.dataset.mult))); });
    }
    var touched = e.target.closest && e.target.closest("[data-rate-to]");
    if (touched && e.isTrusted) touched.dataset.touched = "1";
  });
  document.addEventListener("change", function (e) {
    var f = e.target.closest && e.target.closest("[data-filter-select]");
    if (f) {
      var v = f.value, scope = $(f.dataset.filterSelect), attr = f.dataset.attr || "status";
      $$("[data-row]", scope).forEach(function (r) { r.classList.toggle("hidden", v !== "" && r.dataset[attr] !== v); });
    }
    var sw = e.target.closest && e.target.closest("[data-switch]");
    if (sw) { $$("[data-case]", $(sw.dataset.switch)).forEach(function (p) { p.classList.toggle("hidden", p.dataset["case"] !== sw.value); }); }
    var ph = e.target.closest && e.target.closest("[data-photo]");
    if (ph && ph.files && ph.files[0]) {
      var reader = new FileReader(), img = $(ph.dataset.photo);
      reader.onload = function () { img.src = reader.result; img.classList.remove("hidden"); toast("Photo attached (stays on this device in the demo)"); };
      reader.readAsDataURL(ph.files[0]);
    }
    var mc = e.target.closest && e.target.closest("[data-check-row]");
    if (mc) { mc.closest("[data-row]").classList.toggle("line-through", mc.checked); mc.closest("[data-row]").classList.toggle("opacity-60", mc.checked); }
    var cl = e.target.closest && e.target.closest("[data-closure]");
    if (cl) {
      var o = cl.selectedOptions[0], out = $(cl.dataset.closure);
      if (out) out.textContent = o.dataset.orders + " orders across " + o.dataset.slots + " slots will be skipped; " + o.dataset.customers + " customers notified.";
    }
  });

  /* tabs: deep-link default pane */
  function initTabs() {
    $$("[data-tabs]").forEach(function (g) {
      var hash = (location.hash || "").slice(1), want = hash && $("[data-tab=" + hash + "]", g);  /* #pack opens the Packing tab */
      var first = want || $("[data-tab][aria-selected=true]", g) || $("[data-tab]", g);
      if (first) first.click();
    });
  }

  /* countdowns to a cutoff; when it passes the block locks and its inputs are disabled */
  function tick() {
    $$("[data-countdown]").forEach(function (el) {
      var until = new Date(el.dataset.countdown).getTime(), ms = until - Date.now();
      var lock = el.dataset.lockScope ? $(el.dataset.lockScope) : null;
      if (ms <= 0) {
        el.textContent = el.dataset.lockedText || "Locked";
        cls(el, "chip-void", "chip-active chip-soon");
        if (lock) $$("input,select,button", lock).forEach(function (i) { if (i.dataset.keep === undefined) i.disabled = true; });
        return;
      }
      var m = Math.floor(ms / 60000), h = Math.floor(m / 60), d = Math.floor(h / 24);
      el.textContent = (el.dataset.prefix || "Closes in ") + (d > 0 ? d + "d " + (h % 24) + "h" : h > 0 ? h + "h " + (m % 60) + "m" : m + "m " + Math.floor((ms % 60000) / 1000) + "s");
      cls(el, ms < 3600000 ? "chip-soon" : "chip-active", "chip-active chip-soon chip-void");
    });
  }

  /* counter order: live balance projection + closed-slot guard */
  function orderCalc() {
    var f = $("[data-order-calc]");
    if (!f) return;
    var sel = $("[name=customer]", f), bal = 0, trust = 0;
    function opt() { var o = $$("option", $("#customer-list")).filter(function (x) { return x.value === sel.value; })[0]; return o; }
    function money(p) { return (p < 0 ? "−" : "") + "₹" + Math.abs(p / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    function calc() {
      var o = opt(); bal = o ? parseInt(o.dataset.balance, 10) : 0; trust = o ? parseInt(o.dataset.trust, 10) : 0;
      var total = 0;
      $$("[data-line]", f).forEach(function (l) { total += parseInt(l.dataset.price, 10) * parseInt($("[data-val]", l).textContent, 10); });
      var fee = $("[name=method]:checked", f) && $("[name=method]:checked", f).value === "DELIVERY" ? parseInt(f.dataset.fee, 10) : 0;
      $("[data-items]", f).textContent = money(total);
      $("[data-feeline]", f).textContent = fee ? money(fee) : "\u20b90.00";
      total += fee;
      $("[data-total]", f).textContent = money(total);
      $("[data-cur]", f).textContent = o ? money(bal) : "—";
      var proj = bal - total; $("[data-proj]", f).textContent = o ? money(proj) : "—";
      var warn = $("[data-overdraw]", f);
      warn.classList.toggle("hidden", !(o && proj < 0));
      var over = $("[data-over-limit]", f); over.classList.toggle("hidden", !(o && proj < -trust));
      var date = $("[name=date]", f).value, slot = $("[name=slot]", f), end = slot.selectedOptions[0].dataset.end;
      var closed = date < f.dataset.today || (date === f.dataset.today && new Date(Date.now() + 19800000 + new Date().getTimezoneOffset() * 60000).toTimeString().slice(0, 5) > end);
      var msg = $("[data-closed]", f); msg.classList.toggle("hidden", !closed);
      msg.textContent = closed ? slot.selectedOptions[0].textContent.split("(")[0].trim() + " orders for " + date + " closed at " + end + " — pick another slot or date." : "";
      $("[data-place]", f).disabled = closed;
    }
    f.addEventListener("input", calc); f.addEventListener("change", calc); f.addEventListener("pv:change", calc);
    calc();
  }

  document.addEventListener("DOMContentLoaded", function () { paint(); initTabs(); tick(); orderCalc(); setInterval(tick, 1000); });
})();
