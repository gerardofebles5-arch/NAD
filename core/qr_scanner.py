"""
Lector de QR / Código de barras — validación cruzada exacta
================================================================
Ni PhotoScan, ni CamScanner, ni MinerU leen los códigos QR o de barras que
muchas facturas y tickets fiscales ya traen impresos. Cuando existe uno,
es la fuente MÁS confiable de todas: no depende de interpretar letras
manuscritas ni de la calidad del OCR — es una lectura exacta.

Este módulo:
  1. Detecta y decodifica QR y códigos de barra 1D en la imagen.
  2. Si el contenido parece estructurado (pares clave=valor, o una URL con
     query params — patrón común en comprobantes fiscales), lo parsea.
  3. Busca dentro del texto decodificado patrones ya conocidos (RIF, montos,
     números de control) para poder cruzarlos contra lo que dijo el OCR.

No asume un formato SENIAT específico (no hay un estándar público único),
así que el parseo es deliberadamente genérico y tolerante.
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np


_RIF_RE = re.compile(r'\b([VEJPGvejpg])[\-\.]?\s?(\d{8,9})[\-]?(\d)\b')
_AMOUNT_RE = re.compile(r'\b\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b')
_DATE_RE = re.compile(r'\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b')


def _parse_payload(text: str) -> Dict[str, Any]:
    """Intenta estructurar el contenido decodificado del código."""
    parsed: Dict[str, Any] = {}

    # ¿Es una URL con query params? (patrón típico de QR de verificación fiscal)
    if text.startswith(("http://", "https://")):
        try:
            u = urlparse(text)
            parsed["url"] = f"{u.scheme}://{u.netloc}{u.path}"
            qs = parse_qs(u.query)
            if qs:
                parsed["params"] = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}
        except Exception:
            pass

    # ¿Trae pares clave=valor separados por & o | o ;? (otro patrón común)
    elif any(sep in text for sep in ("&", "|", ";")) and "=" in text:
        pairs = re.split(r'[&|;]', text)
        kv = {}
        for p in pairs:
            if "=" in p:
                k, _, v = p.partition("=")
                if k.strip():
                    kv[k.strip()] = v.strip()
        if kv:
            parsed["params"] = kv

    # Búsqueda de patrones conocidos dentro del texto crudo, independiente
    # de si se pudo estructurar como URL/pares clave=valor — para poder
    # cruzarlos contra el OCR aunque el QR solo traiga texto plano.
    rif_match = _RIF_RE.search(text)
    if rif_match:
        parsed["rif_detectado"] = f"{rif_match.group(1).upper()}-{rif_match.group(2)}-{rif_match.group(3)}"

    amount_match = _AMOUNT_RE.search(text)
    if amount_match:
        parsed["monto_detectado"] = amount_match.group(0)

    date_match = _DATE_RE.search(text)
    if date_match:
        parsed["fecha_detectada"] = date_match.group(0)

    return parsed


def detect_codes(image: np.ndarray) -> List[Dict[str, Any]]:
    """
    Detecta y decodifica todos los códigos QR y de barras 1D en la imagen.

    Args:
        image: Imagen BGR.

    Returns:
        Lista de dicts: {type, raw_value, parsed, points}
        - type: 'qr' o 'barcode'
        - raw_value: texto decodificado tal cual
        - parsed: dict con lo que se pudo estructurar (ver _parse_payload)
        - points: las 4 esquinas del código en la imagen (para overlay/debug)
    """
    results: List[Dict[str, Any]] = []
    if image is None or image.size == 0:
        return results

    # ── QR codes ──
    try:
        qr_detector = cv2.QRCodeDetector()
        ok, decoded_info, points, _ = qr_detector.detectAndDecodeMulti(image)
        if ok:
            for text, pts in zip(decoded_info, points if points is not None else []):
                if not text:
                    continue
                results.append({
                    "type": "qr",
                    "raw_value": text,
                    "parsed": _parse_payload(text),
                    "points": pts.tolist() if pts is not None else None,
                })
    except Exception as e:
        print(f"  [QR] Error detectando QR: {e}")

    # ── Códigos de barra 1D (EAN, CODE128, etc.) ──
    try:
        bc_detector = cv2.barcode.BarcodeDetector()
        ok, decoded_info, decoded_type, points = bc_detector.detectAndDecodeMulti(image)
        if ok:
            for i, text in enumerate(decoded_info):
                if not text:
                    continue
                pts = points[i] if points is not None and i < len(points) else None
                btype = decoded_type[i] if decoded_type is not None and i < len(decoded_type) else "unknown"
                results.append({
                    "type": "barcode",
                    "barcode_format": str(btype),
                    "raw_value": text,
                    "parsed": _parse_payload(text),
                    "points": pts.tolist() if pts is not None else None,
                })
    except Exception as e:
        print(f"  [QR] Error detectando código de barras: {e}")

    return results


def cross_check_with_ocr(codes: List[Dict[str, Any]], ocr_data: Dict[str, Any]) -> List[str]:
    """
    Compara lo leído del QR/barra contra lo que extrajo el OCR y genera
    avisos si no coinciden — un cruce de validación que ningún competidor
    ofrece, porque ninguno lee el código en primer lugar.

    Returns:
        Lista de mensajes de advertencia/confirmación (strings).
    """
    notes: List[str] = []
    for code in codes:
        parsed = code.get("parsed", {})

        rif_qr = parsed.get("rif_detectado") or (parsed.get("params") or {}).get("rif")
        if rif_qr:
            rif_ocr = (ocr_data.get("rif_emisor") or "").upper().replace(" ", "")
            rif_qr_norm = str(rif_qr).upper().replace(" ", "")
            if rif_ocr and rif_ocr != rif_qr_norm:
                notes.append(f"⚠ El RIF leído por OCR ({rif_ocr}) no coincide con el del código {code['type'].upper()} ({rif_qr_norm})")
            elif rif_ocr == rif_qr_norm:
                notes.append(f"✓ RIF confirmado por código {code['type'].upper()}")

        monto_qr = parsed.get("monto_detectado") or (parsed.get("params") or {}).get("monto") or (parsed.get("params") or {}).get("total")
        if monto_qr:
            total_ocr = (ocr_data.get("total") or "").replace(" ", "")
            if total_ocr and str(monto_qr).replace(" ", "") != total_ocr:
                notes.append(f"⚠ El total leído por OCR ({total_ocr}) no coincide con el del código ({monto_qr})")
            elif total_ocr:
                notes.append(f"✓ Total confirmado por código {code['type'].upper()}")

    return notes
