/* ================================================================
   πNAD Scanner — SW Cache Strategies Module
   ================================================================
   Estrategias de caché para el Service Worker:
   - Cache-first:  assets estáticos (CSS, JS, fuentes, iconos)
   - Network-first: APIs y navegación

   Exporta: STATIC_CACHE, API_CACHE, PRECACHE_URLS,
            cacheFirst, networkFirst, onInstall, onActivate
   ================================================================ */

/** Nombre del caché para assets estáticos */
export const STATIC_CACHE = 'pinad-static-v1';

/** Nombre del caché para respuestas de API */
export const API_CACHE = 'pinad-api-v1';

/** URLs para precachear durante el evento install */
export const PRECACHE_URLS = [
  '/',
  '/static/manifest.json',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg',
  '/static/logo_pinad.png',
  'https://fonts.googleapis.com/css2?family=League+Gothic&family=Poppins:wght@300;400;500;600;700&display=swap',
];

/**
 * Estrategia Cache-First: intenta servir desde caché; si no existe,
 * busca en la red y almacena en caché para futuras requests.
 * @param {Request} request
 * @returns {Promise<Response>}
 */
export async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('Offline', { status: 503 });
  }
}

/**
 * Estrategia Network-First: intenta buscar en la red primero;
 * si falla (offline), sirve desde caché. Opcionalmente acepta
 * una URL de fallback para navegación.
 * @param {Request} request
 * @param {string} [fallbackUrl] - URL alternativa para servir
 * @returns {Promise<Response>}
 */
export async function networkFirst(request, fallbackUrl) {
  try {
    const response = await fetch(request);
    if (response.ok && response.type === 'basic') {
      const cache = await caches.open(API_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    if (fallbackUrl) {
      const fallback = await caches.match(fallbackUrl);
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

/**
 * Manejador del evento 'install': precachea assets estáticos.
 * @param {ExtendableEvent} event
 */
export function onInstall(event) {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch((err) => {
        console.warn('[SW] Precache parcial:', err.message);
      });
    })
  );
  self.skipWaiting();
}

/**
 * Manejador del evento 'activate': limpia caches de versiones anteriores.
 * @param {ExtendableEvent} event
 */
export function onActivate(event) {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== API_CACHE)
          .map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
}
