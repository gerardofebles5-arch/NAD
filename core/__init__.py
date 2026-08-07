"""
NAD Scanner — Módulo Core v3.0
Procesamiento de imágenes: captura, alineación, fusión, detección y realce.

Nuevo en v3.0:
- CaptureMode enum (factura/ID/libro/foto/pizarra)
- Edge detection en vivo (detect_edges_live, render_edge_overlay)
- Preview de perspectiva (compute_perspective_preview)
- Parámetros de detección adaptativos por modo
"""

from .capture import (
    capture_multishot,
    capture_continuous,
    preview_camera,
)
from utils.config import CaptureMode
from .align import align_shots, render_matches
from .fusion import fuse_shots, fuse_with_depth_weights
from .detector import (
    detect_document,
    draw_detection,
    detect_edges_live,
    render_edge_overlay,
    compute_perspective_preview,
    order_corners,
    get_mode_params,
)
from .enhancer import (
    perspective_correct,
    enhance_document,
    auto_detect_mode,
)

__all__ = [
    # Capture v3.0
    "capture_multishot",
    "capture_continuous",
    "preview_camera",
    "CaptureMode",
    # Align
    "align_shots",
    "render_matches",
    # Fusion
    "fuse_shots",
    "fuse_with_depth_weights",
    # Detector v3.0
    "detect_document",
    "draw_detection",
    "detect_edges_live",
    "render_edge_overlay",
    "compute_perspective_preview",
    "order_corners",
    "get_mode_params",
    # Enhancer
    "perspective_correct",
    "enhance_document",
    "auto_detect_mode",
]
