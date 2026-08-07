"""
Corrector Automático de Errores OCR
===================================
Corrige errores comunes de OCR en facturas venezolanas.

Tipos de correcciones:
  - Corrección de caracteres similares (O vs 0, I vs 1, etc.)
  - Corrección de palabras comunes mal reconocidas
  - Normalización de formatos
  - Corrección contextual basada en el campo
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Correction:
    """Corrección aplicada."""
    field: str
    original: str
    corrected: str
    confidence: float
    correction_type: str


class OCRCorrector:
    """
    Corrector de errores OCR para facturas venezolanas.
    
    Aplica correcciones específicas para el contexto de facturas.
    """
    
    # Mapeo de caracteres comunes mal reconocidos
    CHAR_CORRECTIONS = {
        'O': '0',  # O -> 0 en números
        'o': '0',
        'I': '1',  # I -> 1 en números
        'i': '1',
        'l': '1',
        'S': '5',  # S -> 5 en números
        's': '5',
        'Z': '2',  # Z -> 2 en números
        'z': '2',
        'B': '8',  # B -> 8 en números
        'G': '6',  # G -> 6 en números
    }
    
    # Palabras comunes mal reconocidas en facturas
    WORD_CORRECTIONS = {
        'FACTUBA': 'FACTURA',
        'FACTURA': 'FACTURA',
        'FACTUIRA': 'FACTURA',
        'FACIURA': 'FACTURA',
        'RIF': 'RIF',
        'R.I.F.': 'RIF',
        'TOTAL': 'TOTAL',
        'TOIAL': 'TOTAL',
        'TOTA': 'TOTAL',
        'IVA': 'IVA',
        'I.V.A.': 'IVA',
        'BASE': 'BASE',
        'BACE': 'BASE',
        'MONTO': 'MONTO',
        'PAGO': 'PAGO',
        'FECHA': 'FECHA',
        'FECHAI': 'FECHA',
    }
    
    def __init__(self):
        self._corrections_applied: List[Correction] = []
    
    def correct_field(self, field_name: str, value: str) -> Tuple[str, List[Correction]]:
        """
        Aplica correcciones a un campo específico.
        
        Args:
            field_name: Nombre del campo
            value: Valor extraído por OCR
            
        Returns:
            (valor_corregido, lista_de_correcciones)
        """
        if not value:
            return value, []
        
        corrections = []
        corrected = value
        
        # Aplicar correcciones específicas por tipo de campo
        if field_name in ['numero_factura', 'numero_control']:
            corrected, field_corrections = self._correct_number_field(corrected)
            corrections.extend(field_corrections)
        
        elif field_name == 'rif_emisor':
            corrected, field_corrections = self._correct_rif_field(corrected)
            corrections.extend(field_corrections)
        
        elif field_name == 'fecha':
            corrected, field_corrections = self._correct_date_field(corrected)
            corrections.extend(field_corrections)
        
        elif field_name in ['base_imponible', 'iva', 'total']:
            corrected, field_corrections = self._correct_amount_field(corrected)
            corrections.extend(field_corrections)
        
        else:
            # Correcciones generales de texto
            corrected, field_corrections = self._correct_text_field(corrected)
            corrections.extend(field_corrections)
        
        self._corrections_applied.extend(corrections)
        return corrected, corrections
    
    def _correct_number_field(self, value: str) -> Tuple[str, List[Correction]]:
        """Corrige campos numéricos (número de factura, control)."""
        corrections = []
        corrected = value
        
        # Corregir caracteres similares en números
        corrected_chars = []
        for char in corrected:
            if char in self.CHAR_CORRECTIONS and char.isalpha():
                # Solo corregir si está en contexto numérico
                if corrected_chars and corrected_chars[-1].isdigit():
                    corrected_chars.append(self.CHAR_CORRECTIONS[char])
                    corrections.append(Correction(
                        field='number',
                        original=char,
                        corrected=self.CHAR_CORRECTIONS[char],
                        confidence=0.8,
                        correction_type='char_substitution'
                    ))
                else:
                    corrected_chars.append(char)
            else:
                corrected_chars.append(char)
        
        corrected = ''.join(corrected_chars)
        
        # Normalizar formato de número de factura
        corrected = self._normalize_invoice_number(corrected)
        
        return corrected, corrections
    
    def _correct_rif_field(self, value: str) -> Tuple[str, List[Correction]]:
        """Corrige campos de RIF."""
        corrections = []
        corrected = value.upper()
        
        # Asegurar formato J-12345678-9
        # Extraer letra, dígitos y dígito verificador
        match = re.match(r'([VJEGPC])[\-.\s]*(\d{8})[\-.\s]*(\d)', corrected)
        
        if match:
            letter, digits, check = match.groups()
            corrected = f"{letter}-{digits}-{check}"
        else:
            # Intentar extraer de formato pegado
            match2 = re.match(r'([VJEGPC])(\d{8})(\d)', corrected)
            if match2:
                letter, digits, check = match2.groups()
                corrected = f"{letter}-{digits}-{check}"
                corrections.append(Correction(
                    field='rif',
                    original=value,
                    corrected=corrected,
                    confidence=0.9,
                    correction_type='format_normalization'
                ))
        
        return corrected, corrections
    
    def _correct_date_field(self, value: str) -> Tuple[str, List[Correction]]:
        """Corrige campos de fecha."""
        corrections = []
        corrected = value
        
        # Normalizar separadores de fecha
        corrected = re.sub(r'[.\s]', '/', corrected)
        
        # Corregir caracteres en fechas
        corrected_chars = []
        for char in corrected:
            if char in self.CHAR_CORRECTIONS and char.isalpha():
                corrected_chars.append(self.CHAR_CORRECTIONS[char])
            else:
                corrected_chars.append(char)
        
        corrected = ''.join(corrected_chars)
        
        return corrected, corrections
    
    def _correct_amount_field(self, value: str) -> Tuple[str, List[Correction]]:
        """Corrige campos de monto."""
        corrections = []
        corrected = value
        
        # Corregir caracteres en montos
        corrected_chars = []
        for char in corrected:
            if char in self.CHAR_CORRECTIONS and char.isalpha():
                corrected_chars.append(self.CHAR_CORRECTIONS[char])
            else:
                corrected_chars.append(char)
        
        corrected = ''.join(corrected_chars)
        
        # Normalizar separadores decimales
        # En Venezuela, la coma es separador decimal
        if ',' in corrected and '.' in corrected:
            # Ambos separadores presentes - asumir formato europeo
            corrected = corrected.replace('.', '').replace(',', '.')
        elif ',' in corrected:
            # Solo coma - asumir separador decimal
            corrected = corrected.replace(',', '.')
        
        # Eliminar espacios en montos
        corrected = corrected.replace(' ', '')
        
        return corrected, corrections
    
    def _correct_text_field(self, value: str) -> Tuple[str, List[Correction]]:
        """Corrige campos de texto general."""
        corrections = []
        
        # Si el valor es un número (float/int), convertirlo a string
        if isinstance(value, (float, int)):
            corrected = str(value)
        else:
            corrected = str(value).upper()
        
        # Corregir palabras comunes mal reconocidas
        for wrong, right in self.WORD_CORRECTIONS.items():
            if wrong in corrected:
                corrected = corrected.replace(wrong, right)
                corrections.append(Correction(
                    field='text',
                    original=wrong,
                    corrected=right,
                    confidence=0.7,
                    correction_type='word_substitution'
                ))
        
        return corrected, corrections
    
    def _normalize_invoice_number(self, value: str) -> str:
        """Normaliza el formato del número de factura."""
        # Asegurar formato F001-000001 o 001-000001
        value = value.upper()
        
        # Eliminar espacios
        value = value.replace(' ', '')
        
        # Normalizar guiones
        value = re.sub(r'[.\s]', '-', value)
        
        return value
    
    def correct_all_fields(self, fields: Dict[str, str]) -> Tuple[Dict[str, str], List[Correction]]:
        """
        Aplica correcciones a todos los campos.
        
        Args:
            fields: Diccionario de campos extraídos
            
        Returns:
            (campos_corregidos, todas_las_correcciones)
        """
        corrected_fields = {}
        all_corrections = []
        
        for field_name, value in fields.items():
            corrected_value, corrections = self.correct_field(field_name, value)
            corrected_fields[field_name] = corrected_value
            all_corrections.extend(corrections)
        
        return corrected_fields, all_corrections
    
    def get_corrections(self) -> List[Correction]:
        """Retorna todas las correcciones aplicadas."""
        return self._corrections_applied.copy()
    
    def reset(self):
        """Limpia el historial de correcciones."""
        self._corrections_applied = []


class ContextualCorrector:
    """
    Corrector contextual basado en relaciones entre campos.
    
    Usa el contexto de otros campos para corregir errores.
    """
    
    def __init__(self):
        self._ocr_corrector = OCRCorrector()
    
    def correct_with_context(self, fields: Dict[str, str]) -> Tuple[Dict[str, str], List[Correction]]:
        """
        Aplica correcciones usando contexto entre campos.
        
        Args:
            fields: Diccionario de campos extraídos
            
        Returns:
            (campos_corregidos, correcciones)
        """
        # Primero aplicar correcciones básicas
        corrected_fields, basic_corrections = self._ocr_corrector.correct_all_fields(fields)
        
        # Luego aplicar correcciones contextuales
        contextual_corrections = []
        
        # Corrección: Si el total no coincide con base + IVA, recalcular IVA
        if 'base_imponible' in corrected_fields and 'iva' in corrected_fields and 'total' in corrected_fields:
            base = self._parse_amount(corrected_fields['base_imponible'])
            iva = self._parse_amount(corrected_fields['iva'])
            total = self._parse_amount(corrected_fields['total'])
            
            if base and total:
                # Intentar calcular IVA esperado (16%)
                expected_iva_16 = base * 0.16
                expected_iva_8 = base * 0.08
                
                # Si el IVA extraído está lejos de ambos, recalcular
                if iva:
                    diff_16 = abs(iva - expected_iva_16)
                    diff_8 = abs(iva - expected_iva_8)
                    
                    if diff_16 > base * 0.05 and diff_8 > base * 0.05:
                        # IVA parece incorrecto, usar el más cercano
                        if diff_16 < diff_8:
                            corrected_fields['iva'] = f"{expected_iva_16:.2f}"
                            contextual_corrections.append(Correction(
                                field='iva',
                                original=f"{iva:.2f}",
                                corrected=f"{expected_iva_16:.2f}",
                                confidence=0.6,
                                correction_type='contextual_recalculation'
                            ))
                        else:
                            corrected_fields['iva'] = f"{expected_iva_8:.2f}"
                            contextual_corrections.append(Correction(
                                field='iva',
                                original=f"{iva:.2f}",
                                corrected=f"{expected_iva_8:.2f}",
                                confidence=0.6,
                                correction_type='contextual_recalculation'
                            ))
        
        # Corrección: Si el RIF tiene formato inválido, intentar corregir
        if 'rif_emisor' in corrected_fields:
            rif = corrected_fields['rif_emisor']
            if not self._validate_rif(rif):
                # Intentar corregir caracteres similares
                corrected_rif, rif_corrections = self._ocr_corrector.correct_field('rif_emisor', rif)
                if corrected_rif != rif and self._validate_rif(corrected_rif):
                    corrected_fields['rif_emisor'] = corrected_rif
                    contextual_corrections.extend(rif_corrections)
        
        all_corrections = basic_corrections + contextual_corrections
        return corrected_fields, all_corrections
    
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
    
    def _validate_rif(self, rif: str) -> bool:
        """Valida el formato de un RIF."""
        rif = rif.upper()
        return bool(re.match(r'[VJEGPC][\-.\s]?\d{8}[\-.\s]?\d', rif))


def correct_ocr_fields(fields: Dict[str, str], use_context: bool = True) -> Tuple[Dict[str, str], List[Correction]]:
    """
    Función de conveniencia para corregir campos OCR.
    
    Args:
        fields: Diccionario de campos extraídos
        use_context: Si True, usa correcciones contextuales
        
    Returns:
        (campos_corregidos, correcciones)
    """
    if use_context:
        corrector = ContextualCorrector()
        return corrector.correct_with_context(fields)
    else:
        corrector = OCRCorrector()
        return corrector.correct_all_fields(fields)
