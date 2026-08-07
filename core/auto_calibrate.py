"""
πNAD Scanner — Auto Calibration Module
========================================
Analiza la primera toma de un documento y ajusta dinámicamente
los thresholds de detección (Canny, Gauss, approx_epsilon) en
lugar de usar valores fijos.

Flujo:
  1. Primera captura → se envía a /calibrate
  2. Servidor analiza la imagen: contraste, entropía, gradiente,
     NCC auto-correlación de la región central
  3. Computa un "detectability score" y genera thresholds calibrados
  4. Los thresholds se almacenan en el AutoCalibrator (singleton
     por sesión) y se aplican en detect_document() como overrides

Esto reemplaza el sistema de parámetros fijos por modo de captura
con valores adaptativos al documento específico. Un documento
de alto contraste (factura impresa) recibe thresholds más estrictos;
uno de bajo contraste (recibo térmico desvaído) recibe tolerancia extra.

Uso:
    from core.auto_calibrate import get_calibrator
    cal = get_calibrator()
    cal.calibrate(first_shot_image)  # primera toma
    params = cal.get_params()        # thresholds calibrados
"""

import math
import time
import uuid
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

import cv2
import numpy as np

from utils.calibration_profiles import (
    save_calibration_sample,
    get_profile_into_calibrated_params,
    get_profile_status,
    update_detectability_ema,
)

log = logging.getLogger('nad.auto_calibrate')


# ══════════════════════════════════════════════════════════════
#  Data classes
# ══════════════════════════════════════════════════════════════

@dataclass
class CalibrationParams:
    """Parámetros de detección calibrados dinámicamente.

    Todos los valores son sobreescribibles: si un valor es None,
    se usa el valor por defecto de DetectorConfig (modo-specific).
    """
    canny_low: Optional[int] = None
    canny_high: Optional[int] = None
    gaussian_kernel: Optional[Tuple[int, int]] = None
    approx_epsilon: Optional[float] = None
    min_area_ratio: Optional[float] = None
    ncc_overlap_ok: Optional[float] = None     # Para UI frontend
    ncc_overlap_warn: Optional[float] = None   # Para UI frontend


@dataclass
class CalibrationStats:
    """Estadísticas extraídas de la imagen de calibración."""
    contrast: float = 0.0           # RMS contrast (0-1)
    entropy: float = 0.0            # Image entropy
    gradient_mean: float = 0.0      # Mean gradient magnitude
    gradient_std: float = 0.0       # Std of gradient magnitude
    ncc_self: float = 0.0           # NCC self-correlation (0-1)
    brightness: float = 0.0         # Mean brightness (0-255)
    sharpness: float = 0.0          # Laplacian variance (blur measure)
    resolution: Tuple[int, int] = (0, 0)
    detectability_score: float = 0.0  # 0=hard, 1=easy
    calibrated_at: float = 0.0


# ══════════════════════════════════════════════════════════════
#  Core calibration logic
# ══════════════════════════════════════════════════════════════

def _compute_ncc_self(gray: np.ndarray) -> float:
    """Computa NCC auto-correlación: divide la imagen en mitades
    izquierda/derecha y calcula la correlación normalizada entre ambas.

    Un documento homogéneo (fondo blanco liso) da NCC bajo (~0.2-0.4).
    Un documento con textura (factura impresa, texto denso) da NCC alto
    (~0.6-0.9).

    Returns:
        NCC score en [0, 1], donde 1 = máxima correlación.
    """
    h, w = gray.shape
    mid = w // 2

    left = gray[:, :mid]
    right = gray[:, mid:mid + mid] if mid * 2 <= w else gray[:, mid:]

    if left.size == 0 or right.size == 0:
        return 0.5

    # Redimensionar al mismo tamaño si es necesario
    if left.shape != right.shape:
        rh, rw = right.shape
        left = cv2.resize(left, (rw, rh))

    # Normalizar
    left_f = left.astype(np.float32)
    right_f = right.astype(np.float32)

    l_mean = np.mean(left_f)
    r_mean = np.mean(right_f)

    l_centered = left_f - l_mean
    r_centered = right_f - r_mean

    num = np.sum(l_centered * r_centered)
    den = np.sqrt(np.sum(l_centered ** 2) * np.sum(r_centered ** 2))

    if den < 1e-8:
        return 0.5

    ncc = num / den
    return max(0.0, min(1.0, (ncc + 1.0) / 2.0))


