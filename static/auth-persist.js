/**
 * iScan Pro By MMA — Auth Persistence
 * ====================================
 * Injected via Nginx sub_filter before </head>.
 * Uses localStorage + URL redirect for reliable auth persistence.
 *
 * Flow:
 * 1. Login → backend injects JS that saves token to localStorage.
 * 2. Page refresh → JS detects no URL token → redirects with ?auth=TOKEN.
 * 3. Backend reads ?auth=TOKEN → validates → authenticates → clears URL.
 * 4. JS cleans URL via history.replaceState (no page reload).
 * 5. sessionStorage flag prevents redirect loops.
 */
(function () {
  if (window.__authPersistReady) return;
  window.__authPersistReady = true;

  var LS_KEY = "iscan_auth_token";
  var REDIRECT_KEY = "iscan_redirect_done";
  var MAX_REDIRECTS = 2;

  var url = new URL(window.location.href);
  var urlToken = url.searchParams.get("auth");

  // ── Case 1: Token in URL → save to localStorage, clean URL ──
  if (urlToken) {
    try { localStorage.setItem(LS_KEY, urlToken); } catch (e) {}
    // Also set a cookie as backup (7 days)
    try {
      var d = new Date();
      d.setTime(d.getTime() + 7 * 24 * 60 * 60 * 1000);
      document.cookie = "iscan_sid=" + encodeURIComponent(urlToken) +
        ";path=/;expires=" + d.toUTCString() + ";SameSite=Lax;Secure";
    } catch (e) {}
    // Clear redirect counter (success)
    try { sessionStorage.removeItem(REDIRECT_KEY); } catch (e) {}
    // Clean URL
    url.searchParams.delete("auth");
    window.history.replaceState({}, "", url.toString());
    return;
  }

  // ── Case 2: No URL token → check if we need to redirect for auth ──
  var storedToken = null;
  try { storedToken = localStorage.getItem(LS_KEY); } catch (e) {}

  if (!storedToken) return;  // No token = nothing to do

  // Check redirect count to prevent loops
  var redirectCount = 0;
  try {
    redirectCount = parseInt(sessionStorage.getItem(REDIRECT_KEY)) || 0;
  } catch (e) {}

  if (redirectCount >= MAX_REDIRECTS) {
    // Too many redirects — token is probably invalid, clean up
    console.warn("[Auth] Too many redirects, clearing stale token");
    try { localStorage.removeItem(LS_KEY); } catch (e) {}
    try { sessionStorage.removeItem(REDIRECT_KEY); } catch (e) {}
    try { document.cookie = "iscan_sid=;path=/;expires=Thu, 01 Jan 1970 00:00:00 GMT"; } catch (e) {}
    return;
  }

  // Redirect with token
  redirectCount++;
  try { sessionStorage.setItem(REDIRECT_KEY, String(redirectCount)); } catch (e) {}
  url.searchParams.set("auth", storedToken);
  window.location.replace(url.toString());
})();
