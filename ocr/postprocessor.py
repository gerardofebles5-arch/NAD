"""
[NAD] FASE 3 — Post-Processing Pipeline
=========================================
Toma el texto OCR crudo + campos extraidos + correcciones y genera un JSON
estructurado con campos tipados (monto, RIF, IVA, fecha, etc.), validacion
cruzada entre campos, y deteccion de inconsistencias.

Pipeline:
  1. FieldConverter  — Convierte campos string a tipos nativos (float, date, RIF, etc.)
  2. CrossValidator  — Valida relaciones entre campos (IVA vs Base, Total vs B+IVA, RIF digit)
  3. InconsistencyDetector — Detecta anomalias con severidad (warning/error/critical)
  4. PostProcessor   — Orquestador que ejecuta todo el pipeline
  5. export_to_json  — Genera JSON estructurado final

Uso:
    from ocr.postprocessor import PostProcessor
    pp = PostProcessor()
    result = pp.process(invoice_data)
    json_str = result.to_json(indent=2)
"""

import re
import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
from collections import defaultdict


# ============================================================
#  Tipos Enumerados
# ============================================================

class Severity(Enum):
    """Nivel de severidad de una inconsistencia."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationStatus(Enum):
    """Estado de validacion de un campo."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNVERIFIED = "unverified"


class CurrencyCode(Enum):
    """Codigos de moneda soportados."""
    BS = "BS"       # Bolivar
    USD = "USD"     # Dolar
    EUR = "EUR"     # Euro
    COP = "COP"     # Peso Colombiano
    ARS = "ARS"     # Peso Argentino
    UNKNOWN = ""


# ============================================================
#  Tipos nativos para campos de factura
# ============================================================

@dataclass
class TypedRIF:
    """RIF venezolano tipado y validado."""
    letter: str = ""       # J, V, E, P, G, C
    digits: str = ""       # 8 digitos
    check_digit: str = ""  # 1 digito verificador
    normalized: str = ""   # Formato J-12345678-9
    is_valid: bool = False
    validation_errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.is_valid:
            if self.normalized:
                return f"{self.normalized} (invalido)"
            return "(invalido)"
        return self.normalized if self.normalized else "(invalido)"


@dataclass
class TypedAmount:
    """Monto tipado con moneda y conversion."""
    raw: str = ""
    value: Optional[float] = None
    currency: str = "BS"
    is_valid: bool = False
    in_bs: Optional[float] = None
    in_usd: Optional[float] = None

    def __str__(self) -> str:
        if self.value is None:
            return "(vacio)"
        if self.currency == "BS":
            return f"Bs. {self.value:,.2f}"
        elif self.currency == "USD":
            return f"$ {self.value:,.2f}"
        elif self.currency == "EUR":
            return f"\u20ac {self.value:,.2f}"
        elif self.currency == "COP":
            return f"$ {self.value:,.2f} COP"
        elif self.currency == "ARS":
            return f"$ {self.value:,.2f} ARS"
        return f"{self.value:,.2f} {self.currency}"


@dataclass
class TypedDate:
    """Fecha tipada y validada."""
    raw: str = ""
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    as_date: Optional[date] = None
    is_valid: bool = False
    format: str = ""  # "dd/mm/yyyy", "yyyy-mm-dd", etc.

    def __str__(self) -> str:
        if self.as_date:
            return self.as_date.strftime("%d/%m/%Y")
        return self.raw if self.raw else "(vacio)"


