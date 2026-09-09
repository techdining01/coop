// Minimal service worker: enables "Add to Home Screen" install prompts and
// caches the static app shell (CSS/JS/icons) so the UI chrome loads
// instantly even on a flaky connection. Deliberately does NOT cache HTML
// pages or API/HTMX responses — this is a financial app, and showing a
// stale balance offline is worse than showing nothing. Every page load
// still hits the network for actual data.

const CACHE_NAME = "al-halal-shell-v1";
const SHELL_ASSETS = [
  "/static/manifest.json",
  "/static/icons/company_logo.png",
  "/static/icons/company_logo.png",
  ];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isShellAsset = SHELL_ASSETS.some((asset) => url.pathname === asset);

  if (isShellAsset) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
  // Everything else (pages, HTMX partials, admin) — always network, never cached.
});
