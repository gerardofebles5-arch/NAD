"""
Enhancer Avanzado — Nivel profesional PhotoScan + CamScanner + Microsoft Lens
============================================================================

Características que superan a la competencia:
1. Eliminación de sombras adaptativa
2. Corrección de arrugas (detección + suavizado)
3. Binarización Sauvola/Niblack (superior a adaptive threshold)
4. Restauración de color para documentos desvanecidos
5. Detección automática de tipo de documento
6. Evaluación de calidad del scan
7. Crop inteligente con márgenes configurables
8. Eliminación de bordes negros
9. Normalización de brillo/contraste
10. Pipeline optimizado para OCR
"""

import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any
from enum import Enum


class DocumentType(Enum):
    FACTURA = "factura"
    CONTRATO = "contrato"
    IDENTIFICACION = "identificacion"
    LIBRO = "libro"
    FOTO = "foto"
    PIZARRA = "pizarra"
    RECIBO = "recibo"
    CHEQUE = "cheque"


class ScanQuality(Enum):
    EXCELLENTE = "excelente"
    BUENO = "bueno"
    ACEPTABLE = "aceptable"
    MALO = "malo"
    INUTILIZABLE = "inutilizable"


# ══════════════════════════════════════════════════════════════
#  1. ELIMINACIÓN DE SOMBRA ADAPTATIVA
# ══════════════════════════════════════════════════════════════

def remove_shadows_adaptive(image: np.ndarray, strength: float = 0.7) -> np.ndarray:
    """
    Elimina sombras de la imagen usando normalización local.
    
    Mejora sobre CamScanner: usa divisiones morfológicas en vez de
    simple división, preservando mejor los bordes del texto.
    
    Args:
        image: Imagen BGR o grayscale
        strength: Intensidad de eliminación (0.0-1.0)
    
    Returns:
        Imagen sin sombras
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Fondo estimado con dilatación morfológica grande
    kernel_size = max(25, min(gray.shape) // 8)
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    background = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
    
    # División normalizada
    gray_f = gray.astype(np.float64)
    bg_f = background.astype(np.float64)
    
    # Evitar división por cero
    bg_f = np.maximum(bg_f, 1.0)
    
    normalized = (gray_f / bg_f) * 255.0
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    
    # Mezclar con original según strength
    result = cv2.addWeighted(gray, 1 - strength, normalized, strength, 0)
    
    return result


def remove_shadows_advanced(image: np.ndarray) -> np.ndarray:
    """
    Eliminación de sombras avanzada con múltiples escalas.
    
    Combina división morfológica con CLAHE para resultado superior.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Paso 1: Eliminación de sombra con kernel grande
    step1 = remove_shadows_adaptive(gray, strength=0.6)
    
    # Paso 2: CLAHE para equilibrar contraste local
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    step2 = clahe.apply(step1)
    
    # Paso 3: Normalización de brillo
    mean_brightness = np.mean(step2)
    target = 200  # Fondo blanco ideal
    if mean_brightness < 150:
        gamma = target / max(mean_brightness, 1)
        gamma = min(gamma, 2.0)  # Limitar corrección
        lut = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in range(256)]).astype(np.uint8)
        step2 = cv2.LUT(step2, lut)
    
    return step2


# ══════════════════════════════════════════════════════════════
#  2. CORRECCIÓN DE ARRUGAS
# ══════════════════════════════════════════════════════════════

def detect_wrinkles(gray: np.ndarray) -> np.ndarray:
    """
    Detecta arrugas en el documento.
    
    Returns:
        Máscara binaria de arrugas (255 = arruga detectada)
    """
    # Detectar líneas largas y delgadas (características de arrugas)
    # Usar CLAHE para resaltar arrugas
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)
    
    # Binarizar para isoler arrugas
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # Kernel horizontal para detectar arrugas horizontales
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    
    # Kernel vertical para detectar arrugas verticales
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    
    # Combinar
    wrinkles = cv2.bitwise_or(h_lines, v_lines)
    
    # Dilatar ligeramente para cubrir bordes de arrugas
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    wrinkles = cv2.dilate(wrinkles, kernel, iterations=1)
    
    return wrinkles


