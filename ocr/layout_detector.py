"""
Detector de Layout de Facturas
==============================
Detecta la estructura de una factura para mejorar la extracción de campos.

Identifica regiones del documento:
  - Header (encabezado): número de factura, fecha, RIF, razón social
  - Items (detalle): lista de productos/servicios
  - Totals (totales): base imponible, IVA, total
  - Footer (pie): condiciones de pago, banco
"""

import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class DocumentRegion(Enum):
    """Regiones del documento."""
    HEADER = "header"
    ITEMS = "items"
    TOTALS = "totals"
    FOOTER = "footer"


@dataclass
class Region:
    """Región detectada en el documento."""
    region_type: DocumentRegion
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float
    content: str = ""


class LayoutDetector:
    """
    Detector de layout de facturas.
    
    Usa técnicas de visión por computadora para identificar
    las diferentes regiones de una factura.
    """
    
    def __init__(self):
        self._regions: List[Region] = []
        self._layout_type: str = "unknown"
    
    def detect(self, image: np.ndarray = None, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> Dict[str, DocumentRegion]:
        """
        Detecta el layout del documento.
        
        Args:
            image: Imagen del documento (opcional)
            words: Lista de palabras con coordenadas (opcional)
            
        Returns:
            Diccionario de regiones detectadas
        """
        if not words or len(words) == 0:
            print("[WARN] No hay palabras para detectar layout")
            return {}
        
        if image is not None:
            return self._detect_from_image(image)
        else:
            return self._detect_from_words(words)
    
    def _detect_from_words(self, words: List[Tuple[str, Tuple[float, float, float, float], float]]) -> Dict[str, Region]:
        """
        Detecta layout usando información de palabras OCR.
        
        Agrupa palabras por posición Y para identificar regiones.
        """
        if not words:
            return {}
        
        # Ordenar palabras por posición Y
        words_sorted = sorted(words, key=lambda w: w[1][1])
        
        # Obtener dimensiones del documento
        max_y = max(w[1][3] for w in words)
        
        # Definir umbrales de región (basados en posición Y)
        thresholds = {
            DocumentRegion.HEADER: (0, max_y * 0.25),
            DocumentRegion.ITEMS: (max_y * 0.25, max_y * 0.70),
            DocumentRegion.TOTALS: (max_y * 0.70, max_y * 0.90),
            DocumentRegion.FOOTER: (max_y * 0.90, max_y),
        }
        
        # Agrupar palabras por región
        regions = {}
        for region_type, (y_min, y_max) in thresholds.items():
            region_words = [w for w in words_sorted if y_min <= w[1][1] <= y_max]
            
            if region_words:
                # Calcular bbox de la región
                x_coords = [w[1][0] for w in region_words]
                y_coords = [w[1][1] for w in region_words]
                x2_coords = [w[1][2] for w in region_words]
                y2_coords = [w[1][3] for w in region_words]
                
                bbox = (
                    min(x_coords),
                    min(y_coords),
                    max(x2_coords),
                    max(y2_coords)
                )
                
                # Reconstruir texto de la región
                region_words_sorted = sorted(region_words, key=lambda w: (w[1][1], w[1][0]))
                content = ' '.join(w[0] for w in region_words_sorted)
                
                regions[region_type.value] = Region(
                    region_type=region_type,
                    bbox=bbox,
                    confidence=0.8,
                    content=content
                )
        
        self._regions = list(regions.values())
        self._determine_layout_type(regions)
        
        return regions
    
    def _detect_from_image(self, image: np.ndarray) -> Dict[str, Region]:
        """
        Detecta layout usando visión por computadora.
        
        Usa detección de bordes y análisis de bloques de texto.
        """
        # Convertir a escala de grises
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Binarizar
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Detectar líneas horizontales
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
        
        # Detectar líneas verticales
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
        
        # Combinar para detectar cajas
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        boxes = cv2.morphologyEx(horizontal_lines + vertical_lines, cv2.MORPH_CLOSE, kernel)
        
        # Encontrar contornos
        contours, _ = cv2.findContours(boxes, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        height, width = image.shape[:2]
        regions = {}
        
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            
            # Filtrar contornos muy pequeños
            if w < width * 0.1 or h < height * 0.05:
                continue
            
            # Determinar tipo de región basado en posición
            y_center = y + h / 2
            region_type = self._classify_region_by_position(y_center, height)
            
            if region_type and region_type.value not in regions:
                # Extraer contenido de la región
                region_image = gray[y:y+h, x:x+w]
                content = self._extract_text_from_region(region_image)
                
                regions[region_type.value] = Region(
                    region_type=region_type,
                    bbox=(x, y, x + w, y + h),
                    confidence=0.7,
                    content=content
                )
        
        self._regions = list(regions.values())
        self._determine_layout_type(regions)
        
        return regions
    
    def _classify_region_by_position(self, y_center: float, height: float) -> Optional[DocumentRegion]:
        """Clasifica una región basándose en su posición vertical."""
        if y_center < height * 0.25:
            return DocumentRegion.HEADER
        elif y_center < height * 0.70:
            return DocumentRegion.ITEMS
        elif y_center < height * 0.90:
            return DocumentRegion.TOTALS
        else:
            return DocumentRegion.FOOTER
    
    def _extract_text_from_region(self, region_image: np.ndarray) -> str:
        """
        Extrae texto de una región de imagen.
        
        En producción, esto usaría OCR. Por ahora retorna
        información sobre la región.
        """
        # Por ahora, solo retornamos información básica
        h, w = region_image.shape
        return f"[Región {w}x{h}px]"
    
    def _determine_layout_type(self, regions: Dict[str, Region]):
        """
        Determina el tipo de layout de la factura.
        
        Tipos comunes:
          - standard: header arriba, items en medio, totals abajo
          - compact: header y items combinados
          - detailed: items con múltiples columnas
        """
        if not regions:
            self._layout_type = "unknown"
            return
        
        # Contar regiones detectadas
        detected_count = len(regions)
        
        if detected_count == 4:
            self._layout_type = "standard"
        elif detected_count == 3:
            self._layout_type = "compact"
        else:
            self._layout_type = "custom"
    
    def get_layout_type(self) -> str:
        """Retorna el tipo de layout detectado."""
        return self._layout_type
    
    def get_regions(self) -> List[Region]:
        """Retorna todas las regiones detectadas."""
        return self._regions.copy()
    
    def visualize_layout(self, image: np.ndarray, output_path: str = None) -> np.ndarray:
        """
        Visualiza el layout detectado sobre la imagen.
        
        Args:
            image: Imagen original
            output_path: Ruta para guardar la visualización (opcional)
            
        Returns:
            Imagen con layout visualizado
        """
        vis_image = image.copy()
        
        # Colores para cada tipo de región
        colors = {
            DocumentRegion.HEADER: (0, 255, 0),      # Verde
            DocumentRegion.ITEMS: (255, 0, 0),       # Azul
            DocumentRegion.TOTALS: (0, 0, 255),      # Rojo
            DocumentRegion.FOOTER: (255, 255, 0),   # Amarillo
        }
        
        for region in self._regions:
            x1, y1, x2, y2 = region.bbox
            color = colors.get(region.region_type, (128, 128, 128))
            
            # Dibujar rectángulo
            cv2.rectangle(vis_image, (x1, y1), (x2, y2), color, 2)
            
            # Dibujar etiqueta
            label = region.region_type.value.upper()
            cv2.putText(vis_image, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        if output_path:
            cv2.imwrite(output_path, vis_image)
        
        return vis_image


class FieldPositionExtractor:
    """
    Extractor de campos basado en posición.
    
    Usa el layout detectado para extraer campos de las
    regiones apropiadas del documento.
    """
    
    def __init__(self, layout_detector: LayoutDetector = None):
        self.layout_detector = layout_detector or LayoutDetector()
    
    def extract_by_region(self, words: List[Tuple[str, Tuple[float, float, float, float], float]], 
                         field_region_map: Dict[str, DocumentRegion]) -> Dict[str, str]:
        """
        Extrae campos basándose en la región donde deberían estar.
        
        Args:
            words: Lista de palabras OCR con coordenadas
            field_region_map: Mapeo campo -> región esperada
            
        Returns:
            Diccionario de campos extraídos
        """
        # Detectar layout
        regions = self.layout_detector.detect(None, words)
        
        results = {}
        
        for field_name, expected_region in field_region_map.items():
            region_key = expected_region.value
            
            if region_key in regions:
                region = regions[region_key]
                
                # Filtrar palabras dentro de la región
                region_words = [
                    w for w in words
                    if (region.bbox[0] <= w[1][0] <= region.bbox[2] and
                        region.bbox[1] <= w[1][1] <= region.bbox[3])
                ]
                
                if region_words:
                    # Reconstruir texto de la región
                    region_words_sorted = sorted(region_words, key=lambda w: (w[1][1], w[1][0]))
                    text = ' '.join(w[0] for w in region_words_sorted)
                    results[field_name] = text
        
        return results
    
    def extract_header_fields(self, words: List[Tuple[str, Tuple[float, float, float, float], float]]) -> Dict[str, str]:
        """Extrae campos del header de la factura."""
        field_region_map = {
            'numero_factura': DocumentRegion.HEADER,
            'numero_control': DocumentRegion.HEADER,
            'fecha': DocumentRegion.HEADER,
            'rif_emisor': DocumentRegion.HEADER,
            'razon_social': DocumentRegion.HEADER,
        }
        return self.extract_by_region(words, field_region_map)
    
    def extract_totals_fields(self, words: List[Tuple[str, Tuple[float, float, float, float], float]]) -> Dict[str, str]:
        """Extrae campos de totales de la factura."""
        field_region_map = {
            'base_imponible': DocumentRegion.TOTALS,
            'iva': DocumentRegion.TOTALS,
            'total': DocumentRegion.TOTALS,
        }
        return self.extract_by_region(words, field_region_map)


def detect_invoice_layout(image: np.ndarray, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> Dict[str, Region]:
    """
    Función de conveniencia para detectar el layout de una factura.
    
    Args:
        image: Imagen BGR de la factura
        words: Lista de palabras OCR con coordenadas (opcional)
        
    Returns:
        Diccionario de regiones detectadas
    """
    detector = LayoutDetector()
    return detector.detect(image, words)


def extract_fields_by_layout(words: List[Tuple[str, Tuple[float, float, float, float], float]]) -> Dict[str, str]:
    """
    Función de conveniencia para extraer campos basándose en layout.
    
    Args:
        words: Lista de palabras OCR con coordenadas
        
    Returns:
        Diccionario de campos extraídos
    """
    extractor = FieldPositionExtractor()
    
    header_fields = extractor.extract_header_fields(words)
    totals_fields = extractor.extract_totals_fields(words)
    
    return {**header_fields, **totals_fields}
