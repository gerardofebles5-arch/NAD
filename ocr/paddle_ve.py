"""
πNAD — PaddleOCR VE: Reconocimiento especializado para facturas venezolanas
=============================================================================
Extiende PaddleOCR con:
  • Diccionario VE personalizado (RIF, IVA, montos, términos contables)
  • Post-processor estadístico con corrección por contexto VE
  • Score de confianza combinado (OCR + patrón VE)
  • Detección de formato NCF (Comprobantes Fiscales)

Uso:
    from ocr.paddle_ve import PaddleOCRVEEngine
    engine = PaddleOCRVEEngine()
    words = engine.recognize(image)  # [(texto, (x1,y1,x2,y2), confianza_ve)]
"""

import os
import re
import csv
import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from utils.config import CONFIG

# ──────────────────────────────────────────────
#  Constantes VE
# ──────────────────────────────────────────────

# Patrones de RIF venezolano
RIF_PATTERN = re.compile(r'\b([VJEGPC])[-.\s]?(\d{8})[-.\s]?(\d)\b', re.IGNORECASE)
RIF_NORMALIZED = re.compile(r'[VJEGPC]\d{9}', re.IGNORECASE)

# Patrones de IVA (alícuotas VE: 8%, 16% estándar)
IVA_PATTERN = re.compile(r'(?:IVA|I\.?\s*V\.?\s*A\.?)\s*(?::\s*)?(?:(\d{1,2}(?:[.,]\d)?)\s*%?\s*)?(?:.*?\$?\s*)?([\d.,]+)', re.IGNORECASE)
IVA_RATE_PATTERN = re.compile(r'(\d{1,2}(?:[.,]\d)?)\s*%')

# Total
TOTAL_PATTERN = re.compile(
    r'(?:TOTAL\s*(?:GENERAL|COMPROBANTE|A\s*PAGAR|BS\.?\s*)?\s*[:.\-]?\s*([\d.,]+))'
    r'|(?:MONTO\s*TOTAL\s*[:.\-]?\s*([\d.,]+))'
    r'|(?:GRAN\s*TOTAL\s*[:.\-]?\s*([\d.,]+))',
    re.IGNORECASE
)

# Base imponible
BASE_PATTERN = re.compile(
    r'(?:BASE\s*(?:IM[Pp]ONIBLE)?|SUBTOTAL|GRAVABLE|EXENTO)\s*[:.\-]?\s*([\d.,]+)',
    re.IGNORECASE
)

# Fecha VE (DD/MM/AAAA o DD-MM-AAAA)
DATE_PATTERN = re.compile(
    r'\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b'
)

# Números de control / factura VE (formatos comunes)
NCF_PATTERN = re.compile(
    r'(?:FACTURA|FACT\.?|NRO|N°|NUMERO|NÚMERO|CONTROL|CTRL|COMPROBANTE|DOC)\s*[:.\-]?\s*([A-Z]*\d[\dA-Z\-/]{3,})',
    re.IGNORECASE
)

# Teléfono VE (0XXX-XXXXXXX o +58 XXX-XXXXXXX)
PHONE_PATTERN = re.compile(
    r'\b(0\d{3}[-.\s]?\d{7})\b'
    r'|\b(\+58\s?\d{3}[-.\s]?\d{7})\b'
    r'|(?:TEL[EÉ]FONO|TELF|TLF)\s*[:.\-]?\s*(\S+)',
    re.IGNORECASE
)

# ──────────────────────────────────────────────
#  Normalizador de monto venezolano
# ──────────────────────────────────────────────

