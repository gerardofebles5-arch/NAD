"""
Bloque 1 — Captura múltiple tipo PhotoScan v3.0
==================================================
Implementación mejorada del sistema de captura multi-toma.

NUEVO EN v3.0:
  ✅ 5 modos de captura seleccionables (factura/ID/libro/foto/pizarra)
  ✅ Edge detection en vivo (overlay semitransparente sobre preview)
  ✅ Preview de perspectiva en ventana secundaria (tiempo real)
  ✅ Parámetros de detección adaptativos por modo
  ✅ Overlay con color distinto por modo
  ✅ Modo ID: detección de bordes más fina para documentos pequeños
  ✅ Modo PIZARRA: detección de bordes de alto contraste
  ✅ Indicador de modo en pantalla con atajos de teclado

FUNCIONALIDADES CLAVE (v2.x heredadas):
  ✅ Detección de movimiento por frame-difference (estabilidad)
  ✅ Score de alineación por correlación de plantilla (no bordes)
  ✅ Auto-capture solo cuando cámara ESTÁ QUIETA + alineada
  ✅ Barras de progreso visuales por círculo guía
  ✅ Indicador de estabilidad en tiempo real
  ✅ Auto-exposición y auto-enfoque
  ✅ Modo continuo con detección de nueva factura
  ✅ Captura manual con ESPACIO

FLUJO PhotoScan REAL:
  1. Cámara en vivo con 4 círculos guía + 1 central
  2. El operador mueve la cámara para alinear el primer círculo
  3. El sistema detecta: (a) alineación OK + (b) cámara quieta → captura
  4. Pide mover al siguiente ángulo
  5. Repite hasta 5 tomas
"""

import cv2
import numpy as np
from typing import List, Optional, Tuple, Set, Dict

from utils.config import CONFIG, CaptureMode
from core.detector import (
    detect_edges_live,
    render_edge_overlay,
    compute_perspective_preview,
    detect_document,
    order_corners,
    get_mode_params,
)


# ═══════════════════════════════════════════════════════════════
#  CONSTANTES DE CALIBRACIÓN (ajustables para diferentes entornos)
# ═══════════════════════════════════════════════════════════════

MOTION_THRESHOLD = 3.5
MOTION_PIXEL_FRACTION = 0.02
STABILITY_FRAMES = 6
ALIGNMENT_THRESHOLD = 0.45
SCORE_SMOOTHING = 0.3

# Info de modos para mostrar en overlay
MODE_DISPLAY: Dict[str, dict] = {
    "factura": {
        "icon": "📄",
        "label": "FACTURA",
        "color": (0, 255, 0),
        "desc": "Documentos estándar A4/carta",
    },
    "id": {
        "icon": "🆔",
        "label": "ID",
        "color": (255, 200, 0),
        "desc": "Cédula / Pasaporte / Carnet",
    },
    "libro": {
        "icon": "📖",
        "label": "LIBRO",
        "color": (0, 200, 255),
        "desc": "Páginas de libro / Revista",
    },
    "foto": {
        "icon": "🖼️",
        "label": "FOTO",
        "color": (255, 100, 100),
        "desc": "Fotografía / Imagen general",
    },
    "pizarra": {
        "icon": "📝",
        "label": "PIZARRA",
        "color": (255, 0, 255),
        "desc": "Pizarra / Whiteboard / Pizarrón",
    },
}


# ═══════════════════════════════════════════════════════════════
#  FUNCIONES AUXILIARES (heredadas de v2.x)
# ═══════════════════════════════════════════════════════════════

def _compute_target_positions(frame_size: Tuple[int, int]) -> List[Tuple[int, int]]:
    """
    Calcula las 5 posiciones objetivo adaptadas al tamaño del frame.

    Retorna: [(centro), (sup-izq), (sup-der), (inf-izq), (inf-der)]
    con márgenes del 22% para dejar espacio al documento.
    """
    w, h = frame_size
    cx, cy = w // 2, h // 2
    mx = int(w * 0.22)
    my = int(h * 0.22)

    return [
        (cx, cy),                          # 0: centro
        (max(10, cx - mx), max(10, cy - my)),  # 1: sup-izq
        (min(w - 10, cx + mx), max(10, cy - my)),  # 2: sup-der
        (max(10, cx - mx), min(h - 10, cy + my)),  # 3: inf-izq
        (min(w - 10, cx + mx), min(h - 10, cy + my)),  # 4: inf-der
    ]


