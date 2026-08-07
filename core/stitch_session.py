"""
Bloque 8 — Stitching Session Manager (Pipeline Asíncrono Incremental)
======================================================================
Gestiona sesiones de stitching donde cada shot se envía individualmente
al servidor, en lugar de esperar a tener todas las N fotos para subirlas
juntas en una sola request HTTP.

Arquitectura:
  capture() → POST /process-shot (shot_0) → sesión creada, canvas = shot_0
  capture() → POST /process-shot (shot_1, session_id=X) → match + stitch incremental
  capture() → POST /process-shot (shot_2, session_id=X) → match + stitch incremental
  ...
  process() → POST /process-shot/X/finalize → crop + OCR + QR → resultado

Ventajas respecto al pipeline síncrono (/process-z):
  - Sin timeout: cada request individual sube UNA foto (~200KB) en ~100ms
  - Progreso visible en la UI: cada shot se marca como "subido" al instante
  - Stitching incremental: cuando el usuario termina de capturar, el canvas
    ya está casi cosido — /finalize solo recorta y ejecuta OCR
  - Reintentos granulares: si una foto falla al subir, se reintenta sin
    afectar a las demás
"""

import os
import sys
import json
import base64
import io
import time
import uuid
import logging
import threading
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass, field

import cv2
import numpy as np

from core.stitch import StitchingEngine

log = logging.getLogger('nad.stitch_session')


# ══════════════════════════════════════════════════════════════
#  Data classes
# ══════════════════════════════════════════════════════════════

@dataclass
class ShotData:
    """Datos de un shot individual recibido."""
    index: int
    width: int
    height: int
    size_bytes: int
    received_at: float
    stored_path: str  # Ruta al archivo JPEG en TEMP_DIR
    ghost_offset_y: float = 0.0  # Ajuste vertical del ghost (fracción del canvas)
    ghost_scale: float = 1.0    # Escala del ghost


@dataclass
class SessionState:
    """Estado interno de una sesión de stitching incremental."""
    session_id: str
    total_shots: int
    overlap_pct: float
    seam_method: str
    output_mode: str
    shots: List[ShotData] = field(default_factory=list)
    current_canvas: Optional[np.ndarray] = field(default=None)  # Canvas con stitching incremental
    canvas_path: str = ""  # Ruta al canvas almacenado
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    incremental_matched: int = 0  # Cuántos pares se han stitchado incrementalmente
    status: str = "active"  # active | finalizing | completed | failed
    error: str = ""
    final_result: Optional[dict] = field(default=None)


# ══════════════════════════════════════════════════════════════
#  Stitching Session Manager
# ══════════════════════════════════════════════════════════════