@dataclass
class TypedInvoice:
    """Modelo tipado completo de una factura venezolana.

    Todos los campos tienen tipos nativos en lugar de strings.
    """
    # Identificacion
    numero_factura: str = ""
    numero_control: str = ""
    cliente: str = ""

    # Fecha
    fecha: Optional[TypedDate] = None

    # Emisor
    rif_emisor: Optional[TypedRIF] = None
    razon_social: str = ""
    direccion: str = ""
    telefono: str = ""

    # Montos
    base_imponible: Optional[TypedAmount] = None
    iva: Optional[TypedAmount] = None
    total: Optional[TypedAmount] = None
    iva_rate: Optional[float] = None  # 16.0, 8.0, etc.

    # Moneda
    currency: str = "BS"
    exchange_rate: Optional[float] = None

    # Pago
    condicion_pago: str = ""

    # Metadatos
    ocr_confidence: float = 0.0
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED
    validation_errors: List[str] = field(default_factory=list)
    inconsistencies: List[Dict[str, Any]] = field(default_factory=list)
    corrections_applied: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_meta: bool = True, raw_strings: bool = False) -> Dict[str, Any]:
        """Convierte a diccionario para serializacion JSON.

        Args:
            include_meta: Incluir metadatos de validacion.
            raw_strings: Si True, montos como strings VE ("1250,00") en vez de float.
                         Compatibilidad con InvoiceData.to_dict() existente.
        """
        d = {
            "numero_factura": self.numero_factura,
            "numero_control": self.numero_control,
            "cliente": self.cliente,
            "fecha": str(self.fecha) if self.fecha else "",
            "rif_emisor": str(self.rif_emisor) if self.rif_emisor else "",
            "razon_social": self.razon_social,
            "direccion": self.direccion,
            "telefono": self.telefono,
        }

        # Montos
        for campo in ["base_imponible", "iva", "total"]:
            val = getattr(self, campo, None)
            if isinstance(val, TypedAmount):
                if raw_strings:
                    d[campo] = val.raw if val.raw else ""
                else:
                    d[campo] = val.value
                d[f"{campo}_raw"] = val.raw
                d[f"{campo}_currency"] = val.currency
                d[f"{campo}_valid"] = val.is_valid
            else:
                d[campo] = None if not raw_strings else ""

        d["iva_rate"] = self.iva_rate
        d["currency"] = self.currency
        d["exchange_rate"] = self.exchange_rate
        d["condicion_pago"] = self.condicion_pago

        if include_meta:
            d["ocr_confidence"] = self.ocr_confidence
            d["validation_status"] = self.validation_status.value
            d["validation_errors"] = self.validation_errors
            d["inconsistencies"] = self.inconsistencies
            d["corrections_applied"] = self.corrections_applied

        return d

    def to_json(self, indent: int = 2) -> str:
        """Serializa a JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_flat_dict(self) -> Dict[str, Any]:
        """Version plana sin anidamiento, para exportacion a tabla/CSV."""
        d = {
            "numero_factura": self.numero_factura,
            "numero_control": self.numero_control,
            "cliente": self.cliente,
            "fecha": str(self.fecha) if self.fecha else "",
            "rif_emisor": str(self.rif_emisor) if self.rif_emisor else "",
            "razon_social": self.razon_social,
            "direccion": self.direccion,
            "telefono": self.telefono,
        }

        for campo in ["base_imponible", "iva", "total"]:
            val = getattr(self, campo, None)
            if isinstance(val, TypedAmount):
                d[campo] = val.value
                d[f"{campo}_currency"] = val.currency
            else:
                d[campo] = None

        d["iva_rate"] = self.iva_rate
        d["currency"] = self.currency
        if self.exchange_rate:
            d["total_bs"] = self.total.in_bs if self.total and self.total.in_bs else 0.0
            d["total_usd"] = self.total.in_usd if self.total and self.total.in_usd else 0.0

        d["condicion_pago"] = self.condicion_pago
        d["ocr_confidence"] = self.ocr_confidence
        d["validation_status"] = self.validation_status.value
        return d


# ============================================================
#  FieldConverter — Convierte campos string a tipos nativos
# ============================================================

# Funciones de parseo compartidas (evitan dependencia circular)
_PARSE_VE_AMOUNT = None
try:
    from ocr.paddle_ve import parse_ve_amount as _pv
    _PARSE_VE_AMOUNT = _pv
except ImportError:
    pass


def _parse_amount(raw: str) -> Optional[float]:
    """Parsea un monto desde string."""
    if not raw or not raw.strip():
        return None
    if _PARSE_VE_AMOUNT:
        try:
            return _PARSE_VE_AMOUNT(raw)
        except Exception:
            pass
    # Fallback manual
    s = raw.strip()
    s = re.sub(r'^[Bb][Ss]\.?\s*', '', s)
    s = re.sub(r'^\$\s*', '', s)
    s = s.replace(' ', '')
    try:
        return float(s.replace(',', '.'))
    except ValueError:
        return None


def _detect_currency(text: str, raw_amount: str) -> str:
    """Detecta la moneda de un monto basado en contexto."""
    # Buscar simbolos de moneda en el texto completo
    if re.search(r'(EUR|€|EUROS?)', text, re.IGNORECASE):
        return "EUR"
    if re.search(r'(COP|PESO\s*COLOMBIANO)', text, re.IGNORECASE):
        return "COP"
    if re.search(r'(ARS|PESO\s*ARGENTINO)', text, re.IGNORECASE):
        return "ARS"
    if re.search(r'(\$|USD|D[OÓ]LAR)', text, re.IGNORECASE) and not re.search(r'(COP|ARS|PESO)', text, re.IGNORECASE):
        return "USD"
    if re.search(r'(BS|Bs|VES|BOL[IÍ]VAR)', text, re.IGNORECASE):
        return "BS"
    # Por defecto, si el monto tiene coma como separador decimal -> BS
    if ',' in raw_amount and '.' in raw_amount:
        return "BS"
    return "BS"


def _parse_date(raw: str) -> TypedDate:
    """Parsea una fecha desde string."""
    td = TypedDate(raw=raw)
    if not raw:
        return td

    # Intentar formatos comunes
    patterns = [
        (r'(\d{1,2})/(\d{1,2})/(\d{4})', "%d/%m/%Y"),
        (r'(\d{1,2})-(\d{1,2})-(\d{4})', "%d-%m-%Y"),
        (r'(\d{4})-(\d{1,2})-(\d{1,2})', "%Y-%m-%d"),
        (r'(\d{4})/(\d{1,2})/(\d{1,2})', "%Y/%m/%d"),
        (r'(\d{1,2})/(\d{1,2})/(\d{2})', "%d/%m/%y"),
    ]

    for pat, fmt in patterns:
        m = re.match(pat, raw.strip())
        if m:
            try:
                td.as_date = datetime.strptime(raw.strip(), fmt).date()
                td.year = td.as_date.year
                td.month = td.as_date.month
                td.day = td.as_date.day
                td.format = fmt
                td.is_valid = True
                break
            except ValueError:
                continue

    return td


def _parse_rif(raw: str) -> TypedRIF:
    """Parsea y valida un RIF venezolano."""
    tr = TypedRIF()

    if not raw:
        return tr

    # Limpiar
    raw = raw.strip().upper()

    # Patron RIF: J-12345678-9
    m = re.match(r'([VJEGPC])[-.\s]?(\d{8})[-.\s]?(\d)', raw)
    if not m:
        # Intentar formato pegado: J123456789
        m2 = re.match(r'([VJEGPC])(\d{8})(\d)', raw)
        if not m2:
            tr.validation_errors.append(f"No se pudo parsear RIF: {raw}")
            return tr
        m = m2

    tr.letter = m.group(1)
    tr.digits = m.group(2)
    tr.check_digit = m.group(3)
    tr.normalized = f"{tr.letter}-{tr.digits}-{tr.check_digit}"

    # Verificar digito
    weights_map = {'V': 4, 'J': 12, 'E': 8, 'P': 16, 'G': 20, 'C': 4}
    w = weights_map.get(tr.letter, 4)
    digit_weights = [3, 2, 7, 6, 5, 4, 3, 2]
    sum_w = w
    for i, d in enumerate(tr.digits):
        sum_w += int(d) * digit_weights[i]

    remainder = sum_w % 11
    if remainder == 0:
        expected = '0'
    elif remainder == 1:
        expected = '0'  # En RIF, 10 se representa como 0
    else:
        expected = str(11 - remainder)

    if tr.check_digit == expected:
        tr.is_valid = True
    else:
        tr.validation_errors.append(
            f"Digito verificador invalido: esperado {expected}, obtenido {tr.check_digit}"
        )

    return tr


class FieldConverter:
    """
    Convierte campos string de InvoiceData a tipos nativos.

    Responsabilidades:
      - Montos -> TypedAmount (float + moneda + validacion)
      - Fechas -> TypedDate (date object + validacion)
      - RIF   -> TypedRIF (estructura + digito verificador)
      - Numericos -> Optional[float]
    """

    def __init__(self, full_text: str = ""):
        self.full_text = full_text

    def convert_amount(self, raw: str, field_name: str = "") -> TypedAmount:
        """Convierte un monto string a TypedAmount."""
        ta = TypedAmount(raw=raw)
        if not raw:
            return ta

        value = _parse_amount(raw)
        if value is not None and value > 0:
            ta.value = round(value, 2)
            ta.currency = _detect_currency(self.full_text, raw)
            ta.is_valid = True
        else:
            ta.is_valid = False

        return ta

    def convert_date(self, raw: str) -> TypedDate:
        """Convierte una fecha string a TypedDate."""
        return _parse_date(raw)

    def convert_rif(self, raw: str) -> TypedRIF:
        """Convierte un RIF string a TypedRIF."""
        return _parse_rif(raw)

    def convert_optional_float(self, raw: str) -> Optional[float]:
        """Convierte un string a float opcional."""
        if not raw:
            return None
        return _parse_amount(raw)

    @staticmethod
    def normalize_phone(raw: str) -> str:
        """Normaliza un telefono venezolano."""
        if not raw:
            return ""
        digits = re.sub(r'[^\d+]', '', raw)
        # Formatear como 0XXX-XXXXXXX
        if len(digits) == 11 and digits.startswith('0'):
            return f"{digits[:4]}-{digits[4:]}"
        if len(digits) == 12 and digits.startswith('+58'):
            return f"{digits[:3]} {digits[3:6]}-{digits[6:]}"
        return digits


# ============================================================
#  CrossValidator — Valida relaciones entre campos
# ============================================================

class CrossValidator:
    """
    Valida relaciones entre campos de una factura venezolana.

    Validaciones:
      - IVA vs Base Imponible: IVA debe ser ~16% o ~8% de la base
      - Total vs Base + IVA: Total debe ser Base + IVA
      - RIF: digito verificador
      - Fecha: no futura, no anterior a 1990
      - Moneda: consistencia entre simbolo y monto
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._iva_rates = self.config.get("iva_rates", [16.0, 8.0])
        self._tolerance = self.config.get("tolerance", 1.0)

    def validate(self, typed: TypedInvoice) -> TypedInvoice:
        """Ejecuta todas las validaciones cruzadas sobre el invoice tipado."""
        # 1. IVA vs Base
        self._validate_iva_base(typed)

        # 2. Total vs Base + IVA
        self._validate_total(typed)

        # 3. RIF
        self._validate_rif(typed)

        # 4. Fecha
        self._validate_date(typed)

        # 5. Moneda
        self._validate_currency(typed)

        # 6. Consistencia IVA rate
        self._validate_iva_rate(typed)

        # Determinar estado general
        self._determine_status(typed)

        return typed

    def _validate_iva_base(self, typed: TypedInvoice):
        """Valida que el IVA corresponda a la base imponible."""
        base = typed.base_imponible
        iva = typed.iva

        if not base or not iva:
            return
        if base.value is None or iva.value is None:
            return
        if base.value <= 0 or iva.value <= 0:
            return

        # Probar todas las alicuotas
        rates = [r / 100.0 for r in self._iva_rates]
        best_diff = float('inf')
        best_rate = None

        for rate in rates:
            expected = round(base.value * rate, 2)
            diff = abs(iva.value - expected)
            if diff < best_diff:
                best_diff = diff
                best_rate = rate * 100

        if best_rate is not None:
            typed.iva_rate = best_rate

        if best_diff > self._tolerance and best_rate is not None:
            expected_val = round(base.value * best_rate / 100.0, 2)
            typed.inconsistencies.append({
                "type": "iva_base_mismatch",
                "severity": Severity.WARNING.value,
                "message": (
                    f"IVA ({iva.value:.2f}) no corresponde a ninguna alicuota "
                    f"de la base ({base.value:.2f}). "
                    f"Para {best_rate:.0f}% se esperaria ~{expected_val:.2f} "
                    f"(diferencia: {best_diff:.2f})"
                ),
                "fields": ["base_imponible", "iva"],
                "expected": expected_val,
                "actual": iva.value,
                "tolerance": self._tolerance,
            })

    def _validate_total(self, typed: TypedInvoice):
        """Valida que Total ~ Base + IVA."""
        base = typed.base_imponible
        iva = typed.iva
        total = typed.total

        if not base or not iva or not total:
            return
        if base.value is None or iva.value is None or total.value is None:
            return
        if total.value <= 0:
            return

        expected = round(base.value + iva.value, 2)
        diff = abs(total.value - expected)

        if diff > self._tolerance * 2:
            typed.inconsistencies.append({
                "type": "total_base_iva_mismatch",
                "severity": Severity.WARNING.value,
                "message": (
                    f"Total ({total.value:.2f}) no coincide con "
                    f"Base + IVA ({base.value:.2f} + {iva.value:.2f} = {expected:.2f}). "
                    f"Diferencia: {diff:.2f}"
                ),
                "fields": ["base_imponible", "iva", "total"],
                "expected": expected,
                "actual": total.value,
                "tolerance": self._tolerance,
            })
        elif diff > 0.02:
            typed.inconsistencies.append({
                "type": "total_base_iva_minor_diff",
                "severity": Severity.INFO.value,
                "message": f"Diferencia minima en total: {diff:.2f} (esperado {expected}, actual {total.value})",
                "fields": ["base_imponible", "iva", "total"],
                "expected": expected,
                "actual": total.value,
            })

    def _validate_rif(self, typed: TypedInvoice):
        """Valida el RIF del emisor."""
        rif = typed.rif_emisor
        if not rif:
            return

        if not rif.is_valid:
            typed.inconsistencies.append({
                "type": "rif_invalid",
                "severity": Severity.ERROR.value,
                "message": f"RIF invalido: {rif.normalized} ({'; '.join(rif.validation_errors)})",
                "fields": ["rif_emisor"],
                "expected": None,
                "actual": rif.normalized,
            })
            typed.validation_errors.append(f"RIF invalido: {rif.normalized}")

    def _validate_date(self, typed: TypedInvoice):
        """Valida que la fecha sea razonable."""
        if not typed.fecha or not typed.fecha.is_valid:
            return

        d = typed.fecha.as_date
        if d is None:
            return

        today = date.today()

        # Fecha futura
        if d > today:
            typed.inconsistencies.append({
                "type": "date_future",
                "severity": Severity.WARNING.value,
                "message": f"Fecha en el futuro: {d}",
                "fields": ["fecha"],
                "expected": f"<={today}",
                "actual": str(d),
            })

        # Demasiado antigua
        if d < date(1990, 1, 1):
            typed.inconsistencies.append({
                "type": "date_too_old",
                "severity": Severity.WARNING.value,
                "message": f"Fecha anterior a 1990: {d}",
                "fields": ["fecha"],
                "expected": ">=1990-01-01",
                "actual": str(d),
            })

    def _validate_currency(self, typed: TypedInvoice):
        """Valida consistencia de moneda."""
        if not typed.currency:
            return

        # Si hay montos con moneda diferente a la principal
        amounts = [
            ("base_imponible", typed.base_imponible),
            ("iva", typed.iva),
            ("total", typed.total),
        ]

        for name, amount in amounts:
            if amount and amount.currency != typed.currency and amount.value is not None:
                typed.inconsistencies.append({
                    "type": "currency_mismatch",
                    "severity": Severity.INFO.value,
                    "message": (
                        f"Campo '{name}' en {amount.currency} "
                        f"pero moneda principal es {typed.currency}"
                    ),
                    "fields": [name, "currency"],
                    "expected": typed.currency,
                    "actual": amount.currency,
                })

    def _validate_iva_rate(self, typed: TypedInvoice):
        """Valida que la tasa de IVA detectada sea valida."""
        if typed.iva_rate is not None:
            valid_rates = self._iva_rates
            # Usar comparación con tolerancia para floats
            rate_match = any(abs(typed.iva_rate - r) < 0.01 for r in valid_rates)
            if not rate_match:
                typed.inconsistencies.append({
                    "type": "iva_rate_unusual",
                    "severity": Severity.INFO.value,
                    "message": (
                        f"Tasa de IVA inusual: {typed.iva_rate:.0f}% "
                        f"(esperada: {', '.join(f'{r:.0f}%' for r in valid_rates)})"
                    ),
                    "fields": ["iva_rate"],
                    "expected": valid_rates,
                    "actual": typed.iva_rate,
                })

    def _determine_status(self, typed: TypedInvoice):
        """Determina el estado de validacion general."""
        severities = [inc["severity"] for inc in typed.inconsistencies]

        if any(s == Severity.CRITICAL.value for s in severities):
            typed.validation_status = ValidationStatus.FAIL
        elif any(s == Severity.ERROR.value for s in severities):
            typed.validation_status = ValidationStatus.FAIL
        elif any(s == Severity.WARNING.value for s in severities):
            typed.validation_status = ValidationStatus.WARN
        elif typed.inconsistencies:
            typed.validation_status = ValidationStatus.WARN
        else:
            typed.validation_status = ValidationStatus.PASS