def _detect_motion(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """
    Detecta cuánto movimiento hay entre dos frames consecutivos.

    Usa diferencia absoluta de píxeles: simple, rápida, efectiva.
    Retorna un score de 0 (quieto) a ~100 (mucho movimiento).
    """
    diff = cv2.absdiff(prev_gray, curr_gray)
    _, motion_mask = cv2.threshold(diff, 15, 255, cv2.THRESH_BINARY)
    motion_mask = cv2.medianBlur(motion_mask, 5)
    motion_pixels = np.sum(motion_mask > 0)
    total_pixels = motion_mask.size
    fraction = motion_pixels / total_pixels
    return min(100, fraction * 500)


def _compute_alignment_score(
    frame_gray: np.ndarray,
    target_x: int,
    target_y: int,
    radius: int,
    prev_region: Optional[np.ndarray] = None,
) -> Tuple[float, Optional[np.ndarray]]:
    """
    Calcula qué tan 'alineado' está un círculo guía con su entorno visual.

    Usa dos métricas complementarias:
      1. Densidad de textura local (varianza): qué tan nítida es la zona
      2. Cambio temporal (si hay prev_region): correlación con frame anterior
    """
    x1 = max(0, target_x - radius)
    x2 = min(frame_gray.shape[1], target_x + radius)
    y1 = max(0, target_y - radius)
    y2 = min(frame_gray.shape[0], target_y + radius)

    region = frame_gray[y1:y2, x1:x2]
    if region.size < 100:
        return 0.0, region

    # Métrica 1: Nitidez local (varianza del Laplaciano)
    laplacian_var = cv2.Laplacian(region, cv2.CV_64F).var()
    sharpness = min(1.0, laplacian_var / 200.0)

    # Métrica 2: Contraste local
    local_std = np.std(region) / 128.0
    contrast = min(1.0, local_std)

    # Métrica 3: Estabilidad temporal
    stability = 1.0
    if prev_region is not None and prev_region.shape == region.shape:
        corr = cv2.matchTemplate(
            region.astype(np.float32),
            prev_region.astype(np.float32),
            cv2.TM_CCOEFF_NORMED,
        )
        stability = float(corr.max())

    alignment_raw = sharpness * 0.5 + contrast * 0.5
    score = alignment_raw * (0.3 + 0.7 * stability)

    return min(1.0, max(0.0, score)), region


def _capture_shot(cap: cv2.VideoCapture, delay_ms: int = 150) -> Optional[np.ndarray]:
    """
    Captura un fotograma asegurando que sea reciente (descarta frames en buffer).
    """
    for _ in range(3):
        cap.grab()
    if delay_ms > 0:
        cv2.waitKey(delay_ms)
    ret, frame = cap.read()
    return frame if ret else None


def _configure_camera(cap: cv2.VideoCapture, resolution: Tuple[int, int]):
    """
    Configura la cámara con los mejores parámetros disponibles
    para captura de documentos.
    """
    target_w, target_h = resolution

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if actual_w < target_w * 0.8:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    if hasattr(cv2, 'CAP_PROP_AUTOFOCUS'):
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
    if hasattr(cv2, 'CAP_PROP_AUTO_EXPOSURE'):
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    if hasattr(cv2, 'CAP_PROP_BRIGHTNESS'):
        cap.set(cv2.CAP_PROP_BRIGHTNESS, 0)
    if hasattr(cv2, 'CAP_PROP_CONTRAST'):
        cap.set(cv2.CAP_PROP_CONTRAST, 32)
    if hasattr(cv2, 'CAP_PROP_SATURATION'):
        cap.set(cv2.CAP_PROP_SATURATION, 64)


# ═══════════════════════════════════════════════════════════════
#  NUEVO v3.0: Overlay de modo de captura
# ═══════════════════════════════════════════════════════════════

def _draw_mode_indicator(
    overlay: np.ndarray,
    mode: CaptureMode,
    edge_enabled: bool,
    perspective_enabled: bool,
):
    """
    Dibuja el indicador de modo de captura en la esquina superior derecha.
    Muestra: icono, nombre del modo, teclas rápidas.
    """
    h, w = overlay.shape[:2]
    info = MODE_DISPLAY.get(mode.value, MODE_DISPLAY["factura"])
    color = info["color"]

    # Fondo semitransparente para el panel de modo
    panel_x = w - 240
    panel_y = 55
    panel_w = 230
    panel_h = 85
    cv2.rectangle(overlay, (panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h),
                  (0, 0, 0), -1)
    cv2.addWeighted(
        overlay[panel_y:panel_y + panel_h, panel_x:panel_x + panel_w],
        1.0,
        np.full((panel_h, panel_w, 3), (30, 30, 30), dtype=np.uint8),
        0.35,
        0,
        overlay[panel_y:panel_y + panel_h, panel_x:panel_x + panel_w],
    )

    # Modo actual
    cv2.putText(overlay, f"MODO: {info['icon']} {info['label']}",
                (panel_x + 8, panel_y + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    cv2.putText(overlay, info["desc"],
                (panel_x + 8, panel_y + 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)

    # Atajos de teclado para modos
    shortcuts = "F:Fact  I:ID  L:Lib  P:Foto  W:Piz"
    cv2.putText(overlay, shortcuts,
                (panel_x + 8, panel_y + 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (140, 140, 140), 1)

    # Estado de overlays
    edge_status = "E:Bordes" + (" ON" if edge_enabled else " OFF")
    persp_status = "R:Persp" + (" ON" if perspective_enabled else " OFF")
    cv2.putText(overlay, f"{edge_status}  |  {persp_status}",
                (panel_x + 8, panel_y + 76),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                (0, 255, 0) if edge_enabled or perspective_enabled else (100, 100, 100), 1)


# ═══════════════════════════════════════════════════════════════
#  NUEVO v3.0: Detección de documento en vivo para edge overlay
# ═══════════════════════════════════════════════════════════════

def _detect_document_fast(
    gray: np.ndarray,
    mode_params: dict,
    img_area: float,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Versión rápida de detect_document para preview en vivo.
    Omite logs y validaciones extra para mantener velocidad.
    """
    # Desenfoque + Canny
    kernel = mode_params.get("gaussian_kernel", (5, 5))
    canny_low = mode_params.get("canny_low", 50)
    canny_high = mode_params.get("canny_high", 150)
    min_area_ratio = mode_params.get("min_area_ratio", 0.05)
    approx_eps = mode_params.get("approx_epsilon", 0.02)

    blurred = cv2.GaussianBlur(gray, kernel, 0)
    edges = cv2.Canny(blurred, canny_low, canny_high)

    result = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(result) == 3:
        _, contours, _ = result
    else:
        contours, _ = result

    if not contours:
        return None, edges

    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < img_area * min_area_ratio:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, approx_eps * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return order_corners(approx.reshape(4, 2)), edges

    # Fallback
    largest = contours[0]
    if cv2.contourArea(largest) > img_area * min_area_ratio:
        rect = cv2.minAreaRect(largest)
        box = cv2.boxPoints(rect)
        return order_corners(box.astype(np.float32)), edges

    return None, edges


def _draw_live_perspective_preview(
    frame: np.ndarray,
    corners: np.ndarray,
    max_width: int = 320,
    max_height: int = 240,
) -> np.ndarray:
    """
    Dibuja un thumbnail de la preview de perspectiva en la esquina inferior
    izquierda del frame, en lugar de una ventana separada.
    Más integrado y menos intrusivo que una ventana secundaria.
    """
    if corners is None or len(corners) != 4:
        return None

    # Calcular warp
    top_w = np.linalg.norm(corners[1] - corners[0])
    bot_w = np.linalg.norm(corners[2] - corners[3])
    dst_w = max(int(top_w), int(bot_w))
    left_h = np.linalg.norm(corners[3] - corners[0])
    right_h = np.linalg.norm(corners[2] - corners[1])
    dst_h = max(int(left_h), int(right_h))

    if dst_w < 10 or dst_h < 10:
        return None

    dst_pts = np.array([
        [0, 0], [dst_w - 1, 0],
        [dst_w - 1, dst_h - 1], [0, dst_h - 1],
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(corners.astype(np.float32), dst_pts)
    warped = cv2.warpPerspective(frame, M, (dst_w, dst_h))

    # Redimensionar al thumbnail
    scale = min(max_width / dst_w, max_height / dst_h, 1.0)
    new_w = int(dst_w * scale)
    new_h = int(dst_h * scale)
    if scale < 1.0:
        warped = cv2.resize(warped, (new_w, new_h))

    return warped


# ═══════════════════════════════════════════════════════════════
#  NUEVO v3.0: Overlay con bordes + preview de perspectiva
# ═══════════════════════════════════════════════════════════════

def _draw_overlay(
    frame: np.ndarray,
    targets: List[Tuple[int, int]],
    scores: List[float],
    aligned_set: Set[int],
    motion_score: float,
    shot_count: int,
    total_shots: int,
    current_direction: str,
    mode: CaptureMode,
    edge_overlay: bool = True,
    perspective_thumbnail: Optional[np.ndarray] = None,
    document_corners: Optional[np.ndarray] = None,
    document_outline: bool = True,
) -> np.ndarray:
    """
    Dibuja el overlay completo del v3.0:

    Componentes:
    1. Fondo semitransparente en márgenes (info)
    2. Círculos guía con barra de progreso
    3. Indicador de modo (superior derecha)
    4. Edge overlay semitransparente
    5. Contorno del documento detectado
    6. Preview thumbnail de perspectiva (inferior izquierda)
    7. Barra de estabilidad (superior izquierda)
    8. Info inferior (toma, dirección, alineación, teclas)
    """
    overlay = frame.copy()
    h, w = frame.shape[:2]
    mode_info = MODE_DISPLAY.get(mode.value, MODE_DISPLAY["factura"])
    mode_color = mode_info["color"]

    # ── 1. Fondo semitransparente en márgenes ──
    margin_overlay = overlay.copy()
    cv2.rectangle(margin_overlay, (0, 0), (w, 45), (0, 0, 0), -1)
    cv2.rectangle(margin_overlay, (0, h - 50), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(margin_overlay, 0.5, overlay, 0.5, 0, overlay)

    # ── 2. Círculos guía con barra de progreso ──
    for i, (cx, cy) in enumerate(targets):
        if i == 0:
            continue

        score = scores[i] if i < len(scores) else 0.0
        is_aligned = i in aligned_set

        if is_aligned:
            color = (0, 255, 0)
            inner_color = (0, 200, 0)
            label_color = (0, 255, 0)
        elif score > 0.5:
            color = (0, 255, 255)
            inner_color = (0, 200, 200)
            label_color = (0, 255, 255)
        else:
            r = int(255 * (1 - score))
            g = int(100 + 155 * score)
            color = (0, g, r)
            inner_color = (0, max(100, g - 50), max(0, r - 50))
            label_color = color

        # Círculo exterior
        cv2.circle(overlay, (cx, cy), 32, (50, 50, 50), 3)
        cv2.circle(overlay, (cx, cy), 30, color, 2)

        # Crosshair
        cv2.line(overlay, (cx - 35, cy), (cx + 35, cy), color, 1)
        cv2.line(overlay, (cx, cy - 35), (cx, cy + 35), color, 1)

        # Punto central
        inner_r = 3 if is_aligned else 5
        cv2.circle(overlay, (cx, cy), inner_r, inner_color, -1)

        # Barra de progreso
        bar_x1, bar_x2 = cx - 25, cx + 25
        bar_y, bar_h = cy + 38, 4
        cv2.rectangle(overlay, (bar_x1, bar_y), (bar_x2, bar_y + bar_h), (50, 50, 50), -1)
        fill_w = int(50 * score)
        fill_color = (0, 255, 0) if is_aligned else color
        cv2.rectangle(overlay, (bar_x1, bar_y), (bar_x1 + fill_w, bar_y + bar_h), fill_color, -1)

        # Etiqueta: G + número + score %
        pct = int(score * 100)
        cv2.putText(overlay, f"G{i} {pct}%", (cx - 20, cy - 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, label_color, 2)

    # ── Círculo central ──
    cx_c, cy_c = targets[0]
    cv2.circle(overlay, (cx_c, cy_c), 20, (200, 200, 200), 2)
    cv2.circle(overlay, (cx_c, cy_c), 3, (200, 200, 200), -1)
    cv2.putText(overlay, "CENTRO", (cx_c - 28, cy_c - 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    # ── 3. Indicador de modo ──
    _draw_mode_indicator(
        overlay, mode,
        edge_enabled=edge_overlay,
        perspective_enabled=(perspective_thumbnail is not None),
    )

    # ── 4. Contorno del documento (si se detectó) ──
    if document_outline and document_corners is not None:
        corners_int = document_corners.astype(int)
        for i in range(4):
            p1 = tuple(corners_int[i])
            p2 = tuple(corners_int[(i + 1) % 4])
            cv2.line(overlay, p1, p2, mode_color, 2)

        # Esquinas
        for pt in corners_int:
            cv2.circle(overlay, tuple(pt), 5, (0, 0, 255), -1)

    # ── 5. Preview thumbnail de perspectiva (inferior izquierda) ──
    if perspective_thumbnail is not None:
        th, tw = perspective_thumbnail.shape[:2]
        margin = 10
        pos_y = h - th - 50 - margin  # bottom-left
        # Fondo
        cv2.rectangle(
            overlay,
            (margin - 2, pos_y - 2),
            (margin + tw + 2, pos_y + th + 2),
            (0, 0, 0), -1,
        )
        cv2.addWeighted(
            overlay[pos_y:pos_y + th, margin:margin + tw],
            1.0,
            perspective_thumbnail,
            0.85,
            0,
            overlay[pos_y:pos_y + th, margin:margin + tw],
        )
        # Borde
        cv2.rectangle(
            overlay,
            (margin - 1, pos_y - 1),
            (margin + tw + 1, pos_y + th + 1),
            mode_color, 1,
        )
        # Etiqueta
        cv2.putText(overlay, "PREVIEW", (margin + 2, pos_y + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, mode_color, 1)

    # ── 6. Barra de estabilidad ──
    cv2.putText(overlay, "ESTABILIDAD", (15, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    cv2.rectangle(overlay, (130, 8), (250, 18), (50, 50, 50), -1)
    stability_pct = max(0, min(100, 100 - motion_score))
    stab_color = (0, 255, 0) if stability_pct > 70 else (0, 255, 255) if stability_pct > 40 else (0, 0, 255)
    fill_w = int(120 * stability_pct / 100)
    cv2.rectangle(overlay, (130, 8), (130 + fill_w, 18), stab_color, -1)
    cv2.putText(overlay, f"{stability_pct:.0f}%", (255, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, stab_color, 1)

    # ── 7. Info inferior ──
    aligned_str = f"{len(aligned_set)}/4 alineados"
    cv2.putText(overlay, f"📷 Toma {shot_count + 1}/{total_shots}", (15, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 2)
    cv2.putText(overlay, f"📍 {current_direction}", (180, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
    cv2.putText(overlay, aligned_str, (380, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (0, 255, 0) if len(aligned_set) == 4 else (200, 200, 200), 2)

    # ── 8. Teclas rápidas ──
    shortcuts_right = "ESP:manual  Q:salir  F/I/L/P/W:modo  E:edges  R:persp"
    cv2.putText(overlay, shortcuts_right, (w - 420, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)

    # ── 9. Mensaje de listo ──
    if len(aligned_set) == 4:
        cv2.rectangle(overlay, (w // 2 - 220, 55), (w // 2 + 220, 95), (0, 0, 0), -1)
        cv2.putText(overlay, "✅ TODOS ALINEADOS — CAPTURANDO...",
                    (w // 2 - 210, 82),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    return overlay


# ═══════════════════════════════════════════════════════════════
#  CAPTURA MULTI-TOMA v3.0 (PhotoScan + modos + edge + perspectiva)
# ═══════════════════════════════════════════════════════════════

SHOT_DIRECTIONS = [
    "Centro",
    "Arriba-Izquierdo",
    "Arriba-Derecho",
    "Abajo-Izquierdo",
    "Abajo-Derecho",
]


def capture_multishot(
    camera_id: Optional[int] = None,
    mode: Optional[CaptureMode] = None,
    edge_overlay: Optional[bool] = None,
    perspective_preview: Optional[bool] = None,
) -> List[np.ndarray]:
    """
    Bucle principal de captura multi-toma estilo PhotoScan v3.0.

    NUEVO EN v3.0:
      - 5 modos de captura seleccionables con teclas F/I/L/P/W
      - Edge detection en vivo overlay (tecla E para toggle)
      - Preview de perspectiva en thumbnail (tecla R para toggle)
      - Detección de documento con contorno en vivo
      - Parámetros adaptativos por modo

    Args:
        camera_id: ID del dispositivo de cámara (None = usar config).
        mode: Modo de captura inicial (None = usar config).
        edge_overlay: Activar edge overlay (None = usar config).
        perspective_preview: Activar preview de perspectiva (None = usar config).

    Returns:
        Lista de hasta 5 imágenes BGR en orden de captura.

    Raises:
        RuntimeError: Si no se puede abrir la cámara.
    """
    cfg = CONFIG.capture
    cam_id = camera_id if camera_id is not None else cfg.camera_id

    cap = cv2.VideoCapture(cam_id)
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir la cámara ID {cam_id}.")

    _configure_camera(cap, cfg.resolution)

    cv2.namedWindow(cfg.window_name, cv2.WINDOW_NORMAL)
    try:
        cv2.setWindowProperty(cfg.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass

    # ── Estado de la captura ──
    current_mode: CaptureMode = mode if mode is not None else cfg.mode
    show_edges: bool = edge_overlay if edge_overlay is not None else cfg.edge_overlay_enabled
    show_perspective: bool = perspective_preview if perspective_preview is not None else cfg.perspective_preview_enabled

    shots: List[np.ndarray] = []

    target_positions: Optional[List[Tuple[int, int]]] = None
    scores: List[float] = [0.0] * 5
    prev_regions: List[Optional[np.ndarray]] = [None] * 5
    prev_gray: Optional[np.ndarray] = None
    motion_score: float = 0.0

    sustain_counters = {i: 0 for i in range(1, 5)}
    stability_counter = 0
    directions = SHOT_DIRECTIONS

    # Contador de frames para actualizar preview de perspectiva (no en cada frame)
    frame_count = 0
    last_perspective: Optional[np.ndarray] = None
    last_corners: Optional[np.ndarray] = None

    print("\n" + "=" * 60)
    print("   ⬡ NAD Scanner — Captura Multi-Toma v3.0")
    print("   PhotoScan + Modos + Edge + Perspectiva")
    print("=" * 60)
    print()
    print("  📋 Instrucciones:")
    print("   1. Coloque el documento sobre una superficie plana")
    print("   2. Alinee el círculo guía moviendo la cámara")
    print("   3. Mantenga quieto 1 segundo → captura automática")
    print("   4. Repita para cada ángulo")
    print("   5. Presione ESPACIO para captura manual, Q para salir")
    print()
    print("  🎮 Atajos de teclado:")
    print("   F=Factura  I=ID  L=Libro  P=Foto  W=Pizarra")
    print("   E=Toggle bordes  R=Toggle perspectiva  ESP=Manual  Q=Salir")
    print()

    try:
        while len(shots) < cfg.num_shots:
            ret, frame = cap.read()
            if not ret:
                continue

            frame_count += 1
            h, w = frame.shape[:2]

            # ── Inicializar posiciones objetivo ──
            if target_positions is None:
                target_positions = _compute_target_positions((w, h))

            # ── Escala de grises ──
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)

            # ── Detectar movimiento ──
            if prev_gray is not None:
                motion_score = _detect_motion(prev_gray, gray)
            prev_gray = gray.copy()
            camera_stable = motion_score < MOTION_THRESHOLD

            # ── Calcular scores de alineación ──
            fresh_scores = [0.0] * 5
            fresh_scores[0] = 1.0
            for i in range(1, 5):
                tx, ty = target_positions[i]
                score, region = _compute_alignment_score(
                    gray, tx, ty, cfg.auto_capture_radius // 2, prev_regions[i],
                )
                fresh_scores[i] = score
                prev_regions[i] = region

            for i in range(5):
                scores[i] = scores[i] * (1 - SCORE_SMOOTHING) + fresh_scores[i] * SCORE_SMOOTHING

            # ── Determinar círculos alineados ──
            aligned_set: Set[int] = set()
            for i in range(1, 5):
                if scores[i] >= ALIGNMENT_THRESHOLD and camera_stable:
                    sustain_counters[i] += 1
                    if sustain_counters[i] >= STABILITY_FRAMES:
                        aligned_set.add(i)
                else:
                    sustain_counters[i] = 0

            all_aligned = len(aligned_set) == 4
            if camera_stable:
                stability_counter += 1
            else:
                stability_counter = 0

            # ── Edge detection en vivo ──
            frame_with_edges = frame.copy()
            document_corners = None

            if show_edges:
                # Edge overlay
                edges = detect_edges_live(gray, current_mode)
                mode_params = get_mode_params(current_mode)
                edge_color = mode_params.get("edge_color", (0, 255, 0))
                frame_with_edges = render_edge_overlay(frame, edges, color=edge_color)

                # Detección rápida de documento cada N frames
                if frame_count % 3 == 0:
                    img_area = h * w
                    document_corners, _ = _detect_document_fast(gray, mode_params, img_area)
                    last_corners = document_corners
                else:
                    document_corners = last_corners
            else:
                document_corners = None
                last_corners = None

            # ── Preview de perspectiva (cada N frames) ──
            if show_perspective and document_corners is not None and frame_count % cfg.perspective_preview_update_interval == 0:
                last_perspective = _draw_live_perspective_preview(frame, document_corners)
            elif not show_perspective:
                last_perspective = None

            # ── Construir overlay ──
            current_shot = len(shots)
            direction_name = directions[current_shot] if current_shot < len(directions) else f"Ángulo {current_shot + 1}"
            display = _draw_overlay(
                frame_with_edges, target_positions, scores, aligned_set,
                motion_score, current_shot, cfg.num_shots, direction_name,
                mode=current_mode,
                edge_overlay=show_edges,
                perspective_thumbnail=last_perspective,
                document_corners=document_corners,
                document_outline=show_edges,
            )

            # ── Captura automática ──
            if all_aligned and stability_counter >= 3:
                cv2.imshow(cfg.window_name, display)
                cv2.waitKey(200)

                shot = _capture_shot(cap, 100)
                if shot is not None:
                    shots.append(shot)
                    shot_num = len(shots)
                    dir_name = directions[shot_num - 1] if shot_num - 1 < len(directions) else f"Ángulo {shot_num}"
                    print(f"  ✅ Toma {shot_num}/{cfg.num_shots} — {dir_name}")

                    if len(shots) >= cfg.num_shots:
                        break

                    sustain_counters = {i: 0 for i in range(1, 5)}
                    stability_counter = 0
                    scores = [0.0] * 5
                    prev_regions = [None] * 5
                    next_dir = directions[len(shots)] if len(shots) < len(directions) else f"Ángulo {len(shots) + 1}"
                    print(f"  👉 Mueva la cámara al ángulo: {next_dir}")

                cv2.waitKey(400)

            # ── Mostrar frame ──
            cv2.imshow(cfg.window_name, display)

            # ── Teclas ──
            key = cv2.waitKey(1) & 0xFF

            # Salir
            if key == ord('q') or key == 27:
                print("\n  ⏹ Captura cancelada por el operador.")
                break

            # Captura manual
            elif key == ord(' '):
                shots.append(frame.copy())
                print(f"  📸 Captura manual — Toma {len(shots)}/{cfg.num_shots}")
                if len(shots) >= cfg.num_shots:
                    break
                sustain_counters = {i: 0 for i in range(1, 5)}
                stability_counter = 0
                scores = [0.0] * 5
                prev_regions = [None] * 5

            # ── Cambio de modo ──
            elif key == ord('f') or key == ord('F'):
                current_mode = CaptureMode.FACTURA
                cfg.mode = CaptureMode.FACTURA
                print(f"  🔄 Modo: {MODE_DISPLAY['factura']['icon']} FACTURA")

            elif key == ord('i') or key == ord('I'):
                current_mode = CaptureMode.ID
                cfg.mode = CaptureMode.ID
                print(f"  🔄 Modo: {MODE_DISPLAY['id']['icon']} ID")

            elif key == ord('l') or key == ord('L'):
                current_mode = CaptureMode.LIBRO
                cfg.mode = CaptureMode.LIBRO
                print(f"  🔄 Modo: {MODE_DISPLAY['libro']['icon']} LIBRO")

            elif key == ord('p') or key == ord('P'):
                current_mode = CaptureMode.FOTO
                cfg.mode = CaptureMode.FOTO
                print(f"  🔄 Modo: {MODE_DISPLAY['foto']['icon']} FOTO")

            elif key == ord('w') or key == ord('W'):
                current_mode = CaptureMode.PIZARRA
                cfg.mode = CaptureMode.PIZARRA
                print(f"  🔄 Modo: {MODE_DISPLAY['pizarra']['icon']} PIZARRA")

            # ── Toggle edge overlay ──
            elif key == ord('e') or key == ord('E'):
                show_edges = not show_edges
                cfg.edge_overlay_enabled = show_edges
                if not show_edges:
                    last_corners = None
                    last_perspective = None
                print(f"  {'✅' if show_edges else '❌'} Edge overlay: {'ON' if show_edges else 'OFF'}")

            # ── Toggle perspectiva ──
            elif key == ord('r') or key == ord('R'):
                show_perspective = not show_perspective
                cfg.perspective_preview_enabled = show_perspective
                if not show_perspective:
                    last_perspective = None
                print(f"  {'✅' if show_perspective else '❌'} Preview perspectiva: {'ON' if show_perspective else 'OFF'}")

    finally:
        cap.release()
        cv2.destroyWindow(cfg.window_name)

    if len(shots) < cfg.num_shots:
        print(f"\n  ⚠ Solo se capturaron {len(shots)}/{cfg.num_shots} tomas.")

    return shots


# ═══════════════════════════════════════════════════════════════
#  CAPTURA CONTINUA (varias facturas en sesión)
# ═══════════════════════════════════════════════════════════════

def capture_continuous(
    camera_id: Optional[int] = None,
    max_invoices: int = 0,
    mode: Optional[CaptureMode] = None,
    edge_overlay: Optional[bool] = None,
    perspective_preview: Optional[bool] = None,
) -> List[List[np.ndarray]]:
    """
    Captura múltiples facturas en una sola sesión.

    Para cada factura, ejecuta capture_multishot(). Al terminar,
    pregunta si desea capturar otra.

    Args:
        camera_id: ID de cámara.
        max_invoices: Máximo de facturas (0 = ilimitado).
        mode: Modo de captura (None = usar config).
        edge_overlay: Activar edge overlay.
        perspective_preview: Activar preview perspectiva.

    Returns:
        Lista de listas de imágenes, una por factura.
    """
    all_shots: List[List[np.ndarray]] = []
    invoice_num = 0

    print("\n" + "=" * 60)
    print("   ⬡ NAD Scanner — Captura Continua v3.0")
    print("=" * 60)

    while True:
        if max_invoices > 0 and invoice_num >= max_invoices:
            break

        invoice_num += 1
        print(f"\n{'=' * 50}")
        print(f"   📄 Documento #{invoice_num}")
        print(f"{'=' * 50}")

        try:
            shots = capture_multishot(
                camera_id=camera_id,
                mode=mode,
                edge_overlay=edge_overlay,
                perspective_preview=perspective_preview,
            )
        except RuntimeError as e:
            print(f"  ❌ Error de cámara: {e}")
            break

        if len(shots) < 2:
            print("  ⏹ Captura insuficiente. Terminando sesión.")
            break

        all_shots.append(shots)

        print(f"\n  ✅ Documento #{invoice_num} capturado ({len(shots)} tomas).")
        print("  Presione ESPACIO para otro documento, Q para salir...")

        key = cv2.waitKey(0) & 0xFF
        if key == ord('q') or key == 27:
            break
        cv2.waitKey(500)

    print(f"\n  📊 Sesión completada: {len(all_shots)} documentos capturados.")
    return all_shots


# ═══════════════════════════════════════════════════════════════
#  PREVIEW (solo cámara, sin captura)
# ═══════════════════════════════════════════════════════════════

def preview_camera(
    camera_id: Optional[int] = None,
    mode: Optional[CaptureMode] = None,
    edge_overlay: Optional[bool] = None,
    perspective_preview: Optional[bool] = None,
) -> None:
    """
    Modo de previsualización con edge detection y perspectiva en vivo.

    Muestra la cámara en vivo con guías de encuadre, edge overlay
    y preview de perspectiva.
    Presione Q para salir.
    """
    cfg = CONFIG.capture
    cam_id = camera_id if camera_id is not None else cfg.camera_id

    current_mode = mode if mode is not None else cfg.mode
    show_edges = edge_overlay if edge_overlay is not None else cfg.edge_overlay_enabled
    show_perspective = perspective_preview if perspective_preview is not None else cfg.perspective_preview_enabled

    cap = cv2.VideoCapture(cam_id)
    if not cap.isOpened():
        print(f"  ❌ Error: No se pudo abrir la cámara ID {cam_id}.")
        return

    _configure_camera(cap, cfg.resolution)

    cv2.namedWindow("Preview — NAD Scanner v3.0", cv2.WINDOW_NORMAL)
    try:
        cv2.setWindowProperty("Preview — NAD Scanner v3.0", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass

    print("\n  === Preview de Cámara v3.0 ===")
    print("  Ajuste la posición del documento.")
    print("  F/I/L/P/W = modo  |  E = bordes  |  R = perspectiva  |  Q = salir\n")

    frame_count = 0
    last_perspective = None
    last_corners = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        overlay = frame.copy()

        # Rectángulo guía central
        mx, my = w // 6, h // 6
        cv2.rectangle(overlay, (mx, my), (w - mx, h - my), (0, 255, 0), 2)

        # Líneas de tercios
        cv2.line(overlay, (w // 3, my), (w // 3, h - my), (255, 255, 255), 1)
        cv2.line(overlay, (2 * w // 3, my), (2 * w // 3, h - my), (255, 255, 255), 1)
        cv2.line(overlay, (mx, h // 3), (w - mx, h // 3), (255, 255, 255), 1)
        cv2.line(overlay, (mx, 2 * h // 3), (w - mx, 2 * h // 3), (255, 255, 255), 1)

        # ── Edge overlay en vivo ──
        if show_edges:
            edges = detect_edges_live(gray, current_mode)
            mode_params = get_mode_params(current_mode)
            edge_color = mode_params.get("edge_color", (0, 255, 0))
            overlay = render_edge_overlay(overlay, edges, color=edge_color, opacity=0.25)

            # Detectar documento para contorno y perspectiva
            if frame_count % 5 == 0:
                img_area = h * w
                document_corners, _ = _detect_document_fast(gray, mode_params, img_area)
                last_corners = document_corners
            else:
                document_corners = last_corners

            # Contorno del documento
            if document_corners is not None:
                corners_int = document_corners.astype(int)
                for i in range(4):
                    p1 = tuple(corners_int[i])
                    p2 = tuple(corners_int[(i + 1) % 4])
                    cv2.line(overlay, p1, p2, edge_color, 2)
        else:
            document_corners = None

        # ── Preview de perspectiva ──
        if show_perspective and document_corners is not None and frame_count % cfg.perspective_preview_update_interval == 0:
            last_perspective = _draw_live_perspective_preview(frame, document_corners)
            if last_perspective is not None:
                th, tw = last_perspective.shape[:2]
                margin = 10
                pos_y = h - th - margin  # bottom-left
                cv2.rectangle(overlay, (margin - 1, pos_y - 1),
                              (margin + tw + 1, pos_y + th + 1), (0, 0, 0), -1)
                overlay[pos_y:pos_y + th, margin:margin + tw] = \
                    last_perspective * 0.85 + overlay[pos_y:pos_y + th, margin:margin + tw] * 0.15
                cv2.rectangle(overlay, (margin - 1, pos_y - 1),
                              (margin + tw + 1, pos_y + th + 1), (0, 255, 0), 1)
                cv2.putText(overlay, "PREVIEW", (margin + 2, pos_y + 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)
        elif not show_perspective:
            last_perspective = None

        # ── Indicador de modo ──
        _draw_mode_indicator(overlay, current_mode, show_edges, show_perspective)

        # ── Info ──
        cv2.putText(overlay, f"🎯 Coloque el documento dentro del rectángulo guía",
                    (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(overlay, "F/I/L/P/W:modo  E:bordes  R:persp  Q:salir",
                    (w - 320, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)

        cv2.imshow("Preview — NAD Scanner v3.0", overlay)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            break
        elif key == ord('f') or key == ord('F'):
            current_mode = CaptureMode.FACTURA
            cfg.mode = CaptureMode.FACTURA
        elif key == ord('i') or key == ord('I'):
            current_mode = CaptureMode.ID
            cfg.mode = CaptureMode.ID
        elif key == ord('l') or key == ord('L'):
            current_mode = CaptureMode.LIBRO
            cfg.mode = CaptureMode.LIBRO
        elif key == ord('p') or key == ord('P'):
            current_mode = CaptureMode.FOTO
            cfg.mode = CaptureMode.FOTO
        elif key == ord('w') or key == ord('W'):
            current_mode = CaptureMode.PIZARRA
            cfg.mode = CaptureMode.PIZARRA
        elif key == ord('e') or key == ord('E'):
            show_edges = not show_edges
            cfg.edge_overlay_enabled = show_edges
        elif key == ord('r') or key == ord('R'):
            show_perspective = not show_perspective
            cfg.perspective_preview_enabled = show_perspective

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        print("\n  🎯 Modo por defecto: FACTURA")
        print("  Presione F/I/L/P/W para cambiar modo durante la captura")
        print("  Presione E para toggle edge overlay")
        print("  Presione R para toggle preview de perspectiva\n")
        shots = capture_multishot()
        print(f"\n  Captura completa: {len(shots)} imágenes.")
        for i, s in enumerate(shots):
            print(f"    Toma {i + 1}: {s.shape[1]}×{s.shape[0]} px")
    except RuntimeError as e:
        print(f"  Error: {e}")
        print("  ¿Tiene una cámara conectada?")
