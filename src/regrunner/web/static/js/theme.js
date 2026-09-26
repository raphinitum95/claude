// Sets data-theme before first paint: the person's saved choice, else the system preference.
(function () {
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
  function saved() { try { return localStorage.getItem('rr.theme'); } catch (e) { return null; } }
  function apply() { root.setAttribute('data-theme', saved() || (media && media.matches ? 'light' : 'dark')); }
  apply();
  if (media && media.addEventListener) media.addEventListener('change', apply);
  window.rrTheme = {
    toggle: function () {
      var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      try { localStorage.setItem('rr.theme', next); } catch (e) { /* private mode: still switches for this page */ }
      root.setAttribute('data-theme', next);
      return next;
    }
  };
})();
