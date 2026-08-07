"""
Layout Detection — Detección de regiones internas del documento.
================================================================================
Detecta: text, title, table, figure, equation, list, header, footer

Estrategia multi-backend:
  1. PaddleOCR ppstructure (si está disponible)
  2. OpenCV fallback (siempre funciona, sin dependencias extra)
"""

import os
import sys
import json
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum

import cv2


# ═══════════════════════════════════════════════════════════════
#  Modelos de región
# ═══════════════════════════════════════════════════════════════

class RegionType(str, Enum):
    TEXT = "text"
    TITLE = "title"
    TABLE = "table"
    FIGURE = "figure"
    EQUATION = "equation"
    LIST = "list"
    HEADER = "header"
    FOOTER = "footer"
    UNKNOWN = "unknown"


@dataclass
class LayoutRegion:
    """Región detectada en el layout del documento."""
    region_type: str
    bbox: List[int]          # [x1, y1, x2, y2]
    confidence: float
    reading_order: int = 0
    text: str = ""
    html: str = ""
    latex: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "region_type": self.region_type,
            "bbox": self.bbox,
            "confidence": round(self.confidence, 4),
            "reading_order": self.reading_order,
            "text": self.text[:200] if self.text else "",
            # OJO: el HTML de una tabla NO se debe truncar a longitud fija
            # como el texto — cortar a la mitad de una etiqueta produce
            # HTML inválido (tags sin cerrar) y rompe la tabla completa
            # en el cliente. Se entrega completo.
            "html": self.html if self.html else "",
            "latex": self.latex[:200] if self.latex else "",
            "metadata": self.metadata or {},
        }


