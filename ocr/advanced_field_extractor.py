"""
Extractor Avanzado de Campos de Factura
========================================
Extracción mejorada de campos usando patrones regex avanzados,
análisis posicional y contexto semántico.

Mejoras sobre extractor.py:
  - Patrones regex más específicos para facturas venezolanas
  - Análisis de posición de campos en el documento
  - Validación de formato de campos extraídos
  - Detección de campos específicos de punto de venta
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np


@dataclass
class FieldMatch:
    """Resultado de extracción de un campo."""
    field_name: str
    value: str
    confidence: float
    position: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    pattern_used: str
    context: str = ""


class AdvancedFieldExtractor:
    """
    Extractor avanzado de campos de factura venezolana.
    
    Usa patrones regex mejorados y análisis posicional para
    aumentar la precisión de extracción.
    """
    
    # Patrones regex mejorados para facturas venezolanas
    PATTERNS = {
        "numero_factura": [
            # Formato estándar: F001-000001, FC-001-000001, etc.
            r'(?:FACTURA|FACT\.?|FC[OA]?|COMPROBANTE)[\s\.:]*N[°ºO]?\.?\s*[:#]?\s*([A-Z]?\d{3}[-]\d{6,7})',
            r'(?:N[°ºO]?\.?\s*)?(?:FACTURA|FACT\.?|FC[OA]?)\s*[:.\-]?\s*([A-Z]?\d{3}[-]\d{6,7})',
            r'([A-Z]?\d{3}[-]\d{6,7})',  # Solo el patrón numérico
            r'N[°ºO]?\.?\s*(\d{2}[-]\d{4,8})',  # Formato corto: N° 01-000123
        ],
        "numero_control": [
            r'(?:CONTROL|CTRL|CTL)[\s\.:]*N[°ºO]?\.?\s*[:#]?\s*(\d{2}[-]\d{8})',
            r'N[°ºO]?\.?\s*(?:CONTROL|CTRL|CTL)\s*[:.\-]?\s*(\d{2}[-]\d{8})',
            r'(\d{2}[-]\d{8})',  # Solo el patrón numérico
        ],
        "fecha": [
            r'(?:FECHA|DATE)[\s\.:]*(?:EMISIÓN|EMISION)?\s*[:#]?\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})',
            r'(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4})',  # DD/MM/YYYY o DD-MM-YYYY
            r'(\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2})',  # YYYY-MM-DD
            r'(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2})',  # DD/MM/YY
        ],
        "rif_emisor": [
            r'(?:RIF|R\.I\.F\.|REGISTRO)[\s\.:]*(?:FISCAL)?\s*[:#]?\s*([VJEGPC][\-.\s]?\d{8}[\-.\s]?\d)',
            r'([VJEGPC])[\-.\s]?(\d{8})[\-.\s]?(\d)',  # Formato pegado
        ],
        "razon_social": [
            r'(?:RAZÓN\s*SOCIAL|NOMBRE|EMPRESA|PROVEEDOR)[\s\.:]*\s*[:#]?\s*([A-ZÁÉÍÓÚÑ\s\.]+?)(?:RIF|C\.I\.|DIRECCIÓN|TELÉFONO|$)',
            r'([A-ZÁÉÍÓÚÑ\s]{5,})\s*RIF',  # Texto antes de RIF
        ],
        "direccion": [
            r'(?:DIRECCIÓN|DIR\.?|UBICACIÓN)[\s\.:]*\s*[:#]?\s*([A-ZÁÉÍÓÚÑ0-9\s\.,#\-]+?)(?:TELÉFONO|TELF\.?|C\.I\.|$)',
        ],
        "telefono": [
            r'(?:TELÉFONO|TELF\.?|TEL\.?)\s*[:#]?\s*(0\d{3}[-.\s]?\d{7})',
            r'(?:TELÉFONO|TELF\.?|TEL\.?)\s*[:#]?\s*(\+58\s?\d{3}[-.\s]?\d{7})',
            r'(0\d{3}[-.\s]?\d{7})',
        ],
        "base_imponible": [
            r'(?:BASE\s*IMPOSIBLE|SUBTOTAL|EXENTO|GRAVABLE|BASE)[\s\.:]*\s*[:#]?\s*([\d.,]+)',
            r'(?:SUB\s*TOTAL|SUBTOTAL)[\s\.:]*\s*[:#]?\s*([\d.,]+)',
        ],
        "iva": [
            r'(?:I\.?\s*V\.?\s*A\.?|IVA)[\s\.:]*(?:\d{1,2}\s*%?\s*)?[:#]?\s*([\d.,]+)',
            r'(?:IMPUESTO\s*AL\s*VALOR\s*AGREGADO|IMPUESTO)[\s\.:]*\s*[:#]?\s*([\d.,]+)',
        ],
        "total": [
            r'(?:TOTAL\s*(?:GENERAL|COMPROBANTE|A\s*PAGAR|BS\.?|PAGAR)?)[\s\.:]*\s*[:#]?\s*([\d.,]+)',
            r'(?:MONTO\s*TOTAL|GRAN\s*TOTAL)[\s\.:]*\s*[:#]?\s*([\d.,]+)',
        ],
        "currency": [
            r'\b(BS|Bs|bs\.?|BOL[IÍ]VAR(?:ES)?|VES)\b',
            r'\b(\$|USD|D[OÓ]LAR(?:ES)?|DIVISAS|AMERICANO)\b',
            r'\b(€|EUR(?:O)?(?:S)?|EUROS?)\b',
            r'\b(COP|COL|PESO(?:S)?\s*COLOMBIANO(?:S)?)\b',
            r'\b(ARS|ARG|PESO(?:S)?\s*ARGENTINO(?:S)?)\b',
        ],
        "condicion_pago": [
            r'(?:CONDICI[OÓ]N\s*(?:DE\s*)?PAGO|FORMA\s*DE\s*PAGO)[\s\.:]*\s*[:#]?\s*([A-ZÁÉÍÓÚÑ\s]+?)(?:\d|\n|$)',
            r'\b(CONTADO|CR[EÉ]DITO\s*\d*\s*D[IÍ]AS|CHEQUE|TRANSFERENCIA|DEPÓSITO)\b',
        ],
        # Campos específicos de punto de venta
        "serial": [
            r'(?:SERIAL|S\.N\.?|SERIE)[\s\.:]*\s*[:#]?\s*(\d+)',
        ],
        "ter": [
            r'(?:TER|TERMINAL)[\s\.:]*\s*[:#]?\s*(\d+)',
        ],
        "afil": [
            r'(?:AFIL|AFILIADO)[\s\.:]*\s*[:#]?\s*(\d+)',
        ],
        "adquirente": [
            r'(?:ADQUIRIENTE|ADQUIRENTE)[\s\.:]*\s*[:#]?\s*(\d+)',
        ],
        "lote": [
            r'(?:LOTE)[\s\.:]*\s*[:#]?\s*(\d*)',
        ],
        "trace": [
            r'(?:TRACE)[\s\.:]*\s*[:#]?\s*(\d*)',
        ],
        "banco": [
            r'(?:BANCO)[\s\.:]*\s*[:#]?\s*([A-ZÁÉÍÓÚÑ\s]+)',
        ],
        "tipo_transaccion": [
            r'\b(COMPRA|VENTA)\b',
        ],
    }
    
    def __init__(self):
        self._field_matches: Dict[str, List[FieldMatch]] = {}
    
    def extract_all(self, text: str, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> Dict[str, str]:
        """
        Extrae todos los campos del texto OCR.
        
        Args:
            text: Texto completo del OCR
            words: Lista de palabras con coordenadas (texto, bbox, confianza)
            
        Returns:
            Diccionario con campos extraídos
        """
        results = {}
        
        for field_name, patterns in self.PATTERNS.items():
            matches = self._extract_field(text, field_name, patterns)
            if matches:
                # Tomar el match con mayor confianza
                best_match = max(matches, key=lambda m: m.confidence)
                results[field_name] = best_match.value
                self._field_matches[field_name] = matches
        
        return results
    
    def _extract_field(self, text: str, field_name: str, patterns: List[str]) -> List[FieldMatch]:
        """
        Extrae un campo específico usando múltiples patrones.
        
        Args:
            text: Texto completo
            field_name: Nombre del campo
            patterns: Lista de patrones regex a probar
            
        Returns:
            Lista de FieldMatch encontrados
        """
        matches = []
        
        for pattern in patterns:
            try:
                for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                    value = match.group(1) if match.groups() else match.group(0)
                    
                    # Calcular confianza basado en la especificidad del patrón
                    confidence = self._calculate_pattern_confidence(pattern, value)
                    
                    field_match = FieldMatch(
                        field_name=field_name,
                        value=value.strip(),
                        confidence=confidence,
                        position=(match.start(), 0, match.end(), 0),  # Posición aproximada
                        pattern_used=pattern
                    )
                    matches.append(field_match)
            except re.error:
                continue
        
        return matches
    
    def _calculate_pattern_confidence(self, pattern: str, value: str) -> float:
        """
        Calcula la confianza de un match basado en la especificidad del patrón.
        
        Patrones más específicos (con más contexto) tienen mayor confianza.
        """
        base_confidence = 0.5
        
        # Aumentar confianza si el patrón tiene contexto (palabras clave)
        if any(keyword in pattern.upper() for keyword in ['FACTURA', 'CONTROL', 'RIF', 'TOTAL', 'IVA']):
            base_confidence += 0.2
        
        # Aumentar confianza si el valor tiene formato válido
        if self._validate_field_format(pattern, value):
            base_confidence += 0.2
        
        # Aumentar confianza si el patrón es específico (más largo)
        if len(pattern) > 30:
            base_confidence += 0.1
        
        return min(base_confidence, 1.0)
    
    def _validate_field_format(self, pattern: str, value: str) -> bool:
        """
        Valida que el valor extraído tenga el formato esperado.
        """
        # Validar número de factura
        if 'FACTURA' in pattern.upper() or 'FC' in pattern.upper():
            return bool(re.match(r'[A-Z]?\d{3}[-]\d{6,7}', value))
        
        # Validar RIF
        if 'RIF' in pattern.upper():
            return bool(re.match(r'[VJEGPC][\-.\s]?\d{8}[\-.\s]?\d', value))
        
        # Validar fecha
        if 'FECHA' in pattern.upper() or 'DATE' in pattern.upper():
            return bool(re.match(r'\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}', value))
        
        # Validar monto
        if any(kw in pattern.upper() for kw in ['TOTAL', 'IVA', 'BASE', 'SUBTOTAL']):
            return bool(re.match(r'[\d.,]+', value))
        
        return True
    
    def extract_with_position(self, words: List[Tuple[str, Tuple[float, float, float, float], float]]) -> Dict[str, str]:
        """
        Extrae campos usando información posicional de las palabras.
        
        Agrupa palabras por región del documento y extrae campos
        basándose en la posición típica de cada campo en una factura.
        """
        if not words:
            return {}
        
        # Ordenar palabras por posición Y (de arriba a abajo)
        words_sorted = sorted(words, key=lambda w: w[1][1])
        
        # Dividir documento en regiones
        height = max(w[1][3] for w in words)
        regions = {
            'header': (0, height * 0.3),      # Top 30%
            'items': (height * 0.3, height * 0.7),  # Middle 40%
            'totals': (height * 0.7, height),     # Bottom 30%
        }
        
        # Agrupar palabras por región
        words_by_region = {
            'header': [],
            'items': [],
            'totals': []
        }
        
        for word in words_sorted:
            y_center = word[1][1]
            for region_name, (y_min, y_max) in regions.items():
                if y_min <= y_center <= y_max:
                    words_by_region[region_name].append(word)
                    break
        
        # Reconstruir texto por región
        text_by_region = {}
        for region_name, region_words in words_by_region.items():
            region_words_sorted = sorted(region_words, key=lambda w: (w[1][1], w[1][0]))
            text_by_region[region_name] = ' '.join(w[0] for w in region_words_sorted)
        
        # Extraer campos específicos por región
        results = {}
        
        # Header: número de factura, fecha, RIF, razón social
        header_text = text_by_region.get('header', '')
        results.update(self._extract_from_text(header_text, [
            'numero_factura', 'numero_control', 'fecha', 'rif_emisor', 'razon_social'
        ]))
        
        # Totals: base imponible, IVA, total
        totals_text = text_by_region.get('totals', '')
        results.update(self._extract_from_text(totals_text, [
            'base_imponible', 'iva', 'total'
        ]))
        
        # Items: condición de pago, banco
        items_text = text_by_region.get('items', '')
        results.update(self._extract_from_text(items_text, [
            'condicion_pago', 'banco'
        ]))
        
        return results
    
    def _extract_from_text(self, text: str, field_names: List[str]) -> Dict[str, str]:
        """Extrae campos específicos de un texto."""
        results = {}
        for field_name in field_names:
            if field_name in self.PATTERNS:
                patterns = self.PATTERNS[field_name]
                matches = self._extract_field(text, field_name, patterns)
                if matches:
                    best_match = max(matches, key=lambda m: m.confidence)
                    results[field_name] = best_match.value
        return results
    
    def get_field_matches(self) -> Dict[str, List[FieldMatch]]:
        """Retorna todos los matches encontrados con sus metadatos."""
        return self._field_matches.copy()


def extract_fields_advanced(text: str, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> Dict[str, str]:
    """
    Función de conveniencia para extracción avanzada de campos.
    
    Args:
        text: Texto completo del OCR
        words: Lista de palabras con coordenadas (opcional)
        
    Returns:
        Diccionario con campos extraídos
    """
    extractor = AdvancedFieldExtractor()
    
    if words:
        # Usar extracción posicional si hay coordenadas
        return extractor.extract_with_position(words)
    else:
        # Usar extracción basada en texto
        return extractor.extract_all(text)


def validate_extracted_fields(fields: Dict[str, str]) -> Dict[str, List[str]]:
    """
    Valida los campos extraídos y retorna errores encontrados.
    
    Args:
        fields: Diccionario de campos extraídos
        
    Returns:
        Diccionario con errores por campo
    """
    errors = {}
    
    # Validar RIF
    if 'rif_emisor' in fields and fields['rif_emisor']:
        rif = fields['rif_emisor'].upper()
        if not re.match(r'[VJEGPC][\-.\s]?\d{8}[\-.\s]?\d', rif):
            errors['rif_emisor'] = ['Formato de RIF inválido']
    
    # Validar fecha
    if 'fecha' in fields and fields['fecha']:
        date = fields['fecha']
        if not re.match(r'\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}', date):
            errors['fecha'] = ['Formato de fecha inválido']
    
    # Validar número de factura
    if 'numero_factura' in fields and fields['numero_factura']:
        num = fields['numero_factura']
        if not re.match(r'[A-Z]?\d{3}[-]\d{6,7}', num):
            errors['numero_factura'] = ['Formato de número de factura inválido']
    
    return errors
