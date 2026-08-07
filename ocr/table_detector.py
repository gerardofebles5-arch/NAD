"""
Detector de Tablas Complejas
============================
Detecta y extrae tablas complejas en facturas.

Funcionalidades:
  - Detección de estructura de tablas
  - Extracción de celdas
  - Identificación de columnas
  - Reconocimiento de encabezados
"""

import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class TableCell:
    """Celda de una tabla."""
    row: int
    col: int
    text: str
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    confidence: float = 0.0


@dataclass
class Table:
    """Tabla detectada."""
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    rows: int
    cols: int
    cells: List[TableCell]
    headers: List[str]
    confidence: float = 0.0


class TableDetector:
    """
    Detector de tablas complejas en facturas.
    
    Detecta tablas con múltiples columnas y extrae su contenido.
    """
    
    def __init__(self):
        self._tables: List[Table] = []
    
    def detect(self, image: np.ndarray, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> List[Table]:
        """
        Detecta tablas en la imagen.
        
        Args:
            image: Imagen del documento
            words: Lista de palabras OCR con coordenadas (opcional)
            
        Returns:
            Lista de tablas detectadas
        """
        self._tables = []
        
        if words:
            # Detección basada en palabras OCR
            self._detect_from_words(words)
        else:
            # Detección basada en visión por computadora
            self._detect_from_image(image)
        
        return self._tables
    
    def _detect_from_words(self, words: List[Tuple[str, Tuple[float, float, float, float], float]]):
        """Detecta tablas basándose en la posición de palabras."""
        # Agrupar palabras por filas (coordenada Y)
        lines_dict = self._group_words_by_lines(words)
        
        # Detectar patrones de tabla
        table_lines = self._detect_table_lines(lines_dict)
        
        if table_lines:
            table = self._create_table_from_lines(table_lines)
            self._tables.append(table)
    
    def _group_words_by_lines(self, words: List[Tuple[str, Tuple[float, float, float, float], float]]) -> Dict[int, List]:
        """Agrupa palabras por líneas basándose en coordenada Y."""
        lines_dict = {}
        
        for word, bbox, conf in words:
            x, y, x2, y2 = bbox
            y_center = (y + y2) / 2
            line_key = int(y_center / 10)  # Agrupar por cada 10px
            
            if line_key not in lines_dict:
                lines_dict[line_key] = []
            
            lines_dict[line_key].append({
                'text': word,
                'bbox': bbox,
                'conf': conf,
                'x': x,
                'y': y
            })
        
        # Ordenar palabras en cada línea por coordenada X
        for line_key in lines_dict:
            lines_dict[line_key].sort(key=lambda w: w['x'])
        
        return lines_dict
    
    def _detect_table_lines(self, lines_dict: Dict[int, List]) -> List[List]:
        """Detecta líneas que forman parte de una tabla."""
        table_lines = []
        
        # Buscar líneas con múltiples palabras (potencialmente columnas)
        for line_key, words in lines_dict.items():
            if len(words) >= 3:  # Al menos 3 palabras = potencial tabla
                table_lines.append(words)
        
        return table_lines
    
    def _create_table_from_lines(self, table_lines: List[List]) -> Table:
        """Crea una estructura de tabla desde las líneas detectadas."""
        if not table_lines:
            return None
        
        # Determinar número de columnas (máximo de palabras en una línea)
        num_cols = max(len(line) for line in table_lines)
        num_rows = len(table_lines)
        
        # Extraer celdas
        cells = []
        for row_idx, line in enumerate(table_lines):
            for col_idx, word_data in enumerate(line):
                cell = TableCell(
                    row=row_idx,
                    col=col_idx,
                    text=word_data['text'],
                    bbox=word_data['bbox'],
                    confidence=word_data['conf']
                )
                cells.append(cell)
        
        # Extraer headers (primera línea)
        headers = [word['text'] for word in table_lines[0]] if table_lines else []
        
        # Calcular bbox de la tabla
        all_x = [word['x'] for line in table_lines for word in line]
        all_y = [word['y'] for line in table_lines for word in line]
        if all_x and all_y:
            x = min(all_x)
            y = min(all_y)
            x2 = max([word['bbox'][2] for line in table_lines for word in line])
            y2 = max([word['bbox'][3] for line in table_lines for word in line])
            bbox = (int(x), int(y), int(x2 - x), int(y2 - y))
        else:
            bbox = (0, 0, 0, 0)
        
        return Table(
            bbox=bbox,
            rows=num_rows,
            cols=num_cols,
            cells=cells,
            headers=headers,
            confidence=0.7
        )
    
    def _detect_from_image(self, image: np.ndarray):
        """Detecta tablas usando visión por computadora."""
        # Convertir a escala de grises
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        # Detección de líneas horizontales
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        horizontal_lines = cv2.morphologyEx(gray, cv2.MORPH_OPEN, horizontal_kernel)
        
        # Detección de líneas verticales
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        vertical_lines = cv2.morphologyEx(gray, cv2.MORPH_OPEN, vertical_kernel)
        
        # Combinar líneas
        table_mask = cv2.addWeighted(horizontal_lines, 0.5, vertical_lines, 0.5, 0.0)
        
        # Encontrar contornos
        contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 1000:  # Filtro de área mínima
                x, y, w, h = cv2.boundingRect(contour)
                
                # Validar ratio de aspecto (tablas suelen ser horizontales)
                aspect_ratio = w / h if h > 0 else 0
                if 1.5 < aspect_ratio < 10:
                    table = Table(
                        bbox=(x, y, w, h),
                        rows=0,
                        cols=0,
                        cells=[],
                        headers=[],
                        confidence=0.6
                    )
                    self._tables.append(table)
    
    def extract_table_data(self, table: Table) -> List[List[str]]:
        """
        Extrae los datos de una tabla como matriz de texto.
        
        Args:
            table: Tabla detectada
            
        Returns:
            Matriz de texto (filas x columnas)
        """
        if not table or not table.cells:
            return []
        
        # Crear matriz vacía
        data = [['' for _ in range(table.cols)] for _ in range(table.rows)]
        
        # Llenar matriz con celdas
        for cell in table.cells:
            if cell.row < table.rows and cell.col < table.cols:
                data[cell.row][cell.col] = cell.text
        
        return data
    
    def get_tables(self) -> List[Table]:
        """Retorna las tablas detectadas."""
        return self._tables.copy()


def detect_tables(image: np.ndarray, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> List[Table]:
    """
    Función de conveniencia para detectar tablas.
    
    Args:
        image: Imagen del documento
        words: Lista de palabras OCR con coordenadas (opcional)
        
    Returns:
        Lista de tablas detectadas
    """
    detector = TableDetector()
    return detector.detect(image, words)