# ============================================================
#  InconsistencyReport — Reporte estructurado de validacion
# ============================================================

@dataclass
class InconsistencyReport:
    """
    Reporte completo de validacion del post-procesamiento.

    Incluye:
      - Inconsistencias detectadas por tipo
      - Campos validados exitosamente
      - Correcciones aplicadas
      - Estadisticas de confianza
    """
    total_checks: int = 0
    passed: int = 0
    warnings: int = 0
    errors: int = 0
    critical: int = 0

    inconsistencies_by_type: Dict[str, List[Dict]] = field(default_factory=lambda: defaultdict(list))
    valid_fields: List[str] = field(default_factory=list)
    corrections: List[Dict] = field(default_factory=list)

    overall_status: ValidationStatus = ValidationStatus.UNVERIFIED

    @property
    def score(self) -> float:
        """Puntaje de confianza 0.0 - 1.0 basado en validaciones."""
        if self.total_checks == 0:
            return 1.0
        weighted = (
            self.passed * 1.0 +
            self.warnings * 0.5 +
            self.errors * 0.0 +
            self.critical * (-1.0)
        )
        return max(0.0, min(1.0, weighted / max(self.total_checks, 1)))

    def to_dict(self) -> Dict:
        return {
            "total_checks": self.total_checks,
            "passed": self.passed,
            "warnings": self.warnings,
            "errors": self.errors,
            "critical": self.critical,
            "score": self.score,
            "status": self.overall_status.value,
            "inconsistencies_by_type": dict(self.inconsistencies_by_type),
            "valid_fields": self.valid_fields,
            "corrections": self.corrections,
        }


