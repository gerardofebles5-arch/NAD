"""
Fase 4: Formula Recognition — Detección y reconocimiento de fórmulas.
================================================================================
Detecta regiones con fórmulas matemáticas y las convierte a LaTeX.

Estrategia:
  1. PaddleOCR FormulaRecognition (si disponible)
  2. Regex-based fallback para fórmulas simples
  3. Detección de patrones matemáticos comunes
"""

import re
import numpy as np
from dataclasses import dataclass
from typing import List, Optional

import cv2


@dataclass
class FormulaResult:
    """Resultado de reconocimiento de fórmula."""
    latex: str
    confidence: float
    bbox: List[int]
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "latex": self.latex,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox,
        }


class FormulaRecognizer:
    """
    Detecta y reconoce fórmulas matemáticas.

    Uso:
        recognizer = FormulaRecognizer()
        formulas = recognizer.detect_formulas(image)
        for f in formulas:
            print(f.latex)
    """

    # Patrones de fórmulas matemáticas comunes
    FORMULA_PATTERNS = [
        # Fórmulas con símbolos matemáticos
        (r'[∑∏∫∂√∞≈≠≤≥±×÷]', 0.7),
        (r'[αβγδεζηθικλμνξπρστυφχψω]', 0.8),
        (r'[ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΠΡΣΤΥΦΧΨΩ]', 0.8),
        # Fórmulas con superíndices/subíndices
        (r'\d+[²³⁴⁵⁶⁷⁸⁹⁰¹]', 0.6),
        (r'[a-zA-Z]\d', 0.4),
        # Operadores matemáticos
        (r'[=+\-*/^_]{2,}', 0.5),
        # Fórmulas con paréntesis
        (r'\([^)]*[=<>≤≥][^)]*\)', 0.6),
        (r'\[[^]]*[=<>≤≥][^]]*\]', 0.6),
        # Expresiones con variables
        (r'[a-zA-Z]\s*[=<>≤≥]\s*\d+', 0.5),
        (r'\d+\s*[=<>≤≥]\s*[a-zA-Z]', 0.5),
    ]

    # Mapeo de símbolos a LaTeX
    SYMBOL_TO_LATEX = {
        '∑': r'\sum',
        '∏': r'\prod',
        '∫': r'\int',
        '∂': r'\partial',
        '√': r'\sqrt',
        '∞': r'\infty',
        '≈': r'\approx',
        '≠': r'\neq',
        '≤': r'\leq',
        '≥': r'\geq',
        '±': r'\pm',
        '×': r'\times',
        '÷': r'\div',
        'α': r'\alpha',
        'β': r'\beta',
        'γ': r'\gamma',
        'δ': r'\delta',
        'ε': r'\epsilon',
        'θ': r'\theta',
        'λ': r'\lambda',
        'μ': r'\mu',
        'π': r'\pi',
        'σ': r'\sigma',
        'φ': r'\phi',
        'ω': r'\omega',
        '²': r'^2',
        '³': r'^3',
        '⁴': r'^4',
    }

    def __init__(self):
        pass

    def detect_formulas(
        self,
        image: np.ndarray,
        bbox: Optional[List[int]] = None,
    ) -> List[FormulaResult]:
        """
        Detecta fórmulas en una imagen.

        Args:
            image: Imagen BGR
            bbox: Región específica (None = imagen completa)

        Returns:
            Lista de fórmulas detectadas
        """
        # Intentar con PaddleOCR
        results = self._try_paddle_formula(image, bbox)
        if results:
            return results

        # Fallback: detección por patrones
        return self._detect_by_patterns(image, bbox)

    def _try_paddle_formula(
        self,
        image: np.ndarray,
        bbox: Optional[List[int]],
    ) -> List[FormulaResult]:
        """Intenta usar PaddleOCR FormulaRecognition."""
        try:
            from paddleocr import FormulaRecognition

            recognizer = FormulaRecognition()

            if bbox:
                x1, y1, x2, y2 = bbox
                crop = image[max(0, y1):min(image.shape[0], y2),
                            max(0, x1):min(image.shape[1], x2)]
            else:
                crop = image

            result = recognizer.predict(input=crop)

            if result:
                formulas = []
                for item in result:
                    if isinstance(item, dict):
                        latex = item.get("latex", item.get("text", ""))
                        score = float(item.get("score", 0.8))
                        box = item.get("bbox", [0, 0, 0, 0])

                        if latex:
                            formulas.append(FormulaResult(
                                latex=latex,
                                confidence=score,
                                bbox=[int(b) for b in box[:4]],
                            ))

                if formulas:
                    return formulas

        except Exception as e:
            pass

        return []

    def _detect_by_patterns(
        self,
        image: np.ndarray,
        bbox: Optional[List[int]],
    ) -> List[FormulaResult]:
        """Detecta fórmulas por patrones visuales."""
        if bbox:
            x1, y1, x2, y2 = bbox
            crop = image[max(0, y1):min(image.shape[0], y2),
                        max(0, x1):min(image.shape[1], x2)]
        else:
            crop = image
            x1, y1 = 0, 0

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Buscar regiones con alta densidad de píxeles oscuros
        # (típico de fórmulas matemáticas)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Dividir en bloques y analizar densidad
        block_h = max(20, h // 10)
        block_w = max(30, w // 5)

        formulas = []

        for y in range(0, h - block_h, block_h // 2):
            for x in range(0, w - block_w, block_w // 2):
                block = binary[y:y+block_h, x:x+block_w]
                density = cv2.countNonZero(block) / (block_h * block_w)

                # Fórmulas suelen tener densidad media (0.1-0.4)
                if 0.08 < density < 0.35:
                    # Verificar si tiene patrones de fórmula
                    # (líneas diagonales, curvas, etc.)
                    edges = cv2.Canny(block, 50, 150)
                    edge_density = cv2.countNonZero(edges) / (block_h * block_w)

                    if 0.05 < edge_density < 0.2:
                        # Probable fórmula
                        formulas.append(FormulaResult(
                            latex=f"[formula en ({x + x1}, {y + y1})]",
                            confidence=0.5,
                            bbox=[x + x1, y + y1, x + x1 + block_w, y + y1 + block_h],
                        ))

        # Fusionar fórmulas cercanas
        formulas = self._merge_close_formulas(formulas)

        return formulas

    def _merge_close_formulas(
        self,
        formulas: List[FormulaResult],
        max_gap: int = 30,
    ) -> List[FormulaResult]:
        """Fusiona fórmulas que están muy cerca."""
        if len(formulas) <= 1:
            return formulas

        # Ordenar por posición
        formulas.sort(key=lambda f: (f.bbox[1], f.bbox[0]))

        merged = [formulas[0]]

        for f in formulas[1:]:
            prev = merged[-1]
            y_gap = f.bbox[1] - prev.bbox[3]
            x_overlap = max(0, min(prev.bbox[2], f.bbox[2]) - max(prev.bbox[0], f.bbox[0]))

            if 0 <= y_gap <= max_gap and x_overlap > 0:
                # Fusionar
                merged[-1] = FormulaResult(
                    latex=prev.latex + " " + f.latex,
                    confidence=min(prev.confidence, f.confidence),
                    bbox=[
                        min(prev.bbox[0], f.bbox[0]),
                        min(prev.bbox[1], f.bbox[1]),
                        max(prev.bbox[2], f.bbox[2]),
                        max(prev.bbox[3], f.bbox[3]),
                    ],
                )
            else:
                merged.append(f)

        return merged

    def text_to_latex(self, text: str) -> str:
        """Convierte texto con símbolos matemáticos a LaTeX."""
        result = text
        for symbol, latex in self.SYMBOL_TO_LATEX.items():
            result = result.replace(symbol, f" {latex} ")
        return result.strip()


# ═══════════════════════════════════════════════════════════════
#  Función de conveniencia
# ═══════════════════════════════════════════════════════════════

def detect_formulas(
    image: np.ndarray,
    bbox: Optional[List[int]] = None,
) -> List[FormulaResult]:
    """Función de conveniencia para detectar fórmulas."""
    recognizer = FormulaRecognizer()
    return recognizer.detect_formulas(image, bbox)
