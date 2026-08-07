/* ================================================================
   πNAD Scanner — Service Worker v2.0 (Classic / Self-Contained)
   ================================================================
   Versión clásica para navegadores que no soportan ES module
   workers (Chrome <80, Firefox <114, Safari <16.4).

   Es auto-contenida (no usa import/export ni importScripts).
   Mantiene paridad funcional con la versión ES module.

   NOTA: Mantener sincronizado con service-worker.js + static/sw/*.
   La versión ES module (service-worker.js + static/sw/) es la
   fuente primaria. Actualizar ambos al hacer cambios.
   ================================================================ */

// ─── CONSTANTES ───
var STATIC_CACHE = 'pinad-static-v1';
var API_CACHE = 'pinad-api-v1';
var PRECACHE_URLS = [
  '/',
  '/static/manifest.json',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg',
  '/static/logo_pinad.png',
  'https://fonts.googleapis.com/css2?family=League+Gothic&family=Poppins:wght@300;400;500;600;700&display=swap',
];

var API_PATTERNS = [
  /\/process/,
  /\/process-z/,
  /\/health/,
  /\/invoices/,
  /\/correct/,
  /\/corrections/,
  /\/sync\//,
  /\/backend-status/,
  /\/format-learner-status/,
  /\/pipeline-preview/,
  /\/analyze/,
  /\/compare/,
  /\/quality/,
  /\/layout/,
  /\/parse-document/,
  /\/save-to-drive/,
  /\/batch-process/,
  /\/batch-pdf/,
  /\/stats\//,
];

// ─── HELPERS ───
function isApiRequest(pathname) {
  return API_PATTERNS.some(function (pattern) { return pattern.test(pathname); });
}

function isStaticAsset(pathname) {
  return /\.(css|js|json|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot)$/.test(pathname) &&
         !pathname.includes('opencv.js');
}

