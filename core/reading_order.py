"""
Fase 3: Reading Order — Orden de lectura humano.
================================================================================
Determina el orden correcto en que deben leerse las regiones del documento.

Algoritmos:
  1. XY-Cut: Recursivo, divide por gaps grandes
  2. Column clustering: Agrupa por columnas verticales
  3. Fallback: Y-then-X simple
"""

import numpy as np
from typing import List, Optional, Tuple
from dataclasses import dataclass

from core.layout_detector import LayoutRegion, DocumentLayout


@dataclass
class ReadingOrderConfig:
    """Configuración del orden de lectura."""
    column_gap_threshold: float = 0.15  # % del ancho para detectar columnas
    row_gap_threshold: float = 0.02     # % del alto para detectar saltos
    use_xy_cut: bool = True
    use_column_clustering: bool = True


class ReadingOrderEngine:
    """
    Determina el orden de lectura correcto de las regiones.

    Soporta:
    - Documentos de una columna
    - Documentos de dos columnas
    - Layouts complejos con headers/footers

    Uso:
        engine = ReadingOrderEngine()
        ordered = engine.sort_regions(layout.regions, page_width, page_height)
    """

    def __init__(self, config: Optional[ReadingOrderConfig] = None):
        self.config = config or ReadingOrderConfig()

    def sort_regions(
        self,
        regions: List[LayoutRegion],
        page_width: int,
        page_height: int,
    ) -> List[LayoutRegion]:
        """
        Ordena regiones siguiendo el orden de lectura humano.

        Args:
            regions: Lista de regiones detectadas
            page_width: Ancho de la página
            page_height: Alto de la página

        Returns:
            Lista ordenada de regiones con reading_order actualizado
        """
        if not regions:
            return regions

        # Separar headers y footers
        headers = [r for r in regions if r.region_type == "header"]
        footers = [r for r in regions if r.region_type == "footer"]
        body = [r for r in regions if r.region_type not in ("header", "footer")]

        # Ordenar headers por Y
        headers.sort(key=lambda r: (r.bbox[1], r.bbox[0]))

        # Ordenar footers por Y
        footers.sort(key=lambda r: (r.bbox[1], r.bbox[0]))

        # Ordenar body
        if body:
            if self.config.use_column_clustering and self._has_multiple_columns(body, page_width):
                body = self._column_aware_sort(body, page_width, page_height)
            elif self.config.use_xy_cut:
                body = self._xy_cut_sort(body, page_width, page_height)
            else:
                body = self._simple_yx_sort(body)

        # Asignar orden
        ordered = []
        order = 0

        for r in headers + body + footers:
            r.reading_order = order
            ordered.append(r)
            order += 1

        return ordered

    def _has_multiple_columns(
        self,
        regions: List[LayoutRegion],
        page_width: int,
    ) -> bool:
        """Detecta si hay múltiples columnas."""
        if len(regions) < 3:
            return False

        # Agrupar por centro X
        centers_x = [(r.bbox[0] + r.bbox[2]) / 2 for r in regions]
        centers_x.sort()

        # Buscar gaps grandes
        max_gap = 0
        for i in range(len(centers_x) - 1):
            gap = centers_x[i + 1] - centers_x[i]
            max_gap = max(max_gap, gap)

        # Si el gap máximo es mayor al umbral, hay columnas
        return max_gap > page_width * self.config.column_gap_threshold

    def _column_aware_sort(
        self,
        regions: List[LayoutRegion],
        page_width: int,
        page_height: int,
    ) -> List[LayoutRegion]:
        """Orden respetando columnas."""
        # Detectar columnas por clustering de centros X
        centers_x = [(r.bbox[0] + r.bbox[2]) / 2 for r in regions]
        columns = self._cluster_columns(centers_x, page_width)

        # Agrupar regiones por columna
        col_groups = {i: [] for i in range(len(columns))}
        for i, r in enumerate(regions):
            center_x = centers_x[i]
            for col_idx, (col_start, col_end) in enumerate(columns):
                if col_start <= center_x <= col_end:
                    col_groups[col_idx].append(r)
                    break

        # Ordenar dentro de cada columna por Y
        ordered = []
        for col_idx in sorted(col_groups.keys()):
            col_regions = col_groups[col_idx]
            col_regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
            ordered.extend(col_regions)

        return ordered

    def _cluster_columns(
        self,
        centers_x: List[float],
        page_width: int,
    ) -> List[Tuple[float, float]]:
        """Agrupa centros X en columnas."""
        if not centers_x:
            return []

        sorted_x = sorted(centers_x)
        columns = []
        current_col = [sorted_x[0]]

        for i in range(1, len(sorted_x)):
            gap = sorted_x[i] - sorted_x[i - 1]
            if gap > page_width * self.config.column_gap_threshold:
                # Nuevo grupo de columna
                columns.append((
                    min(current_col) - 20,
                    max(current_col) + 20,
                ))
                current_col = [sorted_x[i]]
            else:
                current_col.append(sorted_x[i])

        # Última columna
        columns.append((
            min(current_col) - 20,
            max(current_col) + 20,
        ))

        return columns

    def _xy_cut_sort(
        self,
        regions: List[LayoutRegion],
        page_width: int,
        page_height: int,
    ) -> List[LayoutRegion]:
        """Orden using XY-Cut algorithm (recursivo)."""
        if len(regions) <= 1:
            return regions

        # Encontrar el gap más grande
        best_gap = 0
        best_axis = 'y'
        best_split = len(regions) // 2

        # Probar corte horizontal (Y)
        regions_y = sorted(regions, key=lambda r: r.bbox[1])
        for i in range(1, len(regions_y)):
            gap = regions_y[i].bbox[1] - regions_y[i - 1].bbox[3]
            if gap > best_gap:
                best_gap = gap
                best_axis = 'y'
                best_split = i

        # Probar corte vertical (X)
        regions_x = sorted(regions, key=lambda r: r.bbox[0])
        for i in range(1, len(regions_x)):
            gap = regions_x[i].bbox[0] - regions_x[i - 1].bbox[2]
            if gap > best_gap:
                best_gap = gap
                best_axis = 'x'
                best_split = i

        # Si el gap es muy pequeño, usar Y-then-X simple
        if best_gap < page_width * self.config.row_gap_threshold:
            return self._simple_yx_sort(regions)

        # Dividir y ordenar recursivamente
        if best_axis == 'y':
            regions_sorted = regions_y
        else:
            regions_sorted = regions_x

        left = self._xy_cut_sort(regions_sorted[:best_split], page_width, page_height)
        right = self._xy_cut_sort(regions_sorted[best_split:], page_width, page_height)

        return left + right

    def _simple_yx_sort(self, regions: List[LayoutRegion]) -> List[LayoutRegion]:
        """Orden simple: Y primero, luego X."""
        return sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0]))


# ═══════════════════════════════════════════════════════════════
#  Función de conveniencia
# ═══════════════════════════════════════════════════════════════

def sort_reading_order(
    layout: DocumentLayout,
    config: Optional[ReadingOrderConfig] = None,
) -> DocumentLayout:
    """
    Reordena las regiones del layout según el orden de lectura.

    Args:
        layout: DocumentLayout con regiones
        config: Configuración opcional

    Returns:
        DocumentLayout con reading_order actualizado
    """
    engine = ReadingOrderEngine(config)
    layout.regions = engine.sort_regions(
        layout.regions,
        layout.page_width,
        layout.page_height,
    )
    return layout
