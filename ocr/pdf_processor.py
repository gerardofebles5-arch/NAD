"""
Procesador de PDF para OCR
===========================
Convierte archivos PDF a imágenes para procesamiento OCR.

Funcionalidades:
  - Conversión de PDF a imágenes
  - Extracción de páginas individuales
  - Soporte para PDFs escaneados y digitales
"""

import os
from typing import List, Optional, Tuple
from dataclasses import dataclass
import numpy as np


@dataclass
class PDFPage:
    """Página de un PDF convertida a imagen."""
    page_number: int
    image: np.ndarray
    dpi: int


class PDFProcessor:
    """
    Procesador de PDF para OCR.
    
    Convierte archivos PDF a imágenes para ser procesadas por el sistema OCR.
    """
    
    def __init__(self, dpi: int = 200):
        """
        Args:
            dpi: Resolución DPI para conversión (default: 200)
        """
        self.dpi = dpi
        self._pdf2image_available = False
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Verifica si las dependencias están disponibles."""
        try:
            import pdf2image
            self._pdf2image_available = True
        except ImportError:
            print("[WARN] pdf2image no disponible. Instala con: pip install pdf2image")
    
    def convert_pdf_to_images(self, pdf_path: str) -> List[PDFPage]:
        """
        Convierte un PDF a una lista de imágenes.
        
        Args:
            pdf_path: Ruta del archivo PDF
            
        Returns:
            Lista de PDFPage con las imágenes convertidas
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Archivo PDF no encontrado: {pdf_path}")
        
        if not self._pdf2image_available:
            raise ImportError("pdf2image no está instalado. Instala con: pip install pdf2image")
        
        try:
            from pdf2image import convert_from_path
            
            # Convertir PDF a imágenes
            pil_images = convert_from_path(pdf_path, dpi=self.dpi)
            
            # Convertir PIL images a numpy arrays
            pages = []
            for i, pil_img in enumerate(pil_images):
                # Convertir PIL Image a numpy array
                img_array = np.array(pil_img)
                
                # Convertir RGB a BGR (formato OpenCV)
                if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                    img_array = img_array[:, :, ::-1]  # RGB to BGR
                
                page = PDFPage(
                    page_number=i + 1,
                    image=img_array,
                    dpi=self.dpi
                )
                pages.append(page)
            
            return pages
            
        except Exception as e:
            raise RuntimeError(f"Error convirtiendo PDF: {e}")
    
    def convert_pdf_page_to_image(self, pdf_path: str, page_number: int) -> Optional[PDFPage]:
        """
        Convierte una página específica del PDF a imagen.
        
        Args:
            pdf_path: Ruta del archivo PDF
            page_number: Número de página (1-indexed)
            
        Returns:
            PDFPage con la imagen convertida o None
        """
        if not self._pdf2image_available:
            raise ImportError("pdf2image no está instalado. Instala con: pip install pdf2image")
        
        try:
            from pdf2image import convert_from_path
            
            # Convertir solo la página específica
            pil_images = convert_from_path(
                pdf_path, 
                dpi=self.dpi,
                first_page=page_number,
                last_page=page_number
            )
            
            if not pil_images:
                return None
            
            # Convertir PIL Image a numpy array
            img_array = np.array(pil_images[0])
            
            # Convertir RGB a BGR (formato OpenCV)
            if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                img_array = img_array[:, :, ::-1]  # RGB to BGR
            
            return PDFPage(
                page_number=page_number,
                image=img_array,
                dpi=self.dpi
            )
            
        except Exception as e:
            raise RuntimeError(f"Error convirtiendo página {page_number}: {e}")
    
    def get_page_count(self, pdf_path: str) -> int:
        """
        Retorna el número de páginas del PDF.
        
        Args:
            pdf_path: Ruta del archivo PDF
            
        Returns:
            Número de páginas
        """
        if not self._pdf2image_available:
            raise ImportError("pdf2image no está instalado. Instala con: pip install pdf2image")
        
        try:
            from pdf2image import convert_from_path
            
            # Convertir PDF para obtener número de páginas
            pil_images = convert_from_path(pdf_path, dpi=self.dpi)
            return len(pil_images)
            
        except Exception as e:
            raise RuntimeError(f"Error obteniendo número de páginas: {e}")
    
    def is_pdf(self, file_path: str) -> bool:
        """
        Verifica si un archivo es un PDF.
        
        Args:
            file_path: Ruta del archivo
            
        Returns:
            True si es un PDF, False en caso contrario
        """
        return file_path.lower().endswith('.pdf')


def convert_pdf_to_ocr_images(pdf_path: str, dpi: int = 200) -> List[np.ndarray]:
    """
    Función de conveniencia para convertir PDF a imágenes OCR.
    
    Args:
        pdf_path: Ruta del archivo PDF
        dpi: Resolución DPI para conversión
        
    Returns:
        Lista de imágenes numpy arrays
    """
    processor = PDFProcessor(dpi=dpi)
    pages = processor.convert_pdf_to_images(pdf_path)
    return [page.image for page in pages]


def convert_pdf_page_to_ocr_image(pdf_path: str, page_number: int, dpi: int = 200) -> Optional[np.ndarray]:
    """
    Función de conveniencia para convertir una página PDF a imagen OCR.
    
    Args:
        pdf_path: Ruta del archivo PDF
        page_number: Número de página (1-indexed)
        dpi: Resolución DPI para conversión
        
    Returns:
        Imagen numpy array o None
    """
    processor = PDFProcessor(dpi=dpi)
    page = processor.convert_pdf_page_to_image(pdf_path, page_number)
    return page.image if page else None