class InconsistencyDetector:
    """
    Detecta anomalias e inconsistencias en los datos extraidos.

    Opera DESPUES de FieldConverter y CrossValidator para
    generar un reporte consolidado.
    """

    def __init__(self):
        self._checks_run = 0

    def build_report(self, typed: TypedInvoice) -> InconsistencyReport:
        """Construye un reporte de validacion a partir del invoice tipado."""
        report = InconsistencyReport()

        for inc in typed.inconsistencies:
            sev = inc.get("severity", "info")
            inc_type = inc.get("type", "unknown")
            report.inconsistencies_by_type[inc_type].append(inc)

            if sev == Severity.CRITICAL.value:
                report.critical += 1
            elif sev == Severity.ERROR.value:
                report.errors += 1
            elif sev == Severity.WARNING.value:
                report.warnings += 1
            else:
                report.passed += 1

        # Contar campos validos (tienen valor y son validos)
        for campo in ["numero_factura", "numero_control", "fecha",
                       "rif_emisor", "razon_social", "cliente"]:
            val = getattr(typed, campo, None)
            if val and str(val).strip() and str(val) != "(vacio)":
                report.valid_fields.append(campo)

        for campo in ["base_imponible", "iva", "total"]:
            val = getattr(typed, campo, None)
            if isinstance(val, TypedAmount) and val.is_valid and val.value is not None:
                report.valid_fields.append(campo)

        report.corrections = typed.corrections_applied
        report.total_checks = (
            report.passed + report.warnings + report.errors + report.critical
        )

        # Ajustar passed: los items INFO cuentan como passed
        # Los warnings/errors/critical ya estan contados
        info_count = sum(
            1 for inc_list in report.inconsistencies_by_type.values()
            for inc in inc_list
            if inc.get("severity") == Severity.INFO.value
        )
        # Recalcular: passed = total check types - (warnings + errors + critical)
        # Pero en realidad los INFO estan contados como passed, asi que no need to adjust
        # Solo aseguramos que el total refleje chequeos reales

        report.overall_status = typed.validation_status
        return report


