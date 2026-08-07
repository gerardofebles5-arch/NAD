"""
πNAD — ID Card Processor (Modo Cédula/Pasaporte)
==================================================
Procesamiento especializado para documentos de identidad:

1. Detección: heurísticas específicas para IDs (ratio ~1.6:1, bordes nítidos,
   fondo contrastante). Encuentra el cuadrilátero más grande con aspecto carnet.
2. Perspectiva: corrige a proporción oficial (5.1×3.5 cm = ~1.457:1 aspect ratio).
3. Fondo: reemplaza el fondo detectado con blanco puro (#FFFFFF).
4. Escalado: exporta a resolución 300 DPI → ~602×413 px.
5. Exportación: PNG lossless (ideal) o JPEG calidad 95.

Soporta tanto el pipeline síncrono (/process con capture_mode=id) como
un endpoint dedicado /process-id para control fino de parámetros.

Dimensiones de referencia:
  - Cédula venezolana: 5.1 × 3.5 cm
  - Pasaporte VE: 8.5 × 5.4 cm (página de datos)
  - Cédula de identidad COL: 5.4 × 3.5 cm
  - DNI Argentino: 8.5 × 5.4 cm
  - Pasaporte estándar (ICAO 9303): 8.8 × 12.5 cm (página entera)

DPI de impresión:
  - 200 DPI → estándar básico
  - 300 DPI → calidad fotográfica (predeterminado)
  - 600 DPI → ultra alta (archivo, no recomendado para visualización)
"""

import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any
from enum import Enum
import io
import base64

# ═══════════════════════════════════════════════════════════════
#  Configuración de ID Card
# ═══════════════════════════════════════════════════════════════

# Dimensiones oficiales en mm y su aspect ratio
ID_FORMATS_MM = {
    "cedula_ve":       (51.0, 35.0),   # 5.1 × 3.5 cm  → 1.457:1
    "dni_ar":          (85.0, 54.0),   # 8.5 × 5.4 cm  → 1.574:1
    "cedula_col":      (54.0, 35.0),   # 5.4 × 3.5 cm  → 1.543:1
    "pasaporte_page":  (88.0, 125.0),  # 8.8 × 12.5 cm → 0.704:1 (vertical)
    "standard_card":   (85.6, 53.98),  # CR-80 ISO/IEC 7810 ID-1 → 1.586:1
}

# Aspect ratios esperados (ancho/alto) con tolerancia
ID_ASPECT_RATIOS = {
    name: w / h for name, (w, h) in ID_FORMATS_MM.items()
}

# Blanco puro
WHITE = (255, 255, 255)


# ═══════════════════════════════════════════════════════════════
#  Pipeline principal
# ═══════════════════════════════════════════════════════════════

