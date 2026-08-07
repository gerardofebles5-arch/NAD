/* ================================================================
   πNAD Scanner — SW Helpers Module
   ================================================================
   Funciones auxiliares para identificación de rutas y assets.

   Exporta: isApiRequest, isStaticAsset, API_PATTERNS
   ================================================================ */

/** Patrones de rutas API que se benefician de network-first */
export const API_PATTERNS = [
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

/**
 * Determina si una ruta pertenece a un endpoint de API.
 * @param {string} pathname - Ruta de la URL (ej. /process)
 * @returns {boolean}
 */
export function isApiRequest(pathname) {
  return API_PATTERNS.some((pattern) => pattern.test(pathname));
}

/**
 * Determina si una ruta es un asset estático cacheable.
 * Excluye OpenCV.js (binario ~7MB, se sirve siempre desde red).
 * @param {string} pathname - Ruta de la URL
 * @returns {boolean}
 */
export function isStaticAsset(pathname) {
  return /\.(css|js|json|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot)$/.test(pathname) &&
         !pathname.includes('opencv.js');
}