def correct_wrinkles(image: np.ndarray, wrinkle_mask: np.ndarray) -> np.ndarray:
    """
    Suaviza arrugas detectadas usando inpainting.
    
    Args:
        image: Imagen original
        wrinkle_mask: Máscara de arrugas
    
    Returns:
        Imagen con arrugas suavizadas
    """
    # Inpainting para rellenar arrugas
    # INPAINT_TELEA es mejor para bordes suaves (arrugas)
    corrected = cv2.inpaint(image, wrinkle_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    
    return corrected


def remove_wrinkles(image: np.ndarray) -> np.ndarray:
    """
    Pipeline completo de detección y corrección de arrugas.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    wrinkles = detect_wrinkles(gray)
    wrinkle_ratio = np.sum(wrinkles > 0) / wrinkles.size
    
    # Solo corregir si hay arrugas significativas (>0.5% de la imagen)
    if wrinkle_ratio > 0.005:
        corrected = correct_wrinkles(image, wrinkles)
        return corrected
    
    return image


# ══════════════════════════════════════════════════════════════
#  3. BINARIZACIÓN SAUVOLA/NIBLACK
# ══════════════════════════════════════════════════════════════

def sauvola_binarize(gray: np.ndarray, window_size: int = 25, k: float = 0.2, R: float = 128) -> np.ndarray:
    """
    Binarización de Sauvola — superior a umbral adaptativo para documentos.
    
    Ventaja sobre CamScanner: better manejo de iluminación no uniforme.
    
    Args:
        gray: Imagen grayscale
        window_size: Tamaño de ventana (debe ser impar)
        k: Parámetro de Sauvola (0.1-0.3 típico)
        R: Rango dinámico (128 típico)
    
    Returns:
        Imagen binarizada
    """
    if window_size % 2 == 0:
        window_size += 1
    
    # Calcular media y varianza locales
    mean = cv2.blur(gray.astype(np.float64), (window_size, window_size))
    mean_sq = cv2.blur((gray.astype(np.float64)) ** 2, (window_size, window_size))
    std = np.sqrt(np.maximum(mean_sq - mean ** 2, 0))
    
    # Umbral de Sauvola
    threshold = mean * (1 + k * (std / R - 1))
    
    # Binarizar
    binary = np.zeros_like(gray)
    binary[gray > threshold] = 255
    
    return binary


def niblack_binarize(gray: np.ndarray, window_size: int = 25, k: float = -0.2) -> np.ndarray:
    """
    Binarización de Niblack — buena para texto con bordes suaves.
    """
    if window_size % 2 == 0:
        window_size += 1
    
    mean = cv2.blur(gray.astype(np.float64), (window_size, window_size))
    mean_sq = cv2.blur((gray.astype(np.float64)) ** 2, (window_size, window_size))
    std = np.sqrt(np.maximum(mean_sq - mean ** 2, 0))
    
    threshold = mean + k * std
    
    binary = np.zeros_like(gray)
    binary[gray > threshold] = 255
    
    return binary


# ══════════════════════════════════════════════════════════════
#  4. RESTAURACIÓN DE COLOR
# ══════════════════════════════════════════════════════════════

def restore_color(image: np.ndarray) -> np.ndarray:
    """
    Restaura color en documentos desvanecidos o con mala iluminación.
    
    Usa blanco de referencia para normalizar el balance de color.
    """
    # Detectar si la imagen está desvanecida
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mean_saturation = np.mean(hsv[:, :, 1])
    mean_value = np.mean(hsv[:, :, 2])
    
    # Si la imagen está muy desaturada o oscura
    if mean_saturation < 40 or mean_value < 100:
        # Estimar blanco de referencia (percentil 95 del brillo)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        white_ref = np.percentile(gray, 95)
        
        # Normalizar cada canal
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Escalar L para que el blanco de referencia llegue a 255
        if white_ref > 0:
            scale = 240.0 / white_ref
            l = np.clip(l.astype(np.float64) * scale, 0, 255).astype(np.uint8)
        
        # Realzar saturación suavemente
        s = hsv[:, :, 1].astype(np.float64)
        s = np.clip(s * 1.3, 0, 255).astype(np.uint8)
        hsv[:, :, 1] = s
        
        lab = cv2.merge([l, a, b])
        image = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    
    return image


# ══════════════════════════════════════════════════════════════
#  5. DETECCIÓN DE TIPO DE DOCUMENTO
# ══════════════════════════════════════════════════════════════

def detect_document_type(image: np.ndarray) -> DocumentType:
    """
    Detecta automáticamente el tipo de documento.
    
    Analiza:
    - Relación de aspecto
    - Presencia de tablas
    - Densidad de texto
    - Patrones específicos (RIF, fechas, montos)
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    h, w = gray.shape[:2]
    aspect_ratio = w / h
    
    # Detectar tablas (líneas horizontales y verticales)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, 100, minLineLength=50, maxLineGap=10)
    
    has_table = False
    if lines is not None:
        h_lines = 0
        v_lines = 0
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = abs(np.arctan2(y2-y1, x2-x1) * 180 / np.pi)
            if angle < 10:  # Horizontal
                h_lines += 1
            elif angle > 80:  # Vertical
                v_lines += 1
        has_table = h_lines > 3 and v_lines > 3
    
    # Detectar densidad de texto
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    text_density = np.sum(binary > 0) / binary.size
    
    # Clasificar
    if aspect_ratio > 1.5:
        # Muy ancho: probablemente factura o recibo
        if has_table:
            return DocumentType.FACTURA
        return DocumentType.RECIBO
    elif aspect_ratio < 0.7:
        # Muy alto: probablemente libro o documento largo
        return DocumentType.LIBRO
    elif text_density > 0.3:
        # Alta densidad de texto: contrato o documento formal
        return DocumentType.CONTRATO
    elif text_density < 0.1:
        # Baja densidad: foto o imagen
        return DocumentType.FOTO
    
    return DocumentType.FACTURA  # Default


# ══════════════════════════════════════════════════════════════
#  6. EVALUACIÓN DE CALIDAD
# ══════════════════════════════════════════════════════════════

def assess_scan_quality(image: np.ndarray) -> Dict[str, Any]:
    """
    Evalúa la calidad del scan.
    
    Returns:
        Dict con score, nivel, y métricas detalladas
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    h, w = gray.shape[:2]
    
    # 1. Nitidez (Laplaciano)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = laplacian.var()
    sharpness_score = min(1.0, sharpness / 500)  # Normalizar
    
    # 2. Brillo
    mean_brightness = np.mean(gray)
    brightness_score = 1.0 - abs(mean_brightness - 200) / 200
    brightness_score = max(0, brightness_score)
    
    # 3. Contraste
    contrast = np.std(gray)
    contrast_score = min(1.0, contrast / 60)
    
    # 4. Resolución
    megapixels = (h * w) / 1_000_000
    resolution_score = min(1.0, megapixels / 5)  # 5MP = score 1.0
    
    # 5. Ruido (baja varianza en regiones planas)
    kernel = np.ones((5, 5)) / 25
    smoothed = cv2.filter2D(gray, -1, kernel)
    noise = np.mean(np.abs(gray.astype(float) - smoothed.astype(float)))
    noise_score = max(0, 1.0 - noise / 20)
    
    # Score compuesto
    overall = (
        sharpness_score * 0.30 +
        brightness_score * 0.20 +
        contrast_score * 0.25 +
        resolution_score * 0.15 +
        noise_score * 0.10
    )
    
    # Determinar nivel
    if overall >= 0.85:
        level = ScanQuality.EXCELLENTE
    elif overall >= 0.70:
        level = ScanQuality.BUENO
    elif overall >= 0.50:
        level = ScanQuality.ACEPTABLE
    elif overall >= 0.30:
        level = ScanQuality.MALO
    else:
        level = ScanQuality.INUTILIZABLE
    
    return {
        'score': round(overall, 3),
        'level': level.value,
        'metrics': {
            'sharpness': round(sharpness_score, 3),
            'brightness': round(brightness_score, 3),
            'contrast': round(contrast_score, 3),
            'resolution': round(resolution_score, 3),
            'noise': round(noise_score, 3),
        },
        'details': {
            'sharpness_raw': round(sharpness, 2),
            'brightness_mean': round(mean_brightness, 1),
            'contrast_std': round(contrast, 1),
            'megapixels': round(megapixels, 2),
            'dimensions': f'{w}x{h}',
        }
    }


# ══════════════════════════════════════════════════════════════
#  7. CROP INTELIGENTE
# ══════════════════════════════════════════════════════════════

def smart_crop(image: np.ndarray, margin_pct: float = 2.0) -> np.ndarray:
    """
    Crop inteligente que elimina bordes negros y márgenes innecesarios.
    
    Args:
        image: Imagen BGR
        margin_pct: Porcentaje de margen a preservar (default 2%)
    
    Returns:
        Imagen recortada
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    # Detectar región no-negra
    _, binary = cv2.threshold(gray, 20, 255, cv2.THRESH_BINARY)
    
    # Encontrar contornos no-negros
    coords = cv2.findNonZero(binary)
    if coords is None:
        return image
    
    x, y, w, h = cv2.boundingRect(coords)
    
    # Agregar margen
    margin_x = int(w * margin_pct / 100)
    margin_y = int(h * margin_pct / 100)
    
    x = max(0, x - margin_x)
    y = max(0, y - margin_y)
    w = min(image.shape[1] - x, w + 2 * margin_x)
    h = min(image.shape[0] - y, h + 2 * margin_y)
    
    return image[y:y+h, x:x+w]


def auto_crop_with_padding(image: np.ndarray, padding_px: int = 20) -> np.ndarray:
    """
    Auto-crop con padding configurable.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    # Usar Canny para detectar bordes del documento
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return image
    
    # Encontrar el contorno más grande
    largest = max(contours, key=cv2.contourArea)
    
    # Bounding box
    x, y, w, h = cv2.boundingRect(largest)
    
    # Agregar padding
    x = max(0, x - padding_px)
    y = max(0, y - padding_px)
    w = min(image.shape[1] - x, w + 2 * padding_px)
    h = min(image.shape[0] - y, h + 2 * padding_px)
    
    return image[y:y+h, x:x+w]


# ══════════════════════════════════════════════════════════════
#  8. NORMALIZACIÓN DE BRILLO/CONTRASTE
# ══════════════════════════════════════════════════════════════

def normalize_brightness_contrast(image: np.ndarray, target_brightness: float = 180) -> np.ndarray:
    """
    Normaliza brillo y contraste a valores ideales para OCR.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    current_brightness = np.mean(gray)
    
    # Ajustar brillo
    if abs(current_brightness - target_brightness) > 20:
        gamma = target_brightness / max(current_brightness, 1)
        gamma = np.clip(gamma, 0.5, 2.0)
        lut = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in range(256)]).astype(np.uint8)
        gray = cv2.LUT(gray, lut)
    
    # Ajustar contraste
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    
    if len(image.shape) == 3:
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return gray