class IdCardProcessor:
    """Procesa imágenes de documentos de identidad para impresión."""

    def __init__(self, target_dpi: int = 300, white_threshold: int = 220):
        """
        Args:
            target_dpi: DPI de salida para impresión (default 300).
            white_threshold: Valor mínimo de gris para considerar píxel como
                            fondo y reemplazarlo con blanco puro (0-255).
        """
        self.target_dpi = target_dpi
        self.white_threshold = white_threshold

    def process(
        self,
        image: np.ndarray,
        corners: Optional[np.ndarray] = None,
        output_format: str = "png",
        id_format: str = "cedula_ve",
        auto_detect_format: bool = True,
    ) -> Dict[str, Any]:
        """
        Pipeline completo para documento de identidad.

        Args:
            image: Imagen BGR del documento detectado.
            corners: Esquinas opcionales (si ya fueron detectadas).
                     Si es None, se detectan automáticamente.
            output_format: 'png' (lossless, default) o 'jpeg'.
            id_format: Formato de ID objetivo ('cedula_ve', 'standard_card', etc.).
            auto_detect_format: Si True, intenta detectar el formato desde
                               la geometría del documento detectado.

        Returns:
            Dict con:
                - success: bool
                - processed_image: base64 del resultado
                - width_px: ancho en píxeles a 300 DPI
                - height_px: alto en píxeles a 300 DPI
                - width_mm: ancho en milímetros del formato
                - height_mm: alto en milímetros del formato
                - dpi: DPI usado
                - format_detected: string del formato detectado
                - has_white_background: bool
                - error: mensaje si falló
        """
        result = {
            "success": False,
            "format_detected": id_format,
            "dpi": self.target_dpi,
        }

        try:
            h, w = image.shape[:2]

            # 1. Si no hay corners, detectar el documento
            if corners is None:
                corners = self._detect_id_card(image)
                if corners is None:
                    # Fallback: usar toda la imagen como documento
                    corners = np.array([
                        [0, 0],
                        [w - 1, 0],
                        [w - 1, h - 1],
                        [0, h - 1],
                    ], dtype=np.float32)

            # 2. Determinar formato objetivo y aspect ratio
            if auto_detect_format:
                detected = self._detect_id_format(corners)
                if detected:
                    id_format = detected
                    result["format_detected"] = detected

            # 3. Obtener dimensiones en mm para el formato
            target_mm = ID_FORMATS_MM.get(
                id_format,
                ID_FORMATS_MM["cedula_ve"]
            )
            result["width_mm"] = target_mm[0]
            result["height_mm"] = target_mm[1]

            # 4. Calcular dimensiones en píxeles a DPI objetivo
            #    DPI = dots per inch → 1 inch = 25.4 mm
            target_aspect = target_mm[0] / target_mm[1]  # ancho/alto

            # Calcular píxeles a partir de mm y DPI
            target_w_px = int(round(target_mm[0] / 25.4 * self.target_dpi))
            target_h_px = int(round(target_mm[1] / 25.4 * self.target_dpi))

            result["width_px"] = target_w_px
            result["height_px"] = target_h_px

            # 5. Aplicar perspectiva a la proporción correcta
            processed = self._perspective_to_id_format(
                image, corners, target_w_px, target_h_px
            )

            # 6. Reemplazar fondo detectado con blanco puro
            processed = self._make_background_white(processed)

            # 7. Nitidez suave para texto (documento de identidad)
            processed = self._sharpen_id(processed)

            result["has_white_background"] = True

            # 8. Codificar según formato
            if output_format == "png":
                success, buffer = cv2.imencode('.png', processed)
                media_type = "image/png"
            else:
                success, buffer = cv2.imencode(
                    '.jpg', processed,
                    [cv2.IMWRITE_JPEG_QUALITY, 95]
                )
                media_type = "image/jpeg"

            if not success:
                raise ValueError("No se pudo codificar la imagen")

            result["success"] = True
            result["processed_image"] = base64.b64encode(buffer).decode("utf-8")
            result["media_type"] = media_type
            result["width_px_final"] = processed.shape[1]
            result["height_px_final"] = processed.shape[0]

        except Exception as e:
            result["error"] = str(e)
            import traceback
            traceback.print_exc()

        return result

    def _detect_id_card(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Detecta un documento de identidad en la imagen.

        Usa heurísticas específicas para IDs:
        - Canny con umbrales más bajos (bordes finos)
        - Busca cuadriláteros con aspect ratio cercano a 1.5:1
        - Prioriza contornos con bordes nítidos (alta densidad de bordes)

        Args:
            image: Imagen BGR.

        Returns:
            Array (4, 2) con esquinas ordenadas, o None.
        """
        h, w = image.shape[:2]
        img_area = h * w
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Desenfoque mínimo para preservar bordes finos del ID
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)

        # Canny con umbrales bajos para capturar bordes finos
        edges = cv2.Canny(blurred, 30, 100)

        # Encontrar contornos
        result = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if len(result) == 3:
            _, contours, _ = result
        else:
            contours, _ = result

        if not contours:
            return None

        # Ordenar por área descendente
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        best_corners = None
        best_score = 0.0

        for contour in contours[:15]:  # Top 15 contornos
            area = cv2.contourArea(contour)
            if area < img_area * 0.01:  # Mínimo 1% del área
                continue

            peri = cv2.arcLength(contour, True)
            epsilon = 0.015 * peri
            approx = cv2.approxPolyDP(contour, epsilon, True)

            if len(approx) != 4:
                continue
            if not cv2.isContourConvex(approx):
                continue

            corners_ordered = self._order_corners(approx.reshape(4, 2))

            # Calcular aspect ratio del cuadrilátero detectado
            top_w = np.linalg.norm(corners_ordered[1] - corners_ordered[0])
            bot_w = np.linalg.norm(corners_ordered[2] - corners_ordered[3])
            left_h = np.linalg.norm(corners_ordered[3] - corners_ordered[0])
            right_h = np.linalg.norm(corners_ordered[2] - corners_ordered[1])

            det_w = max(top_w, bot_w)
            det_h = max(left_h, right_h)

            if det_w < 1 or det_h < 1:
                continue

            aspect = det_w / det_h

            # Score: qué tan cerca está del aspect ratio esperado para IDs
            # Ideal: ~1.5 (cédula VE), aceptable: 1.3-1.8
            target_aspects = [1.457, 1.574, 1.543, 1.586]
            aspect_score = 1.0 - min(
                abs(aspect - ta) / ta for ta in target_aspects
            )
            aspect_score = max(0.0, aspect_score)

            # Score: área cubierta (preferir contornos grandes)
            area_ratio = area / img_area
            area_score = min(1.0, area_ratio * 5)  # 20% del área → score 1.0

            # Score combinado
            combined = aspect_score * 0.6 + area_score * 0.4

            if combined > best_score:
                best_score = combined
                best_corners = corners_ordered

        return best_corners

    def _detect_id_format(self, corners: np.ndarray) -> Optional[str]:
        """
        Detecta el formato de ID desde la geometría de las esquinas detectadas.

        Args:
            corners: Array (4, 2) con esquinas ordenadas.

        Returns:
            String con el formato ('cedula_ve', 'standard_card', etc.), o None.
        """
        top_w = np.linalg.norm(corners[1] - corners[0])
        bot_w = np.linalg.norm(corners[2] - corners[3])
        left_h = np.linalg.norm(corners[3] - corners[0])
        right_h = np.linalg.norm(corners[2] - corners[1])

        det_w = max(top_w, bot_w)
        det_h = max(left_h, right_h)

        if det_w < 1 or det_h < 1:
            return None

        aspect = det_w / det_h

        # Encontrar el formato más cercano por aspect ratio
        best_match = None
        best_diff = float('inf')

        for name, target_aspect in ID_ASPECT_RATIOS.items():
            diff = abs(aspect - target_aspect) / target_aspect
            if diff < best_diff and diff < 0.20:  # Tolerancia 20%
                best_diff = diff
                best_match = name

        return best_match

    def _perspective_to_id_format(
        self,
        image: np.ndarray,
        corners: np.ndarray,
        target_w: int,
        target_h: int,
    ) -> np.ndarray:
        """
        Corrige la perspectiva del documento de identidad a las dimensiones
        exactas del formato objetivo (target_w × target_h).

        Args:
            image: Imagen BGR original.
            corners: Array (4, 2) con esquinas ordenadas.
            target_w: Ancho objetivo en píxeles.
            target_h: Alto objetivo en píxeles.

        Returns:
            Imagen warp con las dimensiones exactas del formato.
        """
        dst_pts = np.array([
            [0, 0],
            [target_w - 1, 0],
            [target_w - 1, target_h - 1],
            [0, target_h - 1],
        ], dtype=np.float32)

        M = cv2.getPerspectiveTransform(corners.astype(np.float32), dst_pts)
        warped = cv2.warpPerspective(
            image, M, (target_w, target_h),
            flags=cv2.INTER_LANCZOS4,  # Mejor calidad para reducción
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=WHITE,
        )

        return warped

    def _make_background_white(self, image: np.ndarray) -> np.ndarray:
        """
        Reemplaza píxeles de fondo detectado con blanco puro.

        Estrategia:
        1. Convierte a grises.
        2. Los píxeles por encima de white_threshold se consideran fondo
           (papel blanco o fondo claro).
        3. Se aplica un suavizado morfológico para evitar bordes irregulares.
        4. Los píxeles de fondo se reemplazan con (255, 255, 255).

        Args:
            image: Imagen BGR.

        Returns:
            Imagen con fondo blanco puro.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Crear máscara: píxeles que son "fondo" (claros)
        _, mask = cv2.threshold(gray, self.white_threshold, 255, cv2.THRESH_BINARY)

        # Suavizar bordes de la máscara con morfología
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # Suavizar transiciones con blur
        mask_float = cv2.GaussianBlur(mask.astype(np.float32), (5, 5), 0) / 255.0

        # Mezclar: donde mask=1 → blanco puro, donde mask=0 → imagen original
        result = np.zeros_like(image)
        for c in range(3):
            result[:, :, c] = (
                image[:, :, c] * (1.0 - mask_float) +
                WHITE[c] * mask_float
            ).astype(np.uint8)

        return result

    def _sharpen_id(self, image: np.ndarray) -> np.ndarray:
        """
        Aplica nitidez específica para documentos de identidad.

        Usa un kernel de nitidez suave que realza texto sin crear halos.
        Aplica después del blanqueado de fondo para evitar artefactos.

        Args:
            image: Imagen BGR con fondo blanco.

        Returns:
            Imagen con nitidez mejorada.
        """
        # Kernel de nitidez suave (menos agresivo que unsharp masking)
        kernel = np.array([
            [0, -0.2, 0],
            [-0.2, 1.8, -0.2],
            [0, -0.2, 0],
        ])

        sharpened = cv2.filter2D(image, -1, kernel)

        # Saturación media para preservar color
        result = cv2.addWeighted(image, 0.3, sharpened, 0.7, 0)

        return result

    def _order_corners(self, pts: np.ndarray) -> np.ndarray:
        """
        Ordena 4 puntos: [TL, TR, BR, BL].

        Args:
            pts: Array (4, 2) con puntos desordenados.

        Returns:
            Array (4, 2) ordenado.
        """
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]  # TL: suma mínima
        rect[2] = pts[np.argmax(s)]  # BR: suma máxima
        d = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(d)]  # TR: diff mínima
        rect[3] = pts[np.argmax(d)]  # BL: diff máxima
        return rect