def _compute_sharpness(gray: np.ndarray) -> float:
    """Estima la nitidez/blur usando varianza del Laplaciano.

    Returns:
        Valor de nitidez: >500 = sharp, 100-500 = ok, <100 = blurry.
    """
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def _compute_contrast(gray: np.ndarray) -> float:
    """RMS contrast: std / max_possible.

    Returns:
        Contraste normalizado en [0, 1].
    """
    std = np.std(gray)
    return min(1.0, std / 128.0)


def _compute_entropy(gray: np.ndarray) -> float:
    """Entropía de la imagen (medida de complejidad/textura).

    Returns:
        Entropía normalizada en [0, 1].
    """
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    hist = hist.flatten()
    hist = hist[hist > 0]
    hist = hist / hist.sum()
    entropy = -np.sum(hist * np.log2(hist))
    # Máxima entropía para 8-bit es 8.0
    return min(1.0, entropy / 8.0)


def _compute_gradient_stats(gray: np.ndarray) -> Tuple[float, float]:
    """Magnitud del gradiente (Sobel) — mide qué tan definidos
    están los bordes en la imagen.

    Returns:
        (mean, std) de la magnitud del gradiente.
    """
    sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    magnitude = np.sqrt(sobel_x ** 2 + sobel_y ** 2)
    return float(np.mean(magnitude)), float(np.std(magnitude))


def _calibrate_from_stats(stats: CalibrationStats) -> CalibrationParams:
    """Convierte estadísticas de imagen en thresholds calibrados.

    La lógica:
      - Alto detectability (documento claro, nítido, buen contraste):
        thresholds ESTRICTOS (Canny alto, poco blur, epsilon pequeño)
      - Bajo detectability (documento borroso, bajo contraste):
        thresholds TOLERANTES (Canny bajo, más blur, epsilon grande)

    Esto asegura que documentos fáciles se detecten preciso y
    documentos difíciles no se pierdan por thresholds muy ajustados.
    """
    ds = stats.detectability_score  # 0=hard, 1=easy

    # ── Canny: mapeo lineal de detectability a thresholds ──
    #   ds=0.0 (muy difícil) → canny_low=20,  canny_high=80
    #   ds=0.5 (normal)      → canny_low=50,  canny_high=150
    #   ds=1.0 (muy fácil)   → canny_low=80,  canny_high=220
    canny_low = max(15, min(100, int(20 + ds * 60)))
    canny_high = max(60, min(250, int(80 + ds * 140)))

    # ── Gaussian kernel: más blur para documentos difíciles ──
    #   ds baja → kernel grande (más desenfoque, menos ruido)
    #   ds alta → kernel pequeño (preserva bordes finos)
    if ds < 0.3:
        ksize = 7
    elif ds < 0.6:
        ksize = 5
    else:
        ksize = 3
    gaussian_kernel = (ksize, ksize)

    # ── approx_epsilon: más tolerante para docs difíciles ──
    #   ds baja → epsilon grande (contornos más suaves)
    #   ds alta → epsilon pequeño (contornos precisos)
    approx_epsilon = max(0.01, min(0.04, 0.03 - ds * 0.015))

    # ── min_area_ratio: docs difíciles pueden ocupar menos ──
    min_area_ratio = max(0.02, 0.08 - ds * 0.05)

    # ── NCC overlap thresholds para frontend ──
    #   Docs con textura clara → NCC alto natural → thresholds más estrictos
    #   Docs lisos/degradados → NCC bajo → más tolerancia
    ncc_overlap_ok = max(0.15, 0.30 - (ds - 0.5) * 0.15)
    ncc_overlap_warn = max(0.08, 0.18 - (ds - 0.5) * 0.10)

    return CalibrationParams(
        canny_low=canny_low,
        canny_high=canny_high,
        gaussian_kernel=gaussian_kernel,
        approx_epsilon=approx_epsilon,
        min_area_ratio=min_area_ratio,
        ncc_overlap_ok=round(ncc_overlap_ok, 3),
        ncc_overlap_warn=round(ncc_overlap_warn, 3),
    )


