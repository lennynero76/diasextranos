// Días Extraños — interacción ligera (sin dependencias)
(function () {
  "use strict";

  // --- Menú móvil ---
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.querySelector(".site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") nav.classList.remove("open");
    });
  }

  // --- Búsqueda y filtro en la home ---
  var search = document.getElementById("search");
  var cardsWrap = document.getElementById("cards");
  if (!cardsWrap) return;

  var cards = Array.prototype.slice.call(cardsWrap.querySelectorAll(".card"));
  var filters = Array.prototype.slice.call(document.querySelectorAll(".filter"));
  var noResults = document.getElementById("no-results");
  var count = document.getElementById("result-count");
  var total = cards.length;
  var activeCat = "";
  var query = "";

  function norm(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function apply() {
    var q = norm(query.trim());
    var visible = 0;
    cards.forEach(function (card) {
      var hayCat = !activeCat || (" " + card.getAttribute("data-cats") + " ").indexOf(" " + activeCat + " ") !== -1;
      var hayText = !q || norm(card.getAttribute("data-search")).indexOf(q) !== -1;
      var show = hayCat && hayText;
      card.hidden = !show;
      if (show) visible++;
    });
    if (noResults) noResults.hidden = visible !== 0;
    if (count) {
      if (!q && !activeCat) count.textContent = "";
      else count.textContent = visible + (visible === 1 ? " entrada" : " entradas") + " de " + total;
    }
  }

  if (search) {
    search.addEventListener("input", function () { query = search.value; apply(); });
  }
  filters.forEach(function (btn) {
    btn.addEventListener("click", function () {
      filters.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      activeCat = btn.getAttribute("data-cat") || "";
      apply();
    });
  });
})();
