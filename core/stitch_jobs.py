"""
Bloque 9 — Background Job Manager (Stitching Asíncrono con Polling)
====================================================================
Cuando un cliente envía N=12+ fotos a /process-z o /finalize, el stitching
puede tomar 10-30 segundos. Este módulo permite que el servidor devuelva
un job_id inmediatamente y procese el trabajo en un hilo de fondo (daemon),
mientras el cliente hace polling a /job-status/<id> para obtener progreso.

Arquitectura:
  POST /process-z-async (N fotos) → job creado (status="queued") → thread en bg
  GET  /job-status/<id>          → {status, progress%, stage, result?}
  DELETE /job-status/<id>        → cancelar + cleanup

Etapas del progreso:
  queued → stitching → detecting → enhancing → ocr → qr → saving → completed
  Cada etapa tiene un peso (% del total) y mensaje descriptivo.
"""

import os
import time
import uuid
import json
import base64
import logging
import threading
from typing import Dict, Optional, Callable, Any, List
from datetime import datetime
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger('nad.stitch_jobs')


# ══════════════════════════════════════════════════════════════
#  Configuración del progreso
# ══════════════════════════════════════════════════════════════

STAGE_WEIGHTS = {
    "queued":      0.0,
    "stitching":   0.35,   # 0-35%  — ORB pairwise + homografía + feathering
    "detecting":   0.10,   # 35-45% — detect_document + perspective_correct
    "enhancing":   0.10,   # 45-55% — enhance_document / enhanced_pipeline
    "ocr":         0.25,   # 55-80% — extract_invoice_data (OCR lento)
    "qr":          0.08,   # 80-88% — detect_codes + cross_check
    "saving":      0.07,   # 88-95% — save_invoice + codificar imágenes
    "completed":   1.0,    # 100%   — resultado disponible
}

STAGE_LABELS = {
    "queued":      "En cola",
    "stitching":   "Cosiendo imágenes (stitching ORB pairwise)",
    "detecting":   "Detectando documento y corrigiendo perspectiva",
    "enhancing":   "Realzando imagen (contraste, nitidez)",
    "ocr":         "Extrayendo datos con OCR",
    "qr":          "Leyendo códigos QR / barras",
    "saving":      "Guardando en historial",
    "completed":   "Completado",
    "failed":      "Falló",
    "cancelled":   "Cancelado",
}


# ══════════════════════════════════════════════════════════════
#  Data classes
# ══════════════════════════════════════════════════════════════

@dataclass
class JobProgress:
    """Progreso detallado de un job de stitching."""
    stage: str = "queued"
    progress: float = 0.0        # 0.0 a 1.0
    message: str = "En cola..."
    sub_progress: float = 0.0    # Progreso dentro de la etapa actual (0-1)
    sub_message: str = ""        # Mensaje detallado de la sub-etapa
    started_at: float = 0.0
    elapsed: float = 0.0
    estimated_remaining: float = 0.0


@dataclass
class JobState:
    """Estado completo de un job de stitching."""
    job_id: str
    session_id: Optional[str]  # Si viene de /process-shot/<id>/finalize-async
    total_shots: int
    status: str  # queued | running | completed | failed | cancelled
    progress: JobProgress = field(default_factory=JobProgress)
    result: Optional[dict] = None
    error: str = ""
    stage_times: Dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    thread: Optional[threading.Thread] = None
    cancel_flag: bool = False
    queue_position: int = 0  # 0 = no aplica (running/inmediato), >0 = posición en cola
    worker_fn: Optional[Callable] = None  # Callable[[str], None] — función worker del job


# ══════════════════════════════════════════════════════════════
#  Background Job Manager
# ══════════════════════════════════════════════════════════════

