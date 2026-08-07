/* ================================================================
   πNAD Scanner — SW Job Notification Module
   ================================================================
   Polls /job-status/<job_id> in the background and shows a
   Notification when stitching completes or fails.

   The client sends a job to watch via postMessage:
     navigator.serviceWorker.controller.postMessage({
       type: 'watch-job',
       jobId: 'abc123',
       estimatedSeconds: 30,
     })

   The SW polls every 2s (short) to 5s (long), adjusts based on
   estimated time. When the job completes, it shows a browser
   Notification so the user knows even if the tab is in background.

   Export: registerJobNotifyListeners
   ================================================================ */

/**
 * Map of active polling intervals keyed by jobId.
 * @type {Map<string, {interval: number, timer: number, attempts: number}>}
 */
const _activePolls = new Map();

/** Max polling attempts before giving up (~10 min at 2s intervals). */
const MAX_ATTEMPTS = 300;

/** Poll interval in ms (2s for quick response). */
const POLL_INTERVAL_MS = 2000;

/**
 * Starts polling a job status endpoint.
 * @param {string} jobId
 * @param {number} estimatedSeconds - estimated total time for adaptive polling
 */
function startPolling(jobId, estimatedSeconds) {
  // Already polling this job
  if (_activePolls.has(jobId)) return;

  console.log('[SW-Notify] Watching job ' + jobId + ' (est ' + estimatedSeconds + 's)');

  let attempts = 0;

  const poll = async () => {
    try {
      const res = await fetch('/job-status/' + jobId);
      if (!res.ok) {
        if (res.status === 404) {
          stopPolling(jobId);
          return;
        }
        throw new Error('HTTP ' + res.status);
      }

      const data = await res.json();
      if (!data.success || !data.status) {
        stopPolling(jobId);
        return;
      }

      const status = data.status;
      const progress = data.progress || {};

      if (status === 'completed') {
        stopPolling(jobId);
        showNotification(jobId, 'completado', progress, data.result);
        return;
      }

      if (status === 'failed') {
        stopPolling(jobId);
        showNotification(jobId, 'falló', progress, null, data.error);
        return;
      }

      if (status === 'cancelled') {
        stopPolling(jobId);
        showNotification(jobId, 'cancelado', progress);
        return;
      }

      // Still running — continue polling
      attempts++;
      if (attempts >= MAX_ATTEMPTS) {
        stopPolling(jobId);
        console.warn('[SW-Notify] Job ' + jobId + ' exceeded max attempts');
        return;
      }

      // Adaptive: if estimated time is large, increase interval gradually
      let interval = POLL_INTERVAL_MS;
      if (estimatedSeconds > 60) {
        // For very long jobs (>1min), poll every 5s after first 30s
        interval = attempts > 15 ? 5000 : POLL_INTERVAL_MS;
      } else if (estimatedSeconds > 30) {
        interval = attempts > 20 ? 4000 : POLL_INTERVAL_MS;
      }

      // Also show periodic progress updates via the active tab
      if (attempts % 5 === 0 && progress.percent !== undefined) {
        await notifyActiveTab(jobId, progress);
      }

      const entry = _activePolls.get(jobId);
      if (entry) {
        entry.timer = setTimeout(poll, interval);
        entry.attempts = attempts;
      }
    } catch (err) {
      console.warn('[SW-Notify] Poll error for ' + jobId + ':', err.message);
      attempts++;
      if (attempts >= 10) {
        // After 10 consecutive errors, stop polling (server might be down)
        stopPolling(jobId);
        return;
      }
      const entry = _activePolls.get(jobId);
      if (entry) {
        entry.timer = setTimeout(poll, 5000); // Retry in 5s
        entry.attempts = attempts;
      }
    }
  };

  const timer = setTimeout(poll, 5000); // Start after 5s delay (give foreground poll a head start)
  _activePolls.set(jobId, {
    interval: POLL_INTERVAL_MS,
    timer: timer,
    attempts: 0,
  });
}

