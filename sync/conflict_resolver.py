"""
πNAD - Conflict Resolver
========================
Resolución de conflictos en sincronización bidireccional entre SQLite y Supabase.
"""

import json
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
import hashlib


class ConflictResolutionStrategy(str, Enum):
    """Estrategias de resolución de conflictos."""
    LOCAL_WINS = "local_wins"
    REMOTE_WINS = "remote_wins"
    LAST_WRITE_WINS = "last_write_wins"
    MANUAL = "manual"
    MERGE = "merge"


class ConflictResolver:
    """Resuelve conflictos entre registros locales y remotos."""
    
    def __init__(self, default_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.LAST_WRITE_WINS):
        """
        Inicializa el ConflictResolver.
        
        Args:
            default_strategy: Estrategia por defecto para resolver conflictos
        """
        self.default_strategy = default_strategy
        
        # Estrategias específicas por tabla
        self.table_strategies = {
            'invoices': ConflictResolutionStrategy.LAST_WRITE_WINS,
            'tenants': ConflictResolutionStrategy.MANUAL,
            'tenant_users': ConflictResolutionStrategy.REMOTE_WINS,
            'usage_metrics': ConflictResolutionStrategy.REMOTE_WINS,
        }
    
    def resolve(
        self,
        table_name: str,
        local: Dict[str, Any],
        remote: Dict[str, Any],
        strategy: Optional[ConflictResolutionStrategy] = None
    ) -> Dict[str, Any]:
        """
        Resuelve un conflicto entre registros local y remoto.
        
        Args:
            table_name: Nombre de la tabla
            local: Registro local
            remote: Registro remoto
            strategy: Estrategia a usar (opcional, usa la configurada por defecto)
        
        Returns:
            Diccionario con:
                - strategy: Estrategia usada
                - winner: 'local' o 'remote'
                - merged_data: Datos resultantes (si merge)
                - conflict_info: Información del conflicto
        """
        # Determinar estrategia
        if strategy is None:
            strategy = self.table_strategies.get(table_name, self.default_strategy)
        
        # Detectar tipo de conflicto
        conflict_type = self._detect_conflict_type(local, remote)
        
        result = {
            'strategy': strategy,
            'conflict_type': conflict_type,
            'local_updated': local.get('updated_at'),
            'remote_updated': remote.get('updated_at'),
        }
        
        # Aplicar estrategia
        if strategy == ConflictResolutionStrategy.LOCAL_WINS:
            result['winner'] = 'local'
            result['merged_data'] = local
            
        elif strategy == ConflictResolutionStrategy.REMOTE_WINS:
            result['winner'] = 'remote'
            result['merged_data'] = remote
            
        elif strategy == ConflictResolutionStrategy.LAST_WRITE_WINS:
            winner = self._last_write_wins(local, remote)
            result['winner'] = winner
            result['merged_data'] = local if winner == 'local' else remote
            
        elif strategy == ConflictResolutionStrategy.MANUAL:
            result['winner'] = 'manual'
            result['merged_data'] = None
            result['conflict_info'] = {
                'local': local,
                'remote': remote,
                'requires_user_intervention': True,
            }
            
        elif strategy == ConflictResolutionStrategy.MERGE:
            merged = self._merge_records(table_name, local, remote)
            result['winner'] = 'merged'
            result['merged_data'] = merged
        
        return result
    
    def _detect_conflict_type(self, local: Dict[str, Any], remote: Dict[str, Any]) -> str:
        """
        Detecta el tipo de conflicto.
        
        Returns:
            Tipo de conflicto: 'update_update', 'delete_update', 'update_delete', 'delete_delete'
        """
        # Verificar si alguno fue eliminado (marcado con is_active = 0 o similar)
        local_deleted = local.get('is_active') == 0 or local.get('deleted_at') is not None
        remote_deleted = remote.get('is_active') == 0 or remote.get('deleted_at') is not None
        
        if local_deleted and remote_deleted:
            return 'delete_delete'
        elif local_deleted:
            return 'delete_update'
        elif remote_deleted:
            return 'update_delete'
        else:
            return 'update_update'
    
    def _last_write_wins(self, local: Dict[str, Any], remote: Dict[str, Any]) -> str:
        """
        Determina el ganador basado en updated_at más reciente.
        
        Returns:
            'local' o 'remote'
        """
        local_updated = local.get('updated_at', '')
        remote_updated = remote.get('updated_at', '')
        
        if remote_updated > local_updated:
            return 'remote'
        else:
            return 'local'
    
    def _merge_records(self, table_name: str, local: Dict[str, Any], remote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fusiona registros locales y remotos.
        
        Para tablas específicas, usa lógica de merge personalizada.
        """
        if table_name == 'invoices':
            return self._merge_invoices(local, remote)
        elif table_name == 'tenants':
            return self._merge_tenants(local, remote)
        else:
            # Merge genérico: campos no nulos de ambos
            merged = local.copy()
            for key, value in remote.items():
                if value is not None and value != '':
                    merged[key] = value
            return merged
    
    def _merge_invoices(self, local: Dict[str, Any], remote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge específico para facturas.
        Prioriza datos de OCR más recientes y metadatos.
        """
        merged = local.copy()
        
        # Campos que priorizan el remoto (generalmente más actualizado)
        remote_priority_fields = [
            'ocr_text',
            'ocr_confidence',
            'extracted_data',
            'updated_at',
        ]
        
        for field in remote_priority_fields:
            if field in remote and remote[field] is not None:
                merged[field] = remote[field]
        
        # Campos que priorizan el local (metadatos de procesamiento)
        local_priority_fields = [
            'file_path',
            'file_name',
            'created_at',
        ]
        
        for field in local_priority_fields:
            if field in local and local[field] is not None:
                merged[field] = local[field]
        
        # Usar el updated_at más reciente
        if remote.get('updated_at', '') > local.get('updated_at', ''):
            merged['updated_at'] = remote['updated_at']
        
        return merged
    
    def _merge_tenants(self, local: Dict[str, Any], remote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge específico para tenants.
        Prioriza información de contacto y configuración.
        """
        merged = local.copy()
        
        # Campos que priorizan el remoto (configuración)
        remote_priority_fields = [
            'max_users',
            'max_storage_mb',
            'is_active',
            'updated_at',
        ]
        
        for field in remote_priority_fields:
            if field in remote and remote[field] is not None:
                merged[field] = remote[field]
        
        # Campos que priorizan el local (información de contacto)
        local_priority_fields = [
            'name',
            'email',
            'phone',
            'address',
            'rif',
        ]
        
        for field in local_priority_fields:
            if field in local and local[field] is not None:
                merged[field] = local[field]
        
        return merged
    
    def calculate_record_hash(self, record: Dict[str, Any], exclude_fields: list = None) -> str:
        """
        Calcula un hash de un registro para detectar cambios.
        
        Args:
            record: Registro a hashear
            exclude_fields: Campos a excluir del hash (ej: updated_at)
        
        Returns:
            Hash MD5 del registro
        """
        if exclude_fields is None:
            exclude_fields = ['updated_at', 'created_at']
        
        # Crear copia y excluir campos
        data = {k: v for k, v in record.items() if k not in exclude_fields}
        
        # Ordenar y serializar
        data_str = json.dumps(data, sort_keys=True, default=str)
        
        return hashlib.md5(data_str.encode()).hexdigest()
