"""
Bloque 7 — Stitching secuencial pairwise para documentos largos (Modo Z)
========================================================================
Toma N imágenes solapadas verticalmente (~30% de overlap) y las cose en
una sola imagen continua de alta resolución.

Usa ORB pairwise entre cada par de tomas consecutivas para calcular la
homografía que alinea la imagen inferior con la superior. En la zona de
overlap, aplica feathering lineal o graph-cut (seam óptimo) para una
transición suave sin artefactos.

Esto permite escanear facturas Z/recibos térmicos de 30cm+ que una sola
foto no puede capturar con calidad suficiente para OCR.

Arquitectura:
  shots[0] (top) ──► canvas base
  shots[1] ──ORB──► homografía ──► warp ──► blend ──► canvas
  shots[2] ──ORB──► homografía ──► warp ──► blend ──► canvas
  ...
  shots[N-1] (bottom) ──► canvas final ──► recorte ──► OCR pipeline
"""

import cv2
import numpy as np
from typing import List, Optional, Tuple, Literal


class StitchingEngine:
    """Motor de stitching secuencial para documentos largos.

    Toma N imágenes con overlap vertical y las cose pairwise
    usando ORB + homografía + feathering/graph-cut.

    Attributes:
        min_match_count: Mínimo de matches ORB para considerar válida una homografía.
        lowe_ratio: Ratio de Lowe para filtrado de matches.
        seam_method: 'feather' (decaimiento lineal) o 'graphcut' (seam óptimo DP).
        show_debug: Si True, imprime información de cada paso.
    """

    def __init__(
        self,
        min_match_count: int = 10,
        lowe_ratio: float = 0.72,
        seam_method: Literal["feather", "graphcut"] = "feather",
        show_debug: bool = True,
    ):
        self.min_match_count = min_match_count
        self.lowe_ratio = lowe_ratio
        self.seam_method = seam_method
        self.show_debug = show_debug

        # ORB detector (compartido entre pares para consistencia)
        self._orb = cv2.ORB_create(nfeatures=3000, scaleFactor=1.2, nlevels=8)

    def _log(self, msg: str):
        if self.show_debug:
            print(f"  [Stitch] {msg}")

    # ────────────────────────────────────────────────────────────
    #  ORB pairwise matching (FIX: guard <2 descriptors)
    # ────────────────────────────────────────────────────────────

    def _match_pair(
        self, img_top: np.ndarray, img_bot: np.ndarray,
        initial_h: Optional[np.ndarray] = None,
    ) -> Tuple[Optional[np.ndarray], int, List[cv2.KeyPoint], List[cv2.KeyPoint]]:
        """Detecta ORB en un par de imágenes y calcula la homografía H
        que mapea img_bot → img_top.

        Si se proporciona initial_h (p.ej. una translación estimada desde
        el ghost_offset_y del usuario), se usa para limitar la búsqueda
        de matches ORB a una región de interés (ROI) alrededor de la
        posición esperada, mejorando precisión y velocidad.

        Args:
            img_top: Imagen superior (referencia).
            img_bot: Imagen inferior (a warpear).
            initial_h: Homografía inicial estimada (3×3) para acotar ROI.

        Returns:
            (H, num_inliers, kp_top, kp_bot) — H=None si falla.
        """
        gray_top = cv2.cvtColor(img_top, cv2.COLOR_BGR2GRAY)
        gray_bot = cv2.cvtColor(img_bot, cv2.COLOR_BGR2GRAY)

        kp_top, des_top = self._orb.detectAndCompute(gray_top, None)
        kp_bot, des_bot = self._orb.detectAndCompute(gray_bot, None)

        if des_top is None or des_bot is None or len(kp_top) < 5 or len(kp_bot) < 5:
            self._log(f"  ⚠ Pocos features: top={len(kp_top) if kp_top else 0}, bot={len(kp_bot) if kp_bot else 0}")
            return None, 0, kp_top or [], kp_bot or []

        # BFMatcher con NORM_HAMMING (para ORB)
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        try:
            matches = bf.knnMatch(des_top, des_bot, k=2)
        except cv2.error:
            # Ocurre si algún descriptor tiene < 2 features
            self._log("  ⚠ knnMatch(k=2) falló — muy pocos descriptores")
            return None, 0, kp_top, kp_bot

        # Lowe's ratio test
        good = []
        for m_pair in matches:
            if len(m_pair) < 2:
                continue
            m, n = m_pair[0], m_pair[1]
            if m.distance < self.lowe_ratio * n.distance:
                good.append(m)

        if len(good) < self.min_match_count:
            self._log(f"  ⚠ Pocos good matches: {len(good)} (mín {self.min_match_count})")
            return None, len(good), kp_top, kp_bot

        # Extraer puntos
        src_pts = np.float32([kp_bot[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp_top[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)

        # ── RANSAC homography, con initial_h opcional ──
        # Si el usuario ajustó el ghost (offsetY/scale), usamos eso como
        # estimación inicial para limitar la búsqueda de RANSAC a una
        # vecindad alrededor de la posición esperada. Esto mejora la
        # precisión cuando el documento tiene pocos features (texto
        # uniforme, fondos blancos) y reduce falsos positivos.
        if initial_h is not None:
            # Aplicar initial_h a los src_pts para obtener dst_estimados
            # y filtrar outliers antes de RANSAC: solo puntos cuya
            # distancia a la estimación sea razonable
            try:
                src_h = cv2.perspectiveTransform(src_pts, initial_h)
                errors = np.sqrt(((dst_pts - src_h) ** 2).sum(axis=2)).flatten()
                # Umbral: 10% del alto de la imagen
                max_err = img_top.shape[0] * 0.10
                inlier_mask = errors < max_err
                if inlier_mask.sum() >= self.min_match_count:
                    src_filtered = src_pts[inlier_mask]
                    dst_filtered = dst_pts[inlier_mask]
                    self._log(f"  initial_h filtró {inlier_mask.sum()}/{len(inlier_mask)} puntos")
                    H, mask = cv2.findHomography(
                        src_filtered, dst_filtered,
                        cv2.RANSAC, ransacReprojThreshold=5.0,
                    )
                    inliers = int(mask.sum()) if mask is not None else 0
                    if H is not None and inliers >= self.min_match_count:
                        self._log(f"  ✓ {len(good)} matches, {inliers} inliers (con initial_h)")
                        return H, inliers, kp_top, kp_bot
            except Exception as e:
                self._log(f"  ⚠ initial_h falló, usando RANSAC normal: {e}")

        # RANSAC normal (sin initial_h o si falló el filtrado)
        H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, ransacReprojThreshold=5.0)
        inliers = int(mask.sum()) if mask is not None else 0

        if H is None or inliers < self.min_match_count:
            self._log(f"  ⚠ Homografía falló ({inliers} inliers)")
            return None, inliers, kp_top, kp_bot

        self._log(f"  ✓ {len(good)} matches, {inliers} inliers")
        return H, inliers, kp_top, kp_bot

    # ────────────────────────────────────────────────────────────
    #  Feathering blend vectorizado (FIX: reemplaza loop de píxeles)
    # ────────────────────────────────────────────────────────────

    def _feather_blend(
        self,
        canvas: np.ndarray,
        new_warped: np.ndarray,
        overlap_y: int,
        canvas_h: int,
    ) -> np.ndarray:
        """Fusiona new_warped en canvas con feathering lineal vectorizado.

        Usa cv2.addWeighted con máscara alfa en la zona de overlap,
        en lugar del loop de píxeles anterior (que era ~100x más lento).
        """
        h_canvas, w_canvas = canvas.shape[:2]
        h_new, w_new = new_warped.shape[:2]
        max_w = max(w_canvas, w_new)

        # Crear canvas de salida
        result = np.zeros((canvas_h, max_w, 3), dtype=np.uint8)
        result[:h_canvas, :w_canvas] = canvas

        # Determinar zona de overlap
        if overlap_y >= h_canvas:
            # Sin overlap: pegar debajo
            y_start = overlap_y
            h_avail = min(h_new, canvas_h - y_start)
            if h_avail > 0:
                result[y_start:y_start + h_avail, :w_new] = new_warped[:h_avail, :w_new]
            return result

        y_end = min(h_canvas, overlap_y + h_new)
        overlap_h = y_end - overlap_y

        if overlap_h <= 0:
            # Gap entre imágenes — pegar directamente
            y_start = max(overlap_y, h_canvas)
            h_avail = min(h_new, canvas_h - y_start)
            if h_avail > 0:
                new_y_offset = y_start - overlap_y
                result[y_start:y_start + h_avail, :w_new] = (
                    new_warped[new_y_offset:new_y_offset + h_avail, :w_new]
                )
            return result

        # ── Zona de overlap: feathering vectorizado ──
        # Extraer regiones de overlap
        canvas_overlap = canvas[overlap_y:y_end, :max_w].astype(np.float32)
        new_overlap = new_warped[:overlap_h, :max_w].astype(np.float32)

        # Máscara alfa lineal: 0 en el borde superior, 1 en el inferior
        alpha = np.linspace(0, 1, overlap_h, dtype=np.float32).reshape(-1, 1, 1)

        # Detectar píxeles negros (sin información) en cada capa
        c_lum = canvas_overlap.sum(axis=2)  # H_overlap x W
        n_lum = new_overlap.sum(axis=2)

        # Blend: donde ambos tienen datos, usar alpha; donde solo uno, usar ese
        mask_c_has = c_lum > 5
        mask_n_has = n_lum > 5
        mask_both = mask_c_has & mask_n_has
        mask_only_c = mask_c_has & ~mask_n_has
        mask_only_n = ~mask_c_has & mask_n_has

        blended = np.zeros_like(canvas_overlap)
        # Ambos tienen datos → feathering lineal
        alpha_3d = np.repeat(alpha, max_w, axis=1)
        blended[mask_both] = (
            canvas_overlap[mask_both] * (1 - alpha_3d[mask_both]) +
            new_overlap[mask_both] * alpha_3d[mask_both]
        )
        # Solo canvas
        blended[mask_only_c] = canvas_overlap[mask_only_c]
        # Solo new_warped
        blended[mask_only_n] = new_overlap[mask_only_n]

        result[overlap_y:y_end, :max_w] = np.clip(blended, 0, 255).astype(np.uint8)

        # ── Zona inferior (solo new_warped) ──
        new_remaining = h_new - overlap_h
        if new_remaining > 0:
            new_start = overlap_y + overlap_h
            copy_end = min(new_start + new_remaining, canvas_h)
            copy_h = copy_end - new_start
            if copy_h > 0:
                result[new_start:new_start + copy_h, :max_w] = (
                    new_warped[overlap_h:overlap_h + copy_h, :max_w]
                )

        return result

    # ────────────────────────────────────────────────────────────
    #  Graph-cut seam via Dynamic Programming (NUEVO)
    # ────────────────────────────────────────────────────────────

    def _graphcut_blend(
        self,
        canvas: np.ndarray,
        new_warped: np.ndarray,
        overlap_y: int,
        canvas_h: int,
    ) -> np.ndarray:
        """Fusiona con seam óptimo encontrado por programación dinámica.

        En lugar de un blend lineal (feathering), encuentra el camino
        vertical de mínimo costo a través de la zona de overlap, donde
        el costo es la diferencia de color entre las dos imágenes.
        Esto evita el ghosting cuando las imágenes tienen diferencias
        de brillo o alineación imperfecta.

        Algoritmo: DP estándar de seam carving adaptado a stitching.
        """
        h_canvas, w_canvas = canvas.shape[:2]
        h_new, w_new = new_warped.shape[:2]
        max_w = max(w_canvas, w_new)

        # Crear canvas de salida
        result = np.zeros((canvas_h, max_w, 3), dtype=np.uint8)
        result[:h_canvas, :w_canvas] = canvas

        if overlap_y >= h_canvas:
            y_start = overlap_y
            h_avail = min(h_new, canvas_h - y_start)
            if h_avail > 0:
                result[y_start:y_start + h_avail, :w_new] = new_warped[:h_avail, :w_new]
            return result

        y_end = min(h_canvas, overlap_y + h_new)
        overlap_h = y_end - overlap_y

        if overlap_h <= 0:
            y_start = max(overlap_y, h_canvas)
            h_avail = min(h_new, canvas_h - y_start)
            if h_avail > 0:
                new_y_offset = y_start - overlap_y
                result[y_start:y_start + h_avail, :w_new] = (
                    new_warped[new_y_offset:new_y_offset + h_avail, :w_new]
                )
            return result

        w_eff = min(w_canvas, w_new, max_w)

        # Matriz de costo: diferencia absoluta de color en el overlap
        c_overlap = canvas[overlap_y:y_end, :w_eff].astype(np.float32)
        n_overlap = new_warped[:overlap_h, :w_eff].astype(np.float32)
        cost = np.abs(c_overlap - n_overlap).sum(axis=2)  # (overlap_h, w_eff)

        # DP: encontrar seam vertical de mínimo costo
        # M[i][j] = costo mínimo para llegar a (i, j)
        M = cost.copy()
        backtrack = np.zeros_like(M, dtype=np.int32)

        for i in range(1, overlap_h):
            for j in range(w_eff):
                # Revisar 3 vecinos arriba: (i-1, j-1), (i-1, j), (i-1, j+1)
                left = M[i-1, j-1] if j > 0 else np.inf
                up = M[i-1, j]
                right = M[i-1, j+1] if j < w_eff - 1 else np.inf

                min_val = min(left, up, right)
                M[i, j] += min_val

                if min_val == left:
                    backtrack[i, j] = -1
                elif min_val == right:
                    backtrack[i, j] = 1
                else:
                    backtrack[i, j] = 0

        # Encontrar el punto de inicio del seam en la última fila
        j = np.argmin(M[overlap_h - 1, :])

        # Construir el seam de abajo hacia arriba
        seam = np.zeros(overlap_h, dtype=np.int32)
        seam[overlap_h - 1] = j
        for i in range(overlap_h - 2, -1, -1):
            j = j + backtrack[i + 1, j]
            j = max(0, min(w_eff - 1, j))
            seam[i] = j

        # Aplicar el seam: izquierda del seam → canvas, derecha → new_warped
        # Con una pequeña zona de feathering (±3 píxeles) en el seam
        feather_r = 3
        for i in range(overlap_h):
            y_canvas = overlap_y + i
            sj = seam[i]
            left_bound = max(0, sj - feather_r)
            right_bound = min(w_eff, sj + feather_r + 1)

            # Copiar canvas a la izquierda del seam
            if left_bound > 0:
                result[y_canvas, :left_bound] = canvas[y_canvas, :left_bound]

            # Feathering suave alrededor del seam
            for x in range(left_bound, right_bound):
                dist = x - sj
                if dist < -feather_r:
                    result[y_canvas, x] = canvas[y_canvas, x]
                elif dist > feather_r:
                    result[y_canvas, x] = new_warped[i, x]
                else:
                    alpha = (dist + feather_r) / (2 * feather_r)
                    c_pix = canvas[y_canvas, x].astype(np.float32)
                    n_pix = new_warped[i, x].astype(np.float32)
                    blended = c_pix * (1 - alpha) + n_pix * alpha
                    result[y_canvas, x] = np.clip(blended, 0, 255).astype(np.uint8)

            # Copiar new_warped a la derecha
            if right_bound < w_eff:
                result[y_canvas, right_bound:w_eff] = new_warped[i, right_bound:w_eff]

        # ── Zona inferior (solo new_warped) ──
        new_remaining = h_new - overlap_h
        if new_remaining > 0:
            new_start = overlap_y + overlap_h
            copy_end = min(new_start + new_remaining, canvas_h)
            copy_h = copy_end - new_start
            if copy_h > 0:
                result[new_start:new_start + copy_h, :max_w] = (
                    new_warped[overlap_h:overlap_h + copy_h, :max_w]
                )

        return result

    # ────────────────────────────────────────────────────────────
    #  Stitching secuencial principal (FIX: canvas width fijo)
    # ────────────────────────────────────────────────────────────

    def stitch_sequential(
        self,
        shots: List[np.ndarray],
        overlap_pct: float = 0.30,
    ) -> Optional[np.ndarray]:
        """Cose N imágenes con overlap vertical en una sola imagen continua.

        Las imágenes deben estar ordenadas de SUPERIOR a INFERIOR
        (shots[0] = parte más alta del documento).

        Args:
            shots: Lista de N imágenes BGR, ordenadas top→bottom.
            overlap_pct: Fracción de overlap esperada entre tomas
                         (0.30 = 30%).

        Returns:
            Imagen BGR cosida, o None si el stitching falla.
        """
        if len(shots) < 2:
            self._log("Se necesitan al menos 2 imágenes")
            return None

        self._log(f"Iniciando stitching de {len(shots)} imágenes ({overlap_pct*100:.0f}% overlap esperado)")
        self._log(f"Método de seam: {self.seam_method}")

        # FIX 1: Ancho fijo = máximo ancho de todas las imágenes
        # Antes: w_new_est = max(ref_w, bot_w) * 2  → crecía exponencialmente
        # Ahora: todas las imágenes comparten el mismo ancho máximo
        max_width = max(img.shape[1] for img in shots)
        self._log(f"  Ancho máximo fijo: {max_width}px")

        # Normalizar todas las imágenes al mismo ancho (evita problemas de warpeo)
        normalized = []
        for i, img in enumerate(shots):
            h, w = img.shape[:2]
            if w != max_width:
                scale = max_width / w
                new_h = int(h * scale)
                resized = cv2.resize(img, (max_width, new_h), interpolation=cv2.INTER_LINEAR)
                normalized.append(resized)
                self._log(f"  Normalizada imagen {i}: {w}x{h} → {max_width}x{new_h}")
            else:
                normalized.append(img.copy())
        shots = normalized

        # ── Inicializar canvas con la primera imagen ──
        canvas = shots[0].copy()
        h_ref, w_ref = canvas.shape[:2]

        # ── Procesar cada par ──
        cumulative_offset_y = h_ref

        for i in range(len(shots) - 1):
            ref_h, ref_w = canvas.shape[:2]
            bot_h, bot_w = shots[i + 1].shape[:2]

            # La región de referencia es la parte INFERIOR del canvas actual
            ref_region_h = min(ref_h, int(bot_h * 1.5))
            ref_region = canvas[ref_h - ref_region_h:, :min(ref_w, bot_w)]

            self._log(f"\n  Par {i+1}/{len(shots)-1}: superior ({ref_region.shape[1]}x{ref_region.shape[0]}) "
                      f"↔ inferior ({bot_w}x{bot_h})")

            # ORB matching
            H, inliers, kp_top, kp_bot = self._match_pair(ref_region, shots[i + 1])

            if H is not None:
                # Homografía: warpear la imagen inferior
                self._log(f"  Usando homografía ({inliers} inliers)")

                center_pt = np.float32([[[bot_w / 2, 0]]])
                mapped = cv2.perspectiveTransform(center_pt, H)
                y_offset_in_ref = float(mapped[0, 0, 1])
                abs_y = (ref_h - ref_region_h) + y_offset_in_ref

                # FIX 1: Canvas width = max_width (constante), no crece
                h_new_est = int(bot_h * 1.3)
                w_new_est = max_width  # Fijo desde el inicio

                canvas_expanded = np.zeros((ref_h + h_new_est, w_new_est, 3), dtype=np.uint8)
                canvas_expanded[:ref_h, :ref_w] = canvas

                warped = cv2.warpPerspective(
                    shots[i + 1],
                    H,
                    (w_new_est, h_new_est),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )

                # Recortar región no-negra del warpeo
                gray_w = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
                _, mask = cv2.threshold(gray_w, 5, 255, cv2.THRESH_BINARY)
                coords = cv2.findNonZero(mask)
                if coords is not None:
                    x, y, w_bb, h_bb = cv2.boundingRect(coords)
                    warped_trimmed = warped[y:y + h_bb, x:x + w_bb]
                else:
                    warped_trimmed = warped
                    h_bb, w_bb = warped.shape[:2]

                insert_y = max(0, int(abs_y))
                canvas_h_final = max(ref_h, insert_y + warped_trimmed.shape[0])
                canvas_new = np.zeros((canvas_h_final + int(bot_h * 0.2), w_new_est, 3), dtype=np.uint8)
                canvas_new[:ref_h, :ref_w] = canvas

                self._log(f"  Insertando en Y={insert_y}, warped_bb={w_bb}x{h_bb}")

                if insert_y < ref_h:
                    if self.seam_method == "graphcut":
                        canvas_new = self._graphcut_blend(
                            canvas_new[:ref_h, :w_new_est],
                            warped_trimmed,
                            insert_y,
                            canvas_h_final + int(bot_h * 0.2),
                        )
                    else:
                        canvas_new = self._feather_blend(
                            canvas_new[:ref_h, :w_new_est],
                            warped_trimmed,
                            insert_y,
                            canvas_h_final + int(bot_h * 0.2),
                        )
                else:
                    y_end = min(insert_y + warped_trimmed.shape[0], canvas_new.shape[0])
                    h_avail = y_end - insert_y
                    if h_avail > 0:
                        canvas_new[insert_y:insert_y + h_avail, :warped_trimmed.shape[1]] = (
                            warped_trimmed[:h_avail, :warped_trimmed.shape[1]]
                        )

                canvas = canvas_new
                cumulative_offset_y = insert_y + h_bb // 2

            else:
                # Homografía falló: template matching
                self._log("  Homografía falló. Usando correlación de plantilla (translación)...")

                template_h = int(min(ref_h, bot_h) * overlap_pct)
                template = canvas[ref_h - template_h:, :min(ref_w, bot_w)]
                if template.shape[0] > 0 and template.shape[1] > 0:
                    try:
                        gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                        gray_bot = cv2.cvtColor(shots[i + 1], cv2.COLOR_BGR2GRAY)

                        tm_result = cv2.matchTemplate(gray_bot, gray_template, cv2.TM_CCOEFF_NORMED)
                        _, _, _, max_loc = cv2.minMaxLoc(tm_result)
                        best_y = max_loc[1]
                        overlap_actual = template_h - best_y

                        self._log(f"  Template match: overlap_actual={overlap_actual}px "
                                  f"({overlap_actual/bot_h*100:.1f}%)")

                        insert_y = ref_h - overlap_actual
                        extra_h = max(0, insert_y + bot_h - ref_h) + int(bot_h * 0.1)
                        canvas_new = np.zeros((ref_h + extra_h, max_width, 3), dtype=np.uint8) if extra_h > 0 else canvas.copy()
                        if extra_h > 0:
                            canvas_new[:ref_h, :ref_w] = canvas

                        if insert_y < ref_h:
                            if self.seam_method == "graphcut":
                                canvas_new = self._graphcut_blend(
                                    canvas_new[:ref_h, :max_width],
                                    shots[i + 1][:, :max_width],
                                    insert_y,
                                    canvas_new.shape[0],
                                )
                            else:
                                canvas_new = self._feather_blend(
                                    canvas_new[:ref_h, :max_width],
                                    shots[i + 1][:, :max_width],
                                    insert_y,
                                    canvas_new.shape[0],
                                )
                        else:
                            y_end = min(insert_y + bot_h, canvas_new.shape[0])
                            h_avail = y_end - insert_y
                            if h_avail > 0:
                                canvas_new[insert_y:insert_y + h_avail, :min(ref_w, bot_w)] = (
                                    shots[i + 1][:h_avail, :min(ref_w, bot_w)]
                                )

                        canvas = canvas_new
                        cumulative_offset_y = insert_y + bot_h // 2

                    except Exception as e:
                        self._log(f"  ⚠ Template matching falló: {e}. Pegado simple.")
                        canvas_new = np.zeros((ref_h + bot_h, max_width, 3), dtype=np.uint8)
                        canvas_new[:ref_h, :ref_w] = canvas
                        canvas_new[ref_h:ref_h + bot_h, :bot_w] = shots[i + 1][:, :bot_w]
                        canvas = canvas_new
                        cumulative_offset_y = ref_h + bot_h // 2
                else:
                    self._log("  ⚠ Template demasiado pequeño. Pegado simple.")
                    canvas_new = np.zeros((ref_h + bot_h, max_width, 3), dtype=np.uint8)
                    canvas_new[:ref_h, :ref_w] = canvas
                    canvas_new[ref_h:ref_h + bot_h, :bot_w] = shots[i + 1][:, :bot_w]
                    canvas = canvas_new
                    cumulative_offset_y = ref_h + bot_h // 2

            self._log(f"  Canvas ahora: {canvas.shape[1]}x{canvas.shape[0]}")

        # ── Recortar bordes negros ──
        self._log("Recortando bordes negros...")
        canvas = self._crop_black_borders(canvas)

        self._log(f"✅ Stitching completado: {canvas.shape[1]}x{canvas.shape[0]}")
        return canvas

    # ────────────────────────────────────────────────────────────
    #  Utilidades
    # ────────────────────────────────────────────────────────────

    def _crop_black_borders(self, img: np.ndarray, threshold: int = 10) -> np.ndarray:
        """Recorta píxeles negros (o casi negros) de los bordes."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mask = gray > threshold
        coords = cv2.findNonZero(mask.astype(np.uint8))
        if coords is None:
            return img
        x, y, w, h = cv2.boundingRect(coords)
        margin = 5
        x = max(0, x - margin)
        y = max(0, y - margin)
        w = min(img.shape[1] - x, w + 2 * margin)
        h = min(img.shape[0] - y, h + 2 * margin)
        return img[y:y + h, x:x + w]

    def validate_overlap(self, shots: List[np.ndarray], overlap_pct: float = 0.30) -> Tuple[bool, str]:
        """Valida que las imágenes tengan suficiente overlap para stitching."""
        if len(shots) < 2:
            return False, "Se necesitan al menos 2 imágenes"
        min_h = min(img.shape[0] for img in shots)
        expected_overlap = int(min_h * overlap_pct)
        if expected_overlap < 30:
            return False, f"Imágenes muy pequeñas ({min_h}px) — overlap estimado de {expected_overlap}px insuficiente"
        return True, f"{len(shots)} imágenes, ~{expected_overlap}px de overlap esperado"


# ────────────────────────────────────────────────────────────
#  Función de alto nivel
# ────────────────────────────────────────────────────────────

def stitch_sequential(
    shots: List[np.ndarray],
    overlap_pct: float = 0.30,
    seam_method: Literal["feather", "graphcut"] = "feather",
    show_debug: bool = True,
) -> Optional[np.ndarray]:
    """Cose N imágenes con overlap en una sola imagen continua.

    Args:
        shots: Lista de imágenes BGR ordenadas top→bottom.
        overlap_pct: Fracción de overlap esperada (0.30 = 30%).
        seam_method: 'feather' (decaimiento lineal) o 'graphcut' (seam DP óptimo).
        show_debug: Imprimir progreso.

    Returns:
        Imagen cosida, o None si falla.
    """
    engine = StitchingEngine(seam_method=seam_method, show_debug=show_debug)
    return engine.stitch_sequential(shots, overlap_pct)


# ────────────────────────────────────────────────────────────
#  Tests
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os

    print("=" * 60)
    print("  StitchingEngine — Test sintético v2.0")
    print("  Canvas width fijo + Feathering vectorizado + GraphCut")
    print("=" * 60)

    W, H = 400, 600
    OVERLAP_PX = 180  # 30% de 600
    N_SHOTS = 4

    print(f"\nGenerando {N_SHOTS} imágenes sintéticas de {W}x{H} con {OVERLAP_PX}px de overlap...")

    shots = []
    for i in range(N_SHOTS):
        img = np.ones((H, W, 3), dtype=np.uint8) * 240

        y_line = H // 3
        cv2.line(img, (0, y_line), (W, y_line), (180, 180, 180), 2)

        label = f"SEGMENTO {i+1}"
        cv2.putText(img, label, (W // 2 - 80, H // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2, (50, 50, 50), 2)

        for j, y_pos in enumerate(range(50, H, 60)):
            cv2.putText(img, f"L{i}_{j}", (20, y_pos), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (100, 100, 100), 1)

        cv2.rectangle(img, (2, 2), (W - 2, H - 2), (0, 0, 0), 1)
        shots.append(img)

    # Test feathering
    print("\n── Test 1: Feathering ──")
    result_f = stitch_sequential(shots, overlap_pct=OVERLAP_PX / H, seam_method="feather")

    # Test graphcut
    print("\n── Test 2: GraphCut ──")
    result_g = stitch_sequential(shots, overlap_pct=OVERLAP_PX / H, seam_method="graphcut")

    os.makedirs("output", exist_ok=True)

    if result_f is not None:
        print(f"\n✅ Feathering: {result_f.shape[1]}x{result_f.shape[0]}")
        cv2.imwrite("output/test_stitch_feather.png", result_f)

    if result_g is not None:
        print(f"✅ GraphCut:   {result_g.shape[1]}x{result_g.shape[0]}")
        cv2.imwrite("output/test_stitch_graphcut.png", result_g)

    if result_f is None and result_g is None:
        print("\n❌ Ambos métodos fallaron")
        sys.exit(1)

    print("\n✅ Tests completados")