# ============================================================
#  CorrectionsPipeline — Aplica correcciones de usuario + automaticas
# ============================================================

class CorrectionsPipeline:
    """
    Aplica correcciones a los campos extraidos.

    Fuentes de correccion:
      1. Correcciones de usuario (feedback loop de FormatLearner)
      2. Correcciones automaticas (normalizacion, formato)
    """

    def __init__(self, user_corrections: Optional[Dict[str, Tuple[str, str]]] = None):
        self._user_corrections = user_corrections or {}

    def apply(self, raw_fields: Dict[str, str]) -> Tuple[Dict[str, str], List[Dict]]:
        """
        Aplica correcciones a los campos raw.

        Args:
            raw_fields: Dict de campos string extraidos.

        Returns:
            (campos_corregidos, [registro_de_correcciones])
        """
        corrected = dict(raw_fields)
        applied = []

        # 1. Correcciones de usuario
        for field, (wrong, correct) in self._user_corrections.items():
            if field in corrected and corrected[field].strip() == wrong.strip():
                corrected[field] = correct
                applied.append({
                    "field": field,
                    "from": wrong,
                    "to": correct,
                    "source": "user_feedback",
                })

        # 2. Correcciones automaticas: normalizacion de telefono
        if "telefono" in corrected and corrected["telefono"]:
            norm = FieldConverter.normalize_phone(corrected["telefono"])
            if norm != corrected["telefono"]:
                applied.append({
                    "field": "telefono",
                    "from": corrected["telefono"],
                    "to": norm,
                    "source": "auto_normalize",
                })
                corrected["telefono"] = norm

        # 3. Correcciones automaticas: formato de RIF
        if "rif_emisor" in corrected and corrected["rif_emisor"]:
            rif = _parse_rif(corrected["rif_emisor"])
            if rif.normalized and rif.normalized != corrected["rif_emisor"] and rif.is_valid:
                applied.append({
                    "field": "rif_emisor",
                    "from": corrected["rif_emisor"],
                    "to": rif.normalized,
                    "source": "auto_format",
                })
                corrected["rif_emisor"] = rif.normalized

        return corrected, applied


