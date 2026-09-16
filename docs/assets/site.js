/* MUR documentation site — mermaid bootstrap + mobile nav. No build step. */
(function () {
  "use strict";

  // Mobile sidebar toggle.
  var btn = document.querySelector(".menu-btn");
  var sidebar = document.querySelector(".sidebar");
  if (btn && sidebar) {
    btn.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", function (e) {
      if (!sidebar.classList.contains("open")) return;
      if (sidebar.contains(e.target) || btn.contains(e.target)) return;
      sidebar.classList.remove("open");
      btn.setAttribute("aria-expanded", "false");
    });
  }

  // Diagrams render on a light surface in both page themes (see site.css),
  // so mermaid always gets the default light theme rather than following
  // prefers-color-scheme. The source diagrams carry explicit pastel fills
  // that only read correctly against white.
  if (window.mermaid) {
    window.mermaid.initialize({
      startOnLoad: true,
      theme: "default",
      flowchart: { useMaxWidth: true, htmlLabels: true },
      sequence: { useMaxWidth: true },
      gantt: { useMaxWidth: true },
      pie: { useMaxWidth: true }
    });
  }
})();
