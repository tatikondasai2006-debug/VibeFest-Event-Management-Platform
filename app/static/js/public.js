/* VibeFest public site behaviour: live counts, countdown, team builder. */
(function () {
  "use strict";

  /* ---------- live aggregate counts (30s, pause when hidden) ---------- */
  function initLiveCounts() {
    var strip = document.querySelector("[data-live-summary]");
    if (!strip) return;
    var timer = null;

    function render(data) {
      var regEl = strip.querySelector("[data-live-registrations]");
      var evEl = strip.querySelector("[data-live-events]");
      var teamEl = strip.querySelector("[data-live-teams]");
      if (regEl && typeof data.registrations === "number") regEl.textContent = data.registrations;
      if (evEl && typeof data.events === "number") evEl.textContent = data.events;
      if (teamEl && typeof data.teams === "number") teamEl.textContent = data.teams;
    }

    function tick() {
      if (document.hidden) return;
      fetch("/api/summary", { headers: { Accept: "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(render)
        .catch(function () { /* keep last good values */ });
    }

    function start() { if (!timer) timer = setInterval(tick, 30000); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop(); else { tick(); start(); }
    });
    start();
  }

  /* ---------- event page seat counter ---------- */
  function initEventCounts() {
    var box = document.querySelector("[data-event-counts]");
    if (!box) return;
    var slug = box.getAttribute("data-event-slug");
    var timer = null;

    function render(data) {
      var regEl = box.querySelector("[data-count-registered]");
      var seatEl = box.querySelector("[data-count-seats]");
      var barEl = box.querySelector("[data-count-bar]");
      var statusEl = box.querySelector("[data-count-status]");
      if (regEl) regEl.textContent = data.registered;
      if (seatEl) seatEl.textContent = data.seats_left;
      if (barEl && data.capacity > 0) {
        barEl.style.width = Math.min(100, (data.registered / data.capacity) * 100) + "%";
      }
      if (statusEl) {
        statusEl.textContent = data.registration_open ? "Open" : "Closed";
        statusEl.className = "badge " + (data.registration_open ? "badge-open" : "badge-closed");
      }
    }

    function tick() {
      if (document.hidden) return;
      fetch("/api/events/" + encodeURIComponent(slug) + "/counts", { headers: { Accept: "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(render)
        .catch(function () {});
    }

    function start() { if (!timer) timer = setInterval(tick, 30000); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop(); else { tick(); start(); }
    });
    start();
  }

  /* ---------- festival countdown (only with a real configured date) ---------- */
  function initCountdown() {
    var el = document.querySelector("[data-countdown]");
    if (!el) return;
    var targetStr = el.getAttribute("data-countdown");
    if (!targetStr) return;
    var target = new Date(targetStr).getTime();
    if (isNaN(target)) return;

    var spans = {
      days: el.querySelector("[data-cd-days]"),
      hours: el.querySelector("[data-cd-hours]"),
      minutes: el.querySelector("[data-cd-minutes]"),
      seconds: el.querySelector("[data-cd-seconds]"),
    };
    var timer = null;

    function pad(n) { return n < 10 ? "0" + n : String(n); }

    function render() {
      var diff = target - Date.now();
      if (diff <= 0) {
        el.innerHTML = "<p class='tagline'>The festival is live. Enjoy!</p>";
        stop();
        return;
      }
      var s = Math.floor(diff / 1000);
      if (spans.days) spans.days.textContent = Math.floor(s / 86400);
      if (spans.hours) spans.hours.textContent = pad(Math.floor((s % 86400) / 3600));
      if (spans.minutes) spans.minutes.textContent = pad(Math.floor((s % 3600) / 60));
      if (spans.seconds) spans.seconds.textContent = pad(s % 60);
    }

    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    render();
    timer = setInterval(render, 1000);
  }

  /* ---------- team registration dynamic member rows ---------- */
  function initTeamBuilder() {
    var form = document.querySelector("[data-team-form]");
    if (!form) return;
    var list = form.querySelector("[data-member-list]");
    var addBtn = form.querySelector("[data-add-member]");
    var min = parseInt(form.getAttribute("data-min") || "2", 10);
    var max = parseInt(form.getAttribute("data-max") || "5", 10);
    if (!list || !addBtn) return;

    var counter = 0;

    function memberRow(index) {
      var row = document.createElement("div");
      row.className = "member-row";
      row.innerHTML =
        '<div class="form-group"><label for="mname' + index + '">Member ' + index + ' name</label>' +
        '<input class="form-control" id="mname' + index + '" name="member_name" required maxlength="120"></div>' +
        '<div class="form-group"><label for="memail' + index + '">Member ' + index + ' email</label>' +
        '<input class="form-control" type="email" id="memail' + index + '" name="member_email" required maxlength="200"></div>' +
        '<button type="button" class="btn btn-outline btn-sm" data-remove-member aria-label="Remove member ' + index + '">&times;</button>';
      return row;
    }

    function currentCount() { return list.querySelectorAll(".member-row").length; }

    function syncAddButton() {
      addBtn.disabled = currentCount() + 1 >= max;
    }

    addBtn.addEventListener("click", function () {
      if (currentCount() + 1 >= max) return;
      counter += 1;
      list.appendChild(memberRow(counter));
      syncAddButton();
    });

    list.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-remove-member]");
      if (!btn) return;
      btn.closest(".member-row").remove();
      syncAddButton();
    });

    /* Convert name/email inputs to JSON payloads before submit. */
    form.addEventListener("submit", function () {
      var names = form.querySelectorAll("[name='member_name']");
      var emails = form.querySelectorAll("[name='member_email']");
      for (var i = 0; i < names.length; i++) {
        var hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "member_json";
        hidden.value = JSON.stringify({ name: names[i].value, email: emails[i].value });
        form.appendChild(hidden);
        names[i].disabled = true;
        emails[i].disabled = true;
      }
    });

    syncAddButton();
  }

  /* ---------- hero background video: honour motion / data preferences ---------- */
  function initHeroVideo() {
    var video = document.querySelector("[data-hero-video]");
    if (!video) return;
    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    var narrow = window.matchMedia("(max-width: 860px)");
    var saveData = !!(navigator.connection && navigator.connection.saveData);

    /* The video always autoplays muted (browsers block autoplay with sound).
       Sound is opt-in via the toggle button, which is the required user gesture. */
    var toggle = document.querySelector("[data-hero-audio-toggle]");
    var label = document.querySelector("[data-hero-audio-label]");

    function reflectAudio() {
      if (!toggle) return;
      var on = !video.muted;
      toggle.setAttribute("aria-pressed", on ? "true" : "false");
      toggle.setAttribute("aria-label", (on ? "Mute" : "Unmute") + " background video");
      if (label) label.textContent = on ? "Mute" : "Unmute";
    }

    function setAudio(on) {
      video.muted = !on;
      if (on) {
        var attempt = video.play();
        if (attempt && typeof attempt.catch === "function") attempt.catch(function () {});
      }
      reflectAudio();
    }

    if (toggle) {
      reflectAudio();
      toggle.addEventListener("click", function () {
        setAudio(video.muted);
      });
      video.addEventListener("volumechange", reflectAudio);
    }

    function apply() {
      if (reduceMotion.matches || narrow.matches || saveData) {
        video.pause();
        video.removeAttribute("autoplay");
        video.preload = "none";
        if (toggle) toggle.hidden = true;
      } else {
        video.setAttribute("autoplay", "");
        video.preload = "metadata";
        if (toggle) toggle.hidden = false;
        var attempt = video.play();
        if (attempt && typeof attempt.catch === "function") attempt.catch(function () {});
      }
    }

    apply();
    if (typeof reduceMotion.addEventListener === "function") {
      reduceMotion.addEventListener("change", apply);
      narrow.addEventListener("change", apply);
    }
  }

  /* ---------- login: password show/hide ---------- */
  function initPasswordToggle() {
    var btn = document.querySelector("[data-password-toggle]");
    if (!btn) return;
    var input = document.getElementById(btn.getAttribute("aria-controls"));
    if (!input) return;
    btn.addEventListener("click", function () {
      var revealing = input.type === "password";
      input.type = revealing ? "text" : "password";
      btn.textContent = revealing ? "Hide" : "Show";
      btn.setAttribute("aria-pressed", revealing ? "true" : "false");
      input.focus();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initLiveCounts();
    initEventCounts();
    initCountdown();
    initTeamBuilder();
    initHeroVideo();
    initPasswordToggle();
  });
})();