/**
 * Stops polling for a job.
 * @param {string} jobId
 */
function stopPolling(jobId) {
  const entry = _activePolls.get(jobId);
  if (entry) {
    clearTimeout(entry.timer);
    _activePolls.delete(jobId);
    console.log('[SW-Notify] Stopped watching job ' + jobId);
  }
}

/**
 * Shows a browser notification.
 * @param {string} jobId
 * @param {string} outcome - 'completado' | 'falló' | 'cancelado'
 * @param {object} progress
 * @param {object|null} result
 * @param {string|null} errorMsg
 */
function showNotification(jobId, outcome, progress, result, errorMsg) {
  const isSuccess = outcome === 'completado';
  const title = isSuccess
    ? '✓ Stitching completado'
    : outcome === 'falló'
      ? '✗ Stitching falló'
      : 'Stitching cancelado';

  const elapsed = progress.elapsed_seconds
    ? ' (' + Math.round(progress.elapsed_seconds) + 's)'
    : '';

  let body = '';
  if (isSuccess && result) {
    const shots = result.total_shots_used || '?';
    const width = result.stitched_width || 0;
    const height = result.stitched_height || 0;
    const size = (width && height) ? ' — ' + width + '×' + height + 'px' : '';
    body = shots + ' fotos cosidas' + size + elapsed;

    // If OCR data available, add a brief summary
    if (result.ocr_data) {
      const total = result.ocr_data.total || '';
      const cliente = result.ocr_data.cliente || '';
      if (total) body += ' — Total: ' + total;
    }
  } else if (outcome === 'falló') {
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
      renotify: false,
      requireInteraction: !isSuccess, // Keep errors visible until dismissed
      vibrate: isSuccess ? [100, 50, 100] : [200, 100, 200],
      actions: isSuccess
        ? [
            { action: 'view', title: 'Ver resultado' },
            { action: 'dismiss', title: 'Cerrar' },
          ]
        : [
            { action: 'dismiss', title: 'Cerrar' },
          ],
      data: { jobId: jobId, outcome: outcome },
    });
  } catch (e) {
    console.warn('[SW-Notify] Error showing notification:', e.message);
  }
}

/**
 * Sends a progress update to the active client tab.
 * @param {string} jobId
 * @param {object} progress
 */
async function notifyActiveTab(jobId, progress) {
  try {
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of clients) {
      client.postMessage({
        type: 'job-progress',
        jobId: jobId,
        percent: progress.percent,
        stage: progress.stage,
        message: progress.message,
        subMessage: progress.sub_message,
      });
    }
  } catch (e) {
    // Ignore — client might be closed
  }
}

/**
 * Handles incoming messages from the client.
 */
function handleMessage(event) {
  const msg = event.data || {};
  if (!msg || typeof msg !== 'object') return;

  switch (msg.type) {
    case 'watch-job':
      startPolling(msg.jobId, msg.estimatedSeconds || 30);
      break;

    case 'unwatch-job':
      stopPolling(msg.jobId);
      break;

    case 'ping':
      // Respond so the client knows the SW is alive and listening
      if (event.source) {
        event.source.postMessage({ type: 'pong', swVersion: '2.0' });
      }
      break;

    default:
      // Unknown message type — ignore
      break;
  }
}

/**
 * Handles notification click events.
 */
function handleNotificationClick(event) {
  const notification = event.notification;
  const data = notification.data || {};

  notification.close();

  if (event.action === 'dismiss') {
    return;
  }

  // Open or focus the app
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // If we have an open window, focus it
        for (const client of clientList) {
          if (client.url && 'focus' in client) {
            return client.focus();
          }
        }
        // Otherwise open a new window
        if (clients.openWindow) {
          return clients.openWindow('/');
        }
      })
  );
}

/**
 * Registers all job notification listeners.
 */
export function registerJobNotifyListeners() {
  self.addEventListener('message', handleMessage);
  self.addEventListener('notificationclick', handleNotificationClick);
}
