"""
Bloque 5 — Perspectiva + Realce tipo CamScanner
=================================================
Endereza el documento usando la transformación de perspectiva,
aplica CLAHE, umbral adaptativo y morfología para obtener
una imagen con aspecto de escáner de oficina.

Ofrece 3 modos de salida:
- "documento": Blanco y negro de alto contraste.
- "grises": Escala de grises limpia.
- "color": Con realce de contraste.
"""

import cv2
import numpy as np
from typing import Optional, Tuple

from utils.config import CONFIG


def perspective_correct(
    image: np.ndarray,
    corners: np.ndarray,
) -> np.ndarray:
    """
    Endereza el documento aplicando transformación de perspectiva.

    Args:
        image: Imagen BGR original.
        corners: Array (4, 2) con las 4 esquinas del documento
                 en orden: [TL, TR, BR, BL].

    Returns:
        Imagen enderezada (rectángulo perfecto).
    """
    if corners.shape != (4, 2):
        raise ValueError(f"Se esperaban 4 esquinas, got {corners.shape}")

    # Calcular dimensiones de destino
    # Ancho: máximo entre arista superior e inferior
    top_width = np.linalg.norm(corners[1] - corners[0])
    bottom_width = np.linalg.norm(corners[2] - corners[3])
    dst_width = max(int(top_width), int(bottom_width))

    # Alto: máximo entre arista izquierda y derecha
    left_height = np.linalg.norm(corners[3] - corners[0])
    right_height = np.linalg.norm(corners[2] - corners[1])
    dst_height = max(int(left_height), int(right_height))

    # Puntos de destino (rectángulo perfecto)
    dst_pts = np.array([
        [0, 0],
        [dst_width - 1, 0],
        [dst_width - 1, dst_height - 1],
        [0, dst_height - 1],
    ], dtype=np.float32)

    # Calcular y aplicar transformación
    M = cv2.getPerspectiveTransform(corners.astype(np.float32), dst_pts)
    corrected = cv2.warpPerspective(image, M, (dst_width, dst_height))

    print(f"  → Perspectiva corregida: {dst_width}×{dst_height} px")
    return corrected


def enhance_document(
    image: np.ndarray,
    mode: Optional[str] = None,
) -> np.ndarray:
    """
    Aplica realce a la imagen enderezada del documento.

    Args:
        image: Imagen BGR enderezada.
        mode: 'documento' (BN), 'grises', 'color', o 'limpio'.

    Returns:
        Imagen realzada.
    """
    cfg = CONFIG.enhance
    mode = mode or cfg.output_mode

    if mode == "color":
        return _enhance_color(image, cfg)
    elif mode == "grises":
        return _enhance_grayscale(image, cfg)
    elif mode == "limpio":
        return _enhance_clean(image, cfg)
    else:  # documento (BN)
        return _enhance_document(image, cfg)


def _enhance_clean(image: np.ndarray, cfg) -> np.ndarray:
    """Realce limpio: solo mejora suave de contraste sin binarización."""
    print("  → Modo: Limpio (sin binarización)")

    # CLAHE muy suave para equilibrar contraste
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    l = clahe.apply(l)

    lab = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    # Suavizado ligero
    enhanced = cv2.bilateralFilter(enhanced, 3, 30, 30)

    return enhanced


def _enhance_color(image: np.ndarray, cfg) -> np.ndarray:
    """Realce en color: CLAHE en canal L del LAB."""
    print("  → Modo: Color")

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=cfg.clahe_clip_limit,
        tileGridSize=cfg.clahe_grid_size,
    )
    l = clahe.apply(l)

    # Suavizar ruido de color
    a = cv2.bilateralFilter(a, 5, 10, 10)
    b = cv2.bilateralFilter(b, 5, 10, 10)

    lab = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    # Nitidez ligera (kernel más suave para evitar halos)
    # kernel original: [0,-0.5,0;-0.5,3,-0.5;0,-0.5,0] — demasiado agresivo
    kernel = np.array([
        [0, -0.25, 0],
        [-0.25, 1.5, -0.25],
        [0, -0.25, 0],
    ])
    enhanced = cv2.filter2D(enhanced, -1, kernel)

    # Reducción de ruido suave (bilateral preserva bordes)
    enhanced = cv2.bilateralFilter(enhanced, 3, 20, 20)

    return enhanced


def _enhance_grayscale(image: np.ndarray, cfg) -> np.ndarray:
    """Realce en escala de grises."""
    print("  → Modo: Escala de grises")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # CLAHE suave (clipLimit reducido para evitar realzar ruido)
    clahe = cv2.createCLAHE(
        clipLimit=max(0.5, cfg.clahe_clip_limit * 0.6),  # 60% del valor config
        tileGridSize=cfg.clahe_grid_size,
    )
    gray = clahe.apply(gray)

    # Suavizado preservando bordes
    gray = cv2.bilateralFilter(gray, 5, 20, 20)

    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _enhance_document(image: np.ndarray, cfg) -> np.ndarray:
    """Realce tipo documento: BN de alto contraste.
    
    NOTA: Se ha reducido la agresividad del procesamiento para evitar
    la sobre-edición que genera ruido en los contornos. El CLAHE ahora
    usa clipLimit más suave y el bloque adaptativo es más grande para
    evitar artefactos.
    """
    print("  → Modo: Documento (BN)")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 0. Reducción de ruido inicial (mediana suave antes de cualquier realce)
    gray = cv2.medianBlur(gray, 3)

    # 1. CLAHE suave para equilibrar contraste (clipLimit reducido 50%)
    clahe = cv2.createCLAHE(
        clipLimit=max(0.5, cfg.clahe_clip_limit * 0.5),
        tileGridSize=cfg.clahe_grid_size,
    )
    equalized = clahe.apply(gray)

    # 2. Umbral adaptativo gaussiano (block_size más grande = menos ruido)
    block_size = cfg.adaptive_block_size if cfg.adaptive_block_size % 2 == 1 else cfg.adaptive_block_size + 1
    block_size = max(15, block_size + 4)  # bloque más grande = menos fragmentación
    binary = cv2.adaptiveThreshold(
        equalized,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        max(2, cfg.adaptive_c - 2),  # C más bajo = menos sensibilidad a ruido
    )

    # 3. Morfología: kernel más pequeño para no dañar detalles finos
    kernel_size = max(1, cfg.morph_kernel_size - 1)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (kernel_size, kernel_size),
    )
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    # 4. Cerrar pequeños huecos en letras (solo si kernel > 1)
    if kernel_size > 1:
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)

    # 5. Suavizado final para eliminar bordes de píxeles aislados
    cleaned = cv2.medianBlur(cleaned, 3)

    return cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)


def auto_detect_mode(image: np.ndarray) -> str:
    """
    Detecta automáticamente el mejor modo de salida según el contenido.
    - Si el fondo es blanco (>80% de píxeles claros): 'documento'.
    - Si la imagen tiene poca saturación: 'grises'.
    - Si la imagen tiene color: 'color'.

    Args:
        image: Imagen BGR.

    Returns:
        Modo recomendado: 'documento', 'grises' o 'color'.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Porcentaje de píxeles claros
    light_pixels = np.sum(gray > 200) / gray.size

    # Saturación media
    mean_saturation = np.mean(hsv[:, :, 1])

    if light_pixels > 0.8:
        return "documento"
    elif mean_saturation < 30:
        return "grises"
    else:
        return "color"


if __name__ == "__main__":
    print("Módulo de realce NAD Scanner — ejecutar desde main.py")
