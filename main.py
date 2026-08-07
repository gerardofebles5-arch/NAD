#!/usr/bin/env python3
"""
NAD Scanner — Sistema de captura, procesamiento y subida automática de facturas.
================================================================================
Flujo completo:
  1. Captura múltiple (PhotoScan)
  2. Alineación por características (ORB)
  3. Fusión anti-glare (mediana)
  4. Detección de documento (CamScanner)
  5. Perspectiva + Realce (CLAHE + umbral)
  6. OCR + Extracción estructurada
  7. Subida a Google Drive
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from utils.config import CONFIG
from core.capture import capture_multishot, preview_camera
from core.align import align_shots, render_matches
from core.fusion import fuse_shots, fuse_with_depth_weights
from core.detector import detect_document, draw_detection
from core.enhancer import (
    perspective_correct,
    enhance_document,
    auto_detect_mode,
)
from ocr.extractor import extract_invoice_data, InvoiceData
from ocr.exchange_alert import ExchangeAlert, check_exchange_alerts, ALERT_WARNING, ALERT_CRITICAL
from ocr.bcv_rate import CURRENCY_INFO
from drive.uploader import upload_to_drive, flush_queue, OfflineQueueManager


# ══════════════════════════════════════════════
#  Constantes
# ══════════════════════════════════════════════
VERSION = "1.0.0"
APP_NAME = "NAD Scanner — PhotoScan + CamScanner Hybrid"


# ══════════════════════════════════════════════
#  Funciones auxiliares
# ══════════════════════════════════════════════

def _ensure_output_dirs():
    """Crea los directorios de salida si no existen."""
    Path(CONFIG.output_dir, CONFIG.render_subdir).mkdir(parents=True, exist_ok=True)
    Path(CONFIG.output_dir, CONFIG.data_subdir).mkdir(parents=True, exist_ok=True)
    Path(CONFIG.drive.local_queue_dir).mkdir(parents=True, exist_ok=True)


def _generate_filename(invoice_number: str, date_str: str, ext: str) -> str:
    """
    Genera un nombre de archivo estandarizado.

    Args:
        invoice_number: Número de factura.
        date_str: Fecha en formato DD-MM-AAAA.
        ext: Extensión (sin punto).

    Returns:
        Nombre de archivo: "{numero_factura}_{DD-MM-AAAA}.{ext}"
    """
    safe_number = invoice_number.replace("/", "-").replace("\\", "-") if invoice_number else "SIN_NUMERO"
    safe_date = date_str.replace("/", "-") if date_str else datetime.now().strftime("%d-%m-%Y")
    if ext:
        return f"{safe_number}_{safe_date}.{ext}"
    return f"{safe_number}_{safe_date}"


def _save_render(image: np.ndarray, filename: str) -> str:
    """Guarda la imagen renderizada y retorna la ruta."""
    path = os.path.join(CONFIG.output_dir, CONFIG.render_subdir, filename)
    cv2.imwrite(path, image)
    print(f"  💾 Imagen guardada: {path}")
    return path


def _save_json(data: dict, filename: str) -> str:
    """Guarda los datos en JSON y retorna la ruta."""
    path = os.path.join(CONFIG.output_dir, CONFIG.data_subdir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  💾 Datos guardados: {path}")
    return path


def _get_currency_info(currency: str) -> dict:
    """Retorna info de moneda desde CURRENCY_INFO centralizado."""
    curr = currency.upper()
    return CURRENCY_INFO.get(curr, CURRENCY_INFO.get("USD"))


def _format_currency(amount: float, currency: str = 'BS') -> str:
    """Formatea un monto con símbolo de moneda (BS/USD/EUR/COP/ARS). Fuente: CURRENCY_INFO."""
    curr = currency.upper()
    info = _get_currency_info(curr)
    symbol = info["symbol"]
    locale = info["locale"]
    decimals = info["decimals"]

    # Formatos localizados desde CURRENCY_INFO
    if locale in ("ve", "eu", "ar"):
        # VE/EU/AR: 1.250,00
        formatted = f"{amount:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif curr == 'COP':
        # COP: 4.100 (sin decimales)
        formatted = f"{amount:,.0f}".replace(",", ".")
    else:
        # USD: 1,250.00
        formatted = f"{amount:,.{decimals}f}"

    return f"{symbol} {formatted}"


def _show_result(image: np.ndarray, invoice: InvoiceData, window_name: str = "NAD Scanner — Resultado"):
    """Muestra el resultado final en una ventana OpenCV con moneda multi-divisa."""
    # Redimensionar si es muy grande
    h, w = image.shape[:2]
    max_w = 1200
    if w > max_w:
        scale = max_w / w
        new_w = int(w * scale)
        new_h = int(h * scale)
        display = cv2.resize(image, (new_w, new_h))
    else:
        display = image.copy()

    dh, dw = display.shape[:2]

    # ── Calcular partes de conversión multi-moneda ──
    conv_parts = []
    for curr, val in [
        ('BS', invoice.total_bs), ('USD', invoice.total_usd),
        ('EUR', invoice.total_eur), ('COP', invoice.total_cop),
        ('ARS', invoice.total_ars),
    ]:
        if val > 0 and curr != (invoice.currency or 'BS'):
            conv_parts.append(_format_currency(val, curr))
    has_two_lines = len(conv_parts) > 3

    # ── Contar alertas para expandir overlay ──
    exchange_alerts = invoice.ocr_stats.get('exchange_alerts', [])
    overlay_alerts = ExchangeAlert.get_overlay_lines(exchange_alerts, max_lines=2) if exchange_alerts else []
    n_alert_lines = len(overlay_alerts)

    # ── Determinar altura del overlay ANTES de dibujar texto ──
    overlay_height = 160
    if has_two_lines:
        overlay_height = 180
    if n_alert_lines > 0:
        overlay_height += n_alert_lines * 22 + 6

    # ── Fondo semitransparente (una sola vez, altura correcta) ──
    overlay_bg = display.copy()
    cv2.rectangle(overlay_bg, (0, 0), (dw, overlay_height), (0, 0, 0), -1)
    cv2.addWeighted(overlay_bg, 0.55, display, 0.45, 0, display)

    # ── Línea 1: Factura + Fecha ──
    cv2.putText(display, f"Factura: {invoice.numero_factura or 'N/A'}    Fecha: {invoice.fecha or 'N/A'}",
                (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    # ── Línea 2: RIF + Razón Social ──
    cv2.putText(display, f"RIF: {invoice.rif_emisor or 'N/A'}    {invoice.razon_social or ''}",
                (20, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 220, 255), 1)

    # ── Línea 3: Moneda detectada + Total + Tasas (dinámico) ──
    detected = invoice.currency or CONFIG.ocr.currency_default
    curr_info = _get_currency_info(detected)
    sym = curr_info["symbol"]
    currency_line = f"{sym} {invoice.total or 'N/A'}   |   [{detected}]"
    if invoice.exchange_rate > 0:
        currency_line += f"   |   1 USD = {invoice.exchange_rate:.2f} {detected}"
    # Color del símbolo según la moneda detectada
    line_color = (0, 245, 212) if detected in ("BS", "VES") else \
                 (255, 215, 0) if detected == "USD" else \
                 (100, 200, 255)  # EUR/COP/ARS = tono azulado
    cv2.putText(display, currency_line,
                (20, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.6, line_color, 2)

    # ── Línea 4: Multi-monedas convertidas ──
    if conv_parts:
        cv2.putText(display, "  ".join(conv_parts[:3]),
                    (20, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 215, 0), 2)
        if has_two_lines:
            cv2.putText(display, "  ".join(conv_parts[3:]),
                        (20, 124), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 215, 0), 2)

    # ── Línea 5: Condición de pago + confianza ──
    y5 = 148 if has_two_lines else 130
    cv2.putText(display, f"Pago: {invoice.condicion_pago or 'N/A'}    Confianza: {invoice.ocr_confidence:.1%}",
                (20, y5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    # ── Alertas de tasa de cambio (si las hay) ──
    if overlay_alerts:
        y_alert = y5 + 24
        for alert_text, color in overlay_alerts:
            cv2.putText(display, alert_text,
                        (20, y_alert), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            y_alert += 22

    # ── Footer ──
    cv2.putText(display, "Presione ESPACIO para continuar, Q para salir",
                (20, dh - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

    cv2.imshow(window_name, display)
    while True:
        key = cv2.waitKey(0) & 0xFF
        if key == ord(' '):
            break
        elif key == ord('q') or key == 27:
            return False
    cv2.destroyWindow(window_name)
    return True


# ══════════════════════════════════════════════
#  Pipeline principal
# ══════════════════════════════════════════════

def process_invoice(
    shots: List[np.ndarray],
    output_mode: str = "documento",
    interactive: bool = True,
    upload: bool = True,
) -> Optional[InvoiceData]:
    """
    Procesa una factura a través de todo el pipeline.

    Args:
        shots: Lista de 5 tomas capturadas.
        output_mode: 'documento', 'grises', o 'color'.
        interactive: Si True, permite corrección manual de OCR.
        upload: Si True, sube los resultados a Google Drive.

    Returns:
        InvoiceData con los datos extraídos, o None si falló.
    """
    print("\n" + "=" * 60)
    print(f"  {APP_NAME} v{VERSION}")
    print("=" * 60)

    # ── Bloque 2: Alineación ──
    print("\n📐 Bloque 2: Alineando tomas...")
    aligned = align_shots(shots)
    valid_aligned = [a for a in aligned if a is not None]
    if len(valid_aligned) < 3:
        print("  ✗ Error: muy pocas tomas alineadas correctamente.")
        return None
    print(f"  ✓ {len(valid_aligned)}/{len(shots)} tomas alineadas.")

    # ── Bloque 3: Fusión anti-glare ──
    print("\n✨ Bloque 3: Fusionando (anti-glare)...")
    fused = fuse_shots(aligned)
    if fused is None:
        print("  ✗ Error: no se pudo fusionar.")
        return None
    print("  ✓ Fusión completada.")

    # ── Bloque 4: Detección de documento ──
    print("\n🔍 Bloque 4: Detectando documento...")
    corners, contour = detect_document(fused)
    if corners is None:
        print("  ⚠ Usando la imagen completa (sin recorte).")
        # Usar las esquinas de la imagen completa
        h, w = fused.shape[:2]
        corners = np.array([
            [0, 0],
            [w - 1, 0],
            [w - 1, h - 1],
            [0, h - 1],
        ], dtype=np.float32)

    # ── Bloque 5: Perspectiva + Realce ──
    print("\n🎨 Bloque 5: Corrigiendo perspectiva y realzando...")
    corrected = perspective_correct(fused, corners)

    # Detectar modo automático si es "auto" (por imagen, sin reasignar el parámetro)
    effective_mode = output_mode
    if effective_mode == "auto":
        effective_mode = auto_detect_mode(corrected)
        print(f"  → Modo detectado: {effective_mode}")

    enhanced = enhance_document(corrected, effective_mode)
    print("  ✓ Documento procesado.")

    # ── Bloque 6: OCR + Extracción ──
    print("\n📝 Bloque 6: Extrayendo datos con OCR...")
    invoice = extract_invoice_data(enhanced, interactive=interactive)
    print(f"  ✓ OCR completado (confianza: {invoice.ocr_confidence:.2f}).")

    # ── Guardar resultados ──
    print("\n💾 Guardando resultados...")
    date_str = invoice.fecha.replace("/", "-") if invoice.fecha else datetime.now().strftime("%d-%m-%Y")
    filename_base = _generate_filename(invoice.numero_factura, date_str, "")

    render_filename = f"{filename_base}.png"
    json_filename = f"{filename_base}.json"

    render_path = _save_render(enhanced, render_filename)
    data_path = _save_json(invoice.to_dict(), json_filename)

    # ── Mostrar resultado al operador ──
    print("\n📊 Resultado de la extracción:")
    print("-" * 40)
    for key, val in invoice.to_dict().items():
        print(f"  {key:20s}: {val}")
    print("-" * 40)

    # ── Alertas de tasa de cambio ──
    exchange_alerts = []
    if CONFIG.ocr.alert_enabled and invoice.all_rates:
        exchange_alerts = check_exchange_alerts(invoice.all_rates)

    # Mostrar multi-moneda y tasas
    if invoice.exchange_rate > 0 or invoice.all_rates:
        detected = invoice.currency or CONFIG.ocr.currency_default
        curr_info = _get_currency_info(detected)
        print(f"\n💰 Moneda detectada: {detected} ({curr_info['name']})")
        if invoice.all_rates:
            print(f"📊 Tasas de cambio (vs USD):")
            for curr in ['BS', 'VES', 'EUR', 'COP', 'ARS']:
                rate = invoice.all_rates.get(curr, 0)
                if rate > 0:
                    info = _get_currency_info(curr)
                    print(f"   1 USD = {rate:>10.4f} {curr} ({info['name']})")
        else:
            print(f"📊 Tasa {detected}/USD: 1 USD = {invoice.exchange_rate:.2f} {detected}")

        print(f"\n💱 Conversiones ({_format_currency(invoice.total or 0, invoice.currency)}):")
        has_conv = False
        for curr, val in [('BS', invoice.total_bs), ('USD', invoice.total_usd),
                          ('EUR', invoice.total_eur), ('COP', invoice.total_cop),
                          ('ARS', invoice.total_ars)]:
            if val > 0 and curr != invoice.currency:
                print(f"   → {_format_currency(val, curr)}")
                has_conv = True
        if not has_conv:
            print(f"   {_format_currency(invoice.total or 0, invoice.currency)}")

    # Guardar alertas para usar en _show_result
    invoice.ocr_stats['exchange_alerts'] = exchange_alerts

    # Mostrar en ventana (con moneda y BCV)
    if not _show_result(enhanced, invoice):
        print("\n⏹ Procesamiento cancelado por el operador.")
        return invoice

    # ── Bloque 7: Subida a Google Drive ──
    if upload:
        print(f"\n☁️ Bloque 7: Subiendo a Google Drive...")
        upload_to_drive(
            render_path=render_path,
            invoice_data=invoice.to_dict(),
            invoice_number=invoice.numero_factura,
            date_str=date_str,
        )

    # ── Mostrar validaciones ──
    if invoice.validation_errors:
        print(f"\n⚠ Advertencias de validación ({len(invoice.validation_errors)}):")
        for err in invoice.validation_errors:
            print(f"  • {err}")

    return invoice


# ══════════════════════════════════════════════
#  Modo lote: procesar imágenes existentes
# ══════════════════════════════════════════════

def process_batch(image_paths: List[str], output_mode: str = "documento"):
    """
    Procesa imágenes ya capturadas (sin cámara).

    Args:
        image_paths: Lista de rutas a imágenes.
        output_mode: Modo de realce (o 'auto' para detección por imagen).
    """
    print(f"\n📦 Procesando lote de {len(image_paths)} imágenes...")

    for path in image_paths:
        print(f"\n{'='*60}")
        print(f"  Archivo: {path}")
        print(f"{'='*60}")

        img = cv2.imread(path)
        if img is None:
            print(f"  ✗ No se pudo cargar: {path}")
            continue

        # Crear shots simulados (solo 1)
        shots = [img]

        # Saltar alineación y fusión, ir directo a detección
        h, w = img.shape[:2]
        corners = np.array([
            [0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]
        ], dtype=np.float32)

        corrected = perspective_correct(img, corners)

        # Detectar modo por imagen (no reusa el de la iteración anterior)
        current_mode = output_mode
        if current_mode == "auto":
            current_mode = auto_detect_mode(corrected)
            print(f"  → Modo auto detectado: {current_mode}")

        enhanced = enhance_document(corrected, current_mode)

        invoice = extract_invoice_data(enhanced, interactive=True)

        date_str = invoice.fecha.replace("/", "-") or datetime.now().strftime("%d-%m-%Y")
        filename_base = _generate_filename(invoice.numero_factura, date_str, "")
        _save_render(enhanced, f"{filename_base}.png")
        _save_json(invoice.to_dict(), f"{filename_base}.json")

        _show_result(enhanced, invoice)


# ══════════════════════════════════════════════
#  Modo escaneo continuo
# ══════════════════════════════════════════════

def scan_loop(output_mode: str = "documento", interactive: bool = True, upload: bool = True):
    """
    Bucle continuo de escaneo: captura → procesa → sube → repite.

    Args:
        output_mode: Modo de realce.
        interactive: Corrección manual de OCR.
        upload: Subir a Google Drive.
    """
    print(f"\n🔄 {APP_NAME} v{VERSION} — Modo Escaneo Continuo")
    print("=" * 60)
    print("  • Coloque la factura bajo la cámara")
    print("  • Alinee los 4 círculos guía")
    print("  • Revise los datos extraídos")
    print("  • Presione ESPACIO para confirmar")
    print("  • El sistema sube automáticamente a Drive")
    print("  • Repita con la siguiente factura")
    print("  • Presione Q en cualquier momento para salir\n")

    _ensure_output_dirs()
    queue_mgr = OfflineQueueManager()
    invoice_count = 0

    while True:
        print(f"\n📄 Factura #{invoice_count + 1}")
        print("-" * 40)

        try:
            # Bloque 1: Captura
            print("\n📷 Bloque 1: Capturando tomas...")
            print("  → Mueva la cámara para alinear los 4 círculos guía.")
            shots = capture_multishot()
        except Exception as e:
            print(f"  ✗ Error de captura: {e}")
            break

        if len(shots) < 2:
            print("  ⏹ Captura insuficiente. Saliendo...")
            break

        # Procesar
        invoice = process_invoice(
            shots, output_mode=output_mode,
            interactive=interactive, upload=upload,
        )

        if invoice is not None:
            invoice_count += 1
            print(f"\n✅ Factura #{invoice_count} procesada exitosamente.")

        # Verificar cola offline
        if queue_mgr.has_pending():
            print(f"\n📤 {queue_mgr.count_pending()} archivos pendientes en cola.")
            if upload:
                flush_queue()

        # Preguntar si continuar
        print("\n¿Escaneamos otra factura? (ESPACIO = sí, Q = salir)")
        while True:
            key = cv2.waitKey(0) & 0xFF
            if key == ord(' '):
                break
            elif key == ord('q') or key == 27:
                print(f"\n🏁 Sesión completada: {invoice_count} facturas procesadas.")
                # Vaciado final de cola
                if upload and queue_mgr.has_pending():
                    print("  📤 Vaciando cola final...")
                    flush_queue()
                return

    print(f"\n🏁 Sesión terminada: {invoice_count} facturas procesadas.")


# ══════════════════════════════════════════════
#  Punto de entrada
# ══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s                         # Modo interactivo con cámara
  %(prog)s --preview               # Solo previsualizar cámara
  %(prog)s --batch img1.png img2.png   # Procesar imágenes existentes
  %(prog)s --mode grises           # Modo escala de grises
  %(prog)s --no-upload             # Sin subir a Drive
  %(prog)s --no-interactive        # Sin corrección manual
  %(prog)s --flush-queue           # Subir archivos pendientes
        """
    )

    parser.add_argument(
        "--preview", action="store_true",
        help="Solo previsualizar la cámara (sin capturar)"
    )
    parser.add_argument(
        "--batch", nargs="+",
        help="Procesar imágenes existentes (rutas)"
    )
    parser.add_argument(
        "--mode", choices=["documento", "grises", "color", "auto"],
        default="documento",
        help="Modo de realce de salida (default: documento)"
    )
    parser.add_argument(
        "--no-upload", action="store_true",
        help="No subir a Google Drive"
    )
    parser.add_argument(
        "--no-interactive", action="store_true",
        help="No mostrar corrección interactiva de OCR"
    )
    parser.add_argument(
        "--flush-queue", action="store_true",
        help="Reintentar subir archivos pendientes en la cola"
    )
    parser.add_argument(
        "--continuous", action="store_true",
        help="Modo escaneo continuo (loop)"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {VERSION}"
    )

    args = parser.parse_args()

    # ── Acciones ──

    if args.flush_queue:
        print("📤 Reintentando subida de archivos pendientes...")
        flush_queue()
        return

    if args.preview:
        preview_camera()
        return

    if args.batch:
        process_batch(args.batch, output_mode=args.mode)
        return

    # ── Modo normal ──
    _ensure_output_dirs()

    if args.continuous:
        scan_loop(
            output_mode=args.mode,
            interactive=not args.no_interactive,
            upload=not args.no_upload,
        )
        return

    # ── Una sola factura ──
    print(f"\n{'='*60}")
    print(f"  {APP_NAME} v{VERSION}")
    print(f"  Captura → Alineación → Fusión → OCR → Drive")
    print(f"{'='*60}")

    try:
        # Bloque 1: Captura
        print("\n📷 Bloque 1: Capturando 5 tomas...")
        shots = capture_multishot()
    except RuntimeError as e:
        print(f"\n✗ Error: {e}")
        print("  ¿Tiene una cámara conectada?")
        sys.exit(1)

    if len(shots) < 2:
        print("\n✗ No se capturaron suficientes tomas.")
        sys.exit(1)

    # Pipeline completo
    invoice = process_invoice(
        shots,
        output_mode=args.mode,
        interactive=not args.no_interactive,
        upload=not args.no_upload,
    )

    if invoice is None:
        print("\n✗ Error en el procesamiento de la factura.")
        sys.exit(1)

    print(f"\n✅ Procesamiento completado exitosamente.")
    print(f"📁 Imagen: {CONFIG.output_dir}/{CONFIG.render_subdir}/")
    print(f"📁 Datos:  {CONFIG.output_dir}/{CONFIG.data_subdir}/")

    # Verificar cola
    queue = OfflineQueueManager()
    if queue.has_pending():
        print(f"⏳ {queue.count_pending()} archivos pendientes de subida (cola offline).")

    # Vaciado de cola al final
    if not args.no_upload and queue.has_pending():
        print("\n📤 Intentando vaciar cola...")
        flush_queue()


if __name__ == "__main__":
    main()
