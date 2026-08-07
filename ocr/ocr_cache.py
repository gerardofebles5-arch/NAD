"""
Sistema de Cache de Resultados OCR
===================================
Cachea resultados de OCR para evitar reprocesar la misma imagen.

Funcionalidades:
  - Cache basado en hash de imagen
  - Persistencia en disco
  - Expiración de cache
  - Estadísticas de uso
"""

import hashlib
import json
import os
import pickle
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class CacheEntry:
    """Entrada de cache."""
    image_hash: str
    ocr_result: Dict[str, Any]
    timestamp: str
    hit_count: int = 0
    size_bytes: int = 0


class OCRCache:
    """
    Sistema de cache para resultados OCR.
    
    Cachea resultados basándose en el hash de la imagen para evitar
    reprocesar la misma imagen.
    """
    
    def __init__(self, cache_dir: str = None, ttl_hours: int = 24):
        """
        Args:
            cache_dir: Directorio para almacenar cache
            ttl_hours: Tiempo de vida en horas
        """
        if cache_dir is None:
            cache_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data',
                'ocr_cache'
            )
        
        self.cache_dir = cache_dir
        self.ttl_hours = ttl_hours
        self._cache: Dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0
        
        # Crear directorio de cache
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Cargar cache existente
        self._load_cache()
    
    def _get_image_hash(self, image_bytes: bytes) -> str:
        """Calcula el hash SHA256 de la imagen."""
        return hashlib.sha256(image_bytes).hexdigest()
    
    def _load_cache(self):
        """Carga cache desde disco."""
        index_file = os.path.join(self.cache_dir, 'cache_index.json')
        if os.path.exists(index_file):
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for hash_str, entry_data in data.items():
                        entry = CacheEntry(**entry_data)
                        # Verificar si no ha expirado
                        if not self._is_expired(entry):
                            self._cache[hash_str] = entry
            except Exception as e:
                print(f"[WARN] Error cargando cache: {e}")
    
    def _save_cache(self):
        """Guarda cache en disco."""
        index_file = os.path.join(self.cache_dir, 'cache_index.json')
        try:
            data = {}
            for hash_str, entry in self._cache.items():
                data[hash_str] = asdict(entry)
            
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WARN] Error guardando cache: {e}")
    
    def _is_expired(self, entry: CacheEntry) -> bool:
        """Verifica si una entrada ha expirado."""
        entry_time = datetime.fromisoformat(entry.timestamp)
        expiry_time = entry_time + timedelta(hours=self.ttl_hours)
        return datetime.now() > expiry_time
    
    def _cleanup_expired(self):
        """Limpia entradas expiradas."""
        expired = [h for h, e in self._cache.items() if self._is_expired(e)]
        for h in expired:
            del self._cache[h]
            # Eliminar archivo de datos
            data_file = os.path.join(self.cache_dir, f"{h}.pkl")
            if os.path.exists(data_file):
                os.unlink(data_file)
        
        if expired:
            self._save_cache()
    
    def get(self, image_bytes: bytes) -> Optional[Dict[str, Any]]:
        """
        Obtiene resultado cacheado para una imagen.
        
        Args:
            image_bytes: Bytes de la imagen
            
        Returns:
            Resultado OCR cacheado o None
        """
        if image_bytes is None or not isinstance(image_bytes, bytes):
            self._misses += 1
            return None
        
        image_hash = self._get_image_hash(image_bytes)
        
        if image_hash in self._cache:
            entry = self._cache[image_hash]
            
            # Verificar expiración
            if self._is_expired(entry):
                del self._cache[image_hash]
                self._misses += 1
                return None
            
            # Incrementar hit count
            entry.hit_count += 1
            self._hits += 1
            
            # Cargar resultado desde archivo
            data_file = os.path.join(self.cache_dir, f"{image_hash}.pkl")
            if os.path.exists(data_file):
                try:
                    with open(data_file, 'rb') as f:
                        return pickle.load(f)
                except Exception as e:
                    print(f"[WARN] Error cargando resultado cacheado: {e}")
                    del self._cache[image_hash]
                    return None
        
        self._misses += 1
        return None
    
    def set(self, image_bytes: bytes, ocr_result: Dict[str, Any]):
        """
        Cachea un resultado OCR.
        
        Args:
            image_bytes: Bytes de la imagen
            ocr_result: Resultado OCR a cachear
        """
        image_hash = self._get_image_hash(image_bytes)
        
        # Calcular tamaño
        size_bytes = len(pickle.dumps(ocr_result))
        
        # Crear entrada
        entry = CacheEntry(
            image_hash=image_hash,
            ocr_result={},  # No guardamos el resultado en el índice
            timestamp=datetime.now().isoformat(),
            hit_count=0,
            size_bytes=size_bytes
        )
        
        # Guardar resultado en archivo
        data_file = os.path.join(self.cache_dir, f"{image_hash}.pkl")
        try:
            with open(data_file, 'wb') as f:
                pickle.dump(ocr_result, f)
            
            self._cache[image_hash] = entry
            self._save_cache()
        except Exception as e:
            print(f"[WARN] Error guardando resultado en cache: {e}")
    
    def clear(self):
        """Limpia todo el cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        
        # Eliminar archivos
        for filename in os.listdir(self.cache_dir):
            file_path = os.path.join(self.cache_dir, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas del cache."""
        total_size = sum(e.size_bytes for e in self._cache.values())
        hit_rate = self._hits / max(self._hits + self._misses, 1)
        
        return {
            'entries': len(self._cache),
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': hit_rate,
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024),
            'ttl_hours': self.ttl_hours,
        }
    
    def cleanup(self):
        """Limpia entradas expiradas."""
        self._cleanup_expired()


# Instancia global del cache
_global_cache: Optional[OCRCache] = None


def get_ocr_cache(cache_dir: str = None, ttl_hours: int = 24) -> OCRCache:
    """Retorna la instancia global del OCRCache."""
    global _global_cache
    if _global_cache is None:
        _global_cache = OCRCache(cache_dir=cache_dir, ttl_hours=ttl_hours)
    return _global_cache


def cache_ocr_result(image_bytes: bytes, ocr_result: Dict[str, Any]):
    """
    Función de conveniencia para cachear un resultado OCR.
    
    Args:
        image_bytes: Bytes de la imagen
        ocr_result: Resultado OCR a cachear
    """
    cache = get_ocr_cache()
    cache.set(image_bytes, ocr_result)


def get_cached_ocr_result(image_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Función de conveniencia para obtener un resultado cacheado.
    
    Args:
        image_bytes: Bytes de la imagen
        
    Returns:
        Resultado OCR cacheado o None
    """
    cache = get_ocr_cache()
    return cache.get(image_bytes)
