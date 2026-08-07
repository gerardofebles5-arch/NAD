"""
πNAD - PDF Report Generator
===========================
Generación de reportes PDF usando ReportLab.
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image,
)
from reportlab.lib.utils import ImageReader
import io


class PDFReportGenerator:
    """Generador de reportes PDF."""
    
    def __init__(self, output_path: str):
        """
        Inicializa el generador de PDF.
        
        Args:
            output_path: Ruta donde se guardará el PDF
        """
        self.output_path = output_path
        self.doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        self.story = []
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Configura estilos personalizados."""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=30,
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomHeading',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#34495e'),
            spaceAfter=12
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomBody',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=6
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomFooter',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#7f8c8d'),
            alignment=TA_CENTER
        ))
    
    def add_title(self, title: str):
        """Agrega un título al documento."""
        self.story.append(Paragraph(title, self.styles['CustomTitle']))
        self.story.append(Spacer(1, 0.2*inch))
    
    def add_heading(self, heading: str):
        """Agrega un encabezado."""
        self.story.append(Paragraph(heading, self.styles['CustomHeading']))
    
    def add_paragraph(self, text: str):
        """Agrega un párrafo."""
        self.story.append(Paragraph(text, self.styles['CustomBody']))
    
    def add_table(self, data: List[List[str]], headers: List[str], col_widths: Optional[List[float]] = None):
        """
        Agrega una tabla al documento.
        
        Args:
            data: Lista de filas (cada fila es una lista de celdas)
            headers: Encabezados de la tabla
            col_widths: Ancho de cada columna (opcional)
        """
        table_data = [headers] + data
        
        if col_widths:
            table = Table(table_data, colWidths=col_widths)
        else:
            table = Table(table_data)
        
        # Estilo de la tabla
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        self.story.append(table)
        self.story.append(Spacer(1, 0.2*inch))
    
    def add_image(self, image_path: str, width: float = 4*inch, height: Optional[float] = None):
        """
        Agrega una imagen al documento.
        
        Args:
            image_path: Ruta de la imagen
            width: Ancho de la imagen
            height: Alto de la imagen (opcional, mantiene aspect ratio si no se especifica)
        """
        if height:
            img = Image(image_path, width=width, height=height)
        else:
            img = Image(image_path, width=width)
        
        img.hAlign = 'CENTER'
        self.story.append(img)
        self.story.append(Spacer(1, 0.2*inch))
    
    def add_image_from_bytes(self, image_bytes: bytes, width: float = 4*inch, height: Optional[float] = None):
        """
        Agrega una imagen desde bytes.
        
        Args:
            image_bytes: Bytes de la imagen
            width: Ancho de la imagen
            height: Alto de la imagen (opcional)
        """
        img_reader = ImageReader(io.BytesIO(image_bytes))
        
        if height:
            img = Image(img_reader, width=width, height=height)
        else:
            img = Image(img_reader, width=width)
        
        img.hAlign = 'CENTER'
        self.story.append(img)
        self.story.append(Spacer(1, 0.2*inch))
    
    def add_page_break(self):
        """Agrega un salto de página."""
        self.story.append(PageBreak())
    
    def add_footer(self, text: str):
        """Agrega un pie de página."""
        self.story.append(Spacer(1, 0.5*inch))
        self.story.append(Paragraph(text, self.styles['CustomFooter']))
    
    def generate(self) -> str:
        """
        Genera el PDF.
        
        Returns:
            Ruta del PDF generado
        """
        self.doc.build(self.story)
        return self.output_path


def generate_invoice_report(
    invoice_data: Dict[str, Any],
    output_path: str,
    include_image: bool = True,
    image_bytes: Optional[bytes] = None
) -> str:
    """
    Genera un reporte PDF de una factura.
    
    Args:
        invoice_data: Datos de la factura
        output_path: Ruta de salida del PDF
        include_image: Si True, incluye la imagen de la factura
        image_bytes: Bytes de la imagen (opcional)
    
    Returns:
        Ruta del PDF generado
    """
    generator = PDFReportGenerator(output_path)
    
    # Título
    generator.add_title("Reporte de Factura")
    
    # Información general
    generator.add_heading("Información de la Factura")
    
    info_table = [
        ["Número", invoice_data.get('invoice_number', 'N/A')],
        ["Fecha", invoice_data.get('date', 'N/A')],
        ["Vendedor", invoice_data.get('vendor', 'N/A')],
        ["Total", f"${invoice_data.get('total', 0):.2f}"],
        ["Subtotal", f"${invoice_data.get('subtotal', 0):.2f}"],
        ["Impuesto", f"${invoice_data.get('tax', 0):.2f}"],
    ]
    
    generator.add_table(info_table, ["Campo", "Valor"], col_widths=[2*inch, 3*inch])
    
    # Items
    items = invoice_data.get('items', [])
    if items:
        generator.add_heading("Items")
        
        item_data = []
        for item in items:
            item_data.append([
                item.get('name', 'N/A'),
                str(item.get('quantity', 0)),
                f"${item.get('price', 0):.2f}",
                f"${item.get('total', 0):.2f}"
            ])
        
        generator.add_table(
            item_data,
            ["Descripción", "Cantidad", "Precio", "Total"],
            col_widths=[2.5*inch, 1*inch, 1*inch, 1*inch]
        )
    
    # OCR Info
    if 'ocr_confidence' in invoice_data:
        generator.add_heading("Información de OCR")
        generator.add_paragraph(f"Confianza del OCR: {invoice_data['ocr_confidence']:.2%}")
    
    # Imagen
    if include_image and image_bytes:
        generator.add_page_break()
        generator.add_heading("Imagen Original")
        generator.add_image_from_bytes(image_bytes, width=5*inch)
    
    # Footer
    generator.add_footer(f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} por πNAD Scanner")
    
    return generator.generate()


def generate_usage_report(
    usage_data: Dict[str, Any],
    output_path: str
) -> str:
    """
    Genera un reporte PDF de uso del sistema.
    
    Args:
        usage_data: Datos de uso
        output_path: Ruta de salida del PDF
    
    Returns:
        Ruta del PDF generado
    """
    generator = PDFReportGenerator(output_path)
    
    generator.add_title("Reporte de Uso del Sistema")
    
    # Resumen
    generator.add_heading("Resumen")
    
    summary_table = [
        ["Total de Escaneos", str(usage_data.get('total_scans', 0))],
        ["Usuarios Activos", str(usage_data.get('active_users', 0))],
        ["Tenants Activos", str(usage_data.get('active_tenants', 0))],
        ["Almacenamiento Usado", f"{usage_data.get('storage_used_mb', 0):.2f} MB"],
    ]
    
    generator.add_table(summary_table, ["Métrica", "Valor"], col_widths=[2*inch, 3*inch])
    
    # Por tenant
    tenants = usage_data.get('by_tenant', [])
    if tenants:
        generator.add_page_break()
        generator.add_heading("Uso por Tenant")
        
        tenant_data = []
        for tenant in tenants:
            tenant_data.append([
                tenant.get('name', 'N/A'),
                str(tenant.get('scans', 0)),
                f"{tenant.get('storage_mb', 0):.2f} MB"
            ])
        
        generator.add_table(
            tenant_data,
            ["Tenant", "Escaneos", "Almacenamiento"],
            col_widths=[2.5*inch, 1.5*inch, 1.5*inch]
        )
    
    generator.add_footer(f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} por πNAD Scanner")
    
    return generator.generate()