@dataclass
class DocumentLayout:
    """Layout completo de un documento."""
    regions: List[LayoutRegion]
    page_width: int = 0
    page_height: int = 0
    num_pages: int = 1

    def to_dict(self) -> dict:
        return {
            "num_pages": self.num_pages,
            "page_size": [self.page_width, self.page_height],
            "regions": [r.to_dict() for r in self.regions],
            "region_count": len(self.regions),
            "summary": self._summary(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def _summary(self) -> dict:
        types = {}
        for r in self.regions:
            types[r.region_type] = types.get(r.region_type, 0) + 1
        return types

    def get_regions_by_type(self, region_type: str) -> List[LayoutRegion]:
        return [r for r in self.regions if r.region_type == region_type]

    def get_tables(self) -> List[LayoutRegion]:
        return self.get_regions_by_type("table")

    def get_text_blocks(self) -> List[LayoutRegion]:
        return self.get_regions_by_type("text") + self.get_regions_by_type("title")


# ═══════════════════════════════════════════════════════════════
#  Backend 1: PaddleOCR ppstructure
# ═══════════════════════════════════════════════════════════════

def _try_paddle_layout(image: np.ndarray) -> Optional[DocumentLayout]:
    """Intenta usar PaddleOCR para layout detection."""
    try:
        os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
        from paddleocr import PPStructureV3

        engine = PPStructureV3(
            use_table_recognition=True,
            use_formula_recognition=True,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            lang="es",
        )

        result = engine.predict(input=image)

        if result:
            return _parse_paddle_result(result, image.shape)

    except Exception as e:
        print(f"  [Layout] PaddleOCR no disponible: {e}")

    return None


def _parse_paddle_result(result, image_shape) -> DocumentLayout:
    """Parsea resultado de PaddleOCR."""
    h, w = image_shape[:2]
    regions = []

    try:
        for item in result:
            if isinstance(item, dict):
                label = str(item.get("label", item.get("type", "text"))).lower()
                box = item.get("bbox", item.get("box", None))
                score = float(item.get("score", item.get("confidence", 0.5)))

                if box is None:
                    continue

                region_type = _map_paddle_label(label)
                text = item.get("text", "")
                html = item.get("html", "") if region_type == "table" else ""
                latex = item.get("latex", "") if region_type == "equation" else ""

                # Extraer de 'res' si está vacío
                res = item.get("res", "")
                if isinstance(res, str) and not text:
                    text = res

                regions.append(LayoutRegion(
                    region_type=region_type,
                    bbox=[int(b) for b in box[:4]],
                    confidence=score,
                    text=text,
                    html=html,
                    latex=latex,
                ))
    except Exception as e:
        print(f"  [Layout] Error parseando PaddleOCR: {e}")

    return DocumentLayout(regions=regions, page_width=w, page_height=h)


def _map_paddle_label(label: str) -> str:
    """Mapea labels de PaddleOCR a tipos internos."""
    mapping = {
        "text": "text",
        "paragraph_title": "title",
        "doc_title": "title",
        "table": "table",
        "figure": "figure",
        "figure_caption": "figure",
        "chart": "figure",
        "equation": "equation",
        "list": "list",
        "header": "header",
        "footer": "footer",
        "reference": "text",
        "abstract": "text",
        "content": "text",
        "seal": "figure",
        "code": "text",
    }
    return mapping.get(label.lower(), "unknown")


# ═══════════════════════════════════════════════════════════════
#  Backend 2: OpenCV (fallback, siempre funciona)
# ═══════════════════════════════════════════════════════════════

def _opencv_detect_layout(image: np.ndarray) -> DocumentLayout:
    """Detecta layout usando solo OpenCV (sin dependencias extra)."""
    h, w = image.shape[:2]
    regions = []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 1. Detectar tablas por líneas
    table_bboxes = _detect_tables(gray, w, h)
    for bbox in table_bboxes:
        regions.append(LayoutRegion(
            region_type=RegionType.TABLE.value,
            bbox=bbox,
            confidence=0.7,
        ))

    # 2. Detectar regiones de texto por contornos de componentes conectados
    text_bboxes = _detect_text_regions(gray, w, h, exclude_bboxes=table_bboxes)
    for bbox in text_bboxes:
        regions.append(LayoutRegion(
            region_type=RegionType.TEXT.value,
            bbox=bbox,
            confidence=0.6,
        ))

    # 3. Si no se detectó nada, usar imagen completa
    if not regions:
        regions.append(LayoutRegion(
            region_type=RegionType.TEXT.value,
            bbox=[0, 0, w, h],
            confidence=0.5,
        ))

    # 4. Asignar orden de lectura
    regions = _assign_reading_order(regions)

    return DocumentLayout(regions=regions, page_width=w, page_height=h)


def _detect_tables(gray: np.ndarray, w: int, h: int) -> List[List[int]]:
    """Detecta tablas buscando patrones de líneas horizontales + verticales."""
    tables = []

    # Binarizar
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Líneas horizontales
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 15), 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

    # Líneas verticales
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 20)))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    # Combinar para formar grilla
    grid = cv2.add(h_lines, v_lines)

    # Dilatar un poco para conectar líneas cercanas
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    grid = cv2.dilate(grid, dilate_kernel, iterations=2)

    # Encontrar contornos de la grilla
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_table_area = w * h * 0.005  # 0.5% del área total

    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch

        if area > min_table_area and cw > 60 and ch > 40:
            # Verificar que hay suficientes píxeles blancos (líneas) en la grilla
            roi = grid[y:y+ch, x:x+cw]
            pixel_count = cv2.countNonZero(roi)
            pixel_ratio = pixel_count / (cw * ch)

            # Si hay suficiente densidad de píxeles, es una tabla
            if pixel_ratio > 0.01:
                tables.append([x, y, x + cw, y + ch])

    return tables


def _detect_text_regions(
    gray: np.ndarray,
    w: int,
    h: int,
    exclude_bboxes: List[List[int]],
) -> List[List[int]]:
    """Detecta regiones de texto usando componentes conectados."""
    texts = []

    # Binarizar
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Remover tablas del binario
    for bbox in exclude_bboxes:
        x1, y1, x2, y2 = bbox
        binary[y1:y2, x1:x2] = 0

    # Operación morfológica para agrupar texto cercano
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 5))
    dilated = cv2.dilate(binary, kernel, iterations=3)

    # Encontrar contornos
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_text_area = 200  # Píxeles mínimos
    min_text_height = 10

    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch

        if area > min_text_area and ch > min_text_height:
            # Expandir un poco el bbox
            pad = 5
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + cw + pad)
            y2 = min(h, y + ch + pad)
            texts.append([x1, y1, x2, y2])

    # Fusionar regiones cercanas verticales
    texts = _merge_close_regions(texts, max_gap_x=30, max_gap_y=15)

    return texts


