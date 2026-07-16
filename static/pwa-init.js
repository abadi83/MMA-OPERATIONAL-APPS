/**
 * iScan Pro By MMA — PWA Initializer
 * ===================================
 * Loaded via <script src> in Streamlit's st.html().
 * Injects PWA meta tags, manifest link, registers service worker,
 * and handles the beforeinstallprompt event for A2HS (Add to Home Screen).
 *
 * NOTE: On VPS with Nginx, the sub_filter injection handles manifest + meta
 * tags server-side. This file provides client-side fallback for direct
 * Streamlit access.
 */
(function () {
  if (window.__pwaInjected) return;
  window.__pwaInjected = true;

  var d = document;
  var APP_NAME = "iScan Pro By MMA";

  // ── Manifest link ──
  if (!d.querySelector('link[rel="manifest"]')) {
    var link = d.createElement("link");
    link.rel = "manifest";
    link.href = "/app/static/manifest.json";
    link.setAttribute("crossorigin", "use-credentials");
    d.head.appendChild(link);
  }

  // ── Meta tags ──
  var metas = [
    ["theme-color", "#0A84FF"],
    ["mobile-web-app-capable", "yes"],
    ["apple-mobile-web-app-capable", "yes"],
    ["apple-mobile-web-app-status-bar-style", "black-translucent"],
    ["apple-mobile-web-app-title", "iScan Pro"],
    ["application-name", APP_NAME],
  ];
  metas.forEach(function (pair) {
    if (!d.querySelector('meta[name="' + pair[0] + '"]')) {
      var m = d.createElement("meta");
      m.name = pair[0];
      m.content = pair[1];
      d.head.appendChild(m);
    }
  });

  // ── Apple touch icon ──
  if (!d.querySelector('link[rel="apple-touch-icon"]')) {
    var ai = d.createElement("link");
    ai.rel = "apple-touch-icon";
    ai.href = "/app/static/icon-192.png";
    d.head.appendChild(ai);
  }

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

  // ── Handle Install Prompt (A2HS) ──
  var deferredPrompt = null;
  var installBanner = null;

  // Show a custom install banner
  function showInstallBanner() {
    if (installBanner) return;
    installBanner = d.createElement("div");
    installBanner.id = "pwa-install-banner";
    installBanner.style.cssText =
      "position:fixed;bottom:20px;left:50%;transform:translateX(-50%);" +
      "background:#1C1C1E;color:#FFF;padding:16px 24px;border-radius:16px;" +
      "box-shadow:0 8px 32px rgba(0,0,0,0.5);z-index:99999;" +
      "display:flex;align-items:center;gap:14px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;" +
      "border:1px solid #38383A;max-width:90vw;";
    installBanner.innerHTML =
      '<span style="font-size:28px;">📦</span>' +
      '<div style="flex:1;">' +
      '<div style="font-weight:700;font-size:15px;">Install iScan Pro</div>' +
      '<div style="font-size:12px;color:#AEAEB2;">Tambahkan ke home screen untuk akses cepat</div>' +
      '</div>' +
      '<button id="pwa-install-btn" style="background:#0A84FF;color:#FFF;border:none;' +
      'padding:10px 18px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap;">' +
      '⬇️ Install</button>' +
      '<button id="pwa-dismiss-btn" style="background:none;color:#636366;border:none;' +
      'font-size:18px;cursor:pointer;padding:4px 8px;">✕</button>';
    d.body.appendChild(installBanner);

    d.getElementById("pwa-install-btn").addEventListener("click", function () {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function (result) {
          console.log("[PWA] User choice:", result.outcome);
          deferredPrompt = null;
          removeInstallBanner();
        });
      }
    });

    d.getElementById("pwa-dismiss-btn").addEventListener("click", function () {
      removeInstallBanner();
      // Don't show again for 3 days
      try {
        localStorage.setItem("pwa_banner_dismissed", Date.now().toString());
      } catch (e) {}
    });
  }

  function removeInstallBanner() {
    if (installBanner) {
      installBanner.remove();
      installBanner = null;
    }
  }

  // Capture the beforeinstallprompt event
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();  // Prevent default mini-infobar
    deferredPrompt = e;

    // Check if user recently dismissed
    var dismissed = null;
    try { dismissed = localStorage.getItem("pwa_banner_dismissed"); } catch (e) {}
    if (dismissed) {
      var daysSince = (Date.now() - parseInt(dismissed)) / (1000 * 60 * 60 * 24);
      if (daysSince < 3) return;  // Don't show if dismissed within 3 days
    }

    // Check if already installed (standalone mode)
    if (window.matchMedia("(display-mode: standalone)").matches) return;

    // Show banner after a short delay
    setTimeout(showInstallBanner, 2000);
  });

  // Track when app is installed
  window.addEventListener("appinstalled", function () {
    console.log("[PWA] App installed successfully!");
    deferredPrompt = null;
    removeInstallBanner();
  });

  console.log("[PWA] iScan Pro PWA initialized ✓");
})();