def parse_ve_amount(raw: str) -> Optional[float]:
    """
    Convierte un monto en formato venezolano a float.

    "1.250,00"  → 1250.00
    "1250,00"   → 1250.00
    "1,250.00"  → 1250.00  (formato US, tolerado)
    "Bs. 1.250" → 1250.00
    """
    if not raw or not raw.strip():
        return None

    s = raw.strip()
    # Remover prefijos de moneda
    s = re.sub(r'^[Bb][Ss]\.?\s*', '', s)
    s = re.sub(r'^\$\s*', '', s)
    s = s.replace(' ', '')

    if not s:
        return None

    # Detectar formato VE (1.250,00) vs US (1,250.00)
    last_comma = s.rfind(',')
    last_dot = s.rfind('.')

    if last_comma > -1 and last_dot > -1:
        # Ambos separadores. ¿Cuál es decimal?
        if last_comma > last_dot:
            # VE: 1.250,00 → punto es miles, coma es decimal
            s = s.replace('.', '').replace(',', '.')
        else:
            # US: 1,250.00 → coma es miles, punto es decimal
            s = s.replace(',', '')
    elif last_comma > -1:
        # Solo coma. VE si hay 2 decimales, si no es miles
        if re.search(r',\d{2}$', s):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif last_dot > -1:
        # Solo punto. Si hay más de 2 decimales, es miles.
        decimals = len(s) - last_dot - 1
        if decimals > 2:
            s = s.replace('.', '')
        # Si no, es decimal (estilo US)

    try:
        return float(s)
    except ValueError:
        return None


# ──────────────────────────────────────────────
#  Diccionario VE
# ──────────────────────────────────────────────

class VEDictionary:
    """
    Diccionario terminológico de facturas venezolanas para
    corrección y boosting de confianza en post-procesamiento.
    """

    def __init__(self, dict_path: Optional[str] = None):
        self.words: Set[str] = set()
        self._load_default()
        if dict_path and os.path.exists(dict_path):
            self._load_file(dict_path)

    def _load_default(self):
        """Carga el vocabulario VE por defecto (embebido)."""
        defaults = [
            # Tipos RIF
            'v', 'j', 'e', 'p', 'g', 'c', 'rif',
            # Términos de factura
            'factura', 'fact', 'nro', 'numero', 'número', 'control',
            'comprobante', 'recibo', 'nota', 'entrega', 'fiscal',
            'contado', 'crédito', 'credito', 'débito', 'debito',
            'exento', 'gravado', 'gravable', 'imponible',
            'subtotal', 'total', 'monto', 'iva', 'islr',
            'base', 'alicuota', 'alícuota', 'porcentaje',
            # Condiciones de pago
            'cheque', 'transferencia', 'depósito', 'deposito',
            'efectivo', 'tarjeta', 'financiamiento',
            # Datos
            'razón', 'razon', 'social', 'cliente', 'receptor',
            'emisor', 'proveedor', 'vendedor', 'comprador',
            'domicilio', 'dirección', 'direccion', 'teléfono', 'telefono',
            'email', 'correo', 'electrónico', 'electronico',
            # Moneda
            'bolívar', 'bolivar', 'bs', 'dólar', 'dolar', 'usd',
            'euro', 'divisa', 'moneda', 'tasa', 'bcv', 'paralelo',
            'oficial', 'cambio',
            # Multi-moneda
            'eur', 'euros', 'euro', 'cop', 'ars', 'colombiano',
            'colombiana', 'argentino', 'argentina', 'peso', 'pesos',
            # Tributario
            'seniat', 'declaración', 'declaracion', 'impuesto',
            'tributo', 'retención', 'retencion', 'anticipo', 'ajuste',
            # Funcionales
            'son', 'pagó', 'pago', 'recibí', 'recibi', 'conforme',
            'entregué', 'entregue', 'autorizado', 'firma', 'sello',
            # Meses
            'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
            'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
        ]
        self.words.update(defaults)

    def _load_file(self, path: str):
        """Carga palabras desde archivo de texto."""
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                word = line.strip()
                if word and not word.startswith('#'):
                    self.words.add(word.lower())

    def contains(self, word: str) -> bool:
        """Verifica si una palabra está en el diccionario."""
        return word.lower() in self.words

    def get_boost(self, word: str) -> float:
        """
        Retorna un boost de confianza (0.0 - 0.3) para palabras
        del diccionario VE.
        """
        w = word.lower()
        if w in self.words:
            return 0.15
        # Números con formato VE (ej. 1.250,00)
        if re.match(r'^[\d.,]+$', w) and ',' in w:
            return 0.10
        # RIF-like
        if re.match(r'^[VJEGPC]\d{9}$', w, re.IGNORECASE):
            return 0.25
        # Patrón de monto
        if re.match(r'^[\d.,]{4,}$', w):
            return 0.08
        return 0.0


# ──────────────────────────────────────────────
#  Corrector de RIF
# ──────────────────────────────────────────────

