"""
πNAD - Web Push Notifications
==============================
Sistema de notificaciones push para alertas al usuario.
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from utils.config import CONFIG

DB_PATH = f"{CONFIG.output_dir}/nadscanner.db"


@dataclass
class Notification:
    """Representa una notificación."""
    id: Optional[int] = None
    user_id: str = ""
    title: str = ""
    body: str = ""
    icon: str = ""
    data: Dict[str, Any] = None
    created_at: str = ""
    read: bool = False
    type: str = "info"  # info, success, warning, error
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def init_notifications_db():
    """Inicializa la tabla de notificaciones."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            icon TEXT DEFAULT '',
            data TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            read BOOLEAN DEFAULT 0,
            type TEXT DEFAULT 'info'
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_user 
        ON notifications(user_id, created_at DESC)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_read 
        ON notifications(user_id, read)
    """)
    
    conn.commit()
    conn.close()


def create_notification(
    user_id: str,
    title: str,
    body: str,
    icon: str = "",
    data: Optional[Dict[str, Any]] = None,
    notification_type: str = "info"
) -> Notification:
    """
    Crea una nueva notificación.
    
    Args:
        user_id: ID del usuario
        title: Título de la notificación
        body: Cuerpo de la notificación
        icon: URL del icono (opcional)
        data: Datos adicionales (opcional)
        notification_type: Tipo de notificación
    
    Returns:
        Notificación creada
    """
    init_notifications_db()
    
    notification = Notification(
        user_id=user_id,
        title=title,
        body=body,
        icon=icon,
        data=data or {},
        type=notification_type
    )
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute(
        """INSERT INTO notifications 
           (user_id, title, body, icon, data, created_at, read, type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            notification.user_id,
            notification.title,
            notification.body,
            notification.icon,
            json.dumps(notification.data),
            notification.created_at,
            notification.read,
            notification.type
        )
    )
    
    notification.id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return notification


def get_user_notifications(
    user_id: str,
    unread_only: bool = False,
    limit: int = 50
) -> List[Notification]:
    """
    Obtiene notificaciones de un usuario.
    
    Args:
        user_id: ID del usuario
        unread_only: Si True, solo no leídas
        limit: Máximo de notificaciones
    
    Returns:
        Lista de notificaciones
    """
    init_notifications_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM notifications WHERE user_id = ?"
    params = [user_id]
    
    if unread_only:
        query += " AND read = 0"
    
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    notifications = []
    for row in rows:
        notification = Notification(
            id=row['id'],
            user_id=row['user_id'],
            title=row['title'],
            body=row['body'],
            icon=row['icon'],
            data=json.loads(row['data']),
            created_at=row['created_at'],
            read=bool(row['read']),
            type=row['type']
        )
        notifications.append(notification)
    
    conn.close()
    return notifications


def mark_notification_read(notification_id: int) -> bool:
    """Marca una notificación como leída."""
    init_notifications_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE notifications SET read = 1 WHERE id = ?",
        (notification_id,)
    )
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def mark_all_read(user_id: str) -> int:
    """Marca todas las notificaciones de un usuario como leídas."""
    init_notifications_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE notifications SET read = 1 WHERE user_id = ?",
        (user_id,)
    )
    
    count = cursor.rowcount
    conn.commit()
    conn.close()
    
    return count


def delete_notification(notification_id: int) -> bool:
    """Elimina una notificación."""
    init_notifications_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def get_unread_count(user_id: str) -> int:
    """Obtiene el conteo de notificaciones no leídas."""
    init_notifications_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read = 0",
        (user_id,)
    )
    
    count = cursor.fetchone()[0]
    conn.close()
    
    return count


# ═══════════════════════════════════════════════════
#  Funciones de conveniencia para notificaciones comunes
# ═══════════════════════════════════════════════════

def notify_scan_complete(user_id: str, file_name: str, confidence: float):
    """Notifica que un escaneo se completó."""
    return create_notification(
        user_id=user_id,
        title="Escaneo completado",
        body=f"El documento '{file_name}' fue procesado exitosamente (confianza: {confidence:.0%})",
        icon="✅",
        data={"type": "scan_complete", "file_name": file_name, "confidence": confidence},
        notification_type="success"
    )


def notify_sync_complete(user_id: str, synced_count: int):
    """Notifica que la sincronización se completó."""
    return create_notification(
        user_id=user_id,
        title="Sincronización completada",
        body=f"{synced_count} documentos fueron sincronizados con la nube",
        icon="☁️",
        data={"type": "sync_complete", "count": synced_count},
        notification_type="success"
    )


def notify_error(user_id: str, error_message: str):
    """Notifica un error."""
    return create_notification(
        user_id=user_id,
        title="Error",
        body=error_message,
        icon="❌",
        data={"type": "error"},
        notification_type="error"
    )


def notify_warning(user_id: str, warning_message: str):
    """Notifica una advertencia."""
    return create_notification(
        user_id=user_id,
        title="Advertencia",
        body=warning_message,
        icon="⚠️",
        data={"type": "warning"},
        notification_type="warning"
    )
