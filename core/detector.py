"""
Bloque 4 — Detección de documento tipo CamScanner
===================================================
Dado un documento escaneado o fotografiado sobre un fondo contrastante,
encuentra el contorno del documento y devuelve las 4 esquinas.

Flujo:
1. Gris → Gaussiano → Canny → Contornos.
2. Selecciona el contorno más grande.
3. Simplifica a 4 vértices con approxPolyDP.
4. Valida que sea un cuadrilátero convexo.
5. Fallback: minAreaRect si no hay 4 puntos.

Nuevo en v3.0:
- detect_edges_live(): Edge detection rápido para overlay en preview en vivo
- compute_perspective_preview(): Warp preview de perspectiva para mostrar en ventana secundaria
- Parámetros adaptativos por modo de captura (factura/ID/libro/foto/pizarra)
"""

import cv2
import numpy as np
from typing import List, Optional, Tuple

from utils.config import CONFIG, CaptureMode


# ═══════════════════════════════════════════════════════════════
#  FUNCIONES EXISTENTES (v2.x)
# ═══════════════════════════════════════════════════════════════

def order_corners(pts: np.ndarray) -> np.ndarray:
    """
    Ordena 4 puntos en orden consistente:
    [arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda].

    Args:
        pts: Array de 4 puntos (x, y).

    Returns:
        Array reordenado de 4 puntos (x, y).
    """
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def get_mode_params(mode: Optional[CaptureMode] = None) -> dict:
    """
    Retorna los parámetros de detección para el modo de captura activo.

    Args:
        mode: Modo de captura (None = usar el de CONFIG).

    Returns:
        Dict con: canny_low, canny_high, gaussian_kernel, min_area_ratio,
                  approx_epsilon, edge_color.
    """
    if mode is None:
        mode = CONFIG.capture.mode
    return CONFIG.detector.mode_params.get(mode.value, CONFIG.detector.mode_params["factura"])


