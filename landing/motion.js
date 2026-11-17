// Plays the short product clip only for visitors who have not asked for reduced motion,
// and only while it is on screen. A visible button lets anyone pause it (WCAG 2.2.2).
(function () {
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  document.querySelectorAll("video.motion").forEach(function (video) {
    var toggle = video.parentElement.querySelector(".motion-toggle");
    var paused = reduce.matches;

    function sync() {
      if (!toggle) return;
      toggle.hidden = false;
      toggle.textContent = paused ? "Reproducir animación" : "Pausar animación";
      toggle.setAttribute("aria-pressed", String(paused));
    }

    if (toggle) {
      toggle.addEventListener("click", function () {
        paused = !paused;
        if (paused) video.pause(); else video.play().catch(function () {});
        sync();
      });
    }

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && !paused) {
            video.preload = "auto";
            video.play().catch(function () {});
          } else {
            video.pause();
          }
        });
      }, { threshold: 0.4 }).observe(video);
    }
    sync();
  });
})();
