/* Order page (D03.7 b): category and diet filters, date chips, sticky cart bar and checkout sheet. Demo only: nothing is sent. */
(function () {
  "use strict";
  var root = document.querySelector("[data-order]");
  if (!root) { return; }
  var $ = function (s, r) { return (r || root).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || root).querySelectorAll(s)); };
  var min = parseInt(root.dataset.min, 10), fee = parseInt(root.dataset.fee, 10), free = parseInt(root.dataset.free, 10);
  function fmt(p) {
    var r = Math.floor(Math.abs(p) / 100), ps = Math.abs(p) % 100, s = String(r);
    if (s.length > 3) { var h = s.slice(0, -3), out = []; while (h.length > 2) { out.unshift(h.slice(-2)); h = h.slice(0, -2); } if (h) { out.unshift(h); } s = out.join(",") + "," + s.slice(-3); }
    return "₹" + s + (ps ? "." + (ps < 10 ? "0" : "") + ps : "");
  }
  var cat = "", diet = "";
  function filter() {
    var shown = 0;
    $$("[data-item]").forEach(function (li) {
      var ok = (!cat || li.dataset.cat === cat) && (!diet || li.dataset.diet === diet);
      li.classList.toggle("hidden", !ok);
      if (ok) { shown++; }
    });
    $("[data-empty]").classList.toggle("hidden", shown > 0);
  }
  function press(group, btn) { $$(group).forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); }); }
  function lines() {
    return $$("[data-item]").map(function (li) {
      var q = parseInt(($("[data-val]", li) || { textContent: "0" }).textContent, 10) || 0;
      return { name: li.dataset.name, price: parseInt(li.dataset.price, 10), qty: q };
    }).filter(function (l) { return l.qty > 0; });
  }
  function totals() {
    var ls = lines(), sub = ls.reduce(function (a, l) { return a + l.price * l.qty; }, 0), n = ls.reduce(function (a, l) { return a + l.qty; }, 0);
    var pickup = ($("[data-how]:checked") || {}).value === "pickup";
    var f = pickup || sub === 0 || sub >= free ? 0 : fee;
    return { ls: ls, sub: sub, n: n, fee: f, total: sub + f, pickup: pickup };
  }
  function render() {
    var t = totals();
    $("[data-cart-bar]").classList.toggle("hidden", t.n === 0);
    $("[data-bar-count]").textContent = t.n + " " + (t.n === 1 ? root.dataset.one : root.dataset.unit);
    $("[data-bar-total]").textContent = fmt(t.total);
    var ul = $("[data-lines]");
    ul.textContent = "";
    t.ls.forEach(function (l) {
      var li = document.createElement("li");
      li.className = "flex items-center justify-between gap-3 py-2";
      var a = document.createElement("span"); a.textContent = l.qty + " × " + l.name;
      var b = document.createElement("span"); b.className = "font-semibold"; b.textContent = fmt(l.price * l.qty);
      li.appendChild(a); li.appendChild(b); ul.appendChild(li);
    });
    $("[data-sub]").textContent = fmt(t.sub); $("[data-fee]").textContent = t.fee ? fmt(t.fee) : "Free"; $("[data-total]").textContent = fmt(t.total);
    var note = $("[data-free-note]");
    var showFree = !t.pickup && t.sub > 0 && t.sub < free;
    note.classList.toggle("hidden", !showFree);
    if (showFree) { note.textContent = "Add " + fmt(free - t.sub) + " for free delivery"; }
    var short = t.sub > 0 && t.sub < min;
    $("[data-min-note]").classList.toggle("hidden", !short);
    var btn = $("[data-place-order]"); btn.disabled = short || t.n === 0; btn.setAttribute("aria-disabled", btn.disabled ? "true" : "false");
  }
  function open(v) { $("[data-cart-sheet]").classList.toggle("hidden", !v); document.body.classList.toggle("overflow-hidden", v); if (v) { render(); } }
  root.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add]");
    if (add) {
      var li = add.closest("[data-item]"), stp = $("[data-stepper]", li);
      $("[data-val]", li).textContent = "1"; add.classList.add("hidden"); stp.classList.remove("hidden"); stp.classList.add("flex");
      render(); return;
    }
    var c = e.target.closest("[data-cat]"); if (c && c.classList.contains("ord-cat")) { cat = c.dataset.cat; press(".ord-cat", c); filter(); return; }
    var d = e.target.closest(".ord-diet"); if (d) { diet = d.dataset.diet; press(".ord-diet", d); filter(); return; }
    var day = e.target.closest("[data-day-chip]"); if (day) { press("[data-day-chip]", day); $("[data-sheet-day]").textContent = "· " + day.dataset.dayChip; return; }
    if (e.target.closest("[data-open-cart]")) { open(true); return; }
    if (e.target.closest("[data-close-cart]")) { open(false); return; }
    if (e.target.closest("[data-place-order]")) {
      $$("[data-val]").forEach(function (v) { v.textContent = "0"; });
      $$("[data-item]").forEach(function (li) { var st = $("[data-stepper]", li); if (st) { st.classList.add("hidden"); st.classList.remove("flex"); $("[data-add]", li).classList.remove("hidden"); } });
      open(false); render();
    }
  });
  root.addEventListener("change", function (e) { if (e.target.matches("[data-how]")) { render(); } });
  root.addEventListener("pv:change", function (e) {
    var li = e.target.closest("[data-item]");
    if (li && ($("[data-val]", li) || { textContent: "1" }).textContent === "0") {
      var stp = $("[data-stepper]", li); stp.classList.add("hidden"); stp.classList.remove("flex"); $("[data-add]", li).classList.remove("hidden");
    }
    render();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { open(false); } });
  var first = $("[data-day-chip]"); if (first) { $("[data-sheet-day]").textContent = "· " + first.dataset.dayChip; }
  render();
})();

/* Wallet top-up: amount chips swap the real UPI QR and the "Open UPI app" link. */
(function () {
  "use strict";
  var box = document.querySelector("[data-topup]");
  if (!box) { return; }
  var img = document.getElementById("upi-qr"), open = document.getElementById("upi-open"), amt = document.getElementById("amt");
  box.addEventListener("click", function (e) {
    var b = e.target.closest(".ord-amt");
    if (!b) { return; }
    box.querySelectorAll(".ord-amt").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
    var r = b.dataset.amt;
    img.setAttribute("src", img.getAttribute("data-qr-" + r));
    if (open) { open.setAttribute("href", img.getAttribute("data-link-" + r)); }
    if (r !== "0") { amt.value = r; } else { amt.value = ""; amt.focus(); }
  });
})();
