"""
πNAD — Calibration Profiles (Persistent per Document Type)
===========================================================
Almacena perfiles de calibración por tipo de documento en SQLite.
Después de calibrar N=5 documentos del mismo tipo (factura, id, libro, etc.),
el sistema aprende un perfil promedio y lo usa como default, evitando
recalibrar en cada nuevo documento del mismo tipo.

Flujo:
  1. Primera calibración de tipo X → se guarda como muestra #1
  2. ... muestras #2, #3, #4, #5 del mismo tipo X
  3. Al llegar a 5, se computa el perfil promedio y se activa como default
  4. Documentos siguientes del tipo X usan el perfil guardado (sin recalibrar)
  5. El usuario puede forzar recalibración con ?force=true

Estructura en SQLite (tabla calibration_profiles):
  - id, capture_mode, doc_type, calibration_count
  - avg_canny_low, avg_canny_high (average of all calibrations)
  - avg_gaussian_kernel, avg_approx_epsilon, avg_min_area_ratio
  - avg_contrast, avg_entropy, avg_detectability_score
  - last_canny_low, last_canny_high (most recent calibration)
  - last_stats JSON blob
  - created_at, updated_at, is_active
"""

import os
import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

from utils.config import CONFIG

DB_PATH = os.path.join(CONFIG.output_dir, "nadscanner.db")
_lock = threading.RLock()  # RLock, no Lock: varias funciones de este módulo
# se llaman entre sí mientras ya sostienen el lock (ej. list_tenants() ->
# get_tenant_usage_summary() -> _connect() de nuevo). Con un Lock normal
# (no reentrante) eso es un deadlock garantizado del mismo hilo esperando
# a sí mismo — se confirmó reproduciendo el cuelgue real en /api/admin/tenants.

# Umbral: después de cuántas calibraciones del mismo tipo se activa el perfil
PROFILE_MIN_SAMPLES = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_mode TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT '',
    calibration_count INTEGER NOT NULL DEFAULT 0,
    avg_canny_low REAL DEFAULT NULL,
    avg_canny_high REAL DEFAULT NULL,
    avg_gaussian_kernel_size INTEGER DEFAULT NULL,
    avg_approx_epsilon REAL DEFAULT NULL,
    avg_min_area_ratio REAL DEFAULT NULL,
    avg_contrast REAL DEFAULT NULL,
    avg_entropy REAL DEFAULT NULL,
    avg_detectability_score REAL DEFAULT NULL,
    last_canny_low INTEGER DEFAULT NULL,
    last_canny_high INTEGER DEFAULT NULL,
    last_stats TEXT DEFAULT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_calib_profile_mode ON calibration_profiles(capture_mode, doc_type);

CREATE TABLE IF NOT EXISTS calibration_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    capture_mode TEXT NOT NULL,
    doc_type TEXT DEFAULT '',
    canny_low INTEGER NOT NULL,
    canny_high INTEGER NOT NULL,
    gaussian_kernel_size INTEGER DEFAULT NULL,
    approx_epsilon REAL DEFAULT NULL,
    min_area_ratio REAL DEFAULT NULL,
    contrast REAL DEFAULT NULL,
    entropy REAL DEFAULT NULL,
    detectability_score REAL DEFAULT NULL,
    sharpness REAL DEFAULT NULL,
    ncc_self REAL DEFAULT NULL,
    stats_json TEXT DEFAULT NULL,
    calibrated_at TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES calibration_profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_calib_samples_mode ON calibration_samples(capture_mode);
CREATE INDEX IF NOT EXISTS idx_calib_samples_profile ON calibration_samples(profile_id);
"""


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_profiles_db():
    """Initialize calibration profiles tables. Safe to call multiple times."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # Safe migration: check if column exists
        cursor = conn.execute("PRAGMA table_info(calibration_samples)")
        col_names = {row[1] for row in cursor.fetchall()}
        if 'stats_json' not in col_names:
            try:
                conn.execute("ALTER TABLE calibration_samples ADD COLUMN stats_json TEXT DEFAULT NULL")
            except Exception:
                pass


# ── Profile CRUD ──────────────────────────────────────────────

def _get_or_create_profile(capture_mode: str, doc_type: str = "") -> int:
    """Get profile ID for (mode, doc_type) or create one."""
    init_profiles_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM calibration_profiles WHERE capture_mode = ? AND doc_type = ?",
            (capture_mode, doc_type),
        ).fetchone()
        if row:
            return row["id"]
        now = datetime.now().isoformat()
        cur = conn.execute(
            """INSERT INTO calibration_profiles
               (capture_mode, doc_type, calibration_count, created_at, updated_at)
               VALUES (?, ?, 0, ?, ?)""",
            (capture_mode, doc_type, now, now),
        )
        return cur.lastrowid


