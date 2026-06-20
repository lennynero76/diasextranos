// Días Extraños — interacción ligera (sin dependencias), tema F2
(function () {
  "use strict";

  // --- Menú principal responsive (botón .menu-toggle del tema F2) ---
  var nav = document.getElementById("site-navigation");
  var toggle = nav && nav.querySelector(".menu-toggle");
  if (nav && toggle) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("toggled");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") nav.classList.remove("toggled");
    });
  }

  // --- Búsqueda en cliente sobre los listados de entradas ---
  var search = document.getElementById("search");
  var entriesWrap = document.getElementById("entries");
  if (!search || !entriesWrap) return;

  var entries = Array.prototype.slice.call(
    entriesWrap.querySelectorAll(".hentry[data-search]"));
  var noResults = document.getElementById("no-results");
  var count = document.getElementById("result-count");
  var total = entries.length;

  function norm(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function apply() {
    var q = norm(search.value.trim());
    var visible = 0;
    entries.forEach(function (el) {
      var show = !q || norm(el.getAttribute("data-search")).indexOf(q) !== -1;
      el.hidden = !show;
      if (show) visible++;
    });
    if (noResults) noResults.hidden = visible !== 0;
    if (count) {
      count.textContent = q
        ? visible + (visible === 1 ? " entrada" : " entradas") + " de " + total
        : "";
    }
  }

  search.addEventListener("input", apply);
})();
