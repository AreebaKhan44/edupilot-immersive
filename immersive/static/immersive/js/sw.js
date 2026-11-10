/* EduPilot service worker: static files are network-first (always fresh online), lesson pages/manifests network-first with the downloaded lesson pack as fallback.
   Quizzes, grading and event uploads always need the network (no high-stakes offline exams); events queue in localStorage meanwhile. */
const STATIC = 'edupilot-static-v2';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/media/')) {
    e.respondWith(fetch(req).then((r) => { if (r.ok) { const c = r.clone(); caches.open(STATIC).then((ch) => ch.put(req, c)); } return r; }).catch(() => caches.match(req, { ignoreSearch: true })));
    return;
  }
  if (/^\/lessons\/\d+\/(viewer|pack)\/?$/.test(url.pathname) || /^\/v1\/vr\/lessons\/\d+\/manifest/.test(url.pathname) || /\/audio\/$/.test(url.pathname)) {
    e.respondWith(fetch(req).catch(() => caches.match(req, { ignoreSearch: false })));
  }
});