class BackgroundJobManager:
    """Gestiona jobs de stitching en background con polling de progreso.

    Cada job se ejecuta en un hilo daemon separado. El cliente recibe
    un job_id inmediatamente y puede consultar el progreso vía GET.

    Los jobs completados/failed se limpian automáticamente después de
    `completed_ttl` segundos.

    **Concurrencia**: Máximo `max_workers` jobs ejecutándose simultáneamente.
    Cuando se crea un nuevo job y ya hay `max_workers` activos, el job
    se encola con status 'queued' y queue_position > 0. En cuanto un
    worker se libera, el siguiente job en la cola se ejecuta automáticamente.

    Thread-safe mediante _lock.
    """

    def __init__(self, max_workers: int = 2, completed_ttl: int = 600):
        """
        Args:
            max_workers: Máximo número de workers concurrentes (default: 2).
            completed_ttl: TTL en segundos para jobs completados (default: 10 min).
        """
        self._max_workers = max_workers
        self._completed_ttl = completed_ttl
        self._jobs: Dict[str, JobState] = {}
        self._queue: List[str] = []  # job_ids en cola, orden FIFO
        self._active_workers = 0
        self._lock = threading.Lock()

    # ── Gestión de jobs ──────────────────────────────────────

    def create_job(self, session_id: Optional[str] = None,
                   total_shots: int = 0) -> str:
        """Crea un nuevo job y lo registra con status 'queued'.

        El job se inicia ejecutándose (si hay slot libre) o se encola
        automáticamente (si todos los workers están ocupados).
        El scheduling lo maneja `start_job()`.

        Args:
            session_id: ID de sesión de stitching (opcional).
            total_shots: Número total de shots.

        Returns:
            job_id: UUID del job creado.
        """
        job_id = uuid.uuid4().hex[:12]
        now = time.time()

        with self._lock:
            state = JobState(
                job_id=job_id,
                session_id=session_id,
                total_shots=total_shots,
                status="queued",
                progress=JobProgress(
                    stage="queued",
                    progress=0.0,
                    message=STAGE_LABELS["queued"],
                    started_at=now,
                ),
                created_at=now,
                queue_position=0,
            )
            self._jobs[job_id] = state

        self._log(f"Job {job_id} creado ({total_shots} shots, "
                  f"session={session_id or 'direct'})")
        return job_id

    def register_worker(self, job_id: str, worker_fn: Callable[[str], None]):
        """Registra la función worker para un job.

        Necesario para que los jobs desencolados puedan ejecutar
        su worker correctamente cuando se libere un slot.
        """
        with self._lock:
            state = self._jobs.get(job_id)
            if state:
                state.worker_fn = worker_fn

    def start_job(self, job_id: str, worker_fn: Callable[[str], None]):
        """Inicia un job en un hilo de background, o lo encola.

        Es el único punto de scheduling: si hay slot libre
        (_active_workers < _max_workers), arranca directo. Si no,
        encola con queue_position > 0.

        Args:
            job_id: ID del job.
            worker_fn: Función que ejecuta el trabajo. Recibe job_id.
        """
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                self._log(f"Job {job_id} no encontrado para iniciar")
                return

            # Guardar worker_fn para jobs desencolados
            state.worker_fn = worker_fn

            # Si ya está corriendo, no-op
            if state.status == "running" and state.thread is not None:
                return

            # Si no hay slots, encolar
            if self._active_workers >= self._max_workers:
                if job_id not in self._queue:
                    self._queue.append(job_id)
                    state.queue_position = len(self._queue)
                    state.status = "queued"
                    self._log(f"Job {job_id} encolado (posición {state.queue_position}). "
                              f"Workers: {self._active_workers}/{self._max_workers}")
                return

            # Slot libre: incrementar contador y arrancar
            self._active_workers += 1
            state.status = "running"
            state.progress.stage = "stitching"
            state.progress.progress = STAGE_WEIGHTS.get("stitching", 0.0)
            state.progress.message = STAGE_LABELS["stitching"]
            state.progress.elapsed = 0.0
            state.queue_position = 0

        self._start_thread(job_id, worker_fn)

    def _start_thread(self, job_id: str, worker_fn: Callable[[str], None]):
        """Crea e inicia el hilo daemon para un job."""
        thread = threading.Thread(
            target=self._run_wrapper,
            args=(job_id, worker_fn),
            daemon=True,
        )
        with self._lock:
            state = self._jobs.get(job_id)
            if state:
                state.thread = thread
        thread.start()
        self._log(f"Job {job_id} iniciado en background "
                  f"({self._active_workers}/{self._max_workers} workers activos)")

    def _run_wrapper(self, job_id: str, worker_fn: Callable[[str], None]):
        """Wrapper que captura excepciones del worker y libera el slot."""
        try:
            worker_fn(job_id)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._set_failed(job_id, str(e))
        finally:
            # Liberar slot y desencolar siguiente job
            self._on_job_complete(job_id)

    def _on_job_complete(self, job_id: str):
        """
        Se llama cuando un job termina (completado, fallido o cancelado).
        Decrementa el contador de workers activos y, si hay jobs en cola,
        inicia el siguiente.
        """
        next_job_id = None
        with self._lock:
            self._active_workers = max(0, self._active_workers - 1)
            self._log(f"Job {job_id} liberó slot. "
                      f"Workers: {self._active_workers}/{self._max_workers}, "
                      f"Cola: {len(self._queue)}")

            # Desencolar siguiente job si hay
            while self._queue and self._active_workers < self._max_workers:
                candidate = self._queue.pop(0)
                state = self._jobs.get(candidate)
                if state and state.status not in ("cancelled", "failed"):
                    next_job_id = candidate
                    self._active_workers += 1
                    state.status = "running"
                    state.progress.stage = "stitching"
                    state.progress.progress = STAGE_WEIGHTS.get("stitching", 0.0)
                    state.progress.message = STAGE_LABELS["stitching"]
                    state.progress.elapsed = 0.0
                    state.queue_position = 0
                    # Recalcular posiciones para los que quedan en cola
                    self._recalculate_queue_positions()
                    break
                else:
                    # Job cancelado/failed mientras estaba en cola — saltar
                    self._log(f"Job {candidate} saltado de la cola (status={state.status if state else 'unknown'})")

        if next_job_id:
            # Obtener worker_fn del estado (lo necesitamos para arrancar)
            # Como no tenemos el worker_fn almacenado, usamos el del estado
            self._log(f"Desencolando job {next_job_id} para ejecución")
            # Iniciamos el hilo — asumimos que el worker sabe qué hacer
            thread = threading.Thread(
                target=self._run_wrapper_unbound,
                args=(next_job_id,),
                daemon=True,
            )
            with self._lock:
                state = self._jobs.get(next_job_id)
                if state:
                    state.thread = thread
            thread.start()
            self._log(f"Job {next_job_id} desencolado y ejecutándose "
                      f"({self._active_workers}/{self._max_workers} workers)")

    def _recalculate_queue_positions(self):
        """Recalcula queue_position para todos los jobs en cola."""
        for i, jid in enumerate(self._queue):
            state = self._jobs.get(jid)
            if state:
                state.queue_position = i + 1

    def _run_wrapper_unbound(self, job_id: str):
        """Wrapper para jobs desencolados — usa el worker_fn almacenado.

        Cuando un job en cola se desencola al liberarse un slot, este
        wrapper recupera el worker_fn que se guardó en JobState.worker_fn
        durante start_job() y lo ejecuta.

        El worker_fn se almacena en start_job() y register_worker().
        """
        # Obtener worker_fn del estado
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                self._log(f"Job {job_id}: no encontrado para desencolar")
                self._on_job_complete(job_id)  # Liberar slot
                return
            fn = state.worker_fn

        if fn is None:
            self._log(f"Job {job_id}: no hay worker_fn registrado, cancelando")
            self._set_failed(job_id, "Worker no disponible para job desencolado")
            return

        self._log(f"Ejecutando worker para job {job_id} (desencolado)")
        try:
            fn(job_id)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._set_failed(job_id, str(e))
        finally:
            self._on_job_complete(job_id)

    # ── Actualización de progreso ─────────────────────────────

    def set_progress(self, job_id: str, stage: str,
                     sub_progress: float = 0.0,
                     sub_message: str = ""):
        """Actualiza el progreso de un job.

        Args:
            job_id: ID del job.
            stage: Nombre de la etapa actual.
            sub_progress: Progreso dentro de la etapa (0-1).
            sub_message: Mensaje detallado.
        """
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return

            # Calcular progreso global basado en pesos de etapas
            stages_order = ["queued", "stitching", "detecting",
                           "enhancing", "ocr", "qr", "saving", "completed"]
            base_progress = 0.0
            for s in stages_order:
                if s == stage:
                    break
                base_progress += STAGE_WEIGHTS.get(s, 0.0)

            stage_weight = STAGE_WEIGHTS.get(stage, 0.1)
            total_progress = base_progress + stage_weight * sub_progress

            state.progress.stage = stage
            state.progress.progress = min(total_progress, 0.99)
            state.progress.sub_progress = sub_progress
            state.progress.sub_message = sub_message
            state.progress.message = STAGE_LABELS.get(stage, stage)
            state.progress.elapsed = time.time() - state.progress.started_at

            # Estimar tiempo restante
            if state.progress.progress > 0.05:
                elapsed = state.progress.elapsed
                pct = state.progress.progress
                estimated_total = elapsed / pct
                state.progress.estimated_remaining = max(0, estimated_total - elapsed)

            state.last_activity = time.time()

    def set_completed(self, job_id: str, result: dict):
        """Marca un job como completado."""
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return
            state.status = "completed"
            state.result = result
            state.progress.stage = "completed"
            state.progress.progress = 1.0
            state.progress.message = STAGE_LABELS["completed"]
            state.progress.elapsed = time.time() - state.progress.started_at
            state.last_activity = time.time()

        self._log(f"Job {job_id} completado ({state.progress.elapsed:.1f}s)")

    def _set_failed(self, job_id: str, error: str):
        """Marca un job como fallido."""
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return
            state.status = "failed"
            state.error = error[:500]
            state.progress.stage = "failed"
            state.progress.message = STAGE_LABELS["failed"]
            state.progress.elapsed = time.time() - state.progress.started_at
            state.last_activity = time.time()

        self._log(f"Job {job_id} falló: {error[:100]}")

    def cancel_job(self, job_id: str) -> bool:
        """Cancela un job en ejecución.

        El thread se marca para cancelación pero no se mata forzosamente
        (podría corromper datos). La función worker debe verificar
        `is_cancelled()` periódicamente.
        """
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return False
            if state.status not in ("queued", "running"):
                return False
            state.cancel_flag = True
            state.status = "cancelled"
            state.progress.stage = "cancelled"
            state.progress.message = STAGE_LABELS["cancelled"]
            state.last_activity = time.time()

        self._log(f"Job {job_id} cancelado")
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Verifica si un job ha sido cancelado.

        Útil para que el worker lo checkee en puntos de control."""
        with self._lock:
            state = self._jobs.get(job_id)
            return state is not None and state.cancel_flag

    def get_status(self, job_id: str) -> Optional[dict]:
        """Retorna estado completo de un job.

        Returns:
            Dict con job_id, status, progress, queue_position, etc.
        """
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return None

            p = state.progress
            return {
                "job_id": job_id,
                "status": state.status,
                "total_shots": state.total_shots,
                "session_id": state.session_id,
                "queue_position": state.queue_position,
                "queue_length": len(self._queue),
                "max_workers": self._max_workers,
                "active_workers": self._active_workers,
                "progress": {
                    "stage": p.stage,
                    "percent": round(p.progress * 100, 1),
                    "message": p.message,
                    "sub_message": p.sub_message,
                    "sub_progress": round(p.sub_progress, 2),
                    "elapsed_seconds": round(p.elapsed, 1),
                    "estimated_remaining_seconds": round(p.estimated_remaining, 1),
                },
                "result": state.result if state.status == "completed" else None,
                "error": state.error if state.status == "failed" else None,
                "created_at": datetime.fromtimestamp(state.created_at).isoformat(),
                "last_activity": datetime.fromtimestamp(state.last_activity).isoformat(),
            }

    def delete_job(self, job_id: str) -> bool:
        """Elimina un job y libera sus recursos."""
        with self._lock:
            state = self._jobs.pop(job_id, None)
            if not state:
                return False
        self._log(f"Job {job_id} eliminado")
        return True

    def cleanup_expired(self) -> int:
        """Elimina jobs completados/failed expirados.

        Returns:
            Número de jobs eliminados.
        """
        now = time.time()
        expired = []
        with self._lock:
            for jid, state in list(self._jobs.items()):
                if state.status in ("completed", "failed", "cancelled"):
                    if now - state.last_activity > self._completed_ttl:
                        expired.append(jid)

        for jid in expired:
            self.delete_job(jid)

        if expired:
            self._log(f"Limpieza: {len(expired)} jobs expirados eliminados")
        return len(expired)

    def list_active_jobs(self) -> List[dict]:
        """Lista todos los jobs activos (queued + running)."""
        with self._lock:
            return [
                {
                    "job_id": jid,
                    "status": s.status,
                    "stage": s.progress.stage,
                    "percent": round(s.progress.progress * 100, 1),
                    "total_shots": s.total_shots,
                    "elapsed": round(s.progress.elapsed, 1),
                    "session_id": s.session_id,
                    "queue_position": s.queue_position,
                    "created_at": datetime.fromtimestamp(s.created_at).isoformat(),
                }
                for jid, s in sorted(
                    self._jobs.items(),
                    key=lambda x: x[1].created_at,
                    reverse=True,
                )
                if s.status in ("queued", "running")
            ]

    def get_worker_stats(self) -> dict:
        """Retorna estadísticas del pool de workers."""
        with self._lock:
            return {
                "max_workers": self._max_workers,
                "active_workers": self._active_workers,
                "queue_length": len(self._queue),
                "idle": self._max_workers - self._active_workers,
            }

    def _log(self, msg: str):
        log.info(msg)
        print(f"  [JobManager] {msg}")


# ── Singleton global ──

_job_manager: Optional[BackgroundJobManager] = None


def get_job_manager() -> BackgroundJobManager:
    """Retorna la instancia global del BackgroundJobManager."""
    global _job_manager
    if _job_manager is None:
        _job_manager = BackgroundJobManager()
    return _job_manager
