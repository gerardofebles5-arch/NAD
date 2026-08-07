"""
Bloque 3 — Fusión anti-glare tipo PhotoScan
============================================
Apila las 5 tomas alineadas y fusiona usando mediana por píxel.
El reflejo especular solo aparece en 1 o 2 tomas, la mediana lo descarta.
Alternativa: mínimo por píxel para glare muy agresivo.
Post-procesamiento: CLAHE si el histograma queda subexpuesto.
"""

import cv2
import numpy as np
from typing import List, Optional

from utils.config import CONFIG


def fuse_shots(
    aligned_shots: List[Optional[np.ndarray]],
    method: Optional[str] = None,
) -> Optional[np.ndarray]:
    """
    Fusiona las tomas alineadas en una sola imagen libre de reflejos.

    1. Filtra las tomas None (fallos de alineación).
    2. Apila en un array (N, H, W, 3).
    3. Calcula mediana (o mínimo) por píxel.
    4. Valida histograma y aplica CLAHE si es necesario.

    Args:
        aligned_shots: Lista de 5 imágenes BGR (puede contener Nones).
        method: 'median' (por defecto) o 'min'.

    Returns:
        Imagen RGB fusionada, o None si no hay suficientes tomas válidas.
    """
    cfg = CONFIG.fusion
    method = method or cfg.method

    # Filtrar tomas válidas
    valid = [s for s in aligned_shots if s is not None]
    if len(valid) < 2:
        print(f"  ⚠ Fusion: solo {len(valid)} tomas válidas (mínimo 2).")
        return None

    print(f"  ⚙ Fusionando {len(valid)} tomas (método: {method})...")

    # Apilar tomas
    stack = np.stack(valid, axis=0).astype(np.float32)

    # Aplicar método de fusión
    if method == "min":
        fused = np.min(stack, axis=0)
        print("  → Usando mínimo por píxel (anti-glare agresivo)")
    else:
        fused = np.median(stack, axis=0)
        print("  → Usando mediana por píxel (anti-glare estándar)")

    fused = np.clip(fused, 0, 255).astype(np.uint8)

    # Validar histograma
    gray = cv2.cvtColor(fused, cv2.COLOR_BGR2GRAY)
    mean_brightness = np.mean(gray)
    std_brightness = np.std(gray)

    print(f"  → Brillo medio: {mean_brightness:.1f} / Desviación: {std_brightness:.1f}")

    # Aplicar CLAHE si la imagen está subexpuesta o tiene bajo contraste
    if mean_brightness < 80 or std_brightness < 40:
        print("  → Aplicando CLAHE correctivo...")
        lab = cv2.cvtColor(fused, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(
            clipLimit=cfg.clahe_clip_limit,
            tileGridSize=cfg.clahe_grid_size,
        )
        l = clahe.apply(l)
        lab = cv2.merge([l, a, b])
        fused = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        gray_post = cv2.cvtColor(fused, cv2.COLOR_BGR2GRAY)
        print(f"  → Post-CLAHE: brillo {np.mean(gray_post):.1f} / contraste {np.std(gray_post):.1f}")

    return fused


def fuse_with_depth_weights(
    aligned_shots: List[Optional[np.ndarray]],
    reference_sharpness: Optional[float] = None,
) -> Optional[np.ndarray]:
    """
    Variante: fusión ponderada por nitidez local.
    Útil cuando algunas tomas están más desenfocadas que otras.

    Args:
        aligned_shots: Lista de imágenes alineadas.
        reference_sharpness: Nitidez de referencia (opcional).

    Returns:
        Imagen fusionada.
    """
    valid = [s for s in aligned_shots if s is not None]
    if len(valid) < 2:
        return None

    # Calcular mapa de nitidez (varianza del Laplaciano) para cada toma
    sharpness_maps = []
    for img in valid:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = cv2.GaussianBlur(lap ** 2, (15, 15), 0)
        sharpness_maps.append(sharpness)

    # Normalizar pesos
    weight_stack = np.stack(sharpness_maps, axis=0)
    weight_stack = np.maximum(weight_stack, 1e-6)
    weights = weight_stack / np.sum(weight_stack, axis=0, keepdims=True)

    # Fusión ponderada
    img_stack = np.stack(valid, axis=0).astype(np.float32)
    weights_3c = np.stack([weights] * 3, axis=-1)
    fused = np.sum(img_stack * weights_3c, axis=0)
    fused = np.clip(fused, 0, 255).astype(np.uint8)

    return fused


if __name__ == "__main__":
    print("Módulo de fusión NAD Scanner — ejecutar desde main.py")
