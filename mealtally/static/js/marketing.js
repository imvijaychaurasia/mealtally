/* Public landing page (D03.6 B): menus, "Live only" filter, remembered tenant codes, gentle reveal on scroll, double-submit guard. */
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* only one header menu open at a time; close on Escape or outside click */
  var menus = document.querySelectorAll("details[data-menu]");
  function closeOthers(except) { menus.forEach(function (d) { if (d !== except) { d.removeAttribute("open"); } }); }
  menus.forEach(function (d) { d.addEventListener("toggle", function () { if (d.open) { closeOthers(d); } }); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { closeOthers(null); } });
  document.addEventListener("click", function (e) {
    if (!e.target.closest("details[data-menu]")) { closeOthers(null); }
    if (e.target.closest("a[href^='#']")) { closeOthers(null); }
  });

  /* product tour tabs: click, arrow keys, Home/End */
  document.querySelectorAll("[data-tabs]").forEach(function (root) {
    var tabs = Array.prototype.slice.call(root.querySelectorAll("[role=tab]"));
    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.setAttribute("tabindex", on ? "0" : "-1");
        document.getElementById(t.getAttribute("aria-controls")).classList.toggle("hidden", !on);
      });
      if (focus) { tab.focus(); }
    }
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(t, false); });
      t.addEventListener("keydown", function (e) {
        var j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (j === undefined) { return; }
        e.preventDefault();
        select(tabs[(j + tabs.length) % tabs.length], true);
      });
    });
  });

  /* "Live only" filter */
  var box = document.querySelector("[data-live-only]");
  if (box) {
    box.addEventListener("change", function () {
      document.querySelectorAll("[data-features] > li").forEach(function (li) {
        li.classList.toggle("hidden", box.checked && li.getAttribute("data-status") !== "live");
      });
    });
  }

  /* remembered restaurant codes (localStorage, always inside try/catch) */
  var KEY = "mealtally.recent";
  function recent() { try { return JSON.parse(window.localStorage.getItem(KEY) || "[]"); } catch (err) { return []; } }
  document.querySelectorAll("[data-tenant-finder]").forEach(function (form) {
    var wrap = form.querySelector("[data-recent]");
    var input = form.querySelector("input[name=code]");
    var list = recent();
    if (wrap && list.length) {
      wrap.classList.remove("hidden"); wrap.classList.add("flex");
      list.slice(0, 4).forEach(function (code) {
        var b = document.createElement("button");
        b.type = "button"; b.className = "mk-chip"; b.textContent = code;
        b.addEventListener("click", function () { input.value = code; form.submit(); });
        wrap.appendChild(b);
      });
    }
    form.addEventListener("submit", function () {
      var code = (input.value || "").trim().toLowerCase();
      if (!code) { return; }
      var next = [code].concat(recent().filter(function (c) { return c !== code; })).slice(0, 4);
      try { window.localStorage.setItem(KEY, JSON.stringify(next)); } catch (err) { /* private mode */ }
    });
  });

  /* double-submit guard + spinner */
  document.querySelectorAll("form[data-submit-once]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.getAttribute("data-busy") === "1") { e.preventDefault(); return; }
      form.setAttribute("data-busy", "1");
      var sp = form.querySelector(".btn-spinner"); if (sp) { sp.classList.remove("hidden"); }
    });
  });
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-submit-once]").forEach(function (f) {
      f.removeAttribute("data-busy"); var sp = f.querySelector(".btn-spinner"); if (sp) { sp.classList.add("hidden"); }
    });
  });

  /* fade/slide in on scroll: 200 ms, skipped under prefers-reduced-motion */
  var items = document.querySelectorAll("[data-reveal]");
  if (!reduce && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.remove("mk-pre"); io.unobserve(en.target); } });
    }, { rootMargin: "0px 0px -8% 0px" });
    items.forEach(function (el) {
      var r = el.getBoundingClientRect();
      if (r.top > window.innerHeight) { el.classList.add("mk-pre"); io.observe(el); }
    });
  }
})();
