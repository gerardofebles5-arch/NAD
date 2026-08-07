"""
πNAD - Sync Module
==================
Módulo de sincronización bidireccional entre SQLite y Supabase.
"""

from .sync_queue import (
    init_sync_queue,
    enqueue_operation,
    get_pending_operations,
    update_operation_status,
    delete_operation,
    get_sync_stats,
    clear_completed_operations,
    SyncOperation,
    SyncStatus,
)

from .sync_manager import SyncManager
from .conflict_resolver import ConflictResolver, ConflictResolutionStrategy

__all__ = [
    # sync_queue
    'init_sync_queue',
    'enqueue_operation',
    'get_pending_operations',
    'update_operation_status',
    'delete_operation',
    'get_sync_stats',
    'clear_completed_operations',
    'SyncOperation',
    'SyncStatus',
    # sync_manager
    'SyncManager',
    # conflict_resolver
    'ConflictResolver',
    'ConflictResolutionStrategy',
]
