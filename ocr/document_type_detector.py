"""
Detector de Tipo de Documento
=============================
Detecta el tipo de documento (factura, recibo, nota de crédito, etc.)

Tipos de documentos soportados:
  - Factura (estándar, POS, electrónica)
  - Recibo
  - Nota de crédito
  - Nota de débito
  - Orden de compra
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class DocumentType(Enum):
    """Tipos de documentos soportados."""
    INVOICE = "factura"
    RECEIPT = "recibo"
    CREDIT_NOTE = "nota_credito"
    DEBIT_NOTE = "nota_debito"
    PURCHASE_ORDER = "orden_compra"
    UNKNOWN = "desconocido"


@dataclass
class DocumentDetection:
    """Resultado de detección de tipo de documento."""
    document_type: DocumentType
    confidence: float
    indicators: List[str]
    subtype: str = ""  # POS, electrónica, etc.


class DocumentTypeDetector:
    """
    Detector de tipo de documento.
    
    Analiza el texto OCR para determinar el tipo de documento.
    """
    
    # Indicadores por tipo de documento
    INDICATORS = {
        DocumentType.INVOICE: [
            r'FACTURA',
            r'FAC\.?',
            r'FC[OA]?',
            r'COMPROBANTE',
            r'N[°ºO]?\s*FACTURA',
            r'BASE\s*IMPOSIBLE',
            r'IVA',
            r'SUBTOTAL',
        ],
        DocumentType.RECEIPT: [
            r'RECIBO',
            r'REC\.?',
            r'PAGO',
            r'ABONO',
            r'RECIB[ÍI]',
        ],
        DocumentType.CREDIT_NOTE: [
            r'NOTA\s*DE\s*CR[ÉÉ]DITO',
            r'NC',
            r'N\.?C\.?',
            r'CREDIT\s*NOTE',
        ],
        DocumentType.DEBIT_NOTE: [
            r'NOTA\s*DE\s*D[ÉÉ]BITO',
            r'ND',
            r'N\.?D\.?',
            r'DEBIT\s*NOTE',
        ],
        DocumentType.PURCHASE_ORDER: [
            r'ORDEN\s*DE\s*COMPRA',
            r'OC',
            r'O\.?C\.?',
            r'PURCHASE\s*ORDER',
            r'COTIZACI[ÓO]N',
        ],
    }
    
    # Indicadores de subtipos
    SUBTYPE_INDICATORS = {
        'pos': [
            r'SERIAL',
            r'TER',
            r'AFIL',
            r'ADQUIRIENTE',
            r'VISA',
            r'MASTERCARD',
        ],
        'electronica': [
            r'FACTURA\s*ELECTR[ÓO]NICA',
            r'FEE',
            r'CONTROL\s*FISCAL',
            r'QRCODE',
            r'QR',
        ],
    }
    
    def __init__(self):
        self._detection: Optional[DocumentDetection] = None
    
    def detect(self, text: str) -> DocumentDetection:
        """
        Detecta el tipo de documento.
        
        Args:
            text: Texto completo del OCR
            
        Returns:
            DocumentDetection con el tipo detectado
        """
        text_upper = text.upper()
        
        scores = {}
        indicators_found = {}
        
        # Calcular score para cada tipo
        for doc_type, patterns in self.INDICATORS.items():
            score = 0
            found = []
            
            for pattern in patterns:
                matches = re.findall(pattern, text_upper)
                if matches:
                    score += len(matches)
                    found.extend(matches)
            
            scores[doc_type] = score
            indicators_found[doc_type] = found
        
        # Determinar tipo con mayor score
        max_score = max(scores.values()) if scores else 0
        
        if max_score == 0:
            return DocumentDetection(
                document_type=DocumentType.UNKNOWN,
                confidence=0.0,
                indicators=[]
            )
        
        # Encontrar tipo(s) con máximo score
        max_types = [dt for dt, score in scores.items() if score == max_score]
        
        # Si hay empate, preferir factura
        if len(max_types) > 1:
            if DocumentType.INVOICE in max_types:
                detected_type = DocumentType.INVOICE
            else:
                detected_type = max_types[0]
        else:
            detected_type = max_types[0]
        
        # Calcular confianza basada en score total
        total_indicators = sum(len(p) for p in self.INDICATORS.values())
        confidence = min(1.0, max_score / max(total_indicators * 0.3, 1))
        
        # Detectar subtipo
        subtype = self._detect_subtype(text_upper)
        
        detection = DocumentDetection(
            document_type=detected_type,
            confidence=confidence,
            indicators=indicators_found[detected_type],
            subtype=subtype
        )
        
        self._detection = detection
        return detection
    
    def _detect_subtype(self, text_upper: str) -> str:
        """Detecta el subtipo del documento."""
        for subtype, patterns in self.SUBTYPE_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, text_upper):
                    return subtype
        return ""
    
    def is_invoice(self, text: str) -> bool:
        """Determina si el documento es una factura."""
        detection = self.detect(text)
        return detection.document_type == DocumentType.INVOICE
    
    def is_pos_invoice(self, text: str) -> bool:
        """Determina si es una factura de punto de venta."""
        detection = self.detect(text)
        return (detection.document_type == DocumentType.INVOICE and 
                detection.subtype == 'pos')
    
    def is_electronic_invoice(self, text: str) -> bool:
        """Determina si es una factura electrónica."""
        detection = self.detect(text)
        return (detection.document_type == DocumentType.INVOICE and 
                detection.subtype == 'electronica')
    
    def get_detection(self) -> Optional[DocumentDetection]:
        """Retorna la última detección realizada."""
        return self._detection


def detect_document_type(text: str) -> DocumentDetection:
    """
    Función de conveniencia para detectar el tipo de documento.
    
    Args:
        text: Texto completo del OCR
        
    Returns:
        DocumentDetection con el tipo detectado
    """
    detector = DocumentTypeDetector()
    return detector.detect(text)


def is_invoice(text: str) -> bool:
    """Función de conveniencia para determinar si es factura."""
    detector = DocumentTypeDetector()
    return detector.is_invoice(text)


def is_pos_invoice(text: str) -> bool:
    """Función de conveniencia para determinar si es factura POS."""
    detector = DocumentTypeDetector()
    return detector.is_pos_invoice(text)