def detect_document(
    image: np.ndarray,
    min_area_ratio: Optional[float] = None,
    mode: Optional[CaptureMode] = None,
    calibrated_params: Optional[dict] = None,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Detecta el documento más grande en la imagen y devuelve sus 4 esquinas.
    Usa parámetros adaptativos según el modo de captura activo.

    Args:
        image: Imagen BGR.
        min_area_ratio: Fracción mínima del área de la imagen que debe cubrir
                        el contorno para ser considerado documento.
                        None = usar el del modo activo (o calibrado).
        mode: Modo de captura a usar para esta llamada específica. None =
              usar CONFIG.capture.mode (comportamiento anterior). Pasar un
              modo explícito evita mutar el CONFIG global — importante en
              un servidor que puede atender requests concurrentes con
              distinto capture_mode cada una.
        calibrated_params: Dict opcional con thresholds calibrados por
              AutoCalibrator. Si se provee, estos valores tienen prioridad
              sobre los del modo activo. Keys:
                canny_low, canny_high, gaussian_kernel, approx_epsilon,
                min_area_ratio

    Returns:
        (corners_ordered, contour)
        - corners_ordered: Array (4, 2) con esquinas ordenadas, o None si no se detectó.
        - contour: Contorno original (para depuración), o None.
    """
    mode_params = get_mode_params(mode)
    cfg = CONFIG.detector
    h, w = image.shape[:2]
    img_area = h * w

    # Prioridad: calibrated_params > mode_params > cfg.default
    def _p(key, fallback):
        if calibrated_params and key in calibrated_params and calibrated_params[key] is not None:
            return calibrated_params[key]
        return mode_params.get(key, fallback)

    if min_area_ratio is None:
        min_area_ratio = _p("min_area_ratio", 0.05)

    # 1. Escala de grises
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 2. Desenfoque gaussiano (según modo o calibración)
    kernel = _p("gaussian_kernel", cfg.gaussian_kernel)
    blurred = cv2.GaussianBlur(gray, kernel, 0)

    # 3. Detección de bordes Canny (según modo o calibración)
    canny_low = _p("canny_low", cfg.canny_low)
    canny_high = _p("canny_high", cfg.canny_high)
    edges = cv2.Canny(blurred, canny_low, canny_high)

    # 4. Encontrar contornos externos
    result = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(result) == 3:
        _, contours, _ = result
    else:
        contours, _ = result

    if not contours:
        return None, None

    # 5. Ordenar por área descendente
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    # 6. Buscar el primer contorno que sea un cuadrilátero válido
    best_contour = None
    best_corners = None
    approx_epsilon = mode_params.get("approx_epsilon", cfg.approx_epsilon_percent)

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < img_area * min_area_ratio:
            continue

        peri = cv2.arcLength(contour, True)
        # approx_epsilon: prioridad calibrado > modo > cfg
        epsilon_val = _p("approx_epsilon", cfg.approx_epsilon_percent)
        epsilon = epsilon_val * peri
        approx = cv2.approxPolyDP(contour, epsilon, True)

        if len(approx) == 4:
            if cv2.isContourConvex(approx):
                best_contour = contour
                best_corners = order_corners(approx.reshape(4, 2))
                break

    # 7. Fallback: minAreaRect
    if best_corners is None and contours:
        largest = contours[0]
        area = cv2.contourArea(largest)
        if area > img_area * min_area_ratio:
            rect = cv2.minAreaRect(largest)
            box = cv2.boxPoints(rect)
            box = np.int32(box)
            best_corners = order_corners(box.astype(np.float32))
            best_contour = largest

    return best_corners, best_contour


# ═══════════════════════════════════════════════════════════════
#  NUEVO EN v3.0: Edge Detection en VIVO para overlay
# ═══════════════════════════════════════════════════════════════

def detect_edges_live(
    gray: np.ndarray,
    mode: Optional[CaptureMode] = None,
) -> np.ndarray:
    """
    Edge detection optimizado para preview en vivo.

    A diferencia de detect_document(), esta función:
    - No busca contornos ni cuadriláteros (es más rápida)
    - Retorna directamente el mapa de bordes Canny
    - Usa desenfoque más ligero para mantener velocidad
    - Parámetros adaptativos según modo

    Args:
        gray: Frame en escala de grises.
        mode: Modo de captura (None = usar el activo).

    Returns:
        Mapa de bordes (imagen binaria uint8, 0 y 255).
    """
    mode_params = get_mode_params(mode)
    kernel = mode_params.get("gaussian_kernel", (5, 5))
    canny_low = mode_params.get("canny_low", 50)
    canny_high = mode_params.get("canny_high", 150)

    # Desenfoque rápido (GaussianBlur con kernel pequeño)
    blurred = cv2.GaussianBlur(gray, kernel, 0)

    # Canny
    edges = cv2.Canny(blurred, canny_low, canny_high)

    # Dilatar bordes ligeramente para que sean más visibles en el overlay
    kernel_dilate = np.ones((2, 2), np.uint8)
    edges = cv2.dilate(edges, kernel_dilate, iterations=1)

    return edges


def render_edge_overlay(
    frame: np.ndarray,
    edges: np.ndarray,
    color: Optional[Tuple[int, int, int]] = None,
    opacity: Optional[float] = None,
) -> np.ndarray:
    """
    Superpone el mapa de bordes como overlay semitransparente sobre el frame.

    Args:
        frame: Frame BGR original.
        edges: Mapa de bordes binario (0 y 255).
        color: Color BGR del overlay. None = usar el del modo activo.
        opacity: Opacidad (0-1). None = usar CONFIG.

    Returns:
        Frame con overlay de bordes.
    """
    mode_params = get_mode_params()
    if color is None:
        color = mode_params.get("edge_color", (0, 255, 0))
    if opacity is None:
        opacity = CONFIG.capture.edge_overlay_opacity

    # Crear máscara de 3 canales con el color deseado donde hay bordes
    colored_edges = np.zeros_like(frame)
    colored_edges[edges > 0] = color

    # Mezclar: overlay = frame * (1 - opacity) + colored_edges * opacity
    # Pero solo donde hay bordes, el resto queda igual
    mask = (edges > 0).astype(np.float32)
    mask_3c = np.stack([mask] * 3, axis=-1)

    result = (frame.astype(np.float32) * (1 - mask_3c * opacity) +
              colored_edges.astype(np.float32) * mask_3c * opacity)
    result = np.clip(result, 0, 255).astype(np.uint8)

    return result


# ═══════════════════════════════════════════════════════════════
#  NUEVO EN v3.0: Preview de Perspectiva en VIVO
# ═══════════════════════════════════════════════════════════════

def compute_perspective_preview(
    frame: np.ndarray,
    corners: np.ndarray,
    max_width: Optional[int] = None,
) -> Optional[np.ndarray]:
    """
    Calcula la corrección de perspectiva del documento detectado y
    redimensiona la preview para mostrarla en una ventana secundaria.

    Args:
        frame: Frame BGR original.
        corners: Array (4, 2) con esquinas ordenadas del documento.
        max_width: Ancho máximo de salida. None = usar CONFIG.

    Returns:
        Imagen warp (enderezada y redimensionada), o None si falló.
    """
    if corners is None or len(corners) != 4:
        return None

    if max_width is None:
        max_width = CONFIG.capture.perspective_preview_width

    # Calcular dimensiones de destino
    top_w = np.linalg.norm(corners[1] - corners[0])
    bot_w = np.linalg.norm(corners[2] - corners[3])
    dst_w = max(int(top_w), int(bot_w))

    left_h = np.linalg.norm(corners[3] - corners[0])
    right_h = np.linalg.norm(corners[2] - corners[1])
    dst_h = max(int(left_h), int(right_h))

    if dst_w < 10 or dst_h < 10:
        return None

    # Puntos destino
    dst_pts = np.array([
        [0, 0],
        [dst_w - 1, 0],
        [dst_w - 1, dst_h - 1],
        [0, dst_h - 1],
    ], dtype=np.float32)

    # Calcular warp
    M = cv2.getPerspectiveTransform(corners.astype(np.float32), dst_pts)
    warped = cv2.warpPerspective(frame, M, (dst_w, dst_h))

    # Redimensionar si es más ancho que max_width
    if dst_w > max_width:
        scale = max_width / dst_w
        new_w = int(dst_w * scale)
        new_h = int(dst_h * scale)
        warped = cv2.resize(warped, (new_w, new_h))

    return warped


def draw_detection(
    image: np.ndarray,
    corners: np.ndarray,
    contour: Optional[np.ndarray] = None,
    color: Tuple[int, int, int] = (0, 255, 0),
) -> np.ndarray:
    """
    Dibuja la detección del documento sobre la imagen (para depuración).

    Args:
        image: Imagen original.
        corners: 4 esquinas del documento.
        contour: Contorno original (opcional).
        color: Color BGR de las líneas.

    Returns:
        Imagen con overlay de detección.
    """
    overlay = image.copy()

    # Dibujar contorno
    if contour is not None:
        cv2.drawContours(overlay, [contour], -1, color, 2)

    # Dibujar esquinas
    for i, (x, y) in enumerate(corners.astype(int)):
        cv2.circle(overlay, (x, y), 8, (0, 0, 255), -1)
        cv2.putText(overlay, str(i), (x - 15, y - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    # Dibujar líneas entre esquinas
    for i in range(4):
        p1 = corners[i].astype(int)
        p2 = corners[(i + 1) % 4].astype(int)
        cv2.line(overlay, p1, p2, (255, 0, 0), 3)

    return overlay


if __name__ == "__main__":
    print("Módulo de detección NAD Scanner v3.0 — ejecutar desde main.py")