def _merge_close_regions(
    bboxes: List[List[int]],
    max_gap_x: int = 30,
    max_gap_y: int = 15,
) -> List[List[int]]:
    """Fusiona bounding boxes que están cerca verticalmente."""
    if len(bboxes) <= 1:
        return bboxes

    # Ordenar por Y
    bboxes.sort(key=lambda b: (b[1], b[0]))

    merged = [bboxes[0]]

    for bbox in bboxes[1:]:
        prev = merged[-1]

        # Verificar si están cerca
        x_overlap = max(0, min(prev[2], bbox[2]) - max(prev[0], bbox[0]))
        y_gap = bbox[1] - prev[3]

        if x_overlap > 0 and 0 <= y_gap <= max_gap_y:
            # Fusionar
            merged[-1] = [
                min(prev[0], bbox[0]),
                min(prev[1], bbox[1]),
                max(prev[2], bbox[2]),
                max(prev[3], bbox[3]),
            ]
        elif abs(bbox[0] - prev[0]) < max_gap_x and y_gap <= max_gap_y:
            # Fusionar horizontalmente cercanas
            merged[-1] = [
                min(prev[0], bbox[0]),
                min(prev[1], bbox[1]),
                max(prev[2], bbox[2]),
                max(prev[3], bbox[3]),
            ]
        else:
            merged.append(bbox)

    return merged


def _assign_reading_order(regions: List[LayoutRegion]) -> List[LayoutRegion]:
    """Asigna orden de lectura: primero headers/footers, luego por Y then X."""
    # Separar por tipo
    headers = [r for r in regions if r.region_type == "header"]
    footers = [r for r in regions if r.region_type == "footer"]
    body = [r for r in regions if r.region_type not in ("header", "footer")]

    # Headers primero (por Y ascendente)
    headers.sort(key=lambda r: (r.bbox[1], r.bbox[0]))

    # Body por Y then X
    body.sort(key=lambda r: (r.bbox[1], r.bbox[0]))

    # Footers al final
    footers.sort(key=lambda r: (r.bbox[1], r.bbox[0]))

    # Asignar orden
    order = 0
    for r in headers + body + footers:
        r.reading_order = order
        order += 1

    return headers + body + footers


# ═══════════════════════════════════════════════════════════════
#  Layout Detector principal
# ═══════════════════════════════════════════════════════════════

class LayoutDetector:
    """
    Detector de layout multi-backend.

    Estrategia:
      1. Intentar PaddleOCR ppstructure (máxima precisión)
      2. Fallback a OpenCV (siempre funciona)

    Uso:
        detector = LayoutDetector()
        layout = detector.detect(image)
        tables = layout.get_tables()
    """

    def __init__(self, prefer_paddle: bool = True):
        self.prefer_paddle = prefer_paddle
        self._paddle_available = None

    def _is_paddle_available(self) -> bool:
        """Verifica si PaddleOCR funciona correctamente."""
        if self._paddle_available is not None:
            return self._paddle_available

        try:
            import paddle
            from paddleocr import PPStructureV3
            self._paddle_available = True
        except Exception:
            self._paddle_available = False

        return self._paddle_available

    def detect(self, image: np.ndarray) -> DocumentLayout:
        """
        Detecta layout de una imagen.

        Args:
            image: Imagen BGR (numpy array)

        Returns:
            DocumentLayout con todas las regiones detectadas
        """
        if self.prefer_paddle and self._is_paddle_available():
            try:
                layout = _try_paddle_layout(image)
                if layout and layout.regions:
                    print(f"  [Layout] PaddleOCR: {len(layout.regions)} regiones")
                    return layout
            except Exception as e:
                print(f"  [Layout] PaddleOCR error: {e}")

        # Fallback a OpenCV
        layout = _opencv_detect_layout(image)
        print(f"  [Layout] OpenCV: {len(layout.regions)} regiones")
        return layout


# ═══════════════════════════════════════════════════════════════
#  Funciones de conveniencia
# ═══════════════════════════════════════════════════════════════

_detector_instance = None

def get_layout_detector(**kwargs) -> LayoutDetector:
    """Retorna instancia global del LayoutDetector."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = LayoutDetector(**kwargs)
    return _detector_instance


def detect_layout(image: np.ndarray) -> DocumentLayout:
    """Función de conveniencia para detectar layout."""
    return get_layout_detector().detect(image)