class StitchingSessionManager:
    """Gestiona múltiples sesiones de stitching incremental.

    Cada sesión corresponde a un documento largo (Modo Z) que se captura
    en N shots enviados uno por uno. El manager almacena las sesiones en
    memoria (con persistencia opcional a disco para recuperación ante
    fallos del servidor).

    Limpieza automática: sesiones inactivas por más de `session_ttl`
    segundos se eliminan.
    """

    def __init__(self, temp_dir: str, session_ttl: int = 7200):
        """
        Args:
            temp_dir: Directorio para almacenar imágenes temporales.
            session_ttl: TTL en segundos para sesiones inactivas (default: 2h).
        """
        self._temp_dir = temp_dir
        self._session_ttl = session_ttl
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._stitch_engine = StitchingEngine(show_debug=False)
        os.makedirs(temp_dir, exist_ok=True)

    # ── Gestión de sesiones ──────────────────────────────────

    def create_session(self, total_shots: int, overlap_pct: float = 0.30,
                       seam_method: str = "feather", output_mode: str = "limpio") -> str:
        """Crea una nueva sesión de stitching.

        Args:
            total_shots: Número total de shots esperados (N).
            overlap_pct: Fracción de overlap entre tomas.
            seam_method: 'feather' | 'graphcut'.
            output_mode: 'limpio' | 'color' | 'grises'.

        Returns:
            session_id: UUID de la sesión creada.
        """
        session_id = uuid.uuid4().hex[:12]
        shots_dir = os.path.join(self._temp_dir, f"session_{session_id}")
        os.makedirs(shots_dir, exist_ok=True)

        state = SessionState(
            session_id=session_id,
            total_shots=total_shots,
            overlap_pct=overlap_pct,
            seam_method=seam_method,
            output_mode=output_mode,
            canvas_path=os.path.join(shots_dir, "canvas.jpg"),
        )

        with self._lock:
            self._sessions[session_id] = state

        self._log(f"Sesión {session_id} creada: {total_shots} shots, "
                  f"overlap={overlap_pct}, seam={seam_method}")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Obtiene una sesión por ID."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state:
                state.last_activity = time.time()
            return state

    def add_shot(self, session_id: str, shot_index: int,
                 image: np.ndarray,
                 ghost_offset_y: float = 0.0,
                 ghost_scale: float = 1.0) -> Tuple[bool, str]:
        """Agrega un shot a una sesión existente y hace stitching incremental.

        Args:
            session_id: ID de la sesión.
            shot_index: Índice del shot (0-based).
            image: Imagen BGR del shot.

        Returns:
            (success, message)
        """
        with self._lock:
            state = self._sessions.get(session_id)
            if not state:
                return False, "Sesión no encontrada"
            if state.status != "active":
                return False, f"Sesión en estado '{state.status}'"
            if shot_index >= state.total_shots:
                return False, f"Índice {shot_index} fuera de rango (máx {state.total_shots - 1})"

            # Verificar que no duplicamos índices
            existing = [s for s in state.shots if s.index == shot_index]
            if existing:
                self._log(f"  ⚠ Shot {shot_index} ya existe — reemplazando")

            # Guardar imagen a disco
            shots_dir = os.path.join(self._temp_dir, f"session_{session_id}")
            os.makedirs(shots_dir, exist_ok=True)
            shot_path = os.path.join(shots_dir, f"shot_{shot_index}.jpg")
            cv2.imwrite(shot_path, image, [cv2.IMWRITE_JPEG_QUALITY, 92])

            # Registrar shot
            h, w = image.shape[:2]
            shot_size = os.path.getsize(shot_path) if os.path.exists(shot_path) else 0
            shot_data = ShotData(
                index=shot_index,
                width=w,
                height=h,
                size_bytes=shot_size,
                received_at=time.time(),
                stored_path=shot_path,
                ghost_offset_y=ghost_offset_y,
                ghost_scale=ghost_scale,
            )

            # Quitar duplicado si existe
            state.shots = [s for s in state.shots if s.index != shot_index]
            state.shots.append(shot_data)
            state.shots.sort(key=lambda s: s.index)
            state.last_activity = time.time()

            # ── Stitching incremental ──
            # Si ya tenemos al menos 2 shots consecutivos desde el inicio,
            # hacemos stitching incremental inmediato
            try:
                self._incremental_stitch(state)
            except Exception as e:
                self._log(f"  ⚠ Stitching incremental falló (se hará en /finalize): {e}")

            received = len(state.shots)
            self._log(f"  Shot {shot_index} añadido ({w}x{h}, {shot_size} bytes). "
                      f"Recibidos: {received}/{state.total_shots}")
            return True, f"Shot {shot_index} recibido ({received}/{state.total_shots})"

        # Lock released

    def _incremental_stitch(self, state: SessionState):
        """Ejecuta stitching incremental: toma los shots recibidos y
        los cose secuencialmente en el canvas actual.

        Solo stitcha nuevos pares que no se hayan stitchado antes.
        """
        sorted_shots = sorted(state.shots, key=lambda s: s.index)

        if len(sorted_shots) < 2:
            return  # No hay suficiente para stitching

        # Cargar imágenes
        images = []
        for sd in sorted_shots:
            img = cv2.imread(sd.stored_path)
            if img is not None:
                images.append(img)

        if len(images) < 2:
            return

        # Si el canvas actual es None, empezar con la primera imagen
        if state.current_canvas is None:
            state.current_canvas = images[0].copy()
            state.incremental_matched = 0

        # Stitch incremental: solo los pares nuevos
        # `incremental_matched` guarda cuántos pares se han procesado
        # (0 = solo shot_0 en canvas, 1 = shot_0+shot_1 stitchados, etc.)
        while state.incremental_matched < len(images) - 1:
            idx = state.incremental_matched + 1
            if idx >= len(images):
                break

            # Match del canvas actual (que contiene shots[0..idx]) contra shots[idx]
            # Usar ghost_offset_y del último shot como initial_h hint si está disponible
            initial_h = None
            src_shot = state.shots[idx] if idx < len(state.shots) else None
            if src_shot is not None and (abs(src_shot.ghost_offset_y) > 0.001 or abs(src_shot.ghost_scale - 1.0) > 0.001):
                # Construir homografía desde ghost_offset_y + ghost_scale
                # ghost_offset_y = -0.20 → usuario movió ghost 20% arriba
                # → la imagen inferior se coloca MÁS arriba (ty negativo)
                # ghost_scale = 1.10 → usuario hizo zoom out 10%
                # → la imagen inferior se escala 10% más grande
                h_canvas = state.current_canvas.shape[0]
                ty = -src_shot.ghost_offset_y * h_canvas * 0.3
                initial_h = np.eye(3, dtype=np.float32)
                initial_h[0, 0] = src_shot.ghost_scale
                initial_h[1, 1] = src_shot.ghost_scale
                initial_h[1, 2] = ty
                self._log(f"  Usando ghost_offset_y={src_shot.ghost_offset_y:.3f}, "
                          f"ghost_scale={src_shot.ghost_scale:.3f} "
                          f"→ escala={src_shot.ghost_scale:.3f}, translación Y={ty:.0f}px")

            H, inliers, _, _ = self._stitch_engine._match_pair(
                state.current_canvas, images[idx],
                initial_h=initial_h,
            )

            if H is not None:
                # Warpear la nueva imagen
                ref_h, ref_w = state.current_canvas.shape[:2]
                bot_h, bot_w = images[idx].shape[:2]
                h_new_est = int(bot_h * 1.3)
                w_new_est = ref_w  # Ancho fijo

                warped = cv2.warpPerspective(
                    images[idx], H,
                    (w_new_est, h_new_est),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )

                # Recortar warpeo
                gray_w = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
                _, mask = cv2.threshold(gray_w, 5, 255, cv2.THRESH_BINARY)
                coords = cv2.findNonZero(mask)
                if coords is not None:
                    x, y, w_bb, h_bb = cv2.boundingRect(coords)
                    warped_trimmed = warped[y:y + h_bb, x:x + w_bb]
                else:
                    warped_trimmed = warped
                    h_bb, w_bb = warped.shape[:2]

                # Estimar offset Y
                center_pt = np.float32([[[bot_w / 2, 0]]])
                mapped = cv2.perspectiveTransform(center_pt, H)
                insert_y = max(0, int(float(mapped[0, 0, 1])))

                canvas_h = max(ref_h, insert_y + h_bb)
                new_canvas = np.zeros((canvas_h + int(bot_h * 0.2), w_new_est, 3), dtype=np.uint8)
                new_canvas[:ref_h, :ref_w] = state.current_canvas

                # Normalizar ancho antes de feathering (evita shape mismatch)
                if warped_trimmed.shape[1] != new_canvas.shape[1]:
                    from cv2 import resize, INTER_LINEAR
                    warped_trimmed = resize(
                        warped_trimmed,
                        (new_canvas.shape[1], warped_trimmed.shape[0]),
                        interpolation=INTER_LINEAR,
                    )
                if insert_y < ref_h:
                    # Feathering en overlap
                    new_canvas = self._stitch_engine._feather_blend(
                        new_canvas[:ref_h, :new_canvas.shape[1]],  # Usar shape real
                        warped_trimmed,
                        insert_y,
                        new_canvas.shape[0],
                    )
                else:
                    y_end = min(insert_y + h_bb, new_canvas.shape[0])
                    h_avail = y_end - insert_y
                    if h_avail > 0:
                        new_canvas[insert_y:insert_y + h_avail, :w_bb] = (
                            warped_trimmed[:h_avail, :w_bb]
                        )

                state.current_canvas = new_canvas
                state.incremental_matched = idx
                self._log(f"  Incremental: par {idx} stitchado ({inliers} inliers)")
            else:
                # Homografía falló: intentar translación simple
                ref_h, ref_w = state.current_canvas.shape[:2]
                bot_h, bot_w = images[idx].shape[:2]
                canvas_new = np.zeros((ref_h + bot_h, ref_w, 3), dtype=np.uint8)
                canvas_new[:ref_h, :ref_w] = state.current_canvas
                canvas_new[ref_h:ref_h + bot_h, :min(ref_w, bot_w)] = images[idx][:, :min(ref_w, bot_w)]
                state.current_canvas = canvas_new
                state.incremental_matched = idx
                self._log(f"  ⚠ Incremental: par {idx} pegado sin homografía")

    def get_status(self, session_id: str) -> Optional[dict]:
        """Retorna estado actual de la sesión."""
        state = self.get_session(session_id)
        if not state:
            return None

        with self._lock:
            received = len(state.shots)
            canvas_info = None
            if state.current_canvas is not None:
                h, w = state.current_canvas.shape[:2]
                canvas_info = {"width": w, "height": h}

            # Información de shots recibidos
            shot_info = []
            for sd in sorted(state.shots, key=lambda s: s.index):
                shot_info.append({
                    "index": sd.index,
                    "width": sd.width,
                    "height": sd.height,
                    "size_bytes": sd.size_bytes,
                    "received_at": sd.received_at,
                })

            return {
                "session_id": session_id,
                "status": state.status,
                "total_shots": state.total_shots,
                "received_shots": received,
                "missing_shots": state.total_shots - received,
                "shot_indices": [s.index for s in state.shots],
                "shots": shot_info,
                "canvas": canvas_info,
                "incremental_matched": state.incremental_matched,
                "elapsed_seconds": round(time.time() - state.created_at, 1),
                "overlap_pct": state.overlap_pct,
                "seam_method": state.seam_method,
                "output_mode": state.output_mode,
                "error": state.error if state.error else None,
            }

    def finalize(self, session_id: str, run_ocr: bool = True) -> Optional[dict]:
        """Finaliza una sesión de stitching.

        Completa el stitching de todos los shots recibidos, recorta bordes
        negros, y opcionalmente ejecuta el pipeline OCR completo.

        Args:
            session_id: ID de la sesión.
            run_ocr: Si True, ejecuta OCR sobre el resultado.

        Returns:
            Dict con resultado, o None si la sesión no existe.
        """
        with self._lock:
            state = self._sessions.get(session_id)
            if not state:
                return None
            if state.status == "completed" and state.final_result:
                return state.final_result

            state.status = "finalizing"

        try:
            # 1. Cargar TODOS los shots desde disco
            sorted_shots = sorted(state.shots, key=lambda s: s.index)
            images = []
            for sd in sorted_shots:
                img = cv2.imread(sd.stored_path)
                if img is not None:
                    images.append(img)

            if len(images) < 1:
                raise ValueError("No hay imágenes para procesar")

            # 2. Si tenemos < 2 imágenes, usar la única disponible como canvas
            if len(images) == 1:
                canvas = images[0]
            else:
                # 3. Si el stitching incremental ya cubre todo, usar el canvas
                if (state.current_canvas is not None
                        and state.incremental_matched >= len(images) - 1):
                    canvas = state.current_canvas
                    self._log(f"Usando canvas incremental ({canvas.shape[1]}x{canvas.shape[0]})")
                else:
                    # 4. Stitching completo desde cero
                    self._log("Ejecutando stitching completo...")
                    engine = StitchingEngine(
                        seam_method=state.seam_method,
                        show_debug=False,
                    )
                    canvas = engine.stitch_sequential(
                        images, overlap_pct=state.overlap_pct
                    )
                    if canvas is None:
                        raise ValueError("Stitching completo falló")

            # Recortar bordes negros
            canvas = self._stitch_engine._crop_black_borders(canvas)

            # Codificar imagen resultante
            _, buffer = cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
            stitched_b64 = base64.b64encode(buffer).decode('utf-8')

            result = {
                "session_id": session_id,
                "success": True,
                "stitched_image": stitched_b64,
                "stitched_width": canvas.shape[1],
                "stitched_height": canvas.shape[0],
                "total_shots_used": len(images),
                "incremental": state.incremental_matched > 0,
                "incremental_matched": state.incremental_matched,
            }

            # 5. Ejecutar OCR si se solicita
            if run_ocr and len(images) >= 1:
                try:
                    # Importar aquí para evitar dependencias circulares
                    from core.detector import detect_document
                    from core.enhancer import perspective_correct, enhance_document
                    from core.advanced_enhancer import enhanced_pipeline, assess_scan_quality

                    # Detección de documento (con calibración si está disponible)
                    from core.auto_calibrate import get_calibrator
                    cal = get_calibrator()
                    cal_dict_ss = None
                    if cal.is_calibrated:
                        p = cal.get_params()
                        cal_dict_ss = {
                            "canny_low": p.canny_low,
                            "canny_high": p.canny_high,
                            "gaussian_kernel": p.gaussian_kernel,
                            "approx_epsilon": p.approx_epsilon,
                            "min_area_ratio": p.min_area_ratio,
                        }

                    corners, _ = detect_document(canvas, calibrated_params=cal_dict_ss)
                    if corners is None:
                        h, w = canvas.shape[:2]
                        corners = np.array([
                            [0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]
                        ], dtype=np.float32)

                    # Corrección de perspectiva
                    corrected = perspective_correct(canvas, corners)

                    # Realce
                    output_mode = state.output_mode
                    if output_mode == "color":
                        enhanced, enhance_meta = enhanced_pipeline(
                            corrected, mode="color",
                            enable_shadow_removal=False,
                            enable_wrinkle_correction=False,
                            enable_color_restoration=True,
                        )
                    else:
                        enhanced = enhance_document(corrected, output_mode)
                        enhance_meta = {"steps": [output_mode], "improvement": 0}

                    # OCR
                    # Necesitamos importar _extract_best_invoice — pero está en web_server.py
                    # Para evitar dependencia circular, llamamos al extractor directamente
                    from ocr.extractor import extract_invoice_data
                    invoice = extract_invoice_data(enhanced, interactive=False)

                    # Si la confianza es baja, probar con la imagen sin filtrar
                    if corrected is not None and invoice.ocr_confidence < 0.55:
                        try:
                            alt = extract_invoice_data(corrected, interactive=False)
                            if alt.ocr_confidence > invoice.ocr_confidence:
                                invoice = alt
                        except Exception:
                            pass

                    # QR
                    from core.qr_scanner import detect_codes, cross_check_with_ocr
                    qr_codes = []
                    qr_notes = []
                    try:
                        qr_codes = detect_codes(corrected)
                        if not qr_codes:
                            qr_codes = detect_codes(enhanced)
                        if qr_codes:
                            qr_notes = cross_check_with_ocr(qr_codes, invoice.to_dict())
                    except Exception as qr_err:
                        self._log(f"  QR falló: {qr_err}")

                    # Codificar enhanced
                    _, enh_buffer = cv2.imencode('.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    enhanced_b64 = base64.b64encode(enh_buffer).decode('utf-8')

                    # Calidad
                    quality = {"score": 0.8, "level": "buena"}
                    try:
                        quality = assess_scan_quality(enhanced)
                    except Exception:
                        pass

                    ocr_data = invoice.to_dict()
                    ocr_data['raw_text'] = invoice.raw_text
                    all_validation = list(invoice.validation_errors) + qr_notes

                    # Guardar en historial
                    saved_invoice_id = None
                    try:
                        from utils.database import save_invoice
                        saved_invoice_id = save_invoice(
                            ocr_data=ocr_data,
                            validation_errors=all_validation,
                            ocr_confidence=invoice.ocr_confidence,
                            qr_data={"codes": qr_codes} if qr_codes else None,
                            source="z_async",
                            enhanced_image_b64=enhanced_b64,
                        )
                    except Exception as db_err:
                        self._log(f"  DB save falló: {db_err}")

                    result.update({
                        "enhanced_image": enhanced_b64,
                        "ocr_data": ocr_data,
                        "validation_errors": all_validation,
                        "ocr_confidence": round(invoice.ocr_confidence, 4),
                        "qr_codes": qr_codes,
                        "invoice_id": saved_invoice_id,
                        "quality": quality,
                    })

                except Exception as ocr_err:
                    self._log(f"  OCR pipeline falló: {ocr_err}")
                    import traceback
                    traceback.print_exc()
                    result["ocr_error"] = str(ocr_err)

            # Guardar resultado en la sesión
            with self._lock:
                state.final_result = result
                state.status = "completed"
                state.current_canvas = None  # Liberar memoria

            self._log(f"Sesión {session_id} finalizada ({canvas.shape[1]}x{canvas.shape[0]})")
            return result

        except Exception as e:
            import traceback
            traceback.print_exc()
            with self._lock:
                state.status = "failed"
                state.error = str(e)
            return {
                "success": False,
                "session_id": session_id,
                "error": str(e),
            }

    def delete_session(self, session_id: str) -> bool:
        """Elimina una sesión y sus archivos temporales."""
        with self._lock:
            state = self._sessions.pop(session_id, None)
            if not state:
                return False

        # Limpiar directorio de sesión
        shots_dir = os.path.join(self._temp_dir, f"session_{session_id}")
        if os.path.exists(shots_dir):
            import shutil
            try:
                shutil.rmtree(shots_dir)
            except Exception:
                pass

        self._log(f"Sesión {session_id} eliminada")
        return True

    def cleanup_expired(self) -> int:
        """Elimina sesiones inactivas por más de session_ttl segundos.

        Returns:
            Número de sesiones eliminadas.
        """
        now = time.time()
        expired = []
        with self._lock:
            for sid, state in list(self._sessions.items()):
                if state.status == "completed":
                    # Las completadas expiran más rápido (30 min)
                    if now - state.last_activity > 1800:
                        expired.append(sid)
                elif now - state.last_activity > self._session_ttl:
                    expired.append(sid)

        for sid in expired:
            self.delete_session(sid)

        if expired:
            self._log(f"Limpieza: {len(expired)} sesiones expiradas eliminadas")
        return len(expired)

    def list_active_sessions(self) -> List[dict]:
        """Lista todas las sesiones activas (resumen)."""
        with self._lock:
            return [
                {
                    "session_id": sid,
                    "status": s.status,
                    "total_shots": s.total_shots,
                    "received": len(s.shots),
                    "incremental_matched": s.incremental_matched,
                    "elapsed": round(time.time() - s.created_at, 1),
                    "created_at": datetime.fromtimestamp(s.created_at).isoformat(),
                    "last_activity": datetime.fromtimestamp(s.last_activity).isoformat(),
                }
                for sid, s in sorted(
                    self._sessions.items(),
                    key=lambda x: x[1].created_at,
                    reverse=True,
                )
            ]

    def _log(self, msg: str):
        log.info(msg)
        print(f"  [Session] {msg}")


# ── Singleton global ──

_session_manager: Optional[StitchingSessionManager] = None


def get_session_manager(temp_dir: Optional[str] = None) -> StitchingSessionManager:
    """Retorna la instancia global del StitchingSessionManager."""
    global _session_manager
    if _session_manager is None:
        if temp_dir is None:
            # Usar directorio temporal por defecto
            import tempfile as tf
            temp_dir = os.path.join(tf.gettempdir(), "nad_stitch_sessions")
        _session_manager = StitchingSessionManager(temp_dir)
    return _session_manager
