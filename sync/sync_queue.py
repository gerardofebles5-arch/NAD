"""
πNAD - Sync Queue
=================
Gestión de cola de operaciones para sincronización bidireccional
entre SQLite local y Supabase.
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List, Any
from enum import Enum
from utils.config import CONFIG

DB_PATH = f"{CONFIG.output_dir}/nadscanner.db"


class SyncOperation(str, Enum):
    """Tipos de operaciones de sincronización."""
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


class SyncStatus(str, Enum):
    """Estados de una operación de sincronización."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


def init_sync_queue():
    """Inicializa la tabla de cola de sincronización."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error_message TEXT DEFAULT NULL,
            retry_count INTEGER DEFAULT 0,
            direction TEXT NOT NULL DEFAULT 'push'  -- 'push' (local→cloud) or 'pull' (cloud→local)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_queue_status 
        ON sync_queue(status, created_at)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_queue_table 
        ON sync_queue(table_name, record_id)
    """)
    
    conn.commit()
    conn.close()


def enqueue_operation(
    table_name: str,
    operation: SyncOperation,
    record_id: int,
    data: Dict[str, Any],
    direction: str = "push"
) -> int:
    """
    Agrega una operación a la cola de sincronización.
    
    Args:
        table_name: Nombre de la tabla
        operation: Tipo de operación (insert, update, delete)
        record_id: ID del registro
        data: Datos del registro (JSON serializable)
        direction: Dirección de la sync ('push' o 'pull')
    
    Returns:
        ID de la operación encolada
    """
    init_sync_queue()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute(
        """INSERT INTO sync_queue 
           (table_name, operation, record_id, data, status, created_at, updated_at, direction)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (table_name, operation.value, record_id, json.dumps(data), 
         SyncStatus.PENDING.value, now, now, direction)
    )
    
    op_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return op_id


def get_pending_operations(limit: int = 100, direction: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Obtiene operaciones pendientes de sincronización.
    
    Args:
        limit: Máximo número de operaciones a retornar
        direction: Filtrar por dirección (opcional)
    
    Returns:
        Lista de operaciones pendientes
    """
    init_sync_queue()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM sync_queue WHERE status = ?"
    params = [SyncStatus.PENDING.value]
    
    if direction:
        query += " AND direction = ?"
        params.append(direction)
    
    query += " ORDER BY created_at ASC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    operations = []
    for row in rows:
        op = dict(row)
        op['data'] = json.loads(op['data'])
        operations.append(op)
    
    conn.close()
    return operations


def update_operation_status(
    op_id: int,
    status: SyncStatus,
    error_message: Optional[str] = None
) -> bool:
    """
    Actualiza el estado de una operación de sincronización.
    
    Args:
        op_id: ID de la operación
        status: Nuevo estado
        error_message: Mensaje de error (si falló)
    
    Returns:
        True si se actualizó correctamente
    """
    init_sync_queue()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute(
        """UPDATE sync_queue 
           SET status = ?, updated_at = ?, error_message = ?, 
               retry_count = retry_count + 1
           WHERE id = ?""",
        (status.value, now, error_message, op_id)
    )
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def delete_operation(op_id: int) -> bool:
    """
    Elimina una operación de la cola (después de completarse exitosamente).
    
    Args:
        op_id: ID de la operación
    
    Returns:
        True si se eliminó correctamente
    """
    init_sync_queue()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM sync_queue WHERE id = ?", (op_id,))
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def get_sync_stats() -> Dict[str, Any]:
    """
    Obtiene estadísticas de la cola de sincronización.
    
    Returns:
        Diccionario con estadísticas
    """
    init_sync_queue()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    stats = {}
    
    for status in SyncStatus:
        cursor.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE status = ?",
            (status.value,)
        )
        stats[status.value] = cursor.fetchone()[0]
    
    # Por dirección
    cursor.execute(
        "SELECT direction, COUNT(*) FROM sync_queue GROUP BY direction"
    )
    stats['by_direction'] = dict(cursor.fetchall())
    
    # Por tabla
    cursor.execute(
        "SELECT table_name, COUNT(*) FROM sync_queue GROUP BY table_name"
    )
    stats['by_table'] = dict(cursor.fetchall())
    
    conn.close()
    return stats


def clear_completed_operations(older_than_hours: int = 24) -> int:
    """
    Limpia operaciones completadas antiguas.
    
    Args:
        older_than_hours: Eliminar operaciones completadas hace más de X horas
    
    Returns:
        Número de operaciones eliminadas
    """
    init_sync_queue()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(hours=older_than_hours)).isoformat()
    
    cursor.execute(
        """DELETE FROM sync_queue 
           WHERE status = ? AND updated_at < ?""",
        (SyncStatus.COMPLETED.value, cutoff)
    )
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    return deleted
