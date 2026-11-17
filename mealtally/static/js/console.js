/* SPDX-License-Identifier: AGPL-3.0-only */
/* Console shell glue: sidebar collapse (desktop) / drawer (mobile), alert dismissal. No inline script (CSP). */
(function () {
  "use strict";
  var KEY = "mealtally.sidebar";
  function wide() { return window.matchMedia("(min-width: 1024px)").matches; }
  function store(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* private mode etc: the UI works without it */ } }
  function load() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function setOpen(open) {
    document.body.classList.toggle("sb-open", open);
    var scrim = document.querySelector("[data-sb-scrim]"), btn = document.querySelector("[data-sb-toggle]");
    if (scrim) scrim.classList.toggle("hidden", !open);
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : (document.body.classList.contains("sb-collapsed") ? "false" : "true"));
  }
  document.addEventListener("DOMContentLoaded", function () {
    if (load() === "collapsed" && wide()) document.body.classList.add("sb-collapsed");
    var btn = document.querySelector("[data-sb-toggle]");
    if (btn) btn.setAttribute("aria-expanded", wide() && !document.body.classList.contains("sb-collapsed") ? "true" : "false");
  });
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-sb-toggle]");
    if (t) {
      if (wide()) {
        var c = document.body.classList.toggle("sb-collapsed");
        store(c ? "collapsed" : "expanded");
        t.setAttribute("aria-expanded", c ? "false" : "true");
      } else {
        setOpen(!document.body.classList.contains("sb-open"));
      }
      return;
    }
    if (e.target.closest && (e.target.closest("[data-sb-scrim]") || e.target.closest("[data-sb-link]")) && !wide()) setOpen(false);
    var d = e.target.closest && e.target.closest("[data-dismiss]");
    if (d) {  /* dismiss one alert; keep the bell/strip counters honest and show the calm state when none are left */
      var row = d.closest("[data-alert]");
      if (row) row.remove();
      var left = document.querySelectorAll("[data-alert]").length;
      document.querySelectorAll("[data-alert-count]").forEach(function (el) { el.textContent = left; el.classList.toggle("hidden", left === 0); });
      var empty = document.querySelector("[data-alerts-empty]");
      if (empty) empty.classList.toggle("hidden", left > 0);
    }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && document.body.classList.contains("sb-open")) setOpen(false); });
})();