def normalize_and_verify_rif(raw: str) -> Tuple[Optional[str], List[str]]:
    """
    Normaliza un RIF venezolano y verifica el dígito validador.

    Args:
        raw: Texto crudo que puede contener un RIF.

    Returns:
        (rif_normalizado, lista_de_errores)
        Ej: ("J-12345678-9", []) o (None, ["No se encontró RIF válido"])
    """
    m = RIF_PATTERN.search(raw)
    if not m:
        # Intentar con formato pegado: J123456789
        m2 = re.search(r'\b([VJEGPC])(\d{8})(\d)\b', raw.upper())
        if not m2:
            return None, ["No se encontró RIF válido"]
        letter, digits, check = m2.group(1), m2.group(2), m2.group(3)
    else:
        letter = m.group(1).upper()
        digits = m.group(2)
        check = m.group(3)

    # El dígito verificador se calcula así (SENIAT):
    # Suma ponderada: cada dígito (incluyendo letra como número) × peso
    # Letras: V=4, J=12, E=8, P=16, G=20, C=... y demás
    weights = {'V': 4, 'J': 12, 'E': 8, 'P': 16, 'G': 20, 'C': 4}
    w = weights.get(letter, 4)

    # Calcular suma ponderada: 4 + dígitos con pesos 3,2,7,6,5,4,3,2
    digits_str = digits
    sum_w = w
    digit_weights = [3, 2, 7, 6, 5, 4, 3, 2]
    for i, d in enumerate(digits_str):
        sum_w += int(d) * digit_weights[i]

    # Dígito verificador: 11 - (sum_w % 11)
    # Si da 11 → 0, si da 10 → E (se representa como 0 en RIF)
    remainder = sum_w % 11
    if remainder == 0:
        expected_check = '0'
    elif remainder == 1:
        expected_check = '0'  # En RIF, 10 se reemplaza por 0
    else:
        expected_check = str(11 - remainder)

    errors = []
    if check != expected_check:
        errors.append(
            f"Dígito verificador inválido: esperado {expected_check}, obtenido {check}"
        )

    rif_normalized = f"{letter}-{digits}-{expected_check}"
    if check != expected_check:
        rif_normalized = f"{letter}-{digits}-{check} (debería ser {expected_check})"

    return f"{letter}-{digits}-{expected_check}", errors


# ──────────────────────────────────────────────
#  Motor PaddleOCR VE
# ──────────────────────────────────────────────

