/* ================================================================
   πNAD Scanner — Service Worker v2.0 (ES Module)
   ================================================================
   Entry point del Service Worker en formato ES module.
   Importa submódulos de static/sw/ para mejor mantenibilidad
   y testabilidad.

   Registro en scan.html:
     navigator.serviceWorker.register('/sw.js', { type: 'module', scope: '/' })

   Fallback clásico (importScripts): /sw-classic.js
   ================================================================ */

import {
  STATIC_CACHE,
  API_CACHE,
  cacheFirst,
  networkFirst,
  onInstall,
  onActivate,
} from '/static/sw/cache-strategies.js';

import {
  isApiRequest,
  isStaticAsset,
} from '/static/sw/helpers.js';

import {
  registerSyncListeners,
} from '/static/sw/sync.js';

import {
  registerJobNotifyListeners,
} from '/static/sw/job-notify.js';

// ─── INSTALL ───
self.addEventListener('install', onInstall);

// ─── ACTIVATE ───
self.addEventListener('activate', onActivate);

// ─── FETCH ───
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Solo interceptar requests de nuestro origen y Google Fonts
  if (url.origin !== self.location.origin &&
      !url.href.startsWith('https://fonts.googleapis.com') &&
      !url.href.startsWith('https://fonts.gstatic.com')) {
    return;
  }

  // 1. API endpoints → Network-first
  if (isApiRequest(url.pathname)) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // 2. OpenCV.js → Network-first (no cachear binario de 7MB)
  if (url.pathname.includes('opencv.js')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // 3. Assets estáticos → Cache-first
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // 4. Navegación → Network-first con fallback a homepage
  if (event.request.mode === 'navigate') {
    event.respondWith(networkFirst(event.request, '/'));
    return;
  }

  // 5. Default: network-first
  event.respondWith(networkFirst(event.request));
});

// ─── BACKGROUND SYNC ───
registerSyncListeners();

// ─── JOB NOTIFICATIONS ───
registerJobNotifyListeners();
console.log('[SW] Job notification listeners registered');
