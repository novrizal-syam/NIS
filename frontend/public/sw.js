/* Nustrad ERP service worker: offline app shell for the DOR PWA.
 * - Navigations: network first, cached shell when offline.
 * - Built assets (/assets/*, icons, brand): cache first.
 * - API calls are never cached (drafts live in IndexedDB, see features/dor/offlineStore.ts).
 * - Background sync "dor-sync": wakes open pages to push queued DOR drafts. */
const CACHE = 'nustrad-shell-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/favicon.svg', '/icons/icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) {
    return;
  }
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put('/index.html', copy));
          return res;
        })
        .catch(() => caches.match('/index.html')),
    );
    return;
  }
  if (/^\/(assets|icons|brand)\//.test(url.pathname) || url.pathname.endsWith('.webmanifest')) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
            return res;
          }),
      ),
    );
  }
});

self.addEventListener('sync', (event) => {
  if (event.tag !== 'dor-sync') return;
  event.waitUntil(
    self.clients
      .matchAll({ type: 'window' })
      .then((list) => list.forEach((c) => c.postMessage({ type: 'dor-sync' }))),
  );
});
