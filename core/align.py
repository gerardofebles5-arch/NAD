"""
Bloque 2 — Alineación tipo PhotoScan
======================================
Detecta puntos clave en cada toma, los empareja con la imagen central de referencia,
calcula la homografía y remapa cada imagen al espacio de la referencia.

Resultado: 5 imágenes del mismo tamaño, superpuestas píxel a píxel.
"""

import cv2
import numpy as np
from typing import List, Optional, Tuple

from utils.config import CONFIG


def detect_and_match(
    reference: np.ndarray,
    target: np.ndarray,
    max_features: int = 5000,
    lowe_ratio: float = 0.75,
) -> Tuple[Optional[np.ndarray], List[cv2.KeyPoint], List[cv2.KeyPoint], int]:
    """
    Detecta puntos clave con ORB, los empareja con BFMatcher,
    filtra con Lowe's ratio test y calcula la homografía.

    Args:
        reference: Imagen de referencia (central).
        target: Imagen a alinear.
        max_features: Número máximo de puntos clave.
        lowe_ratio: Umbral del ratio test de Lowe.

    Returns:
        (homography_matrix, keypoints_ref, keypoints_target, num_good_matches)
        Si no se puede calcular la homografía, homography_matrix es None.
    """
    # Convertir a grises
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    tgt_gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)

    # Detector ORB
    orb = cv2.ORB_create(nfeatures=max_features)

    # Detectar y computar descriptores
    kp_ref, des_ref = orb.detectAndCompute(ref_gray, None)
    kp_tgt, des_tgt = orb.detectAndCompute(tgt_gray, None)

    if des_ref is None or des_tgt is None:
        return None, [], [], 0

    # Emparejar con BFMatcher (norma Hamming para ORB)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des_ref, des_tgt, k=2)

    # Lowe's ratio test
    good_matches = []
    for m, n in matches:
        if m.distance < lowe_ratio * n.distance:
            good_matches.append(m)

    if len(good_matches) < CONFIG.align.min_matches:
        return None, kp_ref, kp_tgt, len(good_matches)

    # Extraer puntos de los matches
    src_pts = np.float32([kp_ref[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_tgt[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    # Calcular homografía con RANSAC
    H, mask = cv2.findHomography(
        dst_pts, src_pts,
        cv2.RANSAC,
        ransacReprojThreshold=CONFIG.align.ransac_reproj_threshold,
    )

    if H is None:
        return None, kp_ref, kp_tgt, len(good_matches)

    return H, kp_ref, kp_tgt, len(good_matches)


def warp_to_reference(
    target: np.ndarray,
    H: np.ndarray,
    ref_shape: Tuple[int, int],
) -> np.ndarray:
    """
    Aplica warpPerspective para remapear la imagen objetivo al espacio de la referencia.

    Args:
        target: Imagen a transformar.
        H: Matriz de homografía 3×3.
        ref_shape: (alto, ancho) de la imagen de referencia.

    Returns:
        Imagen transformada del mismo tamaño que la referencia.
    """
    h, w = ref_shape[:2]
    warped = cv2.warpPerspective(target, H, (w, h))
    return warped


def align_shots(
    shots: List[np.ndarray],
) -> List[np.ndarray]:
    """
    Alinea todas las tomas a la imagen central (referencia).

    Toma la primera imagen de la lista como referencia (toma central).
    Para cada toma secundaria, calcula la homografía y la remapa.

    Args:
        shots: Lista de 5 imágenes BGR.

    Returns:
        Lista de 5 imágenes alineadas del mismo tamaño.
        Si alguna toma no pudo alinearse, se incluye None en su lugar.

    Raises:
        ValueError: Si hay menos de 2 imágenes.
    """
    if len(shots) < 2:
        raise ValueError("Se necesitan al menos 2 imágenes para alinear.")

    cfg = CONFIG.align
    reference = shots[0]
    ref_shape = reference.shape[:2]  # (alto, ancho)

    aligned = [reference]  # La referencia no necesita transformación

    for i, shot in enumerate(shots[1:], start=1):
        print(f"  ⚙ Alineando toma {i+1}/5...", end=" ")

        H, kp_ref, kp_tgt, num_matches = detect_and_match(
            reference, shot,
            max_features=cfg.max_features,
            lowe_ratio=cfg.lowe_ratio,
        )

        if H is None or num_matches < cfg.min_matches:
            print(f"✗ Falló ({num_matches} matches, mínimo {cfg.min_matches})")
            aligned.append(None)
            continue

        warped = warp_to_reference(shot, H, ref_shape)

        # Validar que la imagen warp no esté en blanco
        if np.mean(warped) < 1.0:
            print(f"✗ Warp resultó en imagen vacía")
            aligned.append(None)
            continue

        aligned.append(warped)
        print(f"✓ ({num_matches} matches)")

    return aligned


def render_matches(
    reference: np.ndarray,
    target: np.ndarray,
    max_features: int = 1000,
) -> np.ndarray:
    """
    Genera una imagen con las correspondencias visualizadas entre dos tomas.
    Útil para depuración y diagnóstico.
    """
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    tgt_gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=max_features)
    kp_ref, des_ref = orb.detectAndCompute(ref_gray, None)
    kp_tgt, des_tgt = orb.detectAndCompute(tgt_gray, None)

    if des_ref is None or des_tgt is None:
        # Fallback: concatenar imágenes
        return np.hstack([reference, target])

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des_ref, des_tgt)
    matches = sorted(matches, key=lambda x: x.distance)[:50]

    result = cv2.drawMatches(
        reference, kp_ref, target, kp_tgt, matches, None,
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )
    return result


if __name__ == "__main__":
    import sys
    print("Módulo de alineación NAD Scanner.")
    print("Este módulo se ejecuta como parte del flujo principal (main.py).")
