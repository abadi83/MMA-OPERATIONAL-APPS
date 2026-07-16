/**
 * iScan Pro By MMA — Auth Persistence
 * ====================================
 * Injected via Nginx sub_filter before </head>.
 * Simple: save token from URL to localStorage + cookie, clean URL.
 * No redirect logic — backend reads cookie from HTTP header directly.
 */
(function () {
  if (window.__authPersistReady) return;
  window.__authPersistReady = true;

  var url = new URL(window.location.href);
  var urlToken = url.searchParams.get("auth");

  // Token in URL → persist, no redirect needed
  if (urlToken) {
    try { localStorage.setItem("iscan_auth_token", urlToken); } catch (e) {}
    try {
      var d = new Date();
      d.setTime(d.getTime() + 7 * 24 * 60 * 60 * 1000);
      document.cookie = "iscan_sid=" + encodeURIComponent(urlToken) +
        ";path=/;expires=" + d.toUTCString() + ";SameSite=Lax;Secure";
    } catch (e) {}
    // Clean URL
    url.searchParams.delete("auth");
    window.history.replaceState({}, "", url.toString());
  }
})();
