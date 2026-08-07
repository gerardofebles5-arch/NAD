"""
Módulo de Preprocesamiento de Imágenes para OCR
================================================
Mejora la calidad de las imágenes antes del OCR para aumentar
la precisión de reconocimiento de texto.
"""

import cv2
import numpy as np
from typing import Optional, Tuple, List
from enum import Enum


class PreprocessingLevel(Enum):
    """Nivel de preprocesamiento a aplicar."""
    NONE = "none"
    BASIC = "basic"
    MEDIUM = "medium"
    AGGRESSIVE = "aggressive"


class ImagePreprocessor:
    """
    Preprocesador de imágenes para mejorar la calidad del OCR.
    """
    
    def __init__(self, level: PreprocessingLevel = PreprocessingLevel.MEDIUM):
        self.level = level
        self._stats = {}
    
    def process(self, image: np.ndarray) -> np.ndarray:
        """Aplica el pipeline de preprocesamiento completo."""
        if self.level == PreprocessingLevel.NONE:
            return image.copy()
        
        processed = image.copy()
        processed = self._denoise(processed)
        processed = self._enhance_contrast(processed)
        
        if self.level in [PreprocessingLevel.MEDIUM, PreprocessingLevel.AGGRESSIVE]:
            processed = self._sharpen(processed)
        
        if self.level == PreprocessingLevel.AGGRESSIVE:
            processed = self._remove_shadows(processed)
        
        processed = self._normalize(processed)
        return processed
    
    def _denoise(self, image: np.ndarray) -> np.ndarray:
        """Reduce el ruido de la imagen (optimizado para velocidad)."""
        # Reducir resolución para procesamiento más rápido
        h, w = image.shape[:2]
        scale = 0.5 if h > 1000 or w > 1000 else 1.0
        
        if scale < 1.0:
            small = cv2.resize(image, (int(w * scale), int(h * scale)))
        else:
            small = image
        
        # Usar denoising más rápido
        if len(image.shape) == 3:
            denoised = cv2.fastNlMeansDenoisingColored(
                small, None, h=5, hColor=5, templateWindowSize=5, searchWindowSize=11
            )
        else:
            denoised = cv2.fastNlMeansDenoising(
                small, None, h=5, templateWindowSize=5, searchWindowSize=11
            )
        
        # Restaurar resolución original
        if scale < 1.0:
            denoised = cv2.resize(denoised, (w, h))
        
        self._stats['denoise_applied'] = True
        return denoised
    
    def _enhance_contrast(self, image: np.ndarray) -> np.ndarray:
        """Mejora el contraste usando CLAHE (optimizado para velocidad)."""
        # Usar tileGridSize más grande para mejor rendimiento
        if len(image.shape) == 3:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
            l = clahe.apply(l)
            enhanced = cv2.merge([l, a, b])
            enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        else:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
            enhanced = clahe.apply(image)
        self._stats['clahe_applied'] = True
        return enhanced
    
    def _sharpen(self, image: np.ndarray) -> np.ndarray:
        """Enfoca la imagen para mejorar bordes de texto."""
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(image, -1, kernel)
        result = cv2.addWeighted(image, 0.7, sharpened, 0.3, 0)
        self._stats['sharpen_applied'] = True
        return result
    
    def _remove_shadows(self, image: np.ndarray) -> np.ndarray:
        """Elimina sombras usando dilatación morfológica."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        dilated = cv2.dilate(gray, kernel)
        divided = np.float32(gray) / np.float32(dilated)
        divided = np.clip(divided * 255, 0, 255).astype(np.uint8)
        
        if len(image.shape) == 3:
            for i in range(3):
                image[:, :, i] = divided
            result = image
        else:
            result = divided
        
        self._stats['shadow_removal_applied'] = True
        return result
    
    def _normalize(self, image: np.ndarray) -> np.ndarray:
        """Normaliza la imagen (brillo y contraste)."""
        normalized = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX)
        self._stats['normalize_applied'] = True
        return normalized
    
    def deskew(self, image: np.ndarray) -> np.ndarray:
        """
        Corrige la inclinación de la imagen (deskew).
        
        Detecta la orientación del texto y corrige la inclinación.
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Binarizar para detección de bordes
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Encontrar coordenadas de todos los píxeles no negros
        coords = np.column_stack(np.where(binary > 0))
        
        if len(coords) == 0:
            return image  # No se pudo deskew
        
        # Calcular ángulo usando PCA
        angle = cv2.minAreaRect(coords)[-1]
        
        # Ajustar ángulo
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        
        # Rotar la imagen
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        
        self._stats['deskew_angle'] = angle
        self._stats['deskew_applied'] = True
        return rotated
    
    def correct_perspective(self, image: np.ndarray) -> np.ndarray:
        """
        Corrige la perspectiva de la imagen.
        
        Detecta las esquinas del documento y aplica transformación de perspectiva.
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Binarizar
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Encontrar contornos
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return image  # No se encontraron contornos
        
        # Buscar el contorno más grande (asumido como el documento)
        largest_contour = max(contours, key=cv2.contourArea)
        
        # Aproximar el contorno a un polígono
        epsilon = 0.02 * cv2.arcLength(largest_contour, True)
        approx = cv2.approxPolyDP(largest_contour, epsilon, True)
        
        # Si el polígono tiene 4 vértices, asumimos que es el documento
        if len(approx) == 4:
            # Ordenar vértices: top-left, top-right, bottom-right, bottom-left
            pts = approx.reshape(4, 2)
            rect = self._order_points(pts)
            
            # Calcular dimensiones del documento
            width_a = np.sqrt(((rect[2][0] - rect[3][0]) ** 2) + ((rect[2][1] - rect[3][1]) ** 2))
            width_b = np.sqrt(((rect[1][0] - rect[0][0]) ** 2) + ((rect[1][1] - rect[0][1]) ** 2))
            max_width = max(int(width_a), int(width_b))
            
            height_a = np.sqrt(((rect[1][0] - rect[2][0]) ** 2) + ((rect[1][1] - rect[2][1]) ** 2))
            height_b = np.sqrt(((rect[0][0] - rect[3][0]) ** 2) + ((rect[0][1] - rect[3][1]) ** 2))
            max_height = max(int(height_a), int(height_b))
            
            # Puntos de destino (rectángulo)
            dst = np.array([
                [0, 0],
                [max_width - 1, 0],
                [max_width - 1, max_height - 1],
                [0, max_height - 1]
            ], dtype="float32")
            
            # Calcular matriz de transformación de perspectiva
            M = cv2.getPerspectiveTransform(rect, dst)
            
            # Aplicar transformación
            warped = cv2.warpPerspective(image, M, (max_width, max_height))
            
            self._stats['perspective_correction_applied'] = True
            return warped
        
        return image
    
    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """
        Ordena los puntos de las esquinas del documento.
        
        Retorna: top-left, top-right, bottom-right, bottom-left
        """
        rect = np.zeros((4, 2), dtype="float32")
        
        # Sumar coordenadas x e y
        s = pts.sum(axis=1)
        
        # Top-left: menor suma
        rect[0] = pts[np.argmin(s)]
        # Bottom-right: mayor suma
        rect[2] = pts[np.argmax(s)]
        
        # Diferencia entre coordenadas
        diff = np.diff(pts, axis=1)
        
        # Top-right: menor diferencia (x grande, y pequeño)
        rect[1] = pts[np.argmin(diff)]
        # Bottom-left: mayor diferencia (x pequeño, y grande)
        rect[3] = pts[np.argmax(diff)]
        
        return rect
    
    def get_stats(self) -> dict:
        """Retorna estadísticas del procesamiento aplicado."""
        return self._stats.copy()


class InvoiceImageEnhancer:
    """Mejorador especializado para imágenes de facturas."""
    
    def __init__(self):
        self.preprocessor = ImagePreprocessor(level=PreprocessingLevel.MEDIUM)
    
    def enhance_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """Mejora la imagen específicamente para OCR de facturas."""
        enhanced = self.preprocessor.process(image)
        enhanced = self.preprocessor.deskew(enhanced)
        enhanced = self._enhance_small_text(enhanced)
        return enhanced
    
    def _enhance_small_text(self, image: np.ndarray) -> np.ndarray:
        """Mejora específicamente el texto pequeño."""
        h, w = image.shape[:2]
        if h < 1000 or w < 1000:
            scale = min(1.5, 1000 / min(h, w))
            enhanced = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        else:
            enhanced = image.copy()
        
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)
        result = cv2.addWeighted(enhanced, 0.8, sharpened, 0.2, 0)
        return result


def preprocess_invoice_image(image: np.ndarray, level: str = "medium") -> np.ndarray:
    """Función de conveniencia para preprocesar una imagen de factura."""
    level_map = {
        'none': PreprocessingLevel.NONE,
        'basic': PreprocessingLevel.BASIC,
        'medium': PreprocessingLevel.MEDIUM,
        'aggressive': PreprocessingLevel.AGGRESSIVE
    }
    preprocessor = ImagePreprocessor(level=level_map.get(level, PreprocessingLevel.MEDIUM))
    return preprocessor.process(image)


def enhance_invoice_for_ocr(image: np.ndarray) -> np.ndarray:
    """Función de conveniencia para mejorar una factura específicamente para OCR."""
    enhancer = InvoiceImageEnhancer()
    return enhancer.enhance_for_ocr(image)
