"""
Sistema de Notificaciones OCR
=============================
Sistema de notificaciones para alertas de calidad.

Funcionalidades:
  - Notificaciones de calidad baja
  - Alertas de errores de validación
  - Notificaciones de rendimiento
  - Soporte para múltiples canales (email, webhook, console)
"""

import json
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import os


class NotificationLevel(Enum):
    """Nivel de notificación."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannel(Enum):
    """Canal de notificación."""
    CONSOLE = "console"
    EMAIL = "email"
    WEBHOOK = "webhook"
    FILE = "file"


@dataclass
class Notification:
    """Notificación del sistema."""
    level: NotificationLevel
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict = field(default_factory=dict)
    channels: List[NotificationChannel] = field(default_factory=lambda: [NotificationChannel.CONSOLE])


class NotificationSystem:
    """
    Sistema de notificaciones para OCR.
    
    Envía alertas sobre calidad, errores y rendimiento.
    """
    
    def __init__(self, config_path: str = None):
        """
        Args:
            config_path: Ruta del archivo de configuración (opcional)
        """
        self._config = self._load_config(config_path)
        self._notifications: List[Notification] = []
        self._handlers: Dict[NotificationChannel, Callable] = {
            NotificationChannel.CONSOLE: self._console_handler,
            NotificationChannel.FILE: self._file_handler,
            NotificationChannel.EMAIL: self._email_handler,
            NotificationChannel.WEBHOOK: self._webhook_handler
        }
    
    def _load_config(self, config_path: str) -> Dict:
        """Carga configuración desde archivo."""
        default_config = {
            'enabled': True,
            'channels': ['console'],
            'thresholds': {
                'confidence_warning': 0.7,
                'confidence_error': 0.5,
                'processing_time_warning': 3000,  # ms
                'processing_time_error': 5000
            },
            'email': {
                'enabled': False,
                'smtp_server': '',
                'smtp_port': 587,
                'username': '',
                'password': '',
                'from_address': '',
                'to_addresses': []
            },
            'webhook': {
                'enabled': False,
                'url': ''
            },
            'file': {
                'enabled': True,
                'path': 'data/notifications.log'
            }
        }
        
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception as e:
                print(f"[WARN] Error cargando configuración: {e}")
        
        return default_config
    
    def notify(self, notification: Notification):
        """
        Envía una notificación.
        
        Args:
            notification: Notificación a enviar
        """
        if not self._config.get('enabled', True):
            return
        
        self._notifications.append(notification)
        
        # Enviar a cada canal configurado
        for channel in notification.channels:
            if channel.value in self._config.get('channels', ['console']):
                handler = self._handlers.get(channel)
                if handler:
                    try:
                        handler(notification)
                    except Exception as e:
                        print(f"[ERROR] Error enviando notificación a {channel.value}: {e}")
    
    def notify_low_confidence(self, confidence: float, metadata: Dict = None):
        """Notifica confianza baja."""
        # Asegurar que confidence sea un float
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            # Si no se puede convertir, usar valor por defecto
            confidence = 0.0
        
        thresholds = self._config.get('thresholds', {})
        
        if confidence < thresholds.get('confidence_error', 0.5):
            level = NotificationLevel.ERROR
            message = f"Confianza OCR crítica: {confidence:.2f}"
        elif confidence < thresholds.get('confidence_warning', 0.7):
            level = NotificationLevel.WARNING
            message = f"Confianza OCR baja: {confidence:.2f}"
        else:
            return
        
        notification = Notification(
            level=level,
            message=message,
            metadata=metadata or {'confidence': confidence}
        )
        self.notify(notification)
    
    def notify_slow_processing(self, processing_time_ms: float, metadata: Dict = None):
        """Notifica procesamiento lento."""
        thresholds = self._config.get('thresholds', {})
        
        if processing_time_ms > thresholds.get('processing_time_error', 5000):
            level = NotificationLevel.ERROR
            message = f"Procesamiento muy lento: {processing_time_ms:.2f}ms"
        elif processing_time_ms > thresholds.get('processing_time_warning', 3000):
            level = NotificationLevel.WARNING
            message = f"Procesamiento lento: {processing_time_ms:.2f}ms"
        else:
            return
        
        notification = Notification(
            level=level,
            message=message,
            metadata=metadata or {'processing_time_ms': processing_time_ms}
        )
        self.notify(notification)
    
    def notify_validation_error(self, errors: List[str], metadata: Dict = None):
        """Notifica errores de validación."""
        if not errors:
            return
        
        level = NotificationLevel.ERROR if len(errors) > 3 else NotificationLevel.WARNING
        message = f"Errores de validación: {len(errors)} errores"
        
        notification = Notification(
            level=level,
            message=message,
            metadata=metadata or {'errors': errors}
        )
        self.notify(notification)
    
    def notify_system_status(self, status: str, metadata: Dict = None):
        """Notifica estado del sistema."""
        level = NotificationLevel.INFO
        message = f"Estado del sistema: {status}"
        
        notification = Notification(
            level=level,
            message=message,
            metadata=metadata or {'status': status}
        )
        self.notify(notification)
    
    def _console_handler(self, notification: Notification):
        """Manejador de notificaciones por consola."""
        level_colors = {
            NotificationLevel.INFO: '\033[94m',    # Azul
            NotificationLevel.WARNING: '\033[93m', # Amarillo
            NotificationLevel.ERROR: '\033[91m',    # Rojo
            NotificationLevel.CRITICAL: '\033[95m'  # Magenta
        }
        reset_color = '\033[0m'
        
        color = level_colors.get(notification.level, '')
        timestamp = notification.timestamp
        message = notification.message
        
        print(f"{color}[{notification.level.value.upper()}] {timestamp} - {message}{reset_color}")
    
    def _file_handler(self, notification: Notification):
        """Manejador de notificaciones por archivo."""
        file_config = self._config.get('file', {})
        if not file_config.get('enabled', True):
            return
        
        file_path = file_config.get('path', 'data/notifications.log')
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'a', encoding='utf-8') as f:
            log_entry = f"[{notification.level.value.upper()}] {notification.timestamp} - {notification.message}\n"
            f.write(log_entry)
    
    def _email_handler(self, notification: Notification):
        """Manejador de notificaciones por email."""
        email_config = self._config.get('email', {})
        if not email_config.get('enabled', False):
            return
        
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart()
            msg['From'] = email_config.get('from_address', '')
            msg['To'] = ', '.join(email_config.get('to_addresses', []))
            msg['Subject'] = f"[OCR {notification.level.value.upper()}] {notification.message}"
            
            body = f"""
            Nivel: {notification.level.value}
            Mensaje: {notification.message}
            Timestamp: {notification.timestamp}
            Metadata: {json.dumps(notification.metadata, indent=2)}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(
                email_config.get('smtp_server', ''),
                email_config.get('smtp_port', 587)
            )
            server.starttls()
            server.login(
                email_config.get('username', ''),
                email_config.get('password', '')
            )
            server.send_message(msg)
            server.quit()
            
        except Exception as e:
            print(f"[ERROR] Error enviando email: {e}")
    
    def _webhook_handler(self, notification: Notification):
        """Manejador de notificaciones por webhook."""
        webhook_config = self._config.get('webhook', {})
        if not webhook_config.get('enabled', False):
            return
        
        try:
            import requests
            
            url = webhook_config.get('url', '')
            payload = {
                'level': notification.level.value,
                'message': notification.message,
                'timestamp': notification.timestamp,
                'metadata': notification.metadata
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
        except Exception as e:
            print(f"[ERROR] Error enviando webhook: {e}")
    
    def get_notifications(self, level: NotificationLevel = None) -> List[Notification]:
        """
        Retorna las notificaciones enviadas.
        
        Args:
            level: Filtrar por nivel (opcional)
            
        Returns:
            Lista de notificaciones
        """
        if level:
            return [n for n in self._notifications if n.level == level]
        return self._notifications.copy()
    
    def clear_notifications(self):
        """Limpia el historial de notificaciones."""
        self._notifications.clear()


def notify_ocr_quality(confidence: float, processing_time_ms: float, errors: List[str] = None):
    """
    Función de conveniencia para notificar calidad OCR.
    
    Args:
        confidence: Confianza OCR
        processing_time_ms: Tiempo de procesamiento en ms
        errors: Lista de errores de validación (opcional)
    """
    system = NotificationSystem()
    
    # Notificar confianza
    system.notify_low_confidence(confidence)
    
    # Notificar tiempo de procesamiento
    system.notify_slow_processing(processing_time_ms)
    
    # Notificar errores de validación
    if errors:
        system.notify_validation_error(errors)