# ============================================================
#  PostProcessor — Orquestador del pipeline FASE 3
# ============================================================

class PostProcessor:
    """
    Orquestador del pipeline de post-procesamiento FASE 3.

    Flujo completo:
      1. Recibe InvoiceData (o dict de campos raw)
      2. CorrectionsPipeline: aplica correcciones de usuario + automaticas
      3. FieldConverter: convierte cada campo a tipo nativo
      4. CrossValidator: valida relaciones entre campos
      5. InconsistencyDetector: genera reporte de validacion
      6. Exportacion: JSON tipado con metadatos de validacion

    Integracion:
      - Si FormatLearner (FASE 2) esta disponible, obtiene correcciones
        del feedback loop de usuarios automaticamente.

    Uso:
        pp = PostProcessor()
        result = pp.process(invoice_data)
        print(result.to_json())        # JSON completo
        print(result.validation_status)  # pass / warn / fail
        print(result.inconsistencies)    # lista de inconsistencias
    """

    def __init__(self, config: Optional[Dict] = None, user_corrections: Optional[Dict] = None,
                 auto_fix: bool = True):
        """
        Args:
            config: Configuracion opcional (iva_rates, tolerance, etc.).
            user_corrections: Correcciones de usuario {campo: (wrong, correct)}.
            auto_fix: Si True, cuando CrossValidator detecte un IVA inconsistente,
                      lo recalcula automaticamente desde la base usando la alicuota
                      mas cercana y marca la correccion como 'auto_fix'.
        """
        self.config = config or {}
        self._auto_fix = auto_fix
        self._corrections_pipeline = CorrectionsPipeline(user_corrections)
        self._cross_validator = CrossValidator(self.config)
        self._inconsistency_detector = InconsistencyDetector()

        # Integracion con FormatLearner (FASE 2) — learning de usuario
        self._learner = None
        try:
            from ocr.format_learner import FormatLearner
            self._learner = FormatLearner()
        except (ImportError, Exception):
            pass

    def process_from_dict(self, raw_fields: Dict[str, str], full_text: str = "") -> TypedInvoice:
        """
        Procesa un dict de campos raw y produce un TypedInvoice validado.

        Args:
            raw_fields: Dict con campos string (ej: {"rif_emisor": "J-12345678-9", ...})
            full_text: Texto OCR completo (para deteccion de moneda)

        Returns:
            TypedInvoice con todos los campos tipados y validados.
        """
        # 1. Correcciones
        corrected, corrections_log = self._corrections_pipeline.apply(raw_fields)

        # 2. Converter
        converter = FieldConverter(full_text)

        typed = TypedInvoice()
        typed.corrections_applied = corrections_log

        # Campos string directos
        for campo in ["numero_factura", "numero_control", "razon_social",
                       "direccion", "cliente"]:
            setattr(typed, campo, corrected.get(campo, ""))

        # Campos con conversion
        typed.fecha = converter.convert_date(corrected.get("fecha", ""))
        typed.rif_emisor = converter.convert_rif(corrected.get("rif_emisor", ""))
        typed.telefono = converter.normalize_phone(corrected.get("telefono", ""))

        # Montos
        typed.base_imponible = converter.convert_amount(
            corrected.get("base_imponible", ""), "base_imponible"
        )
        typed.iva = converter.convert_amount(
            corrected.get("iva", ""), "iva"
        )
        typed.total = converter.convert_amount(
            corrected.get("total", ""), "total"
        )

        # Moneda
        typed.currency = corrected.get("currency", "BS")
        if not typed.currency:
            # Detectar del texto completo
            typed.currency = _detect_currency(full_text or "", corrected.get("total", ""))

        # Tipo de cambio (opcional)
        exchange_raw = corrected.get("exchange_rate", "")
        if exchange_raw:
            try:
                typed.exchange_rate = float(exchange_raw)
            except (ValueError, TypeError):
                pass

        # Condicion de pago
        typed.condicion_pago = corrected.get("condicion_pago", "")

        # Obtener tasas multi-moneda si hay total
        if typed.total and typed.total.value and typed.total.value > 0:
            try:
                from ocr.bcv_rate import get_currency_provider
                provider = get_currency_provider()
                conv = provider.convert_to_all(typed.total.value, typed.currency)
                typed.total.in_bs = conv.get("BS", 0.0)
                typed.total.in_usd = conv.get("USD", 0.0)
            except (ImportError, Exception):
                pass

        # 3. Cross-validacion
        typed = self._cross_validator.validate(typed)

        # 3b. Auto-fix: si hay IVA inconsistente, recalcularlo automaticamente
        if self._auto_fix:
            typed = self._auto_fix_iva(typed)

        # OCR confidence (si se paso como string)
        conf_raw = corrected.get("ocr_confidence", "")
        if conf_raw:
            try:
                typed.ocr_confidence = float(conf_raw)
            except (ValueError, TypeError):
                pass

        return typed

    def _auto_fix_iva(self, typed: TypedInvoice) -> TypedInvoice:
        """
        Auto-corrige el IVA cuando CrossValidator detecta inconsistencia.

        Cuando el IVA extraido no coincide con ninguna alicuota de la base,
        recalcula automaticamente el IVA usando la alicuota mas cercana.

        La correccion se registra en corrections_applied con source='auto_fix'.
        La inconsistencia original se modifica para reflejar la correccion.
        """
        if not typed.base_imponible or not typed.base_imponible.is_valid:
            return typed
        if typed.base_imponible.value is None or typed.base_imponible.value <= 0:
            return typed

        # Buscar inconsistencias de IVA que puedan ser auto-corregidas
        iva_issues = [
            inc for inc in typed.inconsistencies
            if inc["type"] == "iva_base_mismatch"
            and inc.get("expected") is not None
            and inc.get("expected", 0) > 0
        ]

        if not iva_issues:
            return typed

        base_value = typed.base_imponible.value

        # Obtener las alicuotas desde la config del CrossValidator
        iva_rates = self.config.get("iva_rates", [16.0, 8.0])

        # Tomar la primera inconsistencia de IVA
        issue = iva_issues[0]
        expected_iva = issue["expected"]
        actual_iva = issue["actual"]

        # Determinar la mejor alicuota (la que da el expected mas cercano)
        best_rate = None
        best_diff = float('inf')
        for rate in iva_rates:
            calc = round(base_value * rate / 100.0, 2)
            diff = abs(calc - expected_iva)
            if diff < best_diff:
                best_diff = diff
                best_rate = rate

        if best_rate is None:
            return typed

        corrected_iva = round(base_value * best_rate / 100.0, 2)

        # Solo aplicar si el valor corregido es diferente al actual
        if abs(corrected_iva - actual_iva) < 0.01:
            return typed

        # Actualizar el TypedAmount
        if typed.iva:
            typed.iva.value = corrected_iva
            typed.iva.raw = f"{corrected_iva:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            typed.iva.is_valid = True

        # Recalcular total si el total era base + iva_original
        total_was_fixed = False
        old_total_val = None
        new_total_val = None
        if typed.total and typed.total.value is not None and typed.total.value > 0:
            old_total_val = typed.total.value
            if abs(old_total_val - (base_value + actual_iva)) < 2.0:
                new_total_val = round(base_value + corrected_iva, 2)
                typed.total.value = new_total_val
                typed.total.raw = f"{new_total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                typed.total.is_valid = True
                total_was_fixed = True

        # Actualizar iva_rate
        typed.iva_rate = best_rate

        # Registrar la correccion de IVA
        typed.corrections_applied.append({
            "field": "iva",
            "from": f"{actual_iva:.2f}",
            "to": f"{corrected_iva:.2f}",
            "rate": f"{best_rate:.0f}%",
            "source": "auto_fix",
            "reason": (
                f"IVA {actual_iva:.2f} no corresponde a ninguna alicuota de "
                f"base {base_value:.2f}. Recalculado a {corrected_iva:.2f} "
                f"usando alicuota {best_rate:.0f}%"
            ),
        })

        # Si el total tambien se corrigio, registrarlo
        if total_was_fixed and old_total_val is not None and new_total_val is not None:
            if abs(new_total_val - old_total_val) > 0.01:
                typed.corrections_applied.append({
                    "field": "total",
                    "from": f"{old_total_val:.2f}",
                    "to": f"{new_total_val:.2f}",
                    "rate": f"{best_rate:.0f}%",
                    "source": "auto_fix",
                    "reason": f"Total recalculado: base {base_value:.2f} + IVA {corrected_iva:.2f}",
                })

        # Eliminar las inconsistencias de IVA que fueron corregidas
        typed.inconsistencies = [
            inc for inc in typed.inconsistencies
            if not (inc["type"] == "iva_base_mismatch")
        ]

        # Re-validar para actualizar estado
        typed = self._cross_validator.validate(typed)

        return typed

    def build_report(self, typed: TypedInvoice) -> InconsistencyReport:
        """Construye un reporte de validacion."""
        return self._inconsistency_detector.build_report(typed)

    def _get_format_learner_corrections(self, invoice_data: Any) -> Dict[str, Tuple[str, str]]:
        """
        Obtiene correcciones del FormatLearner (FASE 2) si esta disponible.
        Retorna dict {campo: (wrong, correct)} o {} si no hay.
        """
        if self._learner is None:
            return {}
        try:
            # Obtener campos del invoice y aplicar correcciones del learner
            if hasattr(invoice_data, "to_dict"):
                fields = invoice_data.to_dict()
            else:
                fields = invoice_data

            # El FormatLearner.apply_corrections_to_fields() retorna
            # los campos corregidos. Comparamos con original.
            corrected = self._learner.apply_corrections_to_fields(fields)
            corrections = {}
            for field, value in corrected.items():
                original = fields.get(field, "")
                if str(value).strip() and str(value).strip() != str(original).strip():
                    corrections[field] = (str(original), str(value))
            return corrections
        except Exception:
            return {}

    def process(self, invoice_data: Any) -> TypedInvoice:
        """
        Procesa un InvoiceData (de extractor.py) o un dict.

        Si FormatLearner (FASE 2) esta disponible, obtiene correcciones
        del feedback loop de usuarios automaticamente.

        Args:
            invoice_data: InvoiceData object o dict de campos.

        Returns:
            TypedInvoice tipado y validado.
        """
        # Intentar obtener correcciones del FormatLearner
        learner_corrections = self._get_format_learner_corrections(invoice_data)
        if learner_corrections:
            # Incorporar al pipeline de correcciones
            merged = dict(self._corrections_pipeline._user_corrections)
            merged.update(learner_corrections)
            self._corrections_pipeline._user_corrections = merged

        # Si es un objeto InvoiceData, extraer dict
        if hasattr(invoice_data, "to_dict"):
            raw = invoice_data.to_dict()
            full_text = getattr(invoice_data, "raw_text", "")
            raw["ocr_confidence"] = str(getattr(invoice_data, "ocr_confidence", ""))
        elif isinstance(invoice_data, dict):
            raw = invoice_data
            full_text = raw.get("raw_text", "")
        else:
            raise TypeError(f"Tipo no soportado: {type(invoice_data)}")

        return self.process_from_dict(raw, full_text)