def save_calibration_sample(
    capture_mode: str,
    doc_type: str = "",
    canny_low: int = 50,
    canny_high: int = 150,
    gaussian_kernel_size: Optional[int] = 5,
    approx_epsilon: Optional[float] = 0.02,
    min_area_ratio: Optional[float] = 0.05,
    contrast: Optional[float] = None,
    entropy: Optional[float] = None,
    detectability_score: Optional[float] = None,
    sharpness: Optional[float] = None,
    ncc_self: Optional[float] = None,
    stats_dict: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Guarda una muestra de calibración y actualiza el perfil promedio.
    
    Args:
        capture_mode: Tipo de captura (factura, id, libro, foto, pizarra).
        doc_type: Subtipo opcional (ej. "térmica", "láser").
        canny_low: Umbral bajo de Canny calibrado.
        canny_high: Umbral alto de Canny calibrado.
        gaussian_kernel_size: Tamaño del kernel gaussiano.
        approx_epsilon: Epsilon de aproximación.
        min_area_ratio: Relación de área mínima.
        contrast: Contraste de la imagen.
        entropy: Entropía de la imagen.
        detectability_score: Puntaje de detectabilidad (0-1).
        sharpness: Nitidez (Laplacian variance).
        ncc_self: Auto-correlación NCC.
        stats_dict: Diccionario completo de estadísticas.
        
    Returns:
        Dict con el estado del perfil después de guardar.
    """
    init_profiles_db()
    profile_id = _get_or_create_profile(capture_mode, doc_type)
    now = datetime.now().isoformat()

    gk_size = gaussian_kernel_size
    if gk_size is None:
        gk_size = 5

    stats_json = json.dumps(stats_dict, ensure_ascii=False) if stats_dict else None

    with _connect() as conn:
        # Insert sample
        conn.execute(
            """INSERT INTO calibration_samples
               (profile_id, capture_mode, doc_type, canny_low, canny_high,
                gaussian_kernel_size, approx_epsilon, min_area_ratio,
                contrast, entropy, detectability_score, sharpness, ncc_self,
                stats_json, calibrated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, capture_mode, doc_type, canny_low, canny_high,
             gk_size, approx_epsilon, min_area_ratio,
             contrast, entropy, detectability_score, sharpness, ncc_self,
             stats_json, now),
        )

        # Count samples for this profile
        count = conn.execute(
            "SELECT COUNT(*) FROM calibration_samples WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()[0]

        # Recompute averages
        avg = conn.execute(
            """SELECT
                AVG(canny_low) as avg_low,
                AVG(canny_high) as avg_high,
                AVG(gaussian_kernel_size) as avg_gk,
                AVG(approx_epsilon) as avg_eps,
                AVG(min_area_ratio) as avg_mar,
                AVG(contrast) as avg_contrast,
                AVG(entropy) as avg_entropy,
                AVG(detectability_score) as avg_ds
               FROM calibration_samples WHERE profile_id = ?""",
            (profile_id,),
        ).fetchone()

        # Update profile
        is_active = 1 if count >= PROFILE_MIN_SAMPLES else 0
        conn.execute(
            """UPDATE calibration_profiles SET
               calibration_count = ?,
               avg_canny_low = ?, avg_canny_high = ?,
               avg_gaussian_kernel_size = ?, avg_approx_epsilon = ?, avg_min_area_ratio = ?,
               avg_contrast = ?, avg_entropy = ?, avg_detectability_score = ?,
               last_canny_low = ?, last_canny_high = ?,
               last_stats = ?,
               is_active = ?,
               updated_at = ?
               WHERE id = ?""",
            (count,
             round(avg["avg_low"], 1) if avg["avg_low"] else None,
             round(avg["avg_high"], 1) if avg["avg_high"] else None,
             round(avg["avg_gk"]) if avg["avg_gk"] else None,
             round(avg["avg_eps"], 4) if avg["avg_eps"] else None,
             round(avg["avg_mar"], 4) if avg["avg_mar"] else None,
             round(avg["avg_contrast"], 4) if avg["avg_contrast"] else None,
             round(avg["avg_entropy"], 4) if avg["avg_entropy"] else None,
             round(avg["avg_ds"], 4) if avg["avg_ds"] else None,
             canny_low, canny_high,
             stats_json,
             is_active,
             now,
             profile_id),
        )

        return {
            "profile_id": profile_id,
            "capture_mode": capture_mode,
            "doc_type": doc_type,
            "sample_count": count,
            "min_required": PROFILE_MIN_SAMPLES,
            "is_active": bool(is_active),
            "avg_canny_low": round(avg["avg_low"], 1) if avg["avg_low"] else None,
            "avg_canny_high": round(avg["avg_high"], 1) if avg["avg_high"] else None,
            "avg_gaussian_kernel_size": round(avg["avg_gk"]) if avg["avg_gk"] else None,
            "avg_approx_epsilon": round(avg["avg_eps"], 4) if avg["avg_eps"] else None,
            "avg_min_area_ratio": round(avg["avg_mar"], 4) if avg["avg_mar"] else None,
            "avg_detectability_score": round(avg["avg_ds"], 4) if avg["avg_ds"] else None,
        }


def get_active_profile(
    capture_mode: str,
    doc_type: str = "",
) -> Optional[Dict[str, Any]]:
    """Retorna el perfil activo para (mode, doc_type), o None si no hay suficientes muestras.
    
    Un perfil está activo solo si tiene >= PROFILE_MIN_SAMPLES muestras.
    """
    init_profiles_db()
    with _connect() as conn:
        row = conn.execute(
            """SELECT * FROM calibration_profiles
               WHERE capture_mode = ? AND doc_type = ? AND is_active = 1
               AND calibration_count >= ?""",
            (capture_mode, doc_type, PROFILE_MIN_SAMPLES),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("last_stats"):
            try:
                d["last_stats"] = json.loads(d["last_stats"])
            except (json.JSONDecodeError, TypeError):
                d["last_stats"] = None
        return d


def get_profile_status(
    capture_mode: str,
    doc_type: str = "",
) -> Dict[str, Any]:
    """Retorna el estado del perfil (incluso si no está activo aún).
    
    Útil para que el frontend muestre el progreso de calibración.
    """
    init_profiles_db()
    with _connect() as conn:
        row = conn.execute(
            """SELECT * FROM calibration_profiles
               WHERE capture_mode = ? AND doc_type = ?""",
            (capture_mode, doc_type),
        ).fetchone()
        if not row:
            return {
                "capture_mode": capture_mode,
                "doc_type": doc_type,
                "calibration_count": 0,
                "min_required": PROFILE_MIN_SAMPLES,
                "is_active": False,
                "has_profile": False,
            }
        d = dict(row)
        return {
            "has_profile": True,
            "capture_mode": d["capture_mode"],
            "doc_type": d["doc_type"],
            "calibration_count": d["calibration_count"],
            "min_required": PROFILE_MIN_SAMPLES,
            "is_active": bool(d["is_active"]),
            "profile_id": d["id"],
            "avg_canny_low": d["avg_canny_low"],
            "avg_canny_high": d["avg_canny_high"],
            "avg_gaussian_kernel_size": d["avg_gaussian_kernel_size"],
            "avg_approx_epsilon": d["avg_approx_epsilon"],
            "avg_min_area_ratio": d["avg_min_area_ratio"],
            "avg_contrast": d["avg_contrast"],
            "avg_entropy": d["avg_entropy"],
            "avg_detectability_score": d["avg_detectability_score"],
            "samples_needed": max(0, PROFILE_MIN_SAMPLES - d["calibration_count"]),
        }


def get_all_profiles() -> List[Dict[str, Any]]:
    """Lista todos los perfiles de calibración con su estado."""
    init_profiles_db()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM calibration_profiles ORDER BY updated_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_profile_samples(
    profile_id: int,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Retorna las muestras individuales de un perfil."""
    init_profiles_db()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM calibration_samples
               WHERE profile_id = ?
               ORDER BY calibrated_at DESC LIMIT ?""",
            (profile_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_profile(profile_id: int) -> bool:
    """Elimina un perfil y todas sus muestras."""
    init_profiles_db()
    with _connect() as conn:
        conn.execute("DELETE FROM calibration_samples WHERE profile_id = ?", (profile_id,))
        cur = conn.execute("DELETE FROM calibration_profiles WHERE id = ?", (profile_id,))
        return cur.rowcount > 0


def reset_profile(capture_mode: str, doc_type: str = "") -> bool:
    """Reinicia un perfil: elimina todas las muestras y lo desactiva."""
    init_profiles_db()
    profile_id = _get_or_create_profile(capture_mode, doc_type)
    with _connect() as conn:
        conn.execute("DELETE FROM calibration_samples WHERE profile_id = ?", (profile_id,))
        conn.execute(
            """UPDATE calibration_profiles SET
               calibration_count = 0,
               avg_canny_low = NULL, avg_canny_high = NULL,
               avg_gaussian_kernel_size = NULL, avg_approx_epsilon = NULL,
               avg_min_area_ratio = NULL, avg_contrast = NULL,
               avg_entropy = NULL, avg_detectability_score = NULL,
               last_canny_low = NULL, last_canny_high = NULL,
               last_stats = NULL,
               is_active = 0,
               updated_at = ? WHERE id = ?""",
            (datetime.now().isoformat(), profile_id),
        )
        return True


def update_detectability_ema(
    capture_mode: str,
    doc_type: str = "",
    new_score: float = 0.5,
    alpha: float = 0.20,
) -> Dict[str, Any]:
    """Actualiza el detectability_score del perfil con promedio ponderado
    exponencial (EMA): nuevo_score = alpha * nuevo + (1 - alpha) * anterior.

    Esto permite calibración continua: el perfil se adapta incrementalmente
    al tipo de documentos que el usuario escanea más frecuentemente, sin
    necesidad de recalibrar desde cero.

    Args:
        capture_mode: Tipo de captura (factura, id, libro, etc.).
        doc_type: Subtipo opcional.
        new_score: Nuevo detectability_score medido (0-1).
        alpha: Factor de aprendizaje (default 0.20 = 80% anterior + 20% nuevo).

    Returns:
        Dict con el estado actualizado del perfil, o un dict vacío
        si no existe perfil para este modo.
    """
    init_profiles_db()
    profile_id = _get_or_create_profile(capture_mode, doc_type)
    now = datetime.now().isoformat()

    with _connect() as conn:
        # Obtener valor actual
        row = conn.execute(
            "SELECT avg_detectability_score, calibration_count, is_active, last_stats "
            "FROM calibration_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()

        if not row:
            return {}

        current_avg = row["avg_detectability_score"]
        current_count = row["calibration_count"]
        is_active = bool(row["is_active"])

        # Calcular nuevo EMA
        if current_avg is not None and current_count > 0:
            # EMA: 80% anterior + 20% nuevo
            new_avg = round(current_avg * (1 - alpha) + new_score * alpha, 4)
        else:
            # Primer valor: usar el nuevo directamente
            new_avg = round(new_score, 4)

        # Incrementar contador (no es muestra de calibración completa, solo EMA)
        new_count = current_count + 1

        # Activar perfil automáticamente al llegar al umbral
        should_activate = (new_count >= PROFILE_MIN_SAMPLES and not is_active)

        # Decodificar last_stats para preservarlo
        current_stats = None
        if row["last_stats"]:
            try:
                current_stats = json.loads(row["last_stats"])
            except (json.JSONDecodeError, TypeError):
                current_stats = None

        # Agregar EMA info al stats
        ema_entry = {
            "ema_update_at": now,
            "ema_new_score": new_score,
            "ema_alpha": alpha,
            "ema_previous_avg": current_avg,
        }
        if current_stats and isinstance(current_stats, dict):
            ema_history = current_stats.get("ema_history", [])
            ema_history.append(ema_entry)
            if len(ema_history) > 100:  # límite de historial
                ema_history = ema_history[-100:]
            current_stats["ema_history"] = ema_history
            updated_stats_json = json.dumps(current_stats, ensure_ascii=False)
        else:
            updated_stats_json = json.dumps({"ema_history": [ema_entry]}, ensure_ascii=False)

        # Actualizar perfil
        conn.execute(
            """UPDATE calibration_profiles SET
               avg_detectability_score = ?,
               calibration_count = ?,
               last_stats = ?,
               is_active = ?,
               updated_at = ?
               WHERE id = ?""",
            (new_avg, new_count, updated_stats_json,
             1 if should_activate else (1 if is_active else 0),
             now, profile_id),
        )

        return {
            "profile_id": profile_id,
            "capture_mode": capture_mode,
            "doc_type": doc_type,
            "previous_avg_detectability": current_avg,
            "new_detectability": new_score,
            "updated_avg_detectability": new_avg,
            "alpha": alpha,
            "ema_updates_count": new_count,
            "is_active": should_activate or is_active,
        }


def get_profile_into_calibrated_params(
    capture_mode: str,
    doc_type: str = "",
) -> Optional[Dict[str, Any]]:
    """Retorna un dict de parámetros desde un perfil activo,
    compatible con el formato esperado por _get_calibrated_params()
    en web_server.py y detect_document().
    
    Returns:
        Dict con canny_low, canny_high, gaussian_kernel (tuple),
        approx_epsilon, min_area_ratio, source="profile", o None.
    """
    profile = get_active_profile(capture_mode, doc_type)
    if not profile:
        return None

    gk = profile.get("avg_gaussian_kernel_size")
    gaussian_kernel = (gk, gk) if gk else None

    return {
        "canny_low": int(round(profile["avg_canny_low"])) if profile.get("avg_canny_low") else None,
        "canny_high": int(round(profile["avg_canny_high"])) if profile.get("avg_canny_high") else None,
        "gaussian_kernel": gaussian_kernel,
        "approx_epsilon": profile.get("avg_approx_epsilon"),
        "min_area_ratio": profile.get("avg_min_area_ratio"),
        "source": "profile",
        "profile_id": profile["id"],
        "sample_count": profile["calibration_count"],
        "avg_detectability_score": profile.get("avg_detectability_score"),
    }