def analyze_image(image: np.ndarray) -> CalibrationStats:
    """Analiza una imagen y extrae estadísticas completas.

    Args:
        image: Imagen BGR (primera toma del documento).

    Returns:
        CalibrationStats con todas las métricas.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = image.shape[:2]

    contrast = _compute_contrast(gray)
    entropy = _compute_entropy(gray)
    gradient_mean, gradient_std = _compute_gradient_stats(gray)
    ncc_self = _compute_ncc_self(gray)
    sharpness = _compute_sharpness(gray)
    brightness = float(np.mean(gray))

    # ── Detectability Score ──
    #   Combina varias métricas con pesos. Score alto = documento fácil
    #   de detectar (bordes claros, buen contraste, textura suficiente).
    #
    #   Pesos:
    #     - contrast:      0.25  — alto contraste = fácil
    #     - entropy:       0.20  — más textura = más features
    #     - gradient_mean: 0.25  — bordes definidos
    #     - ncc_self:      0.15  — auto-correlación (textura)
    #     - sharpness:     0.15  — nitidez (anti-blur)
    #
    #   Escala: 0.0 = imposible de detectar, 1.0 = trivially easy.

    # Normalizar gradient_mean a [0, 1] (valor típico 0-30)
    grad_norm = min(1.0, gradient_mean / 30.0)

    # Normalizar sharpness a [0, 1] (típico 0-1000)
    sharp_norm = min(1.0, sharpness / 500.0)

    ds = (
        contrast * 0.25 +
        entropy * 0.20 +
        grad_norm * 0.25 +
        ncc_self * 0.15 +
        sharp_norm * 0.15
    )
    ds = max(0.0, min(1.0, ds))

    log.info(
        f"📊 Calibración: contraste={contrast:.2f}, "
        f"entropía={entropy:.2f}, gradiente={grad_norm:.2f}, "
        f"NCC={ncc_self:.2f}, nitidez={sharp_norm:.2f}, "
        f"score={ds:.3f}"
    )

    return CalibrationStats(
        contrast=round(contrast, 4),
        entropy=round(entropy, 4),
        gradient_mean=round(gradient_mean, 2),
        gradient_std=round(gradient_std, 2),
        ncc_self=round(ncc_self, 4),
        brightness=round(brightness, 1),
        sharpness=round(sharpness, 1),
        resolution=(w, h),
        detectability_score=round(ds, 4),
        calibrated_at=time.time(),
    )


# ══════════════════════════════════════════════════════════════
#  Auto Calibrator (singleton por sesión)
# ══════════════════════════════════════════════════════════════

class AutoCalibrator:
    """Calibra thresholds de detección dinámicamente basado en
    el análisis de la primera toma del documento.

    Thread-safe (read-only después de calibrate()).

    Extiende con perfiles persistentes: después de N=5 calibraciones
    del mismo tipo de documento (factura, id, libro, etc.), aprende
    un perfil promedio que se reutiliza automáticamente sin recalibrar
    en cada nuevo documento del mismo tipo.
    """

    def __init__(self):
        self._calibrated = False
        self._stats: Optional[CalibrationStats] = None
        self._params: Optional[CalibrationParams] = None
        self._session_id: str = ""
        self._ref_image: Optional[np.ndarray] = None
        self._capture_mode: str = "factura"
        self._profile_used: bool = False

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    def set_capture_mode(self, mode: str):
        """Establece el modo de captura actual (factura, id, libro, etc.)."""
        self._capture_mode = mode

    def try_load_profile(self, capture_mode: str, doc_type: str = "") -> Optional[Dict]:
        """
        Intenta cargar un perfil activo para este tipo de documento.
        Si existe un perfil con >= PROFILE_MIN_SAMPLES muestras,
        establece los parámetros calibrados desde el perfil guardado
        y evita recalibrar.

        Returns:
            Dict con parámetros del perfil, o None si no hay perfil activo.
        """
        profile_params = get_profile_into_calibrated_params(capture_mode, doc_type)
        if profile_params:
            self._capture_mode = capture_mode
            self._params = CalibrationParams(
                canny_low=profile_params["canny_low"],
                canny_high=profile_params["canny_high"],
                gaussian_kernel=profile_params.get("gaussian_kernel"),
                approx_epsilon=profile_params.get("approx_epsilon"),
                min_area_ratio=profile_params.get("min_area_ratio"),
            )
            self._calibrated = True
            self._profile_used = True
            self._session_id = f"profile_{profile_params.get('profile_id', '?')}"
            print(f"  [Calibrate] Perfil cargado para '{capture_mode}': "
                  f"Canny=({profile_params['canny_low']},{profile_params['canny_high']}), "
                  f"Gauss={profile_params.get('gaussian_kernel')}, "
                  f"{profile_params.get('sample_count', 0)} muestras")
            return profile_params
        self._profile_used = False
        return None

    def calibrate(self, image: np.ndarray) -> CalibrationParams:
        """Ejecuta calibración completa sobre una imagen.

        Args:
            image: Imagen BGR de la primera toma.

        Returns:
            CalibrationParams con thresholds ajustados.
        """
        self._session_id = uuid.uuid4().hex[:8]
        self._ref_image = image.copy()
        self._stats = analyze_image(image)
        self._params = _calibrate_from_stats(self._stats)
        self._calibrated = True
        self._profile_used = False

        print(f"  [Calibrate] Sesión {self._session_id}: "
              f"score={self._stats.detectability_score:.3f}, "
              f"Canny=({self._params.canny_low},{self._params.canny_high}), "
              f"Gauss={self._params.gaussian_kernel}")

        # Guardar muestra en perfil persistente
        self._save_profile_sample()

        return self._params

    def _save_profile_sample(self):
        """Guarda la muestra de calibración actual en el perfil persistente.
        Después de 5 muestras del mismo tipo, el perfil se activa
        automáticamente y se reutiliza sin recalibrar.
        """
        if not self._stats or not self._params:
            return
        try:
            gk = self._params.gaussian_kernel
            gk_size = gk[0] if gk and len(gk) >= 1 else None

            stats_dict = {
                "contrast": self._stats.contrast,
                "entropy": self._stats.entropy,
                "sharpness": self._stats.sharpness,
                "ncc_self": self._stats.ncc_self,
                "gradient_mean": self._stats.gradient_mean,
                "brightness": self._stats.brightness,
                "resolution": list(self._stats.resolution),
            }

            result = save_calibration_sample(
                capture_mode=self._capture_mode,
                doc_type="",
                canny_low=self._params.canny_low or 50,
                canny_high=self._params.canny_high or 150,
                gaussian_kernel_size=gk_size,
                approx_epsilon=self._params.approx_epsilon,
                min_area_ratio=self._params.min_area_ratio,
                contrast=self._stats.contrast,
                entropy=self._stats.entropy,
                detectability_score=self._stats.detectability_score,
                sharpness=self._stats.sharpness,
                ncc_self=self._stats.ncc_self,
                stats_dict=stats_dict,
            )

            if result.get("is_active"):
                print(f"  [Calibrate] Perfil '{self._capture_mode}' ACTIVADO "
                      f"({result['sample_count']} muestras, "
                      f"Canny={result['avg_canny_low']}/{result['avg_canny_high']})")
            else:
                needed = result["min_required"] - result["sample_count"]
                print(f"  [Calibrate] Perfil '{self._capture_mode}': "
                      f"{result['sample_count']}/{result['min_required']} muestras "
                      f"(faltan {needed} para activar)")
        except Exception as e:
            print(f"  [Calibrate] [WARN] No se pudo guardar muestra: {e}")

    def get_params(self) -> CalibrationParams:
        if not self._calibrated or self._params is None:
            return CalibrationParams()
        return self._params

    def get_stats(self) -> Optional[CalibrationStats]:
        return self._stats

    def get_session_id(self) -> str:
        return self._session_id

    @property
    def profile_used(self) -> bool:
        """True si los parámetros actuales vienen de un perfil guardado."""
        return self._profile_used

    def to_dict(self) -> dict:
        params_dict = {}
        if self._params:
            params_dict = {
                "canny_low": self._params.canny_low,
                "canny_high": self._params.canny_high,
                "gaussian_kernel": list(self._params.gaussian_kernel)
                    if self._params.gaussian_kernel else None,
                "approx_epsilon": self._params.approx_epsilon,
                "min_area_ratio": self._params.min_area_ratio,
                "ncc_overlap_ok": self._params.ncc_overlap_ok,
                "ncc_overlap_warn": self._params.ncc_overlap_warn,
            }

        stats_dict = {}
        if self._stats:
            stats_dict = {
                "contrast": self._stats.contrast,
                "entropy": self._stats.entropy,
                "gradient_mean": self._stats.gradient_mean,
                "ncc_self": self._stats.ncc_self,
                "sharpness": self._stats.sharpness,
                "detectability_score": self._stats.detectability_score,
                "resolution": list(self._stats.resolution),
            }

        profile_status = {}
        try:
            profile_status = get_profile_status(self._capture_mode)
        except Exception:
            pass

        return {
            "calibrated": self._calibrated,
            "session_id": self._session_id,
            "profile_used": self._profile_used,
            "capture_mode": self._capture_mode,
            "stats": stats_dict,
            "params": params_dict,
            "profile": profile_status,
        }

    def update_continuous_calibration(
        self,
        image: np.ndarray,
        capture_mode: Optional[str] = None,
        alpha: float = 0.20,
    ) -> Optional[Dict]:
        """Actualiza la calibración continua después de un escaneo exitoso.

        Mide el detectability_score de la imagen procesada (fusión final)
        y actualiza el perfil persistente con EMA:
            nuevo_avg = (1-alpha) * avg_anterior + alpha * nuevo_score

        Esto permite que el detector se adapte incrementalmente al tipo
        de documentos que el usuario escanea más frecuentemente, sin
        necesidad de recalibrar desde cero.

        Args:
            image: Imagen fusionada/procesada (BGR).
            capture_mode: Modo de captura. Si es None, usa el actual.
            alpha: Factor de aprendizaje (0.20 = 80% anterior + 20% nuevo).

        Returns:
            Dict con resultado de la EMA update, o None si falla.
        """
        mode = capture_mode or self._capture_mode
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

            # Medir métricas como en analyze_image() pero más ligero
            contrast = _compute_contrast(gray)
            entropy = _compute_entropy(gray)
            grad_mean, _ = _compute_gradient_stats(gray)
            ncc_self = _compute_ncc_self(gray)
            sharpness = _compute_sharpness(gray)

            grad_norm = min(1.0, grad_mean / 30.0)
            sharp_norm = min(1.0, sharpness / 500.0)

            ds = (
                contrast * 0.25 +
                entropy * 0.20 +
                grad_norm * 0.25 +
                ncc_self * 0.15 +
                sharp_norm * 0.15
            )
            ds = max(0.0, min(1.0, ds))

            result = update_detectability_ema(
                capture_mode=mode,
                doc_type="",
                new_score=ds,
                alpha=alpha,
            )

            if result:
                log.info(
                    f"📈 Calibración continua '{mode}': "
                    f"nuevo_score={ds:.3f}, "
                    f"avg_anterior={result.get('previous_avg_detectability', 'N/A')}, "
                    f"avg_actualizado={result.get('updated_avg_detectability', 'N/A')}, "
                    f"actualizaciones={result.get('ema_updates_count', 0)}"
                )

            return result
        except Exception as e:
            log.warning(f"[WARN] Calibración continua falló: {e}")
            return None

    def reset(self):
        self._calibrated = False
        self._stats = None
        self._params = None
        self._ref_image = None
        self._session_id = ""
        self._profile_used = False
        self._capture_mode = "factura"


# ── Singleton por sesión ──
# En un servidor multi-request, esto debería ser un dict keyed by
# session_id. Para el pipeline síncrono simple, un singleton alcanza.

_calibrator: Optional[AutoCalibrator] = None


def get_calibrator() -> AutoCalibrator:
    """Retorna la instancia global del AutoCalibrator."""
    global _calibrator
    if _calibrator is None:
        _calibrator = AutoCalibrator()
    return _calibrator


def reset_calibrator():
    """Reinicia el calibrador global (nuevo documento)."""
    global _calibrator
    if _calibrator is not None:
        _calibrator.reset()
