/**
 * iScan Pro By MMA — Auth Persistence
 * ====================================
 * Injected via Nginx sub_filter before </head>.
 * Persists auth token across page refreshes using cookies + localStorage.
 *
 * Flow:
 * 1. On login, backend injects JS that sets cookie "iscan_sid" + localStorage.
 * 2. On page refresh: backend reads cookie server-side via st.context.cookies →
 *    auto-login without any redirect. No JS action needed.
 * 3. If cookie is missing (expired/cleared) but localStorage has token →
 *    redirect with ?auth=TOKEN so backend can re-authenticate and set cookie.
 * 4. Token in URL is always saved to cookie + localStorage, then URL is cleaned.
 * 5. On logout, both cookie + localStorage are cleared.
 */
(function () {
  if (window.__authPersistReady) return;
  window.__authPersistReady = true;

  var COOKIE_NAME = "iscan_sid";
  var LS_KEY = "iscan_auth_token";
  var REDIRECT_FLAG = "iscan_auth_redirect";

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : null;
  }

  function hasCookie(name) {
    return document.cookie.indexOf(name + "=") !== -1;
  }

  var url = new URL(window.location.href);
  var urlToken = url.searchParams.get("auth");

  // ── Case 1: Token in URL → persist and clean ──
  if (urlToken) {
    // Set cookie (7 days)
    var d = new Date();
    d.setTime(d.getTime() + 7 * 24 * 60 * 60 * 1000);
    document.cookie =
      COOKIE_NAME + "=" + encodeURIComponent(urlToken) +
      ";path=/;expires=" + d.toUTCString() +
      ";SameSite=Lax";
    // Save to localStorage
    try { localStorage.setItem(LS_KEY, urlToken); } catch (e) {}
    // Clear redirect flag (successful auth)
    try { sessionStorage.removeItem(REDIRECT_FLAG); } catch (e) {}
    // Clean URL
    url.searchParams.delete("auth");
    window.history.replaceState({}, "", url.toString());
    return;
  }

  // ── Case 2: Cookie exists → backend reads it, nothing to do ──
  if (hasCookie(COOKIE_NAME)) {
    return;
  }

  // ── Case 3: No cookie, but localStorage has token → redirect once ──
  // Use sessionStorage flag to prevent redirect loops
  if (sessionStorage.getItem(REDIRECT_FLAG)) return;

  var storedToken = null;
  try { storedToken = localStorage.getItem(LS_KEY); } catch (e) {}
  if (storedToken) {
    sessionStorage.setItem(REDIRECT_FLAG, "1");
    url.searchParams.set("auth", storedToken);
    window.location.replace(url.toString());
  }
})();
