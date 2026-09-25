/* Jochos Don Chente — site behaviour. No dependencies. */
(function () {
  "use strict";

  /* ------------------------------------------------------------------
     CONFIG — the only things that should need editing.
     Keep HOURS in sync with the hours table + JSON-LD in both pages.
     ------------------------------------------------------------------ */
  var CONFIG = {
    timeZone: "America/Chicago",
    // 0 = Sunday … 6 = Saturday. [open, close] in 24h decimal hours. null = closed.
    hours: {
      0: null,
      1: null,
      2: [14, 21.5],
      3: [14, 21.5],
      4: [14, 21.5],
      5: [14, 21.5],
      6: null
    },
    // Catering form: set to a Formspree / Getform / Basin URL to receive
    // submissions by email. Leave empty to fall back to a pre-filled text message.
    formEndpoint: "",
    smsNumber: "+12104612955"
  };

  var lang = document.documentElement.lang === "es" ? "es" : "en";
  var T = {
    en: {
      open: "Open now · until ",
      soon: "Opens today at ",
      closed: "Closed · opens ",
      today: "Today",
      tomorrow: "tomorrow",
      at: " at ",
      days: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
      sending: "Sending…",
      sent: "¡Gracias! We got your request and will reach out soon.",
      smsOpened: "Opening your messages app with your request — just hit send.",
      error: "Something went wrong. Please call us at (210) 461-2955.",
      smsIntro: "Catering request"
    },
    es: {
      open: "Abierto ahora · hasta las ",
      soon: "Abrimos hoy a las ",
      closed: "Cerrado · abrimos el ",
      today: "Hoy",
      tomorrow: "mañana",
      at: " a las ",
      days: ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"],
      sending: "Enviando…",
      sent: "¡Gracias! Recibimos tu solicitud y te contactamos pronto.",
      smsOpened: "Abriendo tus mensajes con tu solicitud — solo presiona enviar.",
      error: "Algo salió mal. Llámanos al (210) 461-2955.",
      smsIntro: "Solicitud de catering"
    }
  }[lang];

  document.documentElement.classList.add("js");

  /* ---------- Helpers ---------- */

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

  function nowInZone() {
    // Returns { day, hour } for the restaurant's local time, whatever the visitor's zone.
    try {
      var parts = new Intl.DateTimeFormat("en-US", {
        timeZone: CONFIG.timeZone, weekday: "short", hour: "numeric", minute: "numeric", hour12: false
      }).formatToParts(new Date());
      var map = {};
      parts.forEach(function (p) { map[p.type] = p.value; });
      var day = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(map.weekday);
      return { day: day, hour: (parseInt(map.hour, 10) % 24) + parseInt(map.minute, 10) / 60 };
    } catch (e) {
      var d = new Date();
      return { day: d.getDay(), hour: d.getHours() + d.getMinutes() / 60 };
    }
  }

  function fmtTime(h) {
    var hr = Math.floor(h), min = Math.round((h - hr) * 60);
    var mm = min ? ":" + String(min).padStart(2, "0") : "";
    var suffix = hr >= 12 ? "pm" : "am";
    var h12 = hr % 12 || 12;
    return h12 + mm + suffix;
  }

  function fmtTimeEs(h) {
    var hr = Math.floor(h), min = Math.round((h - hr) * 60);
    return hr + ":" + String(min).padStart(2, "0");
  }

  function time(h) { return lang === "es" ? fmtTimeEs(h) : fmtTime(h); }

  /* ---------- Open / closed status ---------- */

  function updateStatus() {
    var now = nowInZone();
    var today = CONFIG.hours[now.day];
    var state, text;

    if (today && now.hour >= today[0] && now.hour < today[1]) {
      state = "open";
      text = T.open + time(today[1]);
    } else if (today && now.hour < today[0]) {
      state = "soon";
      text = T.soon + time(today[0]);
    } else {
      state = "closed";
      for (var i = 1; i <= 7; i++) {
        var d = (now.day + i) % 7;
        if (CONFIG.hours[d]) {
          var label = i === 1 ? T.tomorrow : T.days[d];
          text = T.closed + label + T.at + time(CONFIG.hours[d][0]);
          if (lang === "es" && i === 1) text = text.replace("el mañana", "mañana");
          break;
        }
      }
    }

    $$("[data-status]").forEach(function (el) {
      el.setAttribute("data-state", state);
      var label = $(".status-pill__text", el);
      if (label && text) label.textContent = text;
      el.hidden = false;
    });

    $$(".hours tr").forEach(function (tr) {
      var isToday = Number(tr.getAttribute("data-day")) === now.day;
      tr.classList.toggle("is-today", isToday);
      if (isToday) tr.querySelector("th").setAttribute("data-today", T.today);
    });
  }
  updateStatus();
  setInterval(updateStatus, 60 * 1000);

  /* ---------- Header: scrolled state + mobile nav ---------- */

  var header = $(".site-header");
  var actionBar = $(".action-bar");
  var hero = $(".hero");

  function onScroll() {
    var y = window.scrollY;
    header.classList.toggle("is-scrolled", y > 24);
    if (actionBar && hero) actionBar.classList.toggle("is-visible", y > hero.offsetHeight * 0.6);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  var toggle = $(".menu-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var open = header.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    $$(".nav a").forEach(function (a) {
      a.addEventListener("click", function () {
        header.classList.remove("nav-open");
        toggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  /* ---------- Menu filter tabs ---------- */

  var tabs = $$(".tabs [role=tab]");
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var filter = tab.getAttribute("data-filter");
      tabs.forEach(function (t) { t.setAttribute("aria-selected", String(t === tab)); });
      $$(".dish").forEach(function (card) {
        card.hidden = filter !== "all" && card.getAttribute("data-cat") !== filter;
      });
    });
  });

  /* ---------- Order sheet ---------- */

  var sheet = $("#order-sheet");
  function openSheet(itemName) {
    if (!sheet) return;
    var line = $(".sheet__item", sheet);
    if (line) {
      line.hidden = !itemName;
      var slot = $("strong", line);
      if (slot) slot.textContent = itemName || "";
    }
    if (typeof sheet.showModal === "function") sheet.showModal();
    else window.location.hash = "order";
  }
  $$("[data-open-order]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      if (!sheet || typeof sheet.showModal !== "function") return; // fall through to #order link
      e.preventDefault();
      openSheet(btn.getAttribute("data-item"));
    });
  });

  /* Shared dialog behaviour: close button + click outside */
  $$("dialog").forEach(function (dlg) {
    dlg.addEventListener("click", function (e) {
      if (e.target === dlg || e.target.classList.contains("lightbox__inner")) dlg.close();
    });
    $$("[data-close]", dlg).forEach(function (b) {
      b.addEventListener("click", function () { dlg.close(); });
    });
  });

  /* ---------- YouTube facade (loads the player only on click) ---------- */

  $$(".yt").forEach(function (box) {
    var btn = $("button", box);
    if (!btn) return;
    btn.addEventListener("click", function () {
      var id = box.getAttribute("data-id");
      var iframe = document.createElement("iframe");
      iframe.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0";
      iframe.title = box.getAttribute("data-title") || "YouTube video";
      iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
      iframe.allowFullscreen = true;
      box.innerHTML = "";
      box.appendChild(iframe);
    });
  });

  /* ---------- Map facade ---------- */

  var mapBtn = $(".map__load");
  if (mapBtn) {
    mapBtn.addEventListener("click", function () {
      var box = mapBtn.parentNode;
      var iframe = document.createElement("iframe");
      iframe.src = box.getAttribute("data-src");
      iframe.title = mapBtn.getAttribute("aria-label");
      iframe.loading = "lazy";
      iframe.referrerPolicy = "no-referrer-when-downgrade";
      box.innerHTML = "";
      box.appendChild(iframe);
    });
  }

  /* ---------- Gallery lightbox ---------- */

  var lightbox = $("#lightbox");
  var shots = $$(".masonry button");
  var current = 0;
  function show(i) {
    current = (i + shots.length) % shots.length;
    var img = $("img", lightbox);
    var src = $("img", shots[current]);
    img.src = shots[current].getAttribute("data-full");
    img.alt = src.alt;
  }
  if (lightbox && shots.length && typeof lightbox.showModal === "function") {
    shots.forEach(function (btn, i) {
      btn.addEventListener("click", function () { show(i); lightbox.showModal(); });
    });
    $(".lightbox__nav--prev", lightbox).addEventListener("click", function () { show(current - 1); });
    $(".lightbox__nav--next", lightbox).addEventListener("click", function () { show(current + 1); });
    lightbox.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") show(current - 1);
      if (e.key === "ArrowRight") show(current + 1);
    });
  }

  /* ---------- Catering form ---------- */

  var form = $("#catering-form");
  if (form) {
    var status = $(".form__status", form);
    var dateInput = $("input[type=date]", form);
    if (dateInput) dateInput.min = new Date().toISOString().slice(0, 10);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!form.reportValidity()) return;
      if (form.querySelector(".hp input").value) return; // bot

      var data = new FormData(form);
      status.removeAttribute("data-state");
      status.textContent = T.sending;

      if (CONFIG.formEndpoint) {
        fetch(CONFIG.formEndpoint, { method: "POST", body: data, headers: { Accept: "application/json" } })
          .then(function (r) {
            if (!r.ok) throw new Error(r.status);
            status.setAttribute("data-state", "ok");
            status.textContent = T.sent;
            form.reset();
          })
          .catch(function () {
            status.setAttribute("data-state", "err");
            status.textContent = T.error;
          });
        return;
      }

      // No endpoint configured: hand the request to the visitor's messaging app.
      var lines = [T.smsIntro + " — Jochos Don Chente"];
      $$("[name]", form).forEach(function (el) {
        if (el.name.charAt(0) === "_" || !el.value) return;
        var label = form.querySelector('label[for="' + el.id + '"]');
        lines.push((label ? label.textContent.replace("*", "").trim() : el.name) + ": " + el.value);
      });
      var body = encodeURIComponent(lines.join("\n"));
      var sep = /iPhone|iPad|Mac/.test(navigator.userAgent) ? "&" : "?";
      window.location.href = "sms:" + CONFIG.smsNumber + sep + "body=" + body;
      status.setAttribute("data-state", "ok");
      status.textContent = T.smsOpened;
    });
  }

  /* ---------- Language: remember choice, gently suggest Spanish ---------- */

  function store(key, val) {
    try {
      if (val === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, val);
    } catch (e) { return null; }
  }
  $$(".lang-switch a, [data-lang]").forEach(function (a) {
    a.addEventListener("click", function () { store("jdc-lang", a.getAttribute("hreflang") || a.getAttribute("data-lang")); });
  });

  var toast = $("#lang-toast");
  if (toast && lang === "en" && !store("jdc-lang")) {
    var langs = navigator.languages || [navigator.language || ""];
    if (String(langs[0]).toLowerCase().indexOf("es") === 0) {
      setTimeout(function () { toast.hidden = false; }, 1200);
    }
    $("button", toast).addEventListener("click", function () {
      toast.hidden = true;
      store("jdc-lang", "en");
    });
  }

  /* ---------- Reveal on scroll ---------- */

  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    $$(".reveal").forEach(function (el) { io.observe(el); });
  } else {
    $$(".reveal").forEach(function (el) { el.classList.add("is-in"); });
  }

  var year = $("[data-year]");
  if (year) year.textContent = new Date().getFullYear();
})();
