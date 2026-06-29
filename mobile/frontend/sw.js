// Service Worker para PWA (funciona offline para la UI)
const CACHE_NAME = 'bt7274-mobile-v1';
const STATIC_FILES = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_FILES))
    );
});

self.addEventListener('fetch', (e) => {
    // Solo cachear archivos estáticos, no las llamadas a la API
    if (e.request.url.includes('/api/')) return;

    e.respondWith(
        caches.match(e.request).then((cached) => cached || fetch(e.request))
    );
});