# ============================================================
#  Funciones de alto nivel
# ============================================================

def postprocess_invoice(
    invoice_data: Any,
    config: Optional[Dict] = None,
    user_corrections: Optional[Dict] = None,
) -> TypedInvoice:
    """
    Funcion de alto nivel: ejecuta todo el pipeline FASE 3.

    Args:
        invoice_data: InvoiceData object o dict de campos raw.
        config: Configuracion opcional (iva_rates, tolerance, etc.).
        user_corrections: Correcciones de usuario {campo: (wrong, correct)}.

    Returns:
        TypedInvoice tipado y validado.
    """
    pp = PostProcessor(config=config, user_corrections=user_corrections)
    return pp.process(invoice_data)


def validate_invoice(invoice_data: Any) -> InconsistencyReport:
    """
    Valida una factura y retorna solo el reporte de validacion.

    Util para checks rapidos sin necesidad del invoice completo.
    """
    pp = PostProcessor()
    typed = pp.process(invoice_data)
    return pp.build_report(typed)


def format_invoice_summary(typed: TypedInvoice) -> str:
    """Genera un resumen legible del invoice tipado."""
    lines = []
    lines.append("=" * 60)
    lines.append("  [NAD] RESUMEN DE FACTURA - POST-PROCESAMIENTO")
    lines.append("=" * 60)
    lines.append(f"  N. Factura:    {typed.numero_factura or '(vacio)'}")
    lines.append(f"  N. Control:    {typed.numero_control or '(vacio)'}")
    lines.append(f"  Fecha:         {typed.fecha or '(vacio)'}")
    lines.append(f"  RIF:           {typed.rif_emisor or '(vacio)'}")
    lines.append(f"  Razon Social:  {typed.razon_social or '(vacio)'}")
    lines.append(f"  Cliente:       {typed.cliente or '(vacio)'}")
    lines.append(f"  Base Imp.:     {typed.base_imponible or '(vacio)'}")
    lines.append(f"  IVA:           {typed.iva or '(vacio)'}")
    lines.append(f"  IVA Rate:      {f'{typed.iva_rate:.0f}%' if typed.iva_rate else '(auto)'}")
    lines.append(f"  Total:         {typed.total or '(vacio)'}")
    lines.append(f"  Moneda:        {typed.currency}")
    lines.append(f"  Cond. Pago:    {typed.condicion_pago or '(vacio)'}")
    lines.append(f"  Confianza OCR: {typed.ocr_confidence:.2f}")
    lines.append(f"  Estado:        {typed.validation_status.value.upper()}")

    if typed.inconsistencies:
        lines.append("")
        lines.append("  INCONSISTENCIAS:")
        for inc in typed.inconsistencies:
            sev = inc["severity"].upper()
            msg = inc["message"]
            lines.append(f"    [{sev}] {msg}")

    if typed.corrections_applied:
        lines.append("")
        lines.append("  CORRECCIONES:")
        for c in typed.corrections_applied:
            lines.append(f"    {c['field']}: '{c['from']}' -> '{c['to']}' ({c['source']})")

    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