// ─── ESTRATEGIAS DE CACHÉ ───
async function cacheFirst(request) {
  var cached = await caches.match(request);
  if (cached) return cached;
  try {
    var response = await fetch(request);
    if (response.ok) {
      var cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirst(request, fallbackUrl) {
  try {
    var response = await fetch(request);
    if (response.ok && response.type === 'basic') {
      var cache = await caches.open(API_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    var cached = await caches.match(request);
    if (cached) return cached;
    if (fallbackUrl) {
      var fallback = await caches.match(fallbackUrl);
      if (fallback) return fallback;
    }
    return new Response(JSON.stringify({
      success: false,
      error: 'Sin conexión al servidor. Verifica que el servidor NAD esté encendido.',
      offline: true,
    }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

// ─── JOB NOTIFICATIONS ───
var _nActivePolls = {}; // {jobId: {timer, attempts}}
var N_MAX_ATTEMPTS = 300;
var N_POLL_MS = 2000;

function nStopPolling(jobId) {
  var entry = _nActivePolls[jobId];
  if (entry) {
    clearTimeout(entry.timer);
    delete _nActivePolls[jobId];
    console.log('[SW-Notify] Stopped watching job ' + jobId);
  }
}

function nShowNotification(jobId, outcome, progress, result, errorMsg) {
  var isSuccess = outcome === 'completado';
  var title = isSuccess
    ? '\u2713 Stitching completado'
    : outcome === 'fall\u00f3'
      ? '\u2717 Stitching fall\u00f3'
      : 'Stitching cancelado';
  var elapsed = (progress && progress.elapsed_seconds)
    ? ' (' + Math.round(progress.elapsed_seconds) + 's)' : '';
  var body = '';
  if (isSuccess && result) {
    var shots = result.total_shots_used || '?';
    var w = result.stitched_width || 0;
    var h = result.stitched_height || 0;
    var size = (w && h) ? ' \u2014 ' + w + '\u00d7' + h + 'px' : '';
    body = shots + ' fotos cosidas' + size + elapsed;
    if (result.ocr_data && result.ocr_data.total) {
      body += ' \u2014 Total: ' + result.ocr_data.total;
    }
  } else if (outcome === 'fall\u00f3') {
    body = (errorMsg || 'Error desconocido') + elapsed;
  } else {
    body = 'El stitching fue cancelado.' + elapsed;
  }
  try {
    self.registration.showNotification(title, {
      body: body,
      icon: '/static/icons/icon-192.svg',
      badge: '/static/icons/icon-192.svg',
      tag: 'nad-job-' + jobId,
      requireInteraction: !isSuccess,
      vibrate: isSuccess ? [100, 50, 100] : [200, 100, 200],
      actions: isSuccess
        ? [{ action: 'view', title: 'Ver resultado' }, { action: 'dismiss', title: 'Cerrar' }]
        : [{ action: 'dismiss', title: 'Cerrar' }],
      data: { jobId: jobId, outcome: outcome },
    });
  } catch(e) {
    console.warn('[SW-Notify] Error notification:', e.message);
  }
}

function nNotifyActiveTab(jobId, progress) {
  self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clients) {
    for (var i = 0; i < clients.length; i++) {
      clients[i].postMessage({
        type: 'job-progress',
        jobId: jobId,
        percent: progress.percent,
        stage: progress.stage,
      });
    }
  }).catch(function() {});
}

function nStartPolling(jobId, estimatedSeconds) {
  if (_nActivePolls[jobId]) return;
  console.log('[SW-Notify] Watching job ' + jobId);
  var attempts = 0;
  var est = estimatedSeconds || 30;

  function poll() {
    fetch('/job-status/' + jobId)
      .then(function(res) {
        if (res.status === 404) { nStopPolling(jobId); return null; }
        return res.json();
      })
      .then(function(data) {
        if (!data || !data.success || !data.status) {
          nStopPolling(jobId);
          return;
        }
        var s = data.status;
        var pg = data.progress || {};
        if (s === 'completed') { nStopPolling(jobId); nShowNotification(jobId, 'completado', pg, data.result); return; }
        if (s === 'failed') { nStopPolling(jobId); nShowNotification(jobId, 'fall\u00f3', pg, null, data.error); return; }
        if (s === 'cancelled') { nStopPolling(jobId); nShowNotification(jobId, 'cancelado', pg); return; }
        attempts++;
        if (attempts >= N_MAX_ATTEMPTS) { nStopPolling(jobId); return; }
        var interval = N_POLL_MS;
        if (est > 60 && attempts > 15) interval = 5000;
        else if (est > 30 && attempts > 20) interval = 4000;
        if (attempts % 5 === 0 && pg.percent !== undefined) {
          nNotifyActiveTab(jobId, pg);
        }
        _nActivePolls[jobId].timer = setTimeout(poll, interval);
        _nActivePolls[jobId].attempts = attempts;
      })
      .catch(function() {
        attempts++;
        if (attempts >= 10) { nStopPolling(jobId); return; }
        var e = _nActivePolls[jobId];
        if (e) { e.timer = setTimeout(poll, 5000); e.attempts = attempts; }
      });
  }

  _nActivePolls[jobId] = { timer: setTimeout(poll, 5000), attempts: 0, interval: N_POLL_MS };
}

// ─── MESSAGE HANDLER ───
self.addEventListener('message', function(event) {
  var msg = event.data || {};
  if (!msg || typeof msg !== 'object') return;
  switch (msg.type) {
    case 'watch-job':
      nStartPolling(msg.jobId, msg.estimatedSeconds || 30);
      break;
    case 'unwatch-job':
      nStopPolling(msg.jobId);
      break;
    case 'ping':
      if (event.source) event.source.postMessage({ type: 'pong', swVersion: '2.0' });
      break;
  }
});

// ─── NOTIFICATION CLICK HANDLER ───
self.addEventListener('notificationclick', function(event) {
  var notification = event.notification;
  notification.close();
  if (event.action === 'dismiss') return;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clients) {
      for (var i = 0; i < clients.length; i++) {
        if (clients[i].url && typeof clients[i].focus === 'function') {
          return clients[i].focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow('/');
    })
  );
});

// ─── BACKGROUND SYNC ───
async function syncPendingInvoices() {
  console.log('[SW] Sincronizando facturas pendientes...');
}

// ─── INSTALL ───
self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(function (cache) {
      return cache.addAll(PRECACHE_URLS).catch(function (err) {
        console.warn('[SW] Precache parcial:', err.message);
      });
    })
  );
  self.skipWaiting();
});

// ─── ACTIVATE ───
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys
          .filter(function (key) { return key !== STATIC_CACHE && key !== API_CACHE; })
          .map(function (key) { return caches.delete(key); })
      );
    })
  );
  self.clients.claim();
});

// ─── FETCH ───
self.addEventListener('fetch', function (event) {
  var url = new URL(event.request.url);

  if (url.origin !== self.location.origin &&
      !url.href.startsWith('https://fonts.googleapis.com') &&
      !url.href.startsWith('https://fonts.gstatic.com')) {
    return;
  }

  if (isApiRequest(url.pathname)) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  if (url.pathname.includes('opencv.js')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(networkFirst(event.request, '/'));
    return;
  }

  event.respondWith(networkFirst(event.request));
});

// ─── BACKGROUND SYNC ───
self.addEventListener('sync', function (event) {
  if (event.tag === 'sync-invoices') {
    event.waitUntil(syncPendingInvoices());
  }
});
