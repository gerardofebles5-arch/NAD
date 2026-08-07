"""
πNAD - Sync Manager
===================
Orquestador de sincronización bidireccional entre SQLite local y Supabase.
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List, Any
from utils.config import CONFIG
from sync.sync_queue import (
    init_sync_queue,
    enqueue_operation,
    get_pending_operations,
    update_operation_status,
    delete_operation,
    SyncOperation,
    SyncStatus,
)
from sync.conflict_resolver import ConflictResolver, ConflictResolutionStrategy

DB_PATH = f"{CONFIG.output_dir}/nadscanner.db"


class SyncManager:
    """Gestiona la sincronización bidireccional entre SQLite y Supabase."""
    
    def __init__(self, supabase_client=None):
        """
        Inicializa el SyncManager.
        
        Args:
            supabase_client: Cliente de Supabase (opcional, si no se usa Supabase)
        """
        self.supabase = supabase_client
        self.conflict_resolver = ConflictResolver()
        self.sync_enabled = CONFIG.supabase.sync_enabled
        self.tables_to_sync = [
            'invoices',
            'tenants',
            'tenant_users',
            'usage_metrics',
        ]
        
        # Mapeo de columnas entre SQLite y Supabase
        self.column_mappings = {
            'invoices': {
                'id': 'id',
                'created_at': 'created_at',
                'updated_at': 'updated_at',
                'file_name': 'file_name',
                'file_path': 'file_path',
                'ocr_text': 'ocr_text',
                'ocr_confidence': 'ocr_confidence',
                'extracted_data': 'extracted_data',
                'tenant_id': 'tenant_id',
            },
            'tenants': {
                'id': 'id',
                'name': 'name',
                'slug': 'slug',
                'email': 'email',
                'phone': 'phone',
                'address': 'address',
                'rif': 'rif',
                'created_at': 'created_at',
                'updated_at': 'updated_at',
                'is_active': 'is_active',
                'max_users': 'max_users',
                'max_storage_mb': 'max_storage_mb',
                'notes': 'notes',
            },
        }
    
    def is_enabled(self) -> bool:
        """Verifica si la sincronización está habilitada."""
        return self.sync_enabled and self.supabase is not None
    
    async def push_to_supabase(self, table_name: str, limit: int = 50) -> Dict[str, Any]:
        """
        Envía cambios locales a Supabase (push).
        
        Args:
            table_name: Nombre de la tabla a sincronizar
            limit: Máximo de registros a sincronizar
        
        Returns:
            Diccionario con resultados de la sincronización
        """
        if not self.is_enabled():
            return {'success': False, 'error': 'Sync not enabled'}
        
        if table_name not in self.tables_to_sync:
            return {'success': False, 'error': f'Table {table_name} not in sync list'}
        
        results = {
            'success': True,
            'table': table_name,
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'errors': [],
        }
        
        # Obtener operaciones pendientes de push
        operations = get_pending_operations(limit=limit, direction='push')
        table_operations = [op for op in operations if op['table_name'] == table_name]
        
        for op in table_operations:
            try:
                # Marcar como en progreso
                update_operation_status(op['id'], SyncStatus.IN_PROGRESS)
                
                # Ejecutar operación según tipo
                if op['operation'] == SyncOperation.INSERT:
                    success = await self._insert_to_supabase(table_name, op['data'])
                elif op['operation'] == SyncOperation.UPDATE:
                    success = await self._update_to_supabase(table_name, op['record_id'], op['data'])
                elif op['operation'] == SyncOperation.DELETE:
                    success = await self._delete_from_supabase(table_name, op['record_id'])
                else:
                    success = False
                
                if success:
                    update_operation_status(op['id'], SyncStatus.COMPLETED)
                    delete_operation(op['id'])
                    results['succeeded'] += 1
                else:
                    update_operation_status(op['id'], SyncStatus.FAILED, 'Operation failed')
                    results['failed'] += 1
                
                results['processed'] += 1
                
            except Exception as e:
                update_operation_status(op['id'], SyncStatus.FAILED, str(e))
                results['failed'] += 1
                results['errors'].append(str(e))
        
        return results
    
    async def pull_from_supabase(self, table_name: str, since: Optional[str] = None) -> Dict[str, Any]:
        """
        Recibe cambios desde Supabase (pull).
        
        Args:
            table_name: Nombre de la tabla a sincronizar
            since: Fecha ISO desde la cual buscar cambios (opcional)
        
        Returns:
            Diccionario con resultados de la sincronización
        """
        if not self.is_enabled():
            return {'success': False, 'error': 'Sync not enabled'}
        
        if table_name not in self.tables_to_sync:
            return {'success': False, 'error': f'Table {table_name} not in sync list'}
        
        results = {
            'success': True,
            'table': table_name,
            'pulled': 0,
            'conflicts': 0,
            'errors': [],
        }
        
        try:
            # Obtener cambios desde Supabase
            query = self.supabase.from_(table_name).select('*')
            
            if since:
                query = query.gte('updated_at', since)
            
            response = await query.execute()
            
            if response.error:
                return {'success': False, 'error': str(response.error)}
            
            remote_records = response.data
            
            # Sincronizar cada registro
            for remote_record in remote_records:
                try:
                    # Verificar si existe localmente
                    local_record = self._get_local_record(table_name, remote_record['id'])
                    
                    if local_record:
                        # Detectar conflicto
                        if self._has_conflict(local_record, remote_record):
                            resolution = self.conflict_resolver.resolve(
                                table_name,
                                local_record,
                                remote_record
                            )
                            
                            if resolution['strategy'] == ConflictResolutionStrategy.MANUAL:
                                results['conflicts'] += 1
                                # Enqueue para resolución manual
                                enqueue_operation(
                                    table_name,
                                    SyncOperation.UPDATE,
                                    remote_record['id'],
                                    remote_record,
                                    direction='pull'
                                )
                            elif resolution['strategy'] == ConflictResolutionStrategy.REMOTE_WINS:
                                self._update_local_record(table_name, remote_record)
                                results['pulled'] += 1
                            # Si LOCAL_WINS, no hacer nada
                        else:
                            # Sin conflicto, actualizar local
                            self._update_local_record(table_name, remote_record)
                            results['pulled'] += 1
                    else:
                        # No existe localmente, insertar
                        self._insert_local_record(table_name, remote_record)
                        results['pulled'] += 1
                        
                except Exception as e:
                    results['errors'].append(str(e))
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
        
        return results
    
    async def sync_all(self, push: bool = True, pull: bool = True) -> Dict[str, Any]:
        """
        Sincroniza todas las tablas configuradas.
        
        Args:
            push: Si True, envía cambios locales a Supabase
            pull: Si True, recibe cambios desde Supabase
        
        Returns:
            Diccionario con resultados globales
        """
        results = {
            'success': True,
            'tables': {},
            'total_pushed': 0,
            'total_pulled': 0,
            'total_conflicts': 0,
        }
        
        for table_name in self.tables_to_sync:
            table_result = {'table': table_name}
            
            if push:
                push_result = await self.push_to_supabase(table_name)
                table_result['push'] = push_result
                if push_result.get('success'):
                    results['total_pushed'] += push_result.get('succeeded', 0)
            
            if pull:
                pull_result = await self.pull_from_supabase(table_name)
                table_result['pull'] = pull_result
                if pull_result.get('success'):
                    results['total_pulled'] += pull_result.get('pulled', 0)
                    results['total_conflicts'] += pull_result.get('conflicts', 0)
            
            results['tables'][table_name] = table_result
        
        return results
    
    # ── Métodos privados ──
    
    async def _insert_to_supabase(self, table_name: str, data: Dict[str, Any]) -> bool:
        """Inserta un registro en Supabase."""
        try:
            response = await self.supabase.from_(table_name).insert(data).execute()
            return not response.error
        except Exception:
            return False
    
    async def _update_to_supabase(self, table_name: str, record_id: int, data: Dict[str, Any]) -> bool:
        """Actualiza un registro en Supabase."""
        try:
            response = await self.supabase.from_(table_name).update(data).eq('id', record_id).execute()
            return not response.error
        except Exception:
            return False
    
    async def _delete_from_supabase(self, table_name: str, record_id: int) -> bool:
        """Elimina un registro en Supabase."""
        try:
            response = await self.supabase.from_(table_name).delete().eq('id', record_id).execute()
            return not response.error
        except Exception:
            return False
    
    def _get_local_record(self, table_name: str, record_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene un registro local de SQLite."""
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (record_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def _insert_local_record(self, table_name: str, data: Dict[str, Any]) -> bool:
        """Inserta un registro local en SQLite."""
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        
        try:
            columns = list(data.keys())
            placeholders = ', '.join(['?'] * len(columns))
            columns_str = ', '.join(columns)
            
            cursor.execute(
                f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})",
                list(data.values())
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def _update_local_record(self, table_name: str, data: Dict[str, Any]) -> bool:
        """Actualiza un registro local en SQLite."""
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        
        try:
            if 'id' not in data:
                return False
            
            columns = [k for k in data.keys() if k != 'id']
            set_clause = ', '.join([f"{k} = ?" for k in columns])
            values = [data[k] for k in columns] + [data['id']]
            
            cursor.execute(
                f"UPDATE {table_name} SET {set_clause} WHERE id = ?",
                values
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def _has_conflict(self, local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
        """Detecta si hay conflicto entre registros local y remoto."""
        # Si el updated_at remoto es más reciente, no hay conflicto
        local_updated = local.get('updated_at', '')
        remote_updated = remote.get('updated_at', '')
        
        if remote_updated > local_updated:
            return False
        
        # Si tienen el mismo updated_at, comparar hashes
        if remote_updated == local_updated:
            return False
        
        # Si el local es más reciente, hay conflicto potencial
        return True
