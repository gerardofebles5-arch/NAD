"""
Fase 2: Table Extraction — Extracción de tablas → HTML/Markdown.
================================================================================
Detecta la estructura de tablas (filas, columnas, celdas) y las convierte
a HTML o Markdown.

Estrategia:
  1. PaddleOCR table recognition (si disponible)
  2. OpenCV line detection (fallback robusto)
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2


@dataclass
class TableCell:
    """Celda de una tabla."""
    row: int
    col: int
    bbox: List[int]       # [x1, y1, x2, y2]
    text: str = ""
    rowspan: int = 1
    colspan: int = 1


@dataclass
class TableResult:
    """Resultado de extracción de tabla."""
    html: str
    markdown: str
    rows: int
    cols: int
    cells: List[TableCell]

    def to_dict(self) -> dict:
        return {
            "html": self.html,
            "markdown": self.markdown,
            "rows": self.rows,
            "cols": self.cols,
            "cell_count": len(self.cells),
        }


class TableExtractor:
    """
    Extrae tablas de imágenes y las convierte a HTML/Markdown.

    Uso:
        extractor = TableExtractor()
        result = extractor.extract(image, table_bbox)
        print(result.html)
    """

    def __init__(self):
        pass

    def extract(
        self,
        image: np.ndarray,
        bbox: Optional[List[int]] = None,
        ocr_cells: bool = True,
    ) -> TableResult:
        """
        Extrae tabla de una imagen.

        Args:
            image: Imagen BGR completa
            bbox: [x1, y1, x2, y2] de la región de tabla (None = imagen completa)
            ocr_cells: si True, ejecuta OCR sobre cada celda detectada para
                       llenar su texto real. Antes esta clase solo detectaba
                       la ESTRUCTURA de la tabla (filas/columnas) y devolvía
                       celdas siempre vacías (`text=""`) — una tabla sin
                       contenido no sirve de mucho. Usa el mismo motor OCR
                       compartido que el resto de la app (ver
                       ocr.extractor.get_ocr_engine), así que no carga un
                       modelo nuevo por tabla.

        Returns:
            TableResult con HTML, Markdown y celdas
        """
        # Recortar región de tabla
        if bbox:
            x1, y1, x2, y2 = bbox
            crop = image[max(0, y1):min(image.shape[0], y2),
                        max(0, x1):min(image.shape[1], x2)]
        else:
            crop = image.copy()
            x1, y1 = 0, 0

        if crop.size == 0:
            return TableResult(html="", markdown="", rows=0, cols=0, cells=[])

        # Detectar estructura
        cells = self._detect_cells(crop)

        # Si no se detectaron celdas por líneas, usar grid approach
        if not cells:
            cells = self._grid_approach(crop)

        # Si aún no hay celdas, crear una sola celda con todo el texto
        if not cells:
            h, w = crop.shape[:2]
            cells = [TableCell(row=0, col=0, bbox=[0, 0, w, h], text="")]

        # OCR real por celda (antes: cells siempre quedaban con text="")
        if ocr_cells:
            self._ocr_fill_cells(crop, cells)

        # Calcular filas y columnas
        rows = max(c.row for c in cells) + 1 if cells else 1
        cols = max(c.col for c in cells) + 1 if cells else 1

        # Generar HTML y Markdown
        html = self._cells_to_html(cells, rows, cols)
        markdown = self._cells_to_markdown(cells, rows, cols)

        return TableResult(
            html=html,
            markdown=markdown,
            rows=rows,
            cols=cols,
            cells=cells,
        )

    def _ocr_fill_cells(self, crop: np.ndarray, cells: List[TableCell]):
        """
        Corre OCR sobre el recorte de cada celda y llena cell.text.
        Import perezoso de ocr.extractor para evitar acoplar core<->ocr
        en tiempo de import del módulo (solo se necesita si se piden tablas).
        """
        try:
            from ocr.extractor import get_ocr_engine
        except ImportError:
            return  # ocr/ no disponible en este contexto — deja celdas vacías

        engine = get_ocr_engine()
        h, w = crop.shape[:2]

        for cell in cells:
            x1, y1, x2, y2 = cell.bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 - x1 < 4 or y2 - y1 < 4:
                continue  # celda demasiado pequeña para OCR útil
            cell_img = crop[y1:y2, x1:x2]
            try:
                words = engine.recognize(cell_img)
            except Exception:
                continue
            if words:
                # Ordenar por posición (izq→der) antes de unir el texto
                words_sorted = sorted(words, key=lambda w: w[1][0])
                cell.text = " ".join(w[0] for w in words_sorted if w[0]).strip()

    def _detect_cells(self, crop: np.ndarray) -> List[TableCell]:
        """Detecta celdas usando detección de líneas."""
        h, w = crop.shape[:2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        # Binarizar
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Detectar líneas horizontales
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 10), 1))
        h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

        # Detectar líneas verticales
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, h // 15)))
        v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

        # Encontrar intersecciones
        intersections = cv2.bitwise_and(h_lines, v_lines)

        # Encontrar puntos de intersección
        h_points = self._get_line_positions(h_lines, axis='horizontal')
        v_points = self._get_line_positions(v_lines, axis='vertical')

        if len(h_points) < 2 or len(v_points) < 2:
            return []

        # Crear celdas basadas en la grilla de intersecciones
        cells = []
        for i in range(len(h_points) - 1):
            for j in range(len(v_points) - 1):
                y1 = h_points[i]
                y2 = h_points[i + 1]
                x1 = v_points[j]
                x2 = v_points[j + 1]

                if x2 - x1 > 5 and y2 - y1 > 5:
                    cells.append(TableCell(
                        row=i,
                        col=j,
                        bbox=[x1, y1, x2, y2],
                        text="",
                    ))

        return cells

    def _get_line_positions(
        self,
        line_img: np.ndarray,
        axis: str = 'horizontal',
    ) -> List[int]:
        """Obtiene posiciones de líneas detectadas."""
        positions = []

        if axis == 'horizontal':
            # Proyectar verticalmente
            projection = np.sum(line_img, axis=1)
        else:
            # Proyectar horizontalmente
            projection = np.sum(line_img, axis=0)

        # Encontrar picos (líneas)
        threshold = np.max(projection) * 0.3
        in_line = False
        line_start = 0

        for i, val in enumerate(projection):
            if val > threshold and not in_line:
                in_line = True
                line_start = i
            elif val <= threshold and in_line:
                in_line = False
                positions.append((line_start + i) // 2)

        if in_line:
            positions.append((line_start + len(projection) - 1) // 2)

        return positions

    def _grid_approach(self, crop: np.ndarray) -> List[TableCell]:
        """Enfoque alternativo: dividir en grid uniforme."""
        h, w = crop.shape[:2]

        # Estimar tamaño de celda promedio
        min_cell_w = max(30, w // 10)
        min_cell_h = max(15, h // 5)

        cols = max(1, w // min_cell_w)
        rows = max(1, h // min_cell_h)

        cell_w = w // cols
        cell_h = h // rows

        cells = []
        for r in range(rows):
            for c in range(cols):
                x1 = c * cell_w
                y1 = r * cell_h
                x2 = min((c + 1) * cell_w, w)
                y2 = min((r + 1) * cell_h, h)

                cells.append(TableCell(
                    row=r,
                    col=c,
                    bbox=[x1, y1, x2, y2],
                    text="",
                ))

        return cells

    def _cells_to_html(
        self,
        cells: List[TableCell],
        rows: int,
        cols: int,
    ) -> str:
        """Convierte celdas a HTML <table>."""
        if not cells:
            return ""

        # Crear grid
        grid = {}
        for cell in cells:
            grid[(cell.row, cell.col)] = cell

        html = '<table>\n'

        for r in range(rows):
            html += '  <tr>\n'
            for c in range(cols):
                cell = grid.get((r, c))
                if cell:
                    text = cell.text.replace('<', '&lt;').replace('>', '&gt;')
                    attrs = ""
                    if cell.rowspan > 1:
                        attrs += f' rowspan="{cell.rowspan}"'
                    if cell.colspan > 1:
                        attrs += f' colspan="{cell.colspan}"'
                    html += f'    <td{attrs}>{text}</td>\n'
                else:
                    html += '    <td></td>\n'
            html += '  </tr>\n'

        html += '</table>'
        return html

    def _cells_to_markdown(
        self,
        cells: List[TableCell],
        rows: int,
        cols: int,
    ) -> str:
        """Convierte celdas a Markdown table."""
        if not cells:
            return ""

        # Crear grid
        grid = {}
        for cell in cells:
            grid[(cell.row, cell.col)] = cell

        # Encontrar anchos de columna
        col_widths = [10] * cols
        for r in range(rows):
            for c in range(cols):
                cell = grid.get((r, c))
                if cell and cell.text:
                    col_widths[c] = max(col_widths[c], len(cell.text) + 2)

        # Generar Markdown
        lines = []

        # Header
        header = "| " + " | ".join(
            grid.get((0, c), TableCell(0, c, [0,0,0,0], "")).text.ljust(col_widths[c])
            for c in range(cols)
        ) + " |"
        lines.append(header)

        # Separador
        sep = "| " + " | ".join("-" * col_widths[c] for c in range(cols)) + " |"
        lines.append(sep)

        # Filas
        for r in range(1, rows):
            row = "| " + " | ".join(
                grid.get((r, c), TableCell(r, c, [0,0,0,0], "")).text.ljust(col_widths[c])
                for c in range(cols)
            ) + " |"
            lines.append(row)

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  Función de conveniencia
# ═══════════════════════════════════════════════════════════════

def extract_table(
    image: np.ndarray,
    bbox: Optional[List[int]] = None,
) -> TableResult:
    """Función de conveniencia para extraer tabla."""
    extractor = TableExtractor()
    return extractor.extract(image, bbox)
