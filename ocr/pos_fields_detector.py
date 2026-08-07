"""
Detector de Campos de Punto de Venta (POS) Venezolanos
======================================================
Detecta campos específicos de facturas de punto de venta en Venezuela.

Campos típicos de POS:
  - Serial: Número de serie del equipo
  - TER: Terminal
  - AFIL: Afiliado
  - Adquirente: Código de adquirente de tarjeta
  - Lote: Número de lote de transacción
  - Trace: Número de trace/rastreo
  - Tipo de transacción: COMPRA/VENTA
  - Banco: Banco de la tarjeta
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class POSField:
    """Campo de punto de venta detectado."""
    field_name: str
    value: str
    confidence: float
    position: Tuple[int, int, int, int]


class POSFieldsDetector:
    """
    Detector de campos específicos de facturas de punto de venta venezolanas.
    
    Detecta campos como Serial, TER, AFIL, adquirente, lote, trace, etc.
    """
    
    # Patrones específicos para campos POS
    POS_PATTERNS = {
        "serial": [
            r'SERIAL\s*[:#]?\s*(\d{8,12})',
            r'S\.N\.?\s*[:#]?\s*(\d{8,12})',
            r'SERIE\s*[:#]?\s*(\d{8,12})',
            r'(\d{8,12})\s*SERIAL',
        ],
        "ter": [
            r'TER\s*[:#]?\s*(\d{4,8})',
            r'TERMINAL\s*[:#]?\s*(\d{4,8})',
            r'TERMINAL\s*[:#]?\s*(\d{4,8})',
            r'(\d{4,8})\s*TER',
        ],
        "afil": [
            r'AFIL\s*[:#]?\s*(\d{6,10})',
            r'AFILIADO\s*[:#]?\s*(\d{6,10})',
            r'(\d{6,10})\s*AFIL',
        ],
        "adquirente": [
            r'ADQUIRIENTE\s*[:#]?\s*(\d{6,15})',
            r'ADQUIRENTE\s*[:#]?\s*(\d{6,15})',
            r'(\d{6,15})\s*ADQUIRIENTE',
        ],
        "lote": [
            r'LOTE\s*[:#]?\s*(\d{4,10})',
            r'(\d{4,10})\s*LOTE',
        ],
        "trace": [
            r'TRACE\s*[:#]?\s*(\d{6,12})',
            r'(\d{6,12})\s*TRACE',
        ],
        "tipo_transaccion": [
            r'\b(COMPRA|VENTA)\b',
        ],
        "banco": [
            r'BANCAMIGA|BANCO\s*DE\s*VENEZUELA|MERCANTIL|PROVINCIAL|BANESCO|BNC|BOD|TESORO|BANCO\s*ACTIVO|BANCO\s*CARONÍ|BANCO\s*PLAZA|DELTABANCO|BANCO\s*SOFITASA|BANCO\s*EXTERIOR|100%\s*BANCO',
        ],
        "tipo_tarjeta": [
            r'(VISA|MASTERCARD|MAESTRO|AMEX|DISCOVER|ELECTRON)',
        ],
        "ultimos_digitos": [
            r'\*{4,}\s*(\d{4})',  # ****1234
            r'XXXX\s*(\d{4})',
            r'(\d{4})\s*\*{4,}',
        ],
        "autorizacion": [
            r'AUTORIZACIÓN\s*[:#]?\s*(\d{6,10})',
            r'AUTORIZACION\s*[:#]?\s*(\d{6,10})',
            r'AUTH\s*[:#]?\s*(\d{6,10})',
            r'(\d{6,10})\s*AUTORIZACIÓN',
        ],
        "fecha_hora_transaccion": [
            r'FECHA/HORA\s*[:#]?\s*(\d{2}[-]\d{2}[-]\d{4}\s+\d{2}:\d{2})',
            r'FECHA\s*HORA\s*[:#]?\s*(\d{2}[-]\d{2}[-]\d{4}\s+\d{2}:\d{2})',
        ],
    }
    
    def __init__(self):
        self._detected_fields: Dict[str, POSField] = {}
    
    def detect(self, text: str, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> Dict[str, str]:
        """
        Detecta campos POS en el texto OCR.
        
        Args:
            text: Texto completo del OCR
            words: Lista de palabras con coordenadas (opcional)
            
        Returns:
            Diccionario con campos POS detectados
        """
        results = {}
        
        for field_name, patterns in self.POS_PATTERNS.items():
            matches = self._extract_field(text, field_name, patterns)
            if matches:
                # Tomar el match con mayor confianza
                best_match = max(matches, key=lambda m: m.confidence)
                results[field_name] = best_match.value
                self._detected_fields[field_name] = best_match
        
        return results
    
    def _extract_field(self, text: str, field_name: str, patterns: List[str]) -> List[POSField]:
        """
        Extrae un campo específico usando múltiples patrones.
        
        Args:
            text: Texto completo
            field_name: Nombre del campo
            patterns: Lista de patrones regex a probar
            
        Returns:
            Lista de POSField encontrados
        """
        matches = []
        
        for pattern in patterns:
            try:
                for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                    value = match.group(1) if match.groups() else match.group(0)
                    
                    # Calcular confianza
                    confidence = self._calculate_pos_confidence(pattern, value, field_name)
                    
                    pos_field = POSField(
                        field_name=field_name,
                        value=value.strip(),
                        confidence=confidence,
                        position=(match.start(), 0, match.end(), 0)
                    )
                    matches.append(pos_field)
            except re.error:
                continue
        
        return matches
    
    def _calculate_pos_confidence(self, pattern: str, value: str, field_name: str) -> float:
        """
        Calcula la confianza de un match de campo POS.
        
        Patrones con más contexto tienen mayor confianza.
        """
        base_confidence = 0.5
        
        # Aumentar confianza si el patrón tiene el nombre del campo
        if field_name.upper() in pattern.upper():
            base_confidence += 0.3
        
        # Aumentar confianza si el valor tiene formato válido
        if self._validate_pos_format(field_name, value):
            base_confidence += 0.2
        
        return min(base_confidence, 1.0)
    
    def _validate_pos_format(self, field_name: str, value: str) -> bool:
        """
        Valida que el valor tenga el formato esperado para el campo POS.
        """
        # Validar campos numéricos
        if field_name in ['serial', 'ter', 'afil', 'adquirente', 'lote', 'trace', 'autorizacion']:
            return value.isdigit() and len(value) >= 4
        
        # Validar tipo de transacción
        if field_name == 'tipo_transaccion':
            return value.upper() in ['COMPRA', 'VENTA']
        
        # Validar tipo de tarjeta
        if field_name == 'tipo_tarjeta':
            return value.upper() in ['VISA', 'MASTERCARD', 'MAESTRO', 'AMEX', 'DISCOVER', 'ELECTRON']
        
        # Validar últimos dígitos
        if field_name == 'ultimos_digitos':
            return value.isdigit() and len(value) == 4
        
        return True
    
    def detect_card_info(self, text: str) -> Dict[str, str]:
        """
        Detecta información específica de tarjeta de crédito/débito.
        
        Args:
            text: Texto completo del OCR
            
        Returns:
            Diccionario con información de tarjeta
        """
        card_info = {}
        
        # Detectar tipo de tarjeta
        card_patterns = {
            'tipo_tarjeta': r'(VISA|MASTERCARD|MAESTRO|AMEX|DISCOVER|ELECTRON)',
            'ultimos_digitos': r'\*{4,}\s*(\d{4})',
            'autorizacion': r'AUTORIZACIÓN\s*[:#]?\s*(\d{6,10})',
        }
        
        for field_name, pattern in card_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1) if match.groups() else match.group(0)
                card_info[field_name] = value.strip()
        
        return card_info
    
    def is_pos_invoice(self, text: str) -> bool:
        """
        Determina si la factura es de punto de venta.
        
        Args:
            text: Texto completo del OCR
            
        Returns:
            True si parece ser una factura POS
        """
        pos_indicators = [
            'SERIAL', 'TER', 'AFIL', 'ADQUIRIENTE', 'LOTE', 'TRACE',
            'TERMINAL', 'AFILIADO', 'AUTORIZACIÓN', 'VISA', 'MASTERCARD'
        ]
        
        text_upper = text.upper()
        indicator_count = sum(1 for indicator in pos_indicators if indicator in text_upper)
        
        # Si hay 2 o más indicadores POS, es probablemente una factura POS
        return indicator_count >= 2
    
    def get_detected_fields(self) -> Dict[str, POSField]:
        """Retorna todos los campos POS detectados."""
        return self._detected_fields.copy()


def detect_pos_fields(text: str, words: List[Tuple[str, Tuple[float, float, float, float], float]] = None) -> Dict[str, str]:
    """
    Función de conveniencia para detectar campos POS.
    
    Args:
        text: Texto completo del OCR
        words: Lista de palabras con coordenadas (opcional)
        
    Returns:
        Diccionario con campos POS detectados
    """
    detector = POSFieldsDetector()
    return detector.detect(text, words)


def is_pos_invoice(text: str) -> bool:
    """
    Función de conveniencia para determinar si es una factura POS.
    
    Args:
        text: Texto completo del OCR
        
    Returns:
        True si parece ser una factura POS
    """
    detector = POSFieldsDetector()
    return detector.is_pos_invoice(text)
