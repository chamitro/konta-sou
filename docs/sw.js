/* Κοντά σου service worker: makes the page installable and keeps the last copy of the shell for a
   quick start. Live data (API, relay) is never cached here; the page always fetches it fresh. */
const CACHE = "konta-shell-20261026-1612"; // build_docs.py stamps the build version here so every release gets a fresh cache
const SHELL = ["./", "./manifest.webmanifest", "./icons/icon-192.png", "./icons/icon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {})); self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("message", e => { if (e.data === "SKIP_WAITING") self.skipWaiting(); });
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/") || url.pathname.endsWith("version.json")) return;
  // network first, cached shell as a fallback when offline
  e.respondWith(fetch(e.request).then(r => { if (r.ok && (e.request.mode === "navigate" || SHELL.some(p => url.pathname.endsWith(p.slice(1))))) caches.open(CACHE).then(c => c.put(e.request, r.clone())); return r; })
    .catch(() => caches.match(e.request, {ignoreSearch: true})));
});
