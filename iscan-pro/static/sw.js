// ═══════════════════════════════════════════
// iScan Pro By MMA — Service Worker
// ═══════════════════════════════════════════
const CACHE_NAME = "iscan-pro-v2.2.0";
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

  // Skip Streamlit WebSocket / health-check / internal API
  if (
    url.pathname.startsWith("/_stcore/") ||
    url.pathname.startsWith("/healthz") ||
    url.pathname.includes("_stcore") ||
    url.pathname.includes("stream") ||
    url.pathname.includes("ws")
  ) {
    // Streamlit internal — always go network
    return;
  }

  // Static assets: cache-first
  if (
    url.pathname.startsWith("/app/static/") ||
    url.pathname.endsWith(".png") ||
    url.pathname.endsWith(".woff2") ||
    url.pathname.endsWith(".css") ||
    url.pathname.endsWith(".js")
  ) {
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

  // Main app (Streamlit HTML): network-first with cache fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then((cached) => {
          if (cached) {
            console.log("[SW] Serving from cache:", url.pathname);
            return cached;
          }
          // Offline fallback page
          return new Response(
            `<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>iScan Pro — Offline</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0A0A0A; color: #FFF; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; text-align: center; }
    h1 { color: #0A84FF; margin-bottom: 8px; }
    p { color: #AEAEB2; margin: 4px 0; }
    .icon { font-size: 64px; margin-bottom: 16px; }
    button { margin-top: 20px; padding: 12px 24px; background: #0A84FF; color: #FFF; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }
  </style>
</head>
<body>
  <div>
    <div class="icon">📡</div>
    <h1>iScan Pro — Offline</h1>
    <p>Tidak ada koneksi internet.</p>
    <p>Aplikasi ini memerlukan koneksi ke server untuk bekerja.</p>
    <button onclick="location.reload()">🔄 Coba Lagi</button>
  </div>
</body>
</html>`,
            { headers: { "Content-Type": "text/html; charset=utf-8" } }
          );
        });
      })
  );
});
