"""
Sistema de Aprendizaje de Correcciones OCR
===========================================
Aprende de las correcciones que el usuario hace y las aplica
automáticamente en futuros procesamientos.

Funcionalidades:
  - Registro de correcciones de usuario
  - Persistencia de correcciones aprendidas
  - Aplicación automática de correcciones aprendidas
  - Ranking de correcciones por frecuencia
"""

import json
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import defaultdict


@dataclass
class CorrectionEntry:
    """Entrada de corrección aprendida."""
    field_name: str
    wrong_value: str
    correct_value: str
    timestamp: str
    frequency: int = 1
    confidence: float = 0.5


class CorrectionLearner:
    """
    Sistema de aprendizaje de correcciones OCR.
    
    Aprende de las correcciones que el usuario hace y las aplica
    automáticamente en futuros procesamientos.
    """
    
    def __init__(self, storage_path: str = None):
        """
        Args:
            storage_path: Ruta del archivo JSON para persistir correcciones
        """
        if storage_path is None:
            storage_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data',
                'learned_corrections.json'
            )
        
        self.storage_path = storage_path
        self._corrections: Dict[str, List[CorrectionEntry]] = defaultdict(list)
        self._load_corrections()
    
    def _load_corrections(self):
        """Carga correcciones aprendidas desde el archivo."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for field_name, entries in data.items():
                        for entry_data in entries:
                            entry = CorrectionEntry(**entry_data)
                            self._corrections[field_name].append(entry)
            except Exception as e:
                print(f"[WARN] Error cargando correcciones: {e}")
    
    def _save_corrections(self):
        """Guarda correcciones aprendidas en el archivo."""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            data = {}
            for field_name, entries in self._corrections.items():
                data[field_name] = [asdict(entry) for entry in entries]
            
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARN] Error guardando correcciones: {e}")
    
    def register_correction(self, field_name: str, wrong_value: str, correct_value: str):
        """
        Registra una corrección hecha por el usuario.
        
        Args:
            field_name: Nombre del campo corregido
            wrong_value: Valor incorrecto extraído por OCR
            correct_value: Valor correcto proporcionado por el usuario
        """
        # Buscar si ya existe esta corrección
        for entry in self._corrections[field_name]:
            if entry.wrong_value == wrong_value and entry.correct_value == correct_value:
                # Incrementar frecuencia
                entry.frequency += 1
                entry.timestamp = datetime.now().isoformat()
                # Aumentar confianza basado en frecuencia
                entry.confidence = min(0.9, 0.5 + (entry.frequency * 0.1))
                self._save_corrections()
                return
        
        # Nueva corrección
        new_entry = CorrectionEntry(
            field_name=field_name,
            wrong_value=wrong_value,
            correct_value=correct_value,
            timestamp=datetime.now().isoformat(),
            frequency=1,
            confidence=0.5
        )
        self._corrections[field_name].append(new_entry)
        self._save_corrections()
    
    def apply_corrections(self, fields: Dict[str, str]) -> Tuple[Dict[str, str], List[Dict]]:
        """
        Aplica correcciones aprendidas a los campos extraídos.
        
        Args:
            fields: Diccionario de campos extraídos
            
        Returns:
            (campos_corregidos, lista_de_correcciones_aplicadas)
        """
        corrected = dict(fields)
        applied_corrections = []
        
        for field_name, value in fields.items():
            if not value:
                continue
            
            if field_name in self._corrections:
                # Buscar corrección para este valor
                for entry in self._corrections[field_name]:
                    # Coincidencia exacta
                    if entry.wrong_value == value:
                        corrected[field_name] = entry.correct_value
                        applied_corrections.append({
                            'field': field_name,
                            'from': value,
                            'to': entry.correct_value,
                            'confidence': entry.confidence,
                            'frequency': entry.frequency,
                            'source': 'learned'
                        })
                        break
                    
                    # Coincidencia parcial (similitud > 80%)
                    if self._similarity(value, entry.wrong_value) > 0.8:
                        corrected[field_name] = entry.correct_value
                        applied_corrections.append({
                            'field': field_name,
                            'from': value,
                            'to': entry.correct_value,
                            'confidence': entry.confidence * 0.8,  # Menor confianza para parcial
                            'frequency': entry.frequency,
                            'source': 'learned_partial'
                        })
                        break
        
        return corrected, applied_corrections
    
    def _similarity(self, s1: str, s2: str) -> float:
        """Calcula la similitud entre dos strings (Levenshtein simplificado)."""
        if s1 == s2:
            return 1.0
        
        # Similitud basada en longitud y caracteres comunes
        len1, len2 = len(s1), len(s2)
        if len1 == 0 or len2 == 0:
            return 0.0
        
        # Caracteres comunes
        common = sum(1 for c in s1 if c in s2)
        similarity = (common / max(len1, len2))
        
        return similarity
    
    def get_corrections(self, field_name: str = None) -> List[CorrectionEntry]:
        """
        Retorna correcciones aprendidas.
        
        Args:
            field_name: Nombre del campo específico (opcional)
            
        Returns:
            Lista de correcciones
        """
        if field_name:
            return self._corrections.get(field_name, [])
        else:
            # Retornar todas las correcciones
            all_corrections = []
            for entries in self._corrections.values():
                all_corrections.extend(entries)
            return all_corrections
    
    def get_top_corrections(self, field_name: str = None, limit: int = 10) -> List[CorrectionEntry]:
        """
        Retorna las correcciones más frecuentes.
        
        Args:
            field_name: Nombre del campo específico (opcional)
            limit: Número máximo de correcciones a retornar
            
        Returns:
            Lista de correcciones ordenadas por frecuencia
        """
        corrections = self.get_corrections(field_name)
        sorted_corrections = sorted(corrections, key=lambda x: x.frequency, reverse=True)
        return sorted_corrections[:limit]
    
    def clear_corrections(self, field_name: str = None):
        """
        Limpia correcciones aprendidas.
        
        Args:
            field_name: Nombre del campo específico (opcional)
        """
        if field_name:
            self._corrections[field_name] = []
        else:
            self._corrections.clear()
        self._save_corrections()
    
    def export_corrections(self, export_path: str):
        """
        Exporta correcciones aprendidas a un archivo.
        
        Args:
            export_path: Ruta del archivo de exportación
        """
        data = {}
        for field_name, entries in self._corrections.items():
            data[field_name] = [asdict(entry) for entry in entries]
        
        with open(export_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def import_corrections(self, import_path: str):
        """
        Importa correcciones desde un archivo.
        
        Args:
            import_path: Ruta del archivo de importación
        """
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for field_name, entries in data.items():
                    for entry_data in entries:
                        entry = CorrectionEntry(**entry_data)
                        self._corrections[field_name].append(entry)
            self._save_corrections()
        except Exception as e:
            print(f"[WARN] Error importando correcciones: {e}")


# Instancia global del learner
_global_learner: Optional[CorrectionLearner] = None


def get_correction_learner() -> CorrectionLearner:
    """Retorna la instancia global del CorrectionLearner."""
    global _global_learner
    if _global_learner is None:
        _global_learner = CorrectionLearner()
    return _global_learner


def register_user_correction(field_name: str, wrong_value: str, correct_value: str):
    """
    Función de conveniencia para registrar una corrección de usuario.
    
    Args:
        field_name: Nombre del campo corregido
        wrong_value: Valor incorrecto extraído por OCR
        correct_value: Valor correcto proporcionado por el usuario
    """
    learner = get_correction_learner()
    learner.register_correction(field_name, wrong_value, correct_value)


def apply_learned_corrections(fields: Dict[str, str]) -> Tuple[Dict[str, str], List[Dict]]:
    """
    Función de conveniencia para aplicar correcciones aprendidas.
    
    Args:
        fields: Diccionario de campos extraídos
        
    Returns:
        (campos_corregidos, lista_de_correcciones_aplicadas)
    """
    learner = get_correction_learner()
    return learner.apply_corrections(fields)