class PaddleOCRVEEngine:
    """
    Motor OCR basado en PaddleOCR con post-procesamiento
    especializado para facturas venezolanas.

    Características:
      - Diccionario VE para boosting de confianza
      - Corrección de RIF con dígito verificador
      - Parsing VE de montos (1.250,00 → 1250.00)
      - Detección de patrones NCF / factura VE
      - Score combinado: OCR + patrón VE
    """

    def __init__(
        self,
        lang: str = "es",
        use_angle_cls: bool = True,
        ve_dict_path: Optional[str] = None,
    ):
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self._paddle = None
        self._initialized = False

        # Diccionario VE
        dict_path = ve_dict_path or os.path.join(
            os.path.dirname(__file__), "ve_dict.txt"
        )
        self.ve_dict = VEDictionary(dict_path)

        # Estadísticas de corrección
        self.stats = {"total_words": 0, "corrected": 0, "rif_fixes": 0}

    def _lazy_init(self):
        """Inicializa PaddleOCR bajo demanda."""
        if self._initialized:
            return
        try:
            import os as _os
            _os.environ["FLAGS_oneDNN_enabled"] = "0"  # Bug workaround PaddlePaddle 3.x

            from paddleocr import PaddleOCR
            from ocr.backends import _build_paddleocr_instance
            self._paddle = _build_paddleocr_instance(PaddleOCR)
            self._initialized = True
        except ImportError as e:
            raise ImportError(
                "PaddleOCR no está instalado. "
                "Instale con: pip install paddleocr paddlepaddle\n"
                f"Error: {e}"
            )
        except Exception as e:
            # Antes: pasar 'use_gpu=False' directo tumbaba esto con
            # "Unknown argument: use_gpu" en versiones nuevas de PaddleOCR.
            # _build_paddleocr_instance() introspecciona la firma real e
            # intenta varias combinaciones antes de rendirse.
            raise RuntimeError(f"No se pudo inicializar PaddleOCR (paddle_ve): {e}")

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[Tuple[str, Tuple[float, float, float, float], float]]:
        """
        Reconoce texto en imagen usando PaddleOCR + post-procesamiento VE.

        Args:
            image: Imagen BGR.
            confidence_threshold: Umbral de confianza (default: de CONFIG).

        Returns:
            Lista de (texto, (x1, y1, x2, y2), confianza_ve).
            confianza_ve es el score combinado OCR + patrón VE.
        """
        self._lazy_init()

        if confidence_threshold is None:
            threshold = CONFIG.ocr.confidence_threshold
        else:
            threshold = confidence_threshold

        # 1. OCR Paddle
        from ocr.backends import _run_paddle_inference
        raw_results = _run_paddle_inference(self._paddle, image)
        if not raw_results:
            return []

        # Normalizar formato según versión de PaddleOCR
        if isinstance(raw_results, list) and raw_results and isinstance(raw_results[0], list):
            lines = raw_results[0]
        else:
            lines = raw_results

        # 2. Post-procesar cada línea
        processed = []
        for line in lines:
            if line is None:
                continue

            try:
                if len(line) == 3:
                    bbox, text, confidence = line
                elif len(line) == 2:
                    bbox, (text, confidence) = line
                else:
                    continue
            except (ValueError, TypeError):
                continue

            if not isinstance(confidence, (int, float)) or confidence < 0:
                continue

            text = str(text).strip()
            if not text:
                continue

            # 3. Post-procesamiento VE
            corrected_text, ve_boost = self._postprocess_ve(text, confidence)

            # Score combinado: OCR confidence + VE boost + penalización de corrección
            combined_score = min(1.0, confidence + ve_boost)

            # Penalizar si hubo corrección drástica
            if corrected_text != text and len(text) > 3:
                combined_score *= 0.95  # Leve penalización

            if combined_score < threshold:
                continue

            # Bbox normalizado
            x1 = min(p[0] for p in bbox) if hasattr(bbox[0], '__iter__') else bbox[0]
            y1 = min(p[1] for p in bbox) if hasattr(bbox[0], '__iter__') else bbox[1]
            x2 = max(p[0] for p in bbox) if hasattr(bbox[0], '__iter__') else bbox[2]
            y2 = max(p[1] for p in bbox) if hasattr(bbox[0], '__iter__') else bbox[3]

            processed.append((corrected_text, (float(x1), float(y1), float(x2), float(y2)), float(combined_score)))

            # Estadísticas
            self.stats["total_words"] += 1
            if corrected_text != text:
                self.stats["corrected"] += 1
            if re.search(r'[VJEGPC]\d{9}', corrected_text, re.IGNORECASE):
                self.stats["rif_fixes"] += 1

        # 4. Ordenar por posición (Y asc, X asc)
        processed.sort(key=lambda w: (w[1][1], w[1][0]))

        return processed

    def _postprocess_ve(
        self, text: str, ocr_confidence: float
    ) -> Tuple[str, float]:
        """
        Post-procesa un token de OCR para facturas venezolanas.

        Args:
            text: Texto reconocido por PaddleOCR.
            ocr_confidence: Confianza original del OCR.

        Returns:
            (texto_corregido, boost_de_confianza_VE)
        """
        original = text
        boost = 0.0

        # --- Corrección 1: RIF ---
        # PaddleOCR suele reconocer "J-12345678-9" pero a veces sale "J 12345678 9"
        # o "I12345678-9" (I mayúscula como J).
        rif_match = re.search(r'\b([IVJEGPC])[-.\s]?(\d{8})[-.\s]?(\d)\b', text, re.IGNORECASE)
        if rif_match:
            letter = rif_match.group(1).upper()
            # Corregir I → J (error común de OCR en tipografías con serif)
            if letter == 'I':
                letter = 'J'
                text = text[:rif_match.start(1)] + 'J' + text[rif_match.start(1)+1:]
            # Corregir L → 1 (otro error común)
            digits = rif_match.group(2)
            digits_corrected = digits.replace('O', '0').replace('o', '0').replace('l', '1').replace('I', '1')
            if digits_corrected != digits:
                text = text[:rif_match.start(2)] + digits_corrected + text[rif_match.end(2):]
            boost = max(boost, 0.25)
            self.stats["rif_fixes"] += 1

        # --- Corrección 2: Montos VE ---
        # Si el token parece un monto (números con separadores VE)
        if re.match(r'^[\d.,]+$', text) and ',' in text:
            parsed = parse_ve_amount(text)
            if parsed is not None and parsed > 0:
                boost = max(boost, 0.12)

        # --- Corrección 3: Palabras del diccionario VE ---
        # Si la palabra está en el diccionario, dar boost
        if self.ve_dict.contains(text):
            boost = max(boost, 0.15)

        # --- Corrección 4: Fechas VE ---
        if DATE_PATTERN.match(text):
            boost = max(boost, 0.10)

        # --- Corrección 5: Números de control/factura ---
        if re.match(r'^[A-Z]*\d[\dA-Z\-/]{3,}$', text, re.IGNORECASE):
            boost = max(boost, 0.08)

        # --- Corrección 6: Términos de IVA (I.V.A. → IVA) ---
        if re.match(r'^I\s*\.?\s*V\s*\.?\s*A\s*\.?$', text, re.IGNORECASE):
            text = 'IVA'
            boost = max(boost, 0.20)

        # --- Corrección 7: Siglas de moneda ---
        # Bs → Bs.
        if re.match(r'^Bs$', text):
            text = 'Bs.'
            boost = max(boost, 0.10)
        # USD / Dólar → boost
        if re.match(r'^(?:\$|USD|D[OÓ]LAR(?:ES)?)$', text, re.IGNORECASE):
            boost = max(boost, 0.15)
        # VES / Bolívar → boost
        if re.match(r'^(?:VES|BS\.?)$', text, re.IGNORECASE):
            boost = max(boost, 0.12)
        # EUR / Euro → boost
        if re.match(r'^(?:€|EUR(?:O)?(?:S)?)$', text, re.IGNORECASE):
            boost = max(boost, 0.14)
        # COP → boost
        if re.match(r'^(?:COP|PESO(?:S)?)$', text, re.IGNORECASE):
            boost = max(boost, 0.13)
        # ARS → boost
        if re.match(r'^(?:ARS|PESO(?:S)?)$', text, re.IGNORECASE):
            boost = max(boost, 0.13)

        # --- Corrección 8: Porcentajes (16% → 16%) ---
        if re.match(r'^\d{1,2}(?:[.,]\d)?\s*%?$', text):
            boost = max(boost, 0.05)

        return text, boost

    def get_stats(self) -> Dict:
        """Retorna estadísticas de post-procesamiento."""
        return dict(self.stats)

    def reset_stats(self):
        """Reinicia estadísticas."""
        self.stats = {"total_words": 0, "corrected": 0, "rif_fixes": 0}


