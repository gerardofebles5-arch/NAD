"""
Corrector NLP Avanzado para OCR
===============================
Corrección contextual usando técnicas de NLP ligeras.

Funcionalidades:
  - Corrección de palabras basada en similitud
  - Normalización de términos de facturas
  - Corrección contextual por campo
  - Diccionario de términos venezolanos
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class NLPCorrection:
    """Corrección NLP aplicada."""
    original: str
    corrected: str
    confidence: float
    method: str


class NLPCorrector:
    """
    Corrector NLP para corrección contextual de OCR.
    
    Usa técnicas ligeras sin dependencias pesadas.
    """
    
    # Diccionario de términos comunes en facturas venezolanas
    VENEZUELAN_TERMS = {
        'factura': ['factra', 'facutra', 'fatura', 'factira', 'facura'],
        'rif': ['r.i.f', 'rif', 'r f', 'r-f'],
        'razon_social': ['razon social', 'razon social', 'razon_social', 'razon-soc'],
        'base_imponible': ['base imponible', 'base imponible', 'base_imponible', 'base imponibl'],
        'iva': ['iva', 'i.v.a', 'i v a', 'iv a'],
        'total': ['total', 'totl', 'totla', 'toal'],
        'fecha': ['fecha', 'fcha', 'feha', 'fecah'],
        'monto': ['monto', 'mont', 'monta', 'monot'],
        'bolivar': ['bolivar', 'boli var', 'bs', 'b.s', 'bs.'],
        'dolar': ['dolar', 'dolar', 'usd', 'u.s.d', 'u s d'],
        'cedula': ['cedula', 'cedula', 'cédula', 'cedul'],
        'telefono': ['telefono', 'telefon', 'telf', 'telf.'],
        'direccion': ['direccion', 'direccion', 'direcc', 'dir.'],
        'serial': ['serial', 'seral', 'serail', 'seri al'],
        'autorizacion': ['autorizacion', 'autorizacion', 'autoriz', 'auth'],
        'tarjeta': ['tarjeta', 'tarjet', 'tarj', 'tarj.'],
    }
    
    # Patrones de corrección por campo
    FIELD_PATTERNS = {
        'numero_factura': r'[A-Z]{1,3}[-\s]?\d{3}[-\s]?\d{6,7}',
        'rif': r'[VJEGPC][-.\s]?\d{8}[-.\s]?\d',
        'fecha': r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}',
        'monto': r'[\d.,]+\s*(?:BS|USD|EUR)?',
    }
    
    def __init__(self):
        self._corrections: List[NLPCorrection] = []
    
    def correct_text(self, text: str, field_name: str = None) -> Tuple[str, List[NLPCorrection]]:
        """
        Aplica corrección NLP al texto.
        
        Args:
            text: Texto a corregir
            field_name: Nombre del campo (opcional, para corrección específica)
            
        Returns:
            (texto_corregido, lista_de_correcciones)
        """
        self._corrections = []
        corrected = text
        
        # 1. Normalización básica
        corrected = self._normalize_basic(corrected)
        
        # 2. Corrección de términos venezolanos
        corrected = self._correct_venezuelan_terms(corrected)
        
        # 3. Corrección específica por campo
        if field_name:
            corrected = self._correct_by_field(corrected, field_name)
        
        # 4. Corrección contextual
        corrected = self._correct_contextual(corrected)
        
        return corrected, self._corrections
    
    def _normalize_basic(self, text: str) -> str:
        """Normalización básica del texto."""
        # Eliminar espacios múltiples
        text = re.sub(r'\s+', ' ', text)
        # Eliminar caracteres especiales innecesarios
        text = re.sub(r'[^\w\s\-\.\,\:\;\/\(\)]', '', text)
        return text.strip()
    
    def _correct_venezuelan_terms(self, text: str) -> str:
        """Corrige términos venezolanos comunes."""
        text_lower = text.lower()
        
        for correct_term, variations in self.VENEZUELAN_TERMS.items():
            for variation in variations:
                if variation in text_lower:
                    # Reemplazar con el término correcto
                    pattern = re.compile(re.escape(variation), re.IGNORECASE)
                    text = pattern.sub(correct_term, text)
                    self._corrections.append(NLPCorrection(
                        original=variation,
                        corrected=correct_term,
                        confidence=0.8,
                        method='venezuelan_terms'
                    ))
                    break
        
        return text
    
    def _correct_by_field(self, text: str, field_name: str) -> str:
        """Corrige basándose en el tipo de campo."""
        if field_name == 'numero_factura':
            return self._correct_invoice_number(text)
        elif field_name == 'rif':
            return self._correct_rif(text)
        elif field_name == 'fecha':
            return self._correct_date(text)
        elif field_name == 'total':
            return self._correct_amount(text)
        
        return text
    
    def _correct_invoice_number(self, text: str) -> str:
        """Corrige número de factura."""
        # Normalizar formato: F001-000001
        text = text.upper()
        text = re.sub(r'[.\s]', '-', text)
        
        # Asegurar formato correcto
        match = re.search(r'([A-Z]{1,3})[-\s]?(\d{3})[-\s]?(\d{6,7})', text)
        if match:
            letter, num1, num2 = match.groups()
            corrected = f"{letter}-{num1}-{num2}"
            if corrected != text:
                self._corrections.append(NLPCorrection(
                    original=text,
                    corrected=corrected,
                    confidence=0.9,
                    method='invoice_number'
                ))
            return corrected
        
        return text
    
    def _correct_rif(self, text: str) -> str:
        """Corrige RIF."""
        # Normalizar formato: J-12345678-9
        text = text.upper()
        text = re.sub(r'[.\s]', '-', text)
        
        # Asegurar formato correcto
        match = re.search(r'([VJEGPC])[-\s]?(\d{8})[-\s]?(\d)', text)
        if match:
            letter, digits, check = match.groups()
            corrected = f"{letter}-{digits}-{check}"
            if corrected != text:
                self._corrections.append(NLPCorrection(
                    original=text,
                    corrected=corrected,
                    confidence=0.9,
                    method='rif'
                ))
            return corrected
        
        return text
    
    def _correct_date(self, text: str) -> str:
        """Corrige fecha."""
        # Normalizar separadores
        text = re.sub(r'[.\-]', '/', text)
        
        # Intentar formato DD/MM/AAAA
        match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', text)
        if match:
            day, month, year = match.groups()
            # Normalizar a 2 dígitos
            day = day.zfill(2)
            month = month.zfill(2)
            year = year.zfill(4) if len(year) == 4 else f"20{year.zfill(2)}"
            corrected = f"{day}/{month}/{year}"
            if corrected != text:
                self._corrections.append(NLPCorrection(
                    original=text,
                    corrected=corrected,
                    confidence=0.85,
                    method='date'
                ))
            return corrected
        
        return text
    
    def _correct_amount(self, text: str) -> str:
        """Corrige monto."""
        # Normalizar separadores decimales
        text = text.replace(',', '.')
        
        # Eliminar caracteres no numéricos excepto punto
        text = re.sub(r'[^\d.]', '', text)
        
        # Asegurar formato correcto
        if text:
            try:
                amount = float(text)
                corrected = f"{amount:.2f}"
                if corrected != text:
                    self._corrections.append(NLPCorrection(
                        original=text,
                        corrected=corrected,
                        confidence=0.8,
                        method='amount'
                    ))
                return corrected
            except ValueError:
                pass
        
        return text
    
    def _correct_contextual(self, text: str) -> str:
        """Corrección contextual basada en el contexto del documento."""
        # Corrección de caracteres similares OCR
        ocr_corrections = {
            'O': '0',
            'o': '0',
            'I': '1',
            'i': '1',
            'l': '1',
            'S': '5',
            's': '5',
            'Z': '2',
            'z': '2',
            'B': '8',
            'G': '6',
        }
        
        corrected = text
        for wrong, right in ocr_corrections.items():
            # Solo corregir en contexto numérico
            pattern = re.compile(f'{wrong}(?=[0-9])')
            matches = pattern.findall(corrected)
            if matches:
                corrected = pattern.sub(right, corrected)
                if corrected != text:
                    self._corrections.append(NLPCorrection(
                        original=wrong,
                        corrected=right,
                        confidence=0.7,
                        method='contextual_ocr'
                    ))
        
        return corrected
    
    def get_corrections(self) -> List[NLPCorrection]:
        """Retorna las correcciones aplicadas."""
        return self._corrections.copy()


def correct_text_nlp(text: str, field_name: str = None) -> Tuple[str, List[NLPCorrection]]:
    """
    Función de conveniencia para corrección NLP.
    
    Args:
        text: Texto a corregir
        field_name: Nombre del campo (opcional)
        
    Returns:
        (texto_corregido, lista_de_correcciones)
    """
    corrector = NLPCorrector()
    return corrector.correct_text(text, field_name)
