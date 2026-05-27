// Service Worker for Portable Dispatch System
// Enables PWA installation on Android while keeping real-time network dynamic

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (e) => {
  // Pass-through strategy to avoid caching stale real-time data
  e.respondWith(fetch(e.request));
});