# ──────────────────────────────────────────────
#  Post-procesamiento global de texto OCR VE
# ──────────────────────────────────────────────

class VETextPostProcessor:
    """
    Post-procesamiento global de texto OCR para facturas venezolanas.

    Opera sobre el texto completo (no token a token) para:
      - Reconstruir RIF multi-línea
      - Detectar y corregir totales
      - Validar coherencia IVA/Base/Total
      - Normalizar formato de números
    """

    def __init__(self, ve_dict: Optional[VEDictionary] = None):
        self.ve_dict = ve_dict or VEDictionary()

    def process_full_text(self, raw_text: str) -> Tuple[str, List[str]]:
        """
        Procesa el texto completo del OCR.

        Args:
            raw_text: Texto concatenado del OCR.

        Returns:
            (texto_procesado, [advertencias])
        """
        warnings = []
        text = raw_text

        # 1. Normalizar espacios
        text = re.sub(r'\s+', ' ', text).strip()

        # 2. Detectar y asegurar RIF
        rif, rif_warnings = self._ensure_rif(text)
        if rif_warnings:
            warnings.extend(rif_warnings)

        # 3. Detectar y normalizar montos
        text = self._normalize_amounts(text)

        # 4. Detectar formato NCF
        self._detect_ncf(text, warnings)

        return text, warnings

    def _ensure_rif(self, text: str) -> Tuple[Optional[str], List[str]]:
        """Asegura que el RIF esté presente y normalizado."""
        rif, errors = normalize_and_verify_rif(text)
        warnings = []
        if errors:
            warnings.extend(errors)
        return rif, warnings

    def _normalize_amounts(self, text: str) -> str:
        """
        Normaliza montos en formato VE.

        IMPORTANTE: solo debe tocar números que realmente parecen montos
        (ya traen separador decimal de 2 dígitos, ej. "1.450,00"), y nunca
        números pegados a un guion o una barra — esos son RIF, números de
        control o fechas, no montos. Antes esta función usaba
        r'\\b[\\d.,]+\\b', que capturaba CUALQUIER dígito del documento
        (incluidos los del RIF y cada componente de la fecha) y los
        reformateaba como moneda, corrompiendo el texto crudo completo.
        """
        def _replace_amount(m):
            raw = m.group(0)
            parsed = parse_ve_amount(raw)
            if parsed is not None:
                # Mantener formato original pero asegurado
                return f"{parsed:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return raw

        # Solo montos genuinos: dígitos con separador de miles opcional y
        # decimal de 2 dígitos obligatorio, sin letras/guiones/barras pegados
        # (eso descarta RIF "J-12345678-9", fechas "25/07/2026" y números
        # de control, que no deben normalizarse como si fueran dinero).
        pattern = r'(?<![\w/-])\d{1,3}(?:[.,]\d{3})*[.,]\d{2}(?![\w/-])'
        text = re.sub(pattern, _replace_amount, text)
        return text

    def _detect_ncf(self, text: str, warnings: List[str]):
        """Detecta formato de NCF venezolano en el texto."""
        # NCF típico: B01-12345678 o 01-12345678
        ncf = re.search(r'\b([A-Z]?\d{2})-(\d{8})\b', text)
        if ncf:
            prefix = ncf.group(1)
            number = ncf.group(2)
            warnings.append(f"NCF detectado: {prefix}-{number}")
        # También buscar patrón de factura
        inv = NCF_PATTERN.search(text)
        if inv:
            warnings.append(f"N° Factura/Control: {inv.group(1)}")