# ═══════════════════════════════════════════════════════════════
#  Funciones de conveniencia
# ═══════════════════════════════════════════════════════════════

def process_id_card(
    image: np.ndarray,
    corners: Optional[np.ndarray] = None,
    dpi: int = 300,
    output_format: str = "png",
) -> Dict[str, Any]:
    """
    Función de conveniencia para procesar un documento de identidad.

    Args:
        image: Imagen BGR.
        corners: Esquinas opcionales.
        dpi: DPI de salida.
        output_format: 'png' o 'jpeg'.

    Returns:
        Dict con resultado del pipeline.
    """
    processor = IdCardProcessor(target_dpi=dpi)
    return processor.process(
        image, corners=corners,
        output_format=output_format,
        auto_detect_format=True,
    )


def get_id_card_info() -> Dict[str, Any]:
    """
    Retorna información sobre los formatos de ID soportados,
    dimensiones oficiales, y DPI recomendados.

    Útil para que la UI muestre las opciones al usuario.
    """
    formats = {}
    for name, (w_mm, h_mm) in ID_FORMATS_MM.items():
        formats[name] = {
            "width_mm": w_mm,
            "height_mm": h_mm,
            "width_inch": round(w_mm / 25.4, 4),
            "height_inch": round(h_mm / 25.4, 4),
            "aspect_ratio": round(w_mm / h_mm, 4),
            "pixels_at_300dpi": {
                "width": int(round(w_mm / 25.4 * 300)),
                "height": int(round(h_mm / 25.4 * 300)),
            },
            "pixels_at_200dpi": {
                "width": int(round(w_mm / 25.4 * 200)),
                "height": int(round(h_mm / 25.4 * 200)),
            },
            "pixels_at_600dpi": {
                "width": int(round(w_mm / 25.4 * 600)),
                "height": int(round(h_mm / 25.4 * 600)),
            },
        }

    return {
        "formats": formats,
        "default_dpi": 300,
        "dpi_options": [200, 300, 600],
        "output_formats": ["png", "jpeg"],
        "description": (
            "Modo ID: corrige perspectiva a dimensiones oficiales del "
            "documento de identidad, reemplaza fondo con blanco puro, "
            "y exporta a la resolución especificada en DPI para impresión."
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  Test / Demo
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  πNAD — ID Card Processor Test")
    print("=" * 60)

    info = get_id_card_info()
    for name, fmt in info["formats"].items():
        print(f"\n  {name}:")
        print(f"    Dimensiones: {fmt['width_mm']}×{fmt['height_mm']} mm")
        print(f"    Aspect ratio: {fmt['aspect_ratio']}")
        print(f"    300 DPI: {fmt['pixels_at_300dpi']['width']}×{fmt['pixels_at_300dpi']['height']} px")
        print(f"    200 DPI: {fmt['pixels_at_200dpi']['width']}×{fmt['pixels_at_200dpi']['height']} px")
        print(f"    600 DPI: {fmt['pixels_at_600dpi']['width']}×{fmt['pixels_at_600dpi']['height']} px")
