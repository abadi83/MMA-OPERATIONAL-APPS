// ═══════════════════════════════════════════
// iScan Pro — Service Worker Self-Destruct
// ═══════════════════════════════════════════
// Immediately unregisters itself and clears all caches.
self.addEventListener("install", () => { self.skipWaiting(); });
self.addEventListener("activate", () => {
  caches.keys().then(names => Promise.all(names.map(n => caches.delete(n))));
  self.registration.unregister().catch(() => {});
  self.clients.claim();
});
