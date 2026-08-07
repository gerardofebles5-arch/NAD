"""
Bloque 7 — Subida automática a Google Drive
=============================================
Autentica con OAuth 2.0, crea estructura de carpetas por año/mes,
y sube la imagen renderizada, el JSON de datos y un PDF de lote.

Fallback offline: guarda en cola local y reintenta cuando haya conexión.
"""

import os
import json
import time
import pickle
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.config import CONFIG


# ──────────────────────────────────────────────
#  Cliente Google Drive
# ──────────────────────────────────────────────
class GoogleDriveClient:
    """
    Cliente para la API de Google Drive v3.

    Autenticación:
    - Primera vez: requiere OAuth interactivo (abre navegador).
    - Después: usa token.json con refresh token para acceso desatendido.
    """

    def __init__(self, credentials_path: str = None, token_path: str = None):
        cfg = CONFIG.drive
        self.credentials_path = credentials_path or cfg.credentials_path
        self.token_path = token_path or cfg.token_path
        self.service = None
        self._root_id = None

    def authenticate(self) -> bool:
        """
        Autentica con Google Drive usando OAuth 2.0.

        Returns:
            True si la autenticación fue exitosa, False en caso contrario.
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            creds = None

            # Cargar token existente
            if os.path.exists(self.token_path):
                try:
                    creds = Credentials.from_authorized_user_file(
                        self.token_path, CONFIG.drive.scopes
                    )
                except Exception:
                    pass

            # Si no hay credenciales válidas, refrescar o autenticar
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                        print("  → Token refrescado automáticamente.")
                    except Exception as e:
                        print(f"  ⚠ Error al refrescar token: {e}")
                        print("  → Se requiere autenticación manual (una sola vez).")
                        creds = None

                if not creds:
                    # Verificar que credentials.json existe
                    if not os.path.exists(self.credentials_path):
                        print(f"\n  ⚠ No se encuentra '{self.credentials_path}'.")
                        print("  → Descargue el archivo desde Consola Google Cloud →")
                        print("    Credenciales → OAuth 2.0 → credentials.json")
                        print(f"  → Colóquelo en: {os.path.abspath(self.credentials_path)}\n")
                        return False

                    try:
                        flow = InstalledAppFlow.from_client_secrets_file(
                            self.credentials_path, CONFIG.drive.scopes
                        )
                        creds = flow.run_local_server(port=0)
                        print("  ✓ Autenticación exitosa.")
                    except Exception as e:
                        print(f"  ✗ Error de autenticación: {e}")
                        return False

                # Guardar token
                with open(self.token_path, "w") as f:
                    f.write(creds.to_json())
                print(f"  → Token guardado en {self.token_path}")

            # Construir servicio
            self.service = build("drive", "v3", credentials=creds)
            print("  ✓ Conectado a Google Drive API v3.")
            return True

        except ImportError as e:
            print(f"  ✗ Error de importación: {e}")
            print("  → Instale: pip install google-api-python-client google-auth-oauthlib")
            return False

    def _ensure_root_folder(self) -> Optional[str]:
        """
        Crea o recupera el ID de la carpeta raíz en Drive.

        Returns:
            ID de la carpeta raíz, o None si hay error.
        """
        if self._root_id:
            return self._root_id

        name = CONFIG.drive.root_folder_name

        # Buscar si ya existe
        query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = self.service.files().list(
            q=query, spaces="drive", fields="files(id, name)", pageSize=10
        ).execute()
        files = results.get("files", [])

        if files:
            self._root_id = files[0]["id"]
            print(f"  → Carpeta raíz encontrada: {name}")
        else:
            # Crear carpeta raíz
            metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            file = self.service.files().create(body=metadata, fields="id").execute()
            self._root_id = file["id"]
            print(f"  → Carpeta raíz creada: {name}")

        return self._root_id

    def _ensure_subfolder(self, parent_id: str, folder_name: str) -> Optional[str]:
        """
        Crea o recupera una subcarpeta.

        Args:
            parent_id: ID de la carpeta padre.
            folder_name: Nombre de la subcarpeta.

        Returns:
            ID de la subcarpeta.
        """
        query = (
            f"name='{folder_name}' and "
            f"'{parent_id}' in parents and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"trashed=false"
        )
        results = self.service.files().list(
            q=query, spaces="drive", fields="files(id, name)", pageSize=10
        ).execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        # Crear subcarpeta
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        file = self.service.files().create(body=metadata, fields="id").execute()
        return file["id"]

    def _get_folder_path(self) -> Tuple[Optional[str], str]:
        """
        Construye la ruta de carpetas Facturas_NAD_Auto / {AÑO} / {MES} /.

        Returns:
            (folder_id, ruta_local) donde folder_id es el ID de la carpeta MES.
        """
        now = datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")

        root_id = self._ensure_root_folder()
        if not root_id:
            return None, ""

        year_id = self._ensure_subfolder(root_id, year)
        month_id = self._ensure_subfolder(year_id, month) if year_id else None

        path = f"{CONFIG.drive.root_folder_name}/{year}/{month}"
        return month_id, path

    def upload_file(
        self,
        local_path: str,
        drive_folder_id: str,
        mime_type: str = "image/png",
    ) -> bool:
        """
        Sube un archivo a Google Drive.

        Args:
            local_path: Ruta local del archivo.
            drive_folder_id: ID de la carpeta destino en Drive.
            mime_type: Tipo MIME del archivo.

        Returns:
            True si la subida fue exitosa.
        """
        from googleapiclient.http import MediaFileUpload

        if not self.service:
            print("  ⚠ No autenticado. Llamando authenticate()...")
            if not self.authenticate():
                return False

        file_name = os.path.basename(local_path)
        metadata = {
            "name": file_name,
            "parents": [drive_folder_id],
        }

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        try:
            self.service.files().create(
                body=metadata, media_body=media, fields="id"
            ).execute()
            print(f"  ✓ Subido a Drive: {file_name}")
            return True
        except Exception as e:
            print(f"  ✗ Error al subir {file_name}: {e}")
            return False

    def upload_invoice_set(
        self,
        render_path: str,
        json_data: Dict,
        invoice_number: str,
        date_str: str,
    ) -> bool:
        """
        Sube el conjunto de archivos de una factura a Drive.

        Args:
            render_path: Ruta a la imagen renderizada PNG.
            json_data: Diccionario con datos extraídos.
            invoice_number: Número de factura.
            date_str: Fecha en formato DD-MM-AAAA.

        Returns:
            True si al menos la imagen se subió correctamente.
        """
        folder_id, drive_path = self._get_folder_path()
        if not folder_id:
            print(f"  ⚠ No se pudo crear/obtener la carpeta en Drive ({drive_path})")
            return False

        success = False
        drive_file_id = None

        # 1. Subir imagen renderizada
        if os.path.exists(render_path):
            if self.upload_file(render_path, folder_id, "image/png"):
                success = True
                # Obtener ID del archivo subido
                drive_file_id = self._get_file_id(render_path, folder_id)

        # 2. Subir JSON de datos
        json_filename = f"{invoice_number}_{date_str}.json"
        json_path = os.path.join(CONFIG.drive.local_queue_dir, json_filename)
        os.makedirs(CONFIG.drive.local_queue_dir, exist_ok=True)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        if self.upload_file(json_path, folder_id, "application/json"):
            success = True
            os.remove(json_path)  # Limpiar archivo temporal

        return success, drive_file_id
    
    def _get_file_id(self, local_path: str, folder_id: str) -> Optional[str]:
        """Obtiene el ID del archivo subido a Drive."""
        if not self.service:
            return None
        
        file_name = os.path.basename(local_path)
        try:
            results = self.service.files().list(
                q=f"name='{file_name}' and '{folder_id}' in parents",
                fields="files(id, name)",
                pageSize=1
            ).execute()
            
            files = results.get("files", [])
            if files:
                return files[0]["id"]
        except Exception as e:
            print(f"  ⚠ Error obteniendo file_id: {e}")
        
        return None

    def upload_queue(self) -> int:
        """
        Reintenta subir archivos pendientes en la cola local.

        Returns:
            Número de archivos subidos exitosamente.
        """
        queue_dir = Path(CONFIG.drive.local_queue_dir)
        if not queue_dir.exists():
            return 0

        uploaded = 0
        for item in queue_dir.iterdir():
            if item.is_file():
                # Intentar subir
                folder_id, _ = self._get_folder_path()
                if folder_id:
                    ext = item.suffix.lower()
                    mime_map = {
                        ".png": "image/png",
                        ".json": "application/json",
                        ".pdf": "application/pdf",
                    }
                    mime = mime_map.get(ext, "application/octet-stream")
                    if self.upload_file(str(item), folder_id, mime):
                        item.unlink()
                        uploaded += 1

        return uploaded


# ──────────────────────────────────────────────
#  Gestor de cola offline
# ──────────────────────────────────────────────
class OfflineQueueManager:
    """
    Gestiona la cola local de archivos pendientes de subir.
    Cuando no hay internet, los archivos se guardan localmente
    y se suben automáticamente cuando la conexión se restablece.
    """

    def __init__(self):
        self.queue_dir = Path(CONFIG.drive.local_queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, render_path: str, data: Dict, invoice_number: str, date_str: str):
        """
        Guarda archivos en la cola local para subida diferida.

        Args:
            render_path: Ruta de la imagen renderizada.
            data: Diccionario con datos extraídos.
            invoice_number: Número de factura.
            date_str: Fecha en formato DD-MM-AAAA.
        """
        timestamp = datetime.now().strftime("%H%M%S")

        # Copiar imagen
        img_dst = self.queue_dir / f"{invoice_number}_{date_str}_{timestamp}.png"
        if os.path.exists(render_path):
            import shutil
            shutil.copy2(render_path, img_dst)
            print(f"  → Encolado: {img_dst.name}")

        # Guardar JSON
        json_dst = self.queue_dir / f"{invoice_number}_{date_str}_{timestamp}.json"
        with open(json_dst, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  → Encolado: {json_dst.name}")

    def count_pending(self) -> int:
        """Número de archivos en cola."""
        if not self.queue_dir.exists():
            return 0
        return len(list(self.queue_dir.iterdir()))

    def has_pending(self) -> bool:
        """Verifica si hay archivos pendientes."""
        return self.count_pending() > 0


# ──────────────────────────────────────────────
#  Función de alto nivel
# ──────────────────────────────────────────────
def upload_to_drive(
    render_path: str,
    invoice_data: Dict,
    invoice_number: str,
    date_str: str,
) -> bool:
    """
    Sube los archivos de la factura a Google Drive.
    Si no hay conexión, los encola para subida diferida.

    Args:
        render_path: Ruta a la imagen renderizada.
        invoice_data: Diccionario con datos extraídos.
        invoice_number: Número de factura.
        date_str: Fecha en formato DD-MM-AAAA.

    Returns:
        True si se subió exitosamente (o se encoló).
    """
    client = GoogleDriveClient()
    queue_mgr = OfflineQueueManager()

    # Intentar autenticar y subir
    if client.authenticate():
        success = client.upload_invoice_set(
            render_path, invoice_data, invoice_number, date_str
        )
        if success:
            print("  ✓ Factura subida a Google Drive.")
            return True
        else:
            print("  ⚠ Subida parcial. Encolando pendientes...")
            queue_mgr.enqueue(render_path, invoice_data, invoice_number, date_str)
            return False
    else:
        print("  ⚠ Sin conexión a Drive. Encolando para subida diferida...")
        queue_mgr.enqueue(render_path, invoice_data, invoice_number, date_str)
        return False


def flush_queue() -> int:
    """
    Intenta subir todos los archivos pendientes en la cola.

    Returns:
        Número de archivos subidos.
    """
    client = GoogleDriveClient()
    if client.authenticate():
        uploaded = client.upload_queue()
        if uploaded > 0:
            print(f"  ✓ Cola vaciada: {uploaded} archivos subidos.")
        else:
            print("  → No hay archivos pendientes en la cola.")
        return uploaded
    return 0


if __name__ == "__main__":
    # Prueba rápida
    client = GoogleDriveClient()
    if client.authenticate():
        print("✓ Autenticación exitosa. Listo para subir archivos.")
    else:
        print("✗ No se pudo autenticar.")
