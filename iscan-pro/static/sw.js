// ═══════════════════════════════════════════
// iScan Pro By MMA — Service Worker
// ═══════════════════════════════════════════
const CACHE_NAME = "iscan-pro-v2.3.0";
const ASSETS_TO_CACHE = [
  "/",
  "/app/static/manifest.json",
  "/app/static/icon-192.png",
  "/app/static/icon-512.png",
];

// ── Install: pre-cache static assets ──
self.addEventListener("install", (event) => {
  console.log("[SW] Installing service worker...");
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log("[SW] Caching static assets");
      return cache.addAll(ASSETS_TO_CACHE).catch((err) => {
        console.warn("[SW] Some assets failed to cache:", err);
      });
    })
  );
  // Force waiting SW to become active immediately
  self.skipWaiting();
});

// ── Activate: clean old caches ──
self.addEventListener("activate", (event) => {
  console.log("[SW] Activating service worker...");
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => {
            console.log("[SW] Deleting old cache:", name);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// ── Fetch: network-first for live data, cache fallback for static ──
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET requests
  if (event.request.method !== "GET") return;

  // ── Streamlit internal paths — always network, NEVER cache ──
  if (
    url.pathname.startsWith("/_stcore/") ||
    url.pathname.startsWith("/healthz") ||
    url.pathname.startsWith("/static/") ||        // Streamlit's own JS/CSS
    url.pathname.includes("_stcore") ||
    url.pathname.includes("stream") ||
    url.pathname.includes("ws")
  ) {
    return;  // Let browser handle normally (no SW interception)
  }

  // ── PWA static assets only — cache-first ──
  if (url.pathname.startsWith("/app/static/")) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // ── Main app HTML — network-first ──
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && response.headers.get("content-type")?.includes("text/html")) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});