# ──────────────────────────────────────────────
#  Utilidad de alto nivel
# ──────────────────────────────────────────────

def recognize_ve_invoice(
    image: np.ndarray,
    engine: Optional[PaddleOCRVEEngine] = None,
) -> Tuple[List[Tuple[str, Tuple[float, float, float, float], float]], str]:
    """
    Función de alto nivel: reconoce texto en una factura VE
    y retorna (words, full_text_procesado).

    Args:
        image: Imagen BGR.
        engine: Motor PaddleOCRVEEngine (se crea uno por defecto si no se pasa).

    Returns:
        (words, full_text_post_processed)
    """
    if engine is None:
        engine = PaddleOCRVEEngine()

    words = engine.recognize(image)
    raw_text = " ".join(t for t, _, _ in words)

    post_processor = VETextPostProcessor(engine.ve_dict)
    processed_text, _ = post_processor.process_full_text(raw_text)

    return words, processed_text


# ──────────────────────────────────────────────
#  Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  πNAD PaddleOCR VE — Prueba de post-procesamiento")
    print("=" * 60)

    # Test RIF
    test_rifs = [
        ("J-12345678-9", "J-12345678-9"),
        ("J 12345678 9", "J-12345678-9"),
        ("I-12345678-9", "J-12345678-9"),  # I → J
        ("V123456789", "V-12345678-9"),
    ]
    print("\n📋 Corrección de RIF:")
    for raw, expected in test_rifs:
        rif, errors = normalize_and_verify_rif(raw)
        print(f"  {raw:20s} → {str(rif):20s}  {'⚠ ' + str(errors) if errors else '✓'}")

    # Test montos
    test_amounts = [
        "1.250,00",
        "1250,00",
        "Bs. 1.250",
        "$ 500.00",
        "1,250.00",
    ]
    print("\n💰 Parsing de montos:")
    for raw in test_amounts:
        parsed = parse_ve_amount(raw)
        print(f"  {raw:20s} → {parsed}")

    # Test diccionario
    print("\n📖 Diccionario VE:")
    ve_dict = VEDictionary()
    for word in ["RIF", "IVA", "FACTURA", "BOLÍVAR", "SUBTOTAL"]:
        print(f"  {word:15s} → {'✓' if ve_dict.contains(word) else '✗'} boost={ve_dict.get_boost(word):.2f}")

    print("\n✅ Módulo PaddleOCR VE cargado correctamente.")
