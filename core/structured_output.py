"""
Fase 6: Structured Output — Generación de Markdown + JSON.
================================================================================
Convierte el layout detectado en salida estructurada:
  - Markdown (estilo MinerU)
  - JSON con bloques ordenados
  - Campos de factura VE (compatibilidad)
"""

import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from core.layout_detector import DocumentLayout, LayoutRegion
from core.reading_order import ReadingOrderEngine


@dataclass
class StructuredBlock:
    """Bloque estructurado del documento."""
    block_type: str      # 'heading', 'paragraph', 'table', 'equation', 'list', 'image'
    content: str         # Texto, HTML, o LaTeX
    level: int = 1       # Para headings (1-6)
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class StructuredOutputGenerator:
    """
    Genera output estructurado desde un DocumentLayout.

    Uso:
        generator = StructuredOutputGenerator()
        markdown = generator.to_markdown(layout)
        json_data = generator.to_json(layout)
    """

    def __init__(self):
        self.reading_order_engine = ReadingOrderEngine()

    def to_markdown(self, layout: DocumentLayout) -> str:
        """
        Genera Markdown con headers, tablas, listas, fórmulas.

        Args:
            layout: DocumentLayout con regiones detectadas

        Returns:
            String con Markdown formateado
        """
        # Asegurar orden de lectura
        sorted_regions = self.reading_order_engine.sort_regions(
            list(layout.regions), layout.page_width, layout.page_height
        )

        lines = []

        for region in sorted_regions:
            md = self._region_to_markdown(region)
            if md:
                lines.append(md)

        return "\n\n".join(lines)

    def _region_to_markdown(self, region: LayoutRegion) -> str:
        """Convierte una región a Markdown."""
        rtype = region.region_type

        if rtype == "title":
            # Detectar nivel por tamaño del bbox
            height = region.bbox[3] - region.bbox[1]
            if height > 40:
                return f"# {region.text}" if region.text else ""
            elif height > 25:
                return f"## {region.text}" if region.text else ""
            else:
                return f"### {region.text}" if region.text else ""

        elif rtype == "text":
            return region.text if region.text else ""

        elif rtype == "table":
            if region.html:
                return region.html
            return "[Tabla detectada]"

        elif rtype == "equation":
            if region.latex:
                return f"$$\n{region.latex}\n$$"
            return "[Fórmula detectada]"

        elif rtype == "list":
            # Convertir texto a lista
            if region.text:
                items = region.text.split('\n')
                return "\n".join(f"- {item.strip()}" for item in items if item.strip())
            return ""

        elif rtype == "figure":
            return "[Imagen detectada]"

        elif rtype == "header":
            return f"---\n*{region.text}*\n---" if region.text else ""

        elif rtype == "footer":
            return f"*{region.text}*" if region.text else ""

        return region.text if region.text else ""

    def to_json(self, layout: DocumentLayout) -> Dict[str, Any]:
        """
        Genera JSON con bloques ordenados por reading order.

        Args:
            layout: DocumentLayout con regiones detectadas

        Returns:
            Diccionario JSON estructurado
        """
        # Asegurar orden de lectura
        sorted_regions = self.reading_order_engine.sort_regions(
            list(layout.regions), layout.page_width, layout.page_height
        )

        blocks = []
        for region in sorted_regions:
            block = {
                "type": region.region_type,
                "bbox": region.bbox,
                "confidence": round(region.confidence, 4),
                "reading_order": region.reading_order,
            }

            # Agregar contenido según tipo
            if region.text:
                block["text"] = region.text
            if region.html:
                block["html"] = region.html
            if region.latex:
                block["latex"] = region.latex

            blocks.append(block)

        return {
            "document": {
                "num_pages": layout.num_pages,
                "page_size": [layout.page_width, layout.page_height],
            },
            "blocks": blocks,
            "summary": {
                "total_blocks": len(blocks),
                "block_types": self._count_types(blocks),
            },
        }

    def _count_types(self, blocks: List[Dict]) -> Dict[str, int]:
        """Cuenta bloques por tipo."""
        counts = {}
        for block in blocks:
            btype = block.get("type", "unknown")
            counts[btype] = counts.get(btype, 0) + 1
        return counts

    def to_blocks(self, layout: DocumentLayout) -> List[StructuredBlock]:
        """
        Convierte layout a lista de bloques estructurados.

        Args:
            layout: DocumentLayout

        Returns:
            Lista de StructuredBlock
        """
        sorted_regions = self.reading_order_engine.sort_regions(
            list(layout.regions), layout.page_width, layout.page_height
        )

        blocks = []
        for region in sorted_regions:
            # Determinar tipo de bloque
            if region.region_type == "title":
                block_type = "heading"
                level = 1 if (region.bbox[3] - region.bbox[1]) > 40 else 2
            elif region.region_type == "table":
                block_type = "table"
                level = 0
            elif region.region_type == "equation":
                block_type = "equation"
                level = 0
            elif region.region_type == "list":
                block_type = "list"
                level = 0
            elif region.region_type == "figure":
                block_type = "image"
                level = 0
            else:
                block_type = "paragraph"
                level = 0

            # Contenido
            content = region.text or region.html or region.latex or ""

            blocks.append(StructuredBlock(
                block_type=block_type,
                content=content,
                level=level,
                metadata={
                    "bbox": region.bbox,
                    "confidence": region.confidence,
                    "reading_order": region.reading_order,
                },
            ))

        return blocks

    def to_invoice_data(self, layout: DocumentLayout) -> Dict[str, Any]:
        """
        Genera datos de factura VE desde el layout.
        Compatibilidad con el sistema actual de NAD Scanner.

        Args:
            layout: DocumentLayout

        Returns:
            Diccionario con campos de factura
        """
        # Extraer todo el texto
        all_text = []
        for region in layout.regions:
            if region.text:
                all_text.append(region.text)

        full_text = "\n".join(all_text)

        # Buscar campos comunes de factura
        import re

        data = {
            "numero_factura": self._extract_field(full_text, r'(?:factura|nro?\.?\s*(?:factura)?)\s*[:#]?\s*(\S+)'),
            "numero_control": self._extract_field(full_text, r'(?:control|nro?\.?\s*(?:control)?)\s*[:#]?\s*(\S+)'),
            "fecha": self._extract_field(full_text, r'fecha\s*[:#]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})'),
            "rif_emisor": self._extract_field(full_text, r'(?:RIF|rif)\s*[:#]?\s*([VJEGP]-\d{8}-\d)'),
            "razon_social": self._extract_field(full_text, r'(?:razón\s*social|razon\s*social|R\.S\.)\s*[:#]?\s*(.+)'),
            "base_imponible": self._extract_field(full_text, r'(?:base\s*imponible|base)\s*[:#]?\s*([\d\.,]+)'),
            "iva": self._extract_field(full_text, r'(?:IVA|iva)\s*[:#]?\s*([\d\.,]+)'),
            "total": self._extract_field(full_text, r'(?:total|TOTAL)\s*[:#]?\s*([\d\.,]+)'),
            "raw_text": full_text[:2000],
        }

        return data

    def _extract_field(self, text: str, pattern: str) -> str:
        """Extrae un campo usando regex."""
        import re
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else ""


# ═══════════════════════════════════════════════════════════════
#  Funciones de conveniencia
# ═══════════════════════════════════════════════════════════════

def layout_to_markdown(layout: DocumentLayout) -> str:
    """Convierte layout a Markdown."""
    generator = StructuredOutputGenerator()
    return generator.to_markdown(layout)


def layout_to_json(layout: DocumentLayout) -> Dict[str, Any]:
    """Convierte layout a JSON."""
    generator = StructuredOutputGenerator()
    return generator.to_json(layout)
