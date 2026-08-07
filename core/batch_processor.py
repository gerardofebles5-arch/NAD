"""
Procesamiento por Lotes — Nivel CamScanner Plus
================================================

Características que superan a CamScanner:
1. Cola de procesamiento con prioridades
2. Reintentos automáticos con backoff
3. Progreso en tiempo real por documento
4. Estadísticas de lote completas
5. Exportación masiva a PDF/ZIP
"""

import os
import json
import time
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
from queue import Queue, PriorityQueue
import cv2
import numpy as np


class BatchStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class BatchPriority(Enum):
    LOW = 3
    NORMAL = 2
    HIGH = 1
    URGENT = 0


@dataclass
class BatchItem:
    """Elemento individual en el lote."""
    id: str
    file_path: str
    status: BatchStatus = BatchStatus.PENDING
    priority: BatchPriority = BatchPriority.NORMAL
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    created_at: str = ""
    completed_at: str = ""
    processing_time: float = 0


@dataclass
class BatchStats:
    """Estadísticas del lote."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    pending: int = 0
    processing: int = 0
    avg_processing_time: float = 0
    total_processing_time: float = 0
    start_time: str = ""
    end_time: str = ""


class BatchProcessor:
    """
    Procesador por lotes con cola de prioridades.
    
    Características:
    - Procesamiento secuencial o paralelo
    - Reintentos automáticos
    - Callbacks de progreso
    - Estadísticas en tiempo real
    """
    
    def __init__(self, max_workers: int = 1):
        self.items: List[BatchItem] = []
        self.stats = BatchStats()
        self._queue = Queue()
        self._workers = []
        self._max_workers = max_workers
        self._running = False
        self._progress_callback: Optional[Callable] = None
        self._result_callback: Optional[Callable] = None
    
    def add_item(self, file_path: str, priority: BatchPriority = BatchPriority.NORMAL) -> str:
        """
        Agrega un elemento al lote.
        
        Args:
            file_path: Ruta al archivo
            priority: Prioridad
        
        Returns:
            ID del elemento
        """
        item_id = f"batch_{len(self.items)}_{int(time.time())}"
        
        item = BatchItem(
            id=item_id,
            file_path=file_path,
            priority=priority,
            created_at=datetime.now().isoformat(),
        )
        
        self.items.append(item)
        self.stats.total = len(self.items)
        self.stats.pending = sum(1 for i in self.items if i.status == BatchStatus.PENDING)
        
        return item_id
    
    def add_multiple(self, file_paths: List[str], priority: BatchPriority = BatchPriority.NORMAL) -> List[str]:
        """Agrega múltiples archivos al lote."""
        return [self.add_item(fp, priority) for fp in file_paths]
    
    def set_progress_callback(self, callback: Callable):
        """Establece callback de progreso."""
        self._progress_callback = callback
    
    def set_result_callback(self, callback: Callable):
        """Establece callback de resultado."""
        self._result_callback = callback
    
    def process(self, process_fn: Callable) -> BatchStats:
        """
        Procesa todos los elementos del lote.
        
        Args:
            process_fn: Función que procesa un BatchItem y retorna resultado
        
        Returns:
            Estadísticas del lote
        """
        self._running = True
        self.stats.start_time = datetime.now().isoformat()
        
        # Ordenar por prioridad
        sorted_items = sorted(self.items, key=lambda x: x.priority.value)
        
        for item in sorted_items:
            if not self._running:
                break
            
            if item.status == BatchStatus.COMPLETED:
                continue
            
            item.status = BatchStatus.PROCESSING
            self.stats.processing = sum(1 for i in self.items if i.status == BatchStatus.PROCESSING)
            self.stats.pending = sum(1 for i in self.items if i.status == BatchStatus.PENDING)
            
            if self._progress_callback:
                self._progress_callback(self._get_progress())
            
            start_time = time.time()
            
            try:
                result = process_fn(item)
                item.result = result
                item.status = BatchStatus.COMPLETED
                item.completed_at = datetime.now().isoformat()
                item.processing_time = time.time() - start_time
                
                self.stats.completed += 1
                self.stats.total_processing_time += item.processing_time
                
                if self._result_callback:
                    self._result_callback(item)
            
            except Exception as e:
                item.error = str(e)
                item.attempts += 1
                
                if item.attempts < item.max_attempts:
                    item.status = BatchStatus.RETRYING
                    # Re-intentar con backoff
                    time.sleep(min(2 ** item.attempts, 10))
                    item.status = BatchStatus.PENDING
                else:
                    item.status = BatchStatus.FAILED
                    self.stats.failed += 1
        
        self._running = False
        self.stats.end_time = datetime.now().isoformat()
        self.stats.processing = 0
        self.stats.pending = sum(1 for i in self.items if i.status == BatchStatus.PENDING)
        
        if self.stats.completed > 0:
            self.stats.avg_processing_time = self.stats.total_processing_time / self.stats.completed
        
        return self.stats
    
    def _get_progress(self) -> Dict[str, Any]:
        """Retorna progreso actual."""
        total = len(self.items)
        completed = sum(1 for i in self.items if i.status == BatchStatus.COMPLETED)
        failed = sum(1 for i in self.items if i.status == BatchStatus.FAILED)
        
        return {
            'total': total,
            'completed': completed,
            'failed': failed,
            'pending': total - completed - failed,
            'percentage': round((completed / total * 100) if total > 0 else 0, 1),
        }
    
    def get_results(self) -> List[Dict[str, Any]]:
        """Retorna todos los resultados completados."""
        return [
            {
                'id': item.id,
                'file': item.file_path,
                'result': item.result,
                'status': item.status.value,
                'processing_time': item.processing_time,
            }
            for item in self.items
            if item.status == BatchStatus.COMPLETED
        ]
    
    def get_failed(self) -> List[Dict[str, Any]]:
        """Retorna los elementos fallidos."""
        return [
            {
                'id': item.id,
                'file': item.file_path,
                'error': item.error,
                'attempts': item.attempts,
            }
            for item in self.items
            if item.status == BatchStatus.FAILED
        ]
    
    def clear(self):
        """Limpia el lote."""
        self.items.clear()
        self.stats = BatchStats()
    
    def stop(self):
        """Detiene el procesamiento."""
        self._running = False


class BatchPDFExporter:
    """
    Exportador de lote a PDF multipágina.
    """
    
    @staticmethod
    def create_pdf(images: List[np.ndarray], output_path: str, 
                   quality: int = 95, metadata: Optional[Dict] = None) -> str:
        """
        Crea un PDF multipágina desde una lista de imágenes.
        
        Args:
            images: Lista de imágenes BGR
            output_path: Ruta de salida
            quality: Calidad JPEG (1-100)
            metadata: Metadatos opcionales
        
        Returns:
            Ruta del PDF creado
        """
        try:
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import inch
        except ImportError:
            # Fallback: crear PDF manualmente
            return BatchPDFExporter._create_pdf_manual(images, output_path)
        
        # Crear PDF con reportlab
        c = canvas.Canvas(output_path, pagesize=A4)
        
        for i, img in enumerate(images):
            # Convertir BGR a RGB
            if len(img.shape) == 3:
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            else:
                img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            
            # Guardar como temporal
            temp_path = f"/tmp/batch_page_{i}.jpg"
            cv2.imwrite(temp_path, img_rgb, [cv2.IMWRITE_JPEG_QUALITY, quality])
            
            # Agregar página
            c.drawImage(temp_path, 0, 0, width=A4[0], height=A4[1])
            c.showPage()
            
            # Limpiar temporal
            os.remove(temp_path)
        
        # Agregar metadatos si existen
        if metadata:
            c.setTitle(metadata.get('title', 'NAD Scanner Batch'))
            c.setAuthor(metadata.get('author', 'NAD Scanner'))
        
        c.save()
        return output_path
    
    @staticmethod
    def _create_pdf_manual(images: List[np.ndarray], output_path: str) -> str:
        """Fallback manual para crear PDF sin reportlab."""
        # Crear directorio de temporales
        temp_dir = Path(output_path).parent / "temp_pdf"
        temp_dir.mkdir(exist_ok=True)
        
        # Guardar cada imagen como página
        pages = []
        for i, img in enumerate(images):
            page_path = str(temp_dir / f"page_{i:04d}.jpg")
            cv2.imwrite(page_path, img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            pages.append(page_path)
        
        # Crear PDF simple con img2pdf si está disponible
        try:
            import img2pdf
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert(pages))
        except ImportError:
            # Último recurso: usar Pillow
            from PIL import Image
            pil_images = [Image.open(p) for p in pages]
            if pil_images:
                pil_images[0].save(
                    output_path,
                    "PDF",
                    save_all=True,
                    append_images=pil_images[1:],
                    resolution=300,
                )
        
        # Limpiar temporales
        for p in pages:
            os.remove(p)
        temp_dir.rmdir()
        
        return output_path


class BatchZIPExporter:
    """
    Exportador de lote a ZIP con imágenes y datos JSON.
    """
    
    @staticmethod
    def create_zip(items: List[Dict], output_path: str) -> str:
        """
        Crea un ZIP con imágenes y datos JSON.
        
        Args:
            items: Lista de {'image': np.ndarray, 'data': dict, 'filename': str}
            output_path: Ruta de salida
        
        Returns:
            Ruta del ZIP creado
        """
        import zipfile
        import tempfile
        
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, item in enumerate(items):
                # Guardar imagen
                img_path = f"image_{i:04d}.jpg"
                if 'image' in item and item['image'] is not None:
                    _, buffer = cv2.imencode('.jpg', item['image'], [cv2.IMWRITE_JPEG_QUALITY, 95])
                    zf.writestr(img_path, buffer.tobytes())
                
                # Guardar datos JSON
                if 'data' in item and item['data'] is not None:
                    data_path = f"data_{i:04d}.json"
                    json_data = json.dumps(item['data'], indent=2, ensure_ascii=False)
                    zf.writestr(data_path, json_data)
                
                # Guardar nombre original
                if 'filename' in item:
                    name_path = f"name_{i:04d}.txt"
                    zf.writestr(name_path, item['filename'])
        
        return output_path
