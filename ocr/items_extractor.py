"""
Extractor de Items/Líneas de Factura
=====================================
Extrae las líneas de detalle de una factura (productos/servicios).

Estructura típica de una línea:
  - Cantidad
  - Descripción del producto/servicio
  - Precio unitario
  - Monto total de la línea
  - IVA (opcional)
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class InvoiceItem:
    """Una línea de detalle de factura."""
    line_number: int
    quantity: Optional[float] = None
    description: str = ""
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    iva: Optional[float] = None
    confidence: float = 0.0


class ItemsExtractor:
    """
    Extractor de líneas de detalle de factura.
    
    Detecta y extrae items del cuerpo de la factura.
    """
    
    # Patrones para detectar líneas de items
    ITEM_PATTERNS = [
        # Formato: cantidad | descripción | precio unitario | total
        r'(\d+(?:\.\d+)?)\s+([A-ZÁÉÍÓÚÑ\s\.]+?)\s+([\d.,]+)\s+([\d.,]+)',
        # Formato: cantidad x precio = total
        r'(\d+(?:\.\d+)?)\s*[xX]\s*([\d.,]+)\s*[=]\s*([\d.,]+)',
        # Formato simple: descripción con monto
        r'([A-ZÁÉÍÓÚÑ\s\.]{5,})\s+([\d.,]+)',
    ]
    
    # Patrones para detectar encabezados de tabla
    TABLE_HEADER_PATTERNS = [
        r'CANTIDAD|CANT\.?|QTY',
        r'DESCRIPCIÓN|DESC\.?|DESCRIPCION',
        r'P\.?\s*U\.?|PRECIO\s*UNITARIO|UNIT\s*PRICE',
        r'TOTAL|IMPORTE|MONTO',
    ]
    
    def __init__(self):
        self._items: List[InvoiceItem] = []
    
    def extract(self, text: str, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> List[InvoiceItem]:
        """
        Extrae items del texto OCR.
        
        Args:
            text: Texto completo del OCR
            words: Lista de palabras con coordenadas (opcional)
            
        Returns:
            Lista de InvoiceItem extraídos
        """
        self._items = []
        
        if words:
            # Usar extracción posicional
            self._extract_from_words(words)
        else:
            # Usar extracción basada en texto
            self._extract_from_text(text)
        
        return self._items
    
    def _extract_from_text(self, text: str):
        """Extrae items basándose en patrones de texto."""
        lines = text.split('\n')
        
        # Buscar inicio de tabla de items
        table_start = self._find_table_start(lines)
        
        if table_start == -1:
            # No se encontró tabla, intentar extraer de todo el texto
            relevant_lines = lines
        else:
            relevant_lines = lines[table_start:]
        
        # Extraer items línea por línea
        line_num = 0
        for line in relevant_lines:
            line_num += 1
            item = self._parse_line(line, line_num)
            if item:
                self._items.append(item)
    
    def _find_table_start(self, lines: List[str]) -> int:
        """Encuentra el inicio de la tabla de items."""
        for i, line in enumerate(lines):
            line_upper = line.upper()
            # Verificar si la línea contiene múltiples indicadores de tabla
            header_count = sum(1 for pattern in self.TABLE_HEADER_PATTERNS 
                              if re.search(pattern, line_upper))
            if header_count >= 2:
                return i + 1  # Retornar la siguiente línea
        return -1
    
    def _parse_line(self, line: str, line_number: int) -> Optional[InvoiceItem]:
        """Parsea una línea individual para extraer un item."""
        line = line.strip()
        if not line or len(line) < 5:
            return None
        
        # Intentar cada patrón
        for pattern in self.ITEM_PATTERNS:
            try:
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    return self._create_item_from_match(match, line_number, pattern)
            except re.error:
                continue
        
        return None
    
    def _create_item_from_match(self, match: re.Match, line_number: int, pattern: str) -> InvoiceItem:
        """Crea un InvoiceItem desde un match de regex."""
        groups = match.groups()
        item = InvoiceItem(line_number=line_number)
        
        # Determinar el formato basado en el número de grupos
        if len(groups) == 4:
            # Formato: cantidad | descripción | precio unitario | total
            item.quantity = self._parse_amount(groups[0])
            item.description = groups[1].strip()
            item.unit_price = self._parse_amount(groups[2])
            item.line_total = self._parse_amount(groups[3])
            item.confidence = 0.8
        
        elif len(groups) == 3:
            # Formato: cantidad x precio = total
            item.quantity = self._parse_amount(groups[0])
            item.unit_price = self._parse_amount(groups[1])
            item.line_total = self._parse_amount(groups[2])
            item.description = "Item"
            item.confidence = 0.7
        
        elif len(groups) == 2:
            # Formato simple: descripción | monto
            item.description = groups[0].strip()
            item.line_total = self._parse_amount(groups[1])
            item.quantity = 1.0  # Asumir cantidad 1
            item.confidence = 0.6
        
        return item
    
    def _extract_from_words(self, words: List[Tuple[str, Tuple[float, float, float, float], float]]):
        """Extrae items basándose en coordenadas de palabras."""
        # Agrupar palabras por líneas (coordenada Y)
        lines_dict = {}
        for word, bbox, conf in words:
            y_center = bbox[1]
            # Agrupar por línea (usando un umbral de 10px)
            line_key = int(y_center / 10)
            if line_key not in lines_dict:
                lines_dict[line_key] = []
            lines_dict[line_key].append((word, bbox, conf))
        
        # Ordenar líneas por posición Y
        sorted_lines = sorted(lines_dict.items(), key=lambda x: x[0])
        
        # Procesar cada línea
        line_num = 0
        for line_key, line_words in sorted_lines:
            line_num += 1
            
            # Ordenar palabras por posición X
            line_words_sorted = sorted(line_words, key=lambda w: w[1][0])
            
            # Reconstruir texto de la línea
            line_text = ' '.join(w[0] for w in line_words_sorted)
            
            # Parsear línea
            item = self._parse_line(line_text, line_num)
            if item:
                self._items.append(item)
    
    def _parse_amount(self, value: str) -> Optional[float]:
        """Parsea un monto string a float."""
        if not value:
            return None
        try:
            # Eliminar símbolos de moneda
            value = re.sub(r'[BbSs$€£]', '', value)
            # Normalizar separadores
            value = value.replace(',', '.')
            return float(value)
        except ValueError:
            return None
    
    def get_items(self) -> List[InvoiceItem]:
        """Retorna todos los items extraídos."""
        return self._items.copy()
    
    def calculate_total(self) -> Optional[float]:
        """Calcula el total de todos los items."""
        if not self._items:
            return None
        
        total = 0.0
        for item in self._items:
            if item.line_total:
                total += item.line_total
            elif item.quantity and item.unit_price:
                total += item.quantity * item.unit_price
        
        return total if total > 0 else None
    
    def validate_items(self, invoice_total: Optional[float]) -> Dict[str, List[str]]:
        """
        Valida los items extraídos contra el total de la factura.
        
        Args:
            invoice_total: Total de la factura
            
        Returns:
            Diccionario con errores de validación
        """
        errors = {}
        
        if not self._items:
            errors['no_items'] = ['No se detectaron items en la factura']
            return errors
        
        items_total = self.calculate_total()
        
        if items_total and invoice_total:
            diff = abs(items_total - invoice_total)
            tolerance = invoice_total * 0.05  # 5% de tolerancia
            
            if diff > tolerance:
                errors['total_mismatch'] = [
                    f'Total de items ({items_total:.2f}) no coincide con total de factura ({invoice_total:.2f}). Diferencia: {diff:.2f}'
                ]
        
        # Validar items sin descripción
        items_without_desc = [i.line_number for i in self._items if not i.description]
        if items_without_desc:
            errors['missing_description'] = [
                f'Items sin descripción en líneas: {items_without_desc}'
            ]
        
        return errors


def extract_invoice_items(text: str, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> List[InvoiceItem]:
    """
    Función de conveniencia para extraer items de factura.
    
    Args:
        text: Texto completo del OCR
        words: Lista de palabras con coordenadas (opcional)
        
    Returns:
        Lista de InvoiceItem extraídos
    """
    extractor = ItemsExtractor()
    return extractor.extract(text, words)


def validate_items_against_total(items: List[InvoiceItem], invoice_total: float) -> Dict[str, List[str]]:
    """
    Función de conveniencia para validar items contra total.
    
    Args:
        items: Lista de items extraídos
        invoice_total: Total de la factura
        
    Returns:
        Diccionario con errores de validación
    """
    extractor = ItemsExtractor()
    extractor._items = items
    return extractor.validate_items(invoice_total)