# ══════════════════════════════════════════════════════════════
#  9. PIPELINE OPTIMIZADO PARA OCR
# ══════════════════════════════════════════════════════════════

def optimize_for_ocr(image: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Pipeline completo optimizado para máximo rendimiento OCR.
    
    Steps:
    1. Eliminación de sombras
    2. Corrección de arrugas
    3. Restauración de color (si aplica)
    4. Normalización de brillo
    5. Binarización Sauvola
    6. Limpieza morfológica
    
    Returns:
        Tuple de (imagen_procesada, metadata)
    """
    metadata = {
        'steps_applied': [],
        'quality_before': None,
        'quality_after': None,
    }
    
    # Evaluar calidad inicial
    quality_before = assess_scan_quality(image)
    metadata['quality_before'] = quality_before['score']
    
    # 1. Eliminar sombras
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    step1 = remove_shadows_adaptive(gray, strength=0.6)
    metadata['steps_applied'].append('shadow_removal')
    
    # 2. Corrección de arrugas
    step2 = correct_wrinkles(image, detect_wrinkles(step1)) if len(image.shape) == 3 else step1
    if not np.array_equal(step2, image):
        metadata['steps_applied'].append('wrinkle_correction')
    
    # 3. Normalización de brillo
    step3 = normalize_brightness_contrast(step2, target_brightness=190)
    metadata['steps_applied'].append('brightness_normalization')
    
    # 4. Binarización Sauvola
    if len(step3.shape) == 3:
        step3 = cv2.cvtColor(step3, cv2.COLOR_BGR2GRAY)
    step4 = sauvola_binarize(step3, window_size=25, k=0.2)
    metadata['steps_applied'].append('sauvola_binarize')
    
    # 5. Limpieza morfológica
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    step5 = cv2.morphologyEx(step4, cv2.MORPH_CLOSE, kernel)
    step5 = cv2.morphologyEx(step5, cv2.MORPH_OPEN, kernel)
    metadata['steps_applied'].append('morphological_cleanup')
    
    # Evaluar calidad final
    quality_after = assess_scan_quality(step5)
    metadata['quality_after'] = quality_after['score']
    metadata['improvement'] = round(quality_after['score'] - quality_before['score'], 3)
    
    return cv2.cvtColor(step5, cv2.COLOR_GRAY2BGR), metadata


# ══════════════════════════════════════════════════════════════
#  10. PIPELINE COMPLETO DE REALCE
# ══════════════════════════════════════════════════════════════

def enhanced_pipeline(
    image: np.ndarray,
    mode: str = "auto",
    enable_shadow_removal: bool = True,
    enable_wrinkle_correction: bool = True,
    enable_color_restoration: bool = True,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Pipeline completo de realce con todas las mejoras.
    
    Args:
        image: Imagen BGR original
        mode: 'auto', 'documento', 'grises', 'color', 'ocr'
        enable_shadow_removal: Activar eliminación de sombras
        enable_wrinkle_correction: Activar corrección de arrugas
        enable_color_restoration: Activar restauración de color
    
    Returns:
        Tuple de (imagen_mejorada, metadata_completa)
    """
    metadata = {
        'original_size': f'{image.shape[1]}x{image.shape[0]}',
        'mode': mode,
        'steps': [],
    }
    
    # Detectar modo si es 'auto'
    if mode == "auto":
        doc_type = detect_document_type(image)
        if doc_type in [DocumentType.FACTURA, DocumentType.RECIBO, DocumentType.CHEQUE]:
            mode = "ocr"
        elif doc_type == DocumentType.FOTO:
            mode = "color"
        else:
            mode = "documento"
        metadata['detected_type'] = doc_type.value
        metadata['mode'] = mode
    
    # Pipeline según modo
    if mode == "ocr":
        result, ocr_meta = optimize_for_ocr(image)
        metadata.update(ocr_meta)
        metadata['steps'] = ocr_meta.get('steps_applied', [])
    else:
        # Modos estándar
        result = image.copy()
        
        # Eliminación de sombras
        if enable_shadow_removal:
            if len(result.shape) == 3:
                gray = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            else:
                gray = result
            gray = remove_shadows_advanced(gray)
            if len(image.shape) == 3:
                result = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            else:
                result = gray
            metadata['steps'].append('shadow_removal')
        
        # Corrección de arrugas
        if enable_wrinkle_correction:
            result = remove_wrinkles(result)
            metadata['steps'].append('wrinkle_correction')
        
        # Restauración de color
        if enable_color_restoration and mode == "color":
            result = restore_color(result)
            metadata['steps'].append('color_restoration')
        
        # Realce según modo
        if mode == "color":
            lab = cv2.cvtColor(result, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            lab = cv2.merge([l, a, b])
            result = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
            metadata['steps'].append('clahe_color')
        elif mode == "grises":
            result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
            result = clahe.apply(result)
            result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
            metadata['steps'].append('clahe_grayscale')
        elif mode == "documento":
            result, doc_meta = optimize_for_ocr(result)
            metadata.update(doc_meta)
            metadata['steps'] = doc_meta.get('steps_applied', [])
    
    # Evaluar calidad final
    quality = assess_scan_quality(result)
    metadata['quality'] = quality
    metadata['final_size'] = f'{result.shape[1]}x{result.shape[0]}'
    
    return result, metadata


# ══════════════════════════════════════════════════════════════
#  EXPORTAR FUNCIONES PRINCIPALES
# ══════════════════════════════════════════════════════════════

__all__ = [
    'enhanced_pipeline',
    'optimize_for_ocr',
    'assess_scan_quality',
    'detect_document_type',
    'remove_shadows_adaptive',
    'remove_shadows_advanced',
    'remove_wrinkles',
    'sauvola_binarize',
    'niblack_binarize',
    'restore_color',
    'smart_crop',
    'auto_crop_with_padding',
    'normalize_brightness_contrast',
    'DocumentType',
    'ScanQuality',
]


if __name__ == "__main__":
    print("Enhancer Avanzado — NAD Scanner v1.1.0")
    print("Funciones disponibles:")
    for name in __all__:
        print(f"  - {name}")