#  Auto-test / demo
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  [NAD] FASE 3 - Demo de Post-Processing")
    print("=" * 60)

    # Datos de prueba (simulan salida de OCR)
    demo_fields = {
        "numero_factura": "001-0012345",
        "numero_control": "01-12345678",
        "fecha": "15/03/2025",
        "rif_emisor": "J-12345678-9",
        "razon_social": "COMERCIALIZADORA NACIONAL C.A.",
        "direccion": "Av. Principal, Edif. Centro, Caracas",
        "telefono": "0212-5551234",
        "cliente": "CLIENTE GENERICO S.A.",
        "base_imponible": "1250,00",
        "iva": "200,00",
        "total": "1450,00",
        "currency": "BS",
        "condicion_pago": "CONTADO",
    }

    # Procesar
    pp = PostProcessor()
    typed = pp.process_from_dict(demo_fields, "FACTURA N: 001-0012345 TOTAL: Bs. 1.450,00")

    print("\n[+] JSON tipado:")
    print(typed.to_json(indent=2))

    print("\n[+] Resumen:")
    print(format_invoice_summary(typed))

    # Reporte
    report = pp.build_report(typed)
    print(f"\n[+] Reporte de validacion:")
    print(f"  Score: {report.score:.2%}")
    print(f"  Status: {report.overall_status.value}")
    print(f"  Checks: {report.total_checks} (P:{report.passed} W:{report.warnings} E:{report.errors} C:{report.critical})")
