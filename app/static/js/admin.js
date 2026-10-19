/* Admin behaviour: sidebar toggle, chart rendering from embedded JSON. */
(function () {
  "use strict";

  function initSidebar() {
    var toggle = document.querySelector("[data-nav-toggle]");
    var sidebar = document.querySelector(".admin-sidebar");
    if (!toggle || !sidebar) return;
    toggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var PALETTE = ["#FF6B35", "#37D6C0", "#EAA7FF", "#B8CC3D", "#211B2B", "#175CD3", "#A16207", "#1F8A55"];

  function renderCharts() {
    if (typeof Chart === "undefined") return;

    var overTime = readJson("chart-over-time");
    var byEvent = readJson("chart-by-event");
    var byCategory = readJson("chart-by-category");
    var utilisation = readJson("chart-utilisation");

    if (overTime && overTime.labels) {
      var el = document.getElementById("chartOverTime");
      if (el) {
        new Chart(el, {
          type: "line",
          data: {
            labels: overTime.labels,
            datasets: [{
              label: "Registrations",
              data: overTime.values,
              borderColor: "#FF6B35",
              backgroundColor: "rgba(255,107,53,0.12)",
              fill: true,
              tension: 0.3,
            }],
          },
          options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
          },
        });
      }
    }

    if (byEvent && byEvent.labels) {
      var el2 = document.getElementById("chartByEvent");
      if (el2) {
        new Chart(el2, {
          type: "bar",
          data: {
            labels: byEvent.labels,
            datasets: [{ label: "Registrations", data: byEvent.values, backgroundColor: "#37D6C0" }],
          },
          options: {
            indexAxis: "y",
            responsive: true,
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
          },
        });
      }
    }

    if (byCategory && byCategory.labels) {
      var el3 = document.getElementById("chartByCategory");
      if (el3) {
        new Chart(el3, {
          type: "doughnut",
          data: {
            labels: byCategory.labels,
            datasets: [{ data: byCategory.values, backgroundColor: PALETTE }],
          },
          options: { responsive: true, plugins: { legend: { position: "bottom" } } },
        });
      }
    }

    if (utilisation && utilisation.labels) {
      var el4 = document.getElementById("chartUtilisation");
      if (el4) {
        new Chart(el4, {
          type: "bar",
          data: {
            labels: utilisation.labels,
            datasets: [
              { label: "Used", data: utilisation.used, backgroundColor: "#FF6B35" },
              { label: "Remaining", data: utilisation.capacity.map(function (c, i) { return c - utilisation.used[i]; }), backgroundColor: "#E4DFE8" },
            ],
          },
          options: {
            responsive: true,
            plugins: { legend: { position: "bottom" } },
            scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } },
          },
        });
      }
    }
  }

  function initCancelConfirm() {
    document.querySelectorAll("[data-cancel-form]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        if (!window.confirm(form.getAttribute("data-cancel-message") || "Cancel this record?")) {
          e.preventDefault();
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initSidebar();
    renderCharts();
    initCancelConfirm();
  });
})();
