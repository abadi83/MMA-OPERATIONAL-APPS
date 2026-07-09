/**
 * iScan Pro By MMA — PWA Initializer
 * ===================================
 * Loaded via <script src> in Streamlit's st.html().
 * Injects PWA meta tags, manifest link, and registers service worker.
 *
 * NOTE: On VPS with Nginx, the sub_filter injection handles this server-side.
 * This file provides client-side fallback for direct Streamlit access.
 */
(function () {
  if (window.__pwaInjected) return;
  window.__pwaInjected = true;

  var d = document;

  // ── Manifest link ──
  var link = d.createElement("link");
  link.rel = "manifest";
  link.href = "/app/static/manifest.json";
  link.setAttribute("crossorigin", "use-credentials");
  d.head.appendChild(link);

  // ── Meta tags ──
  var metas = [
    ["theme-color", "#0A84FF"],
    ["mobile-web-app-capable", "yes"],
    ["apple-mobile-web-app-capable", "yes"],
    ["apple-mobile-web-app-status-bar-style", "black-translucent"],
    ["apple-mobile-web-app-title", "iScan Pro"],
    ["application-name", "iScan Pro By MMA"],
  ];
  metas.forEach(function (pair) {
    var m = d.createElement("meta");
    m.name = pair[0];
    m.content = pair[1];
    d.head.appendChild(m);
  });

  // ── Apple touch icon ──
  var ai = d.createElement("link");
  ai.rel = "apple-touch-icon";
  ai.href = "/app/static/icon-192.png";
  d.head.appendChild(ai);

  // ── Register Service Worker ──
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/app/static/sw.js", { scope: "/" })
      .then(function (r) {
        console.log("[PWA] Service Worker registered:", r.scope);
      })
      .catch(function (e) {
        console.warn("[PWA] SW registration failed:", e.message);
      });
  }

  console.log("[PWA] iScan Pro PWA initialized ✓");
})();
