/* ================================================================
   πNAD Scanner — SW Background Sync Module
   ================================================================
   Sincronización en segundo plano para cola de subidas offline.

   Exporta: syncPendingInvoices, registerSyncListeners
   ================================================================ */

/**
 * Sincroniza facturas pendientes cuando el dispositivo recupera
 * la conexión. Recupera facturas de IndexedDB y las reenvía al servidor.
 */
export async function syncPendingInvoices() {
  console.log('[SW] Sincronizando facturas pendientes...');
  
  try {
    // Abrir IndexedDB de UploadStore
    const db = await openUploadDB();
    if (!db) {
      console.error('[SW] No se pudo abrir IndexedDB');
      return;
    }
    
    // Obtener entradas pendientes
    const pendingEntries = await getPendingEntries(db);
    console.log(`[SW] ${pendingEntries.length} entradas pendientes para sincronizar`);
    
    // Sincronizar cada entrada con el backend
    for (const entry of pendingEntries) {
      try {
        await syncEntryWithBackend(entry);
        await markEntryCompleted(db, entry.queueId);
        console.log(`[SW] Entrada ${entry.queueId} sincronizada exitosamente`);
      } catch (error) {
        console.error(`[SW] Error sincronizando entrada ${entry.queueId}:`, error);
        await incrementEntryRetries(db, entry.queueId);
      }
    }
    
    // Cerrar DB
    db.close();
    
  } catch (error) {
    console.error('[SW] Error en sincronización:', error);
  }
}

/**
 * Abre la base de datos IndexedDB de UploadStore.
 */
async function openUploadDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('pinad_uploads_v1', 2);
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains('uploads')) {
        const store = db.createObjectStore('uploads', { keyPath: 'queueId' });
        store.createIndex('status', 'status', { unique: false });
      }
    };
  });
}

/**
 * Obtiene entradas pendientes de IndexedDB.
 */
async function getPendingEntries(db) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(['uploads'], 'readonly');
    const store = transaction.objectStore('uploads');
    const index = store.index('status');
    const request = index.getAll('queued');
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result || []);
  });
}

/**
 * Sincroniza una entrada con el backend.
 */
async function syncEntryWithBackend(entry) {
  const { queueId, blob, fileName, options } = entry;
  
  // Convertir ArrayBuffer a Blob
  const fileBlob = new Blob([blob], { type: entry.mimeType || 'application/octet-stream' });
  
  // Crear FormData para enviar al backend
  const formData = new FormData();
  formData.append('file', fileBlob, fileName);
  formData.append('queueId', queueId);
  if (options) {
    formData.append('options', JSON.stringify(options));
  }
  
  // Enviar al endpoint de sync del backend
  const response = await fetch('/api/sync/upload', {
    method: 'POST',
    body: formData,
  });
  
  if (!response.ok) {
    throw new Error(`Backend sync failed: ${response.status}`);
  }
  
  return await response.json();
}

/**
 * Marca una entrada como completada en IndexedDB.
 */
async function markEntryCompleted(db, queueId) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(['uploads'], 'readwrite');
    const store = transaction.objectStore('uploads');
    const request = store.put({
      queueId,
      status: 'completed',
      updatedAt: new Date().toISOString(),
    });
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
  });
}

/**
 * Incrementa el contador de reintentos de una entrada.
 */
async function incrementEntryRetries(db, queueId) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(['uploads'], 'readwrite');
    const store = transaction.objectStore('uploads');
    const getRequest = store.get(queueId);
    
    getRequest.onerror = () => reject(getRequest.error);
    getRequest.onsuccess = () => {
      const entry = getRequest.result;
      if (entry) {
        entry.retries = (entry.retries || 0) + 1;
        entry.updatedAt = new Date().toISOString();
        
        if (entry.retries >= (entry.maxRetries || 3)) {
          entry.status = 'failed';
        }
        
        const putRequest = store.put(entry);
        putRequest.onerror = () => reject(putRequest.error);
        putRequest.onsuccess = () => resolve();
      } else {
        resolve();
      }
    };
  });
}

/**
 * Registra el listener del evento 'sync' para Background Sync.
 */
export function registerSyncListeners() {
  self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-invoices') {
      event.waitUntil(syncPendingInvoices());
    }
  });
}

/**
 * Registra listener para cambios de conectividad.
 */
export function registerConnectivityListeners() {
  self.addEventListener('online', () => {
    console.log('[SW] Conexión recuperada, iniciando sincronización...');
    syncPendingInvoices();
  });
}
