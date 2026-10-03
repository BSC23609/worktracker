// Work Tracker service worker. Bump VERSION to force clients to refresh caches.
const VERSION = 'wt-v1';

self.addEventListener('install', (e) => self.skipWaiting());

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Only cache static assets (cache-first). Everything else — pages, API, auth —
// always goes to the network so no user-specific data is ever cached.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method === 'GET' && url.origin === self.location.origin
      && url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.open(VERSION).then((cache) =>
        cache.match(e.request).then((hit) =>
          hit || fetch(e.request).then((res) => { cache.put(e.request, res.clone()); return res; })
        )
      )
    );
  }
});
