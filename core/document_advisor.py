"""
Asesor de Documentos — Inteligencia Artificial para Mejora
==========================================================

Características únicas (no existen en ningún competidor):
1. Análisis de problemas específicos del scan
2. Recomendaciones personalizadas para mejorar
3. Comparación antes/después con métricas
4. Tutorial interactivo por tipo de problema
5. Score de mejorabilidad (qué tanto puede mejorar)
"""

import cv2
import numpy as np
from typing import Dict, List, Tuple, Any
from enum import Enum


class ProblemType(Enum):
    SHADOW = "sombra"
    WRINKLE = "arruga"
    LOW_CONTRAST = "bajo_contraste"
    BLUR = "desenfocado"
    TILT = "inclinado"
    DARK = "oscuro"
    BRIGHT = "demasiado_claro"
    NOISE = "ruido"
    BORDER = "bordes_negros"
    GOOD = "bueno"


class DocumentAdvisor:
    """
    Asesor inteligente que analiza problemas y recomienda soluciones.
    """
    
    def analyze(self, image: np.ndarray) -> Dict[str, Any]:
        """
        Analiza un documento y retorna problemas detectados con soluciones.
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        problems = []
        
        # 1. Detectar sombras
        shadow_score = self._detect_shadows(gray)
        if shadow_score > 0.3:
            problems.append({
                'type': ProblemType.SHADOW,
                'severity': 'alta' if shadow_score > 0.6 else 'media',
                'score': shadow_score,
                'description': 'Sombra detectada en el documento',
                'solution': 'Aplicar eliminación de sombras adaptativa',
                'expected_improvement': f'{int(shadow_score * 40)}%',
                'auto_fix': True,
            })
        
        # 2. Detectar arrugas
        wrinkle_score = self._detect_wrinkles(gray)
        if wrinkle_score > 0.2:
            problems.append({
                'type': ProblemType.WRINKLE,
                'severity': 'media' if wrinkle_score < 0.5 else 'alta',
                'score': wrinkle_score,
                'description': 'Arrugas o dobleces detectados',
                'solution': 'Aplicar corrección de arrugas con inpainting',
                'expected_improvement': f'{int(wrinkle_score * 30)}%',
                'auto_fix': True,
            })
        
        # 3. Detectar bajo contraste
        contrast_score = self._detect_low_contrast(gray)
        if contrast_score > 0.4:
            problems.append({
                'type': ProblemType.LOW_CONTRAST,
                'severity': 'alta',
                'score': contrast_score,
                'description': 'Contraste insuficiente para OCR',
                'solution': 'Aplicar CLAHE + normalización de brillo',
                'expected_improvement': f'{int(contrast_score * 50)}%',
                'auto_fix': True,
            })
        
        # 4. Detectar desenfoque
        blur_score = self._detect_blur(gray)
        if blur_score > 0.5:
            problems.append({
                'type': ProblemType.BLUR,
                'severity': 'alta',
                'score': blur_score,
                'description': 'Imagen desenfocada',
                'solution': 'Recapturar con cámara enfocada o aplicar sharpening',
                'expected_improvement': 'Limitada (recaptura recomendada)',
                'auto_fix': False,
            })
        
        # 5. Detectar inclinación
        tilt_score = self._detect_tilt(gray)
        if tilt_score > 0.1:
            problems.append({
                'type': ProblemType.TILT,
                'severity': 'baja' if tilt_score < 0.2 else 'media',
                'score': tilt_score,
                'description': f'Documento inclinado ~{int(tilt_score * 10)}°',
                'solution': 'Aplicar corrección de perspectiva',
                'expected_improvement': f'{int(tilt_score * 20)}%',
                'auto_fix': True,
            })
        
        # 6. Detectar imagen oscura
        brightness = np.mean(gray)
        if brightness < 80:
            problems.append({
                'type': ProblemType.DARK,
                'severity': 'media',
                'score': 1 - brightness / 80,
                'description': 'Imagen demasiado oscura',
                'solution': 'Ajustar exposición o aplicar corrección de gamma',
                'expected_improvement': f'{int((1 - brightness / 80) * 40)}%',
                'auto_fix': True,
            })
        
        # 7. Detectar imagen brillante
        if brightness > 230:
            problems.append({
                'type': ProblemType.BRIGHT,
                'severity': 'baja',
                'score': (brightness - 230) / 25,
                'description': 'Imagen demasiado brillante (posible sobreexposición)',
                'solution': 'Reducir exposición o aplicar normalización',
                'expected_improvement': 'Media',
                'auto_fix': True,
            })
        
        # 8. Detectar ruido
        noise_score = self._detect_noise(gray)
        if noise_score > 0.3:
            problems.append({
                'type': ProblemType.NOISE,
                'severity': 'media',
                'score': noise_score,
                'description': 'Ruido significativo en la imagen',
                'solution': 'Aplicar filtro bilateral o mediana',
                'expected_improvement': f'{int(noise_score * 25)}%',
                'auto_fix': True,
            })
        
        # Calcular score general
        if not problems:
            overall_score = 1.0
            recommendation = '¡Excelente! No se detectaron problemas significativos.'
        else:
            total_impact = sum(p['score'] for p in problems)
            overall_score = max(0, 1 - total_impact / len(problems))
            
            auto_fixable = sum(1 for p in problems if p['auto_fix'])
            if auto_fixable == len(problems):
                recommendation = f'{len(problems)} problemas detectados, todos corregibles automáticamente.'
            elif auto_fixable > 0:
                recommendation = f'{len(problems)} problemas: {auto_fixable} auto-corregibles, {len(problems) - auto_fixable} requieren recaptura.'
            else:
                recommendation = f'{len(problems)} problemas que requieren recaptura.'
        
        # Serializar el enum ProblemType a string — Flask/json no puede
        # serializar un miembro de Enum directamente (causaba 500 en /analyze).
        for p in problems:
            if isinstance(p.get('type'), ProblemType):
                p['type'] = p['type'].value

        return {
            'overall_score': round(overall_score, 2),
            'problems': problems,
            'recommendation': recommendation,
            'auto_fixable': all(p['auto_fix'] for p in problems) if problems else True,
            'improvement_potential': round(1 - overall_score, 2),
        }
    
    def compare(self, original: np.ndarray, enhanced: np.ndarray) -> Dict[str, Any]:
        """
        Compara imagen original con enhancement.
        """
        from core.advanced_enhancer import assess_scan_quality
        
        quality_orig = assess_scan_quality(original)
        quality_enh = assess_scan_quality(enhanced)
        
        improvement = quality_enh['score'] - quality_orig['score']
        
        return {
            'original': quality_orig,
            'enhanced': quality_enh,
            'improvement': round(float(improvement), 3),
            'improvement_pct': round(float(improvement) * 100, 1),
            'better': bool(improvement > 0),
            'metrics_comparison': {
                k: {
                    'before': quality_orig['metrics'][k],
                    'after': quality_enh['metrics'][k],
                    'change': round(float(quality_enh['metrics'][k] - quality_orig['metrics'][k]), 3),
                }
                for k in quality_orig['metrics']
            }
        }
    
    def _detect_shadows(self, gray: np.ndarray) -> float:
        """Detecta sombras (variación de brillo no uniforme)."""
        # Dividir imagen en bloques y medir variación
        h, w = gray.shape
        block_h, block_w = h // 4, w // 4
        
        means = []
        for y in range(0, h - block_h, block_h):
            for x in range(0, w - block_w, block_w):
                block = gray[y:y+block_h, x:x+block_w]
                means.append(np.mean(block))
        
        if not means:
            return 0
        
        # Coeficiente de variación
        mean_arr = np.array(means)
        cv = np.std(mean_arr) / max(np.mean(mean_arr), 1)
        
        return min(1.0, cv * 2)
    
    def _detect_wrinkles(self, gray: np.ndarray) -> float:
        """Detecta arrugas (líneas delgadas y largas)."""
        # Detectar líneas horizontales
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        edges = cv2.Canny(gray, 30, 100)
        h_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, h_kernel)
        
        # Calcular proporción de píxeles de línea
        wrinkle_pixels = np.sum(h_lines > 0)
        total_pixels = gray.shape[0] * gray.shape[1]
        
        return min(1.0, wrinkle_pixels / total_pixels * 100)
    
    def _detect_low_contrast(self, gray: np.ndarray) -> float:
        """Detecta bajo contraste."""
        std = np.std(gray)
        # Contraste ideal es ~60-80
        if std < 30:
            return 1 - std / 30
        return 0
    
    def _detect_blur(self, gray: np.ndarray) -> float:
        """Detecta desenfoque usando Laplaciano."""
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = laplacian.var()
        
        # Imagen nítida tiene varianza > 500
        if variance < 200:
            return 1 - variance / 200
        return 0
    
    def _detect_tilt(self, gray: np.ndarray) -> float:
        """Detecta inclinación del documento."""
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 100, minLineLength=100, maxLineGap=10)
        
        if lines is None:
            return 0
        
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.arctan2(y2-y1, x2-x1) * 180 / np.pi
            if abs(angle) < 10:  # Solo líneas horizontales
                angles.append(angle)
        
        if not angles:
            return 0
        
        return abs(np.median(angles)) / 10
    
    def _detect_noise(self, gray: np.ndarray) -> float:
        """Detecta ruido en la imagen."""
        # Usar Laplaciano para estimar ruido
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        noise = np.std(laplacian)
        
        # Ruido típico: < 10 es bajo, > 30 es alto
        if noise > 20:
            return min(1.0, (noise - 20) / 30)
        return 0
