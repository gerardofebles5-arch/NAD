"""
NAD Scanner — Corrections Sync via Supabase
=============================================
Sincroniza las correcciones de OCR entre todos los usuarios
a través de Supabase. Cada usuario se beneficia de las correcciones
de los demás.

Flujo:
  1. Usuario A corrige un campo → POST /correct
  2. FormatLearner.correct_field() → guarda localmente
  3. SupabaseSync.push_correction() → INSERT en Supabase
  4. Usuario B inicia sesión → FormatLearner.__init__()
  5. SupabaseSync.pull_corrections() → SELECT de Supabase
  6. SupabaseSync.merge_into_learner() → apply_corrections_to_fields()

Tabla Supabase:
  ocr_corrections (id, user_id, field_name, wrong_value,
                   correct_value, created_at, updated_at)

RLS:
  - Todos los usuarios autenticados pueden SELECT (leer correcciones)
  - Cada usuario solo puede INSERT sus propias correcciones
  - UPDATE/DELETE solo para superadmin
"""

import hashlib
import json
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import defaultdict

from utils.config import CONFIG


# ═══════════════════════════════════════════════════════════════
#  UTILIDADES (standalone para evitar circular import con format_learner)
# ═══════════════════════════════════════════════════════════════

def _normalize_text(t: str) -> str:
    """Normaliza texto para matching."""
    if not t:
        return ""
    t = t.lower().strip()
    t = t.replace('\xe1', 'a').replace('\xe9', 'e')
    t = t.replace('\xed', 'i').replace('\xf3', 'o')
    t = t.replace('\xfa', 'u').replace('\xfc', 'u')
    t = t.replace('\xf1', 'n')
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# Import opcional de Supabase
_HAS_SUPABASE = False
_HAS_REQUESTS = False
_supabase_client: Any = None

try:
    from supabase import create_client, Client
    _HAS_SUPABASE = True
except ImportError:
    pass

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════
#  CONSTANTES
# ═══════════════════════════════════════════════════════════════

# Máximo de correcciones a descargar por sync
MAX_CORRECTIONS_PER_SYNC = 5000

# Nombre del canal Realtime en Supabase
REALTIME_CHANNEL_NAME = "ocr-corrections-realtime"

# Intervalo de reconexión (segundos) si la suscripción se cae
REALTIME_RECONNECT_INTERVAL = 5

# Hash para deduplicación
def _correction_hash(field_name: str, wrong_value: str) -> str:
    """Hash único para una corrección (field_name + wrong_value normalizado)."""
    key = f"{field_name.lower().strip()}:{_normalize_text(wrong_value)}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()


# ═══════════════════════════════════════════════════════════════
#  SupabaseSync — Sincronización de correcciones
# ═══════════════════════════════════════════════════════════════

class SupabaseSync:
    """
    Sincroniza correcciones de OCR con Supabase.

    Uso:
        sync = SupabaseSync()

        # Enviar corrección
        sync.push_correction("total", "13.920,00", "14.000,00", user_id="...")

        # Descargar correcciones de otros usuarios
        remote = sync.pull_corrections()

        # Fusionar en FormatLearner
        sync.merge_into_learner(learner, remote)
    """

    def __init__(self):
        self._client: Optional[Any] = None
        self._connected = False
        self._last_sync: Optional[datetime] = None

        # Cache local de correcciones remotas
        self._remote_corrections: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._remote_count: int = 0

        # ── Realtime subscription ──
        self._realtime_sub: Optional[Any] = None
        self._realtime_thread: Optional[threading.Thread] = None
        self._realtime_active = False
        self._realtime_learner: Any = None
        self._realtime_callback: Optional[Callable[[str, str, str], None]] = None
        self._save_lock: threading.Lock = threading.Lock()

        # Inicializar conexión si está configurada
        if CONFIG.supabase.sync_enabled and CONFIG.supabase.url and CONFIG.supabase.anon_key:
            self._connect()

    def _connect(self) -> bool:
        """Conecta con Supabase."""
        global _supabase_client
        if not _HAS_SUPABASE:
            print("  [SupabaseSync] supabase-py no instalado. pip install supabase")
            return False
        try:
            if _supabase_client is None:
                _supabase_client = create_client(
                    CONFIG.supabase.url,
                    CONFIG.supabase.anon_key,
                )
            self._client = _supabase_client
            self._connected = True
            return True
        except Exception as e:
            print(f"  [SupabaseSync] Error de conexion: {e}")
            return False

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Push ──

    def push_correction(
        self,
        field_name: str,
        wrong_value: str,
        correct_value: str,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> bool:
        """
        Envía una corrección a Supabase.

        Args:
            field_name: Nombre del campo.
            wrong_value: Valor incorrecto.
            correct_value: Valor correcto.
            user_id: ID del usuario (opcional, usa 'system' si no se provee).
            user_email: Email del usuario (opcional, permite a los admins
                        identificar quién corrigió qué campo).

        Returns:
            True si se envió correctamente.
        """
        if not self._connected and not self._connect():
            return False

        uid = user_id or "system"
        uemail = user_email or ""
        corr_hash = _correction_hash(field_name, wrong_value)

        try:
            # Verificar si ya existe (por hash)
            existing = self._client.table(CONFIG.supabase.corrections_table) \
                .select("id") \
                .eq("correction_hash", corr_hash) \
                .limit(1) \
                .execute()

            # Si no existe o si el valor correcto es diferente, upsert
            if existing.data and len(existing.data) > 0:
                # Ya existe esta corrección: verificar si el valor correcto cambió
                existing_id = existing.data[0]["id"]
                update_data: Dict[str, Any] = {
                    "correct_value": correct_value,
                    "user_id": uid,
                    "updated_at": datetime.utcnow().isoformat(),
                }
                if uemail:
                    update_data["user_email"] = uemail
                self._client.table(CONFIG.supabase.corrections_table) \
                    .update(update_data) \
                    .eq("id", existing_id) \
                    .execute()
            else:
                # Nueva corrección
                insert_data: Dict[str, Any] = {
                    "correction_hash": corr_hash,
                    "user_id": uid,
                    "field_name": field_name,
                    "wrong_value": wrong_value,
                    "correct_value": correct_value,
                    "user_email": uemail,
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                self._client.table(CONFIG.supabase.corrections_table) \
                    .insert(insert_data) \
                    .execute()

            self._last_sync = datetime.utcnow()
            email_suffix = f" ({uemail})" if uemail else ""
            print(f"  [SupabaseSync] Push: {field_name} '{wrong_value}' -> '{correct_value}'{email_suffix}")
            return True

        except Exception as e:
            print(f"  [SupabaseSync] Error push: {e}")
            return False

    # ── Pull ──

    def pull_corrections(
        self,
        since: Optional[str] = None,
        limit: int = MAX_CORRECTIONS_PER_SYNC,
    ) -> List[Dict[str, Any]]:
        """
        Descarga correcciones de Supabase.

        Args:
            since: Filtro ISO datetime (solo correcciones más recientes).
            limit: Máximo de registros.

        Returns:
            Lista de dicts con correcciones.
        """
        if not self._connected and not self._connect():
            return []

        try:
            query = self._client.table(CONFIG.supabase.corrections_table) \
                .select("*") \
                .order("created_at", desc=True) \
                .limit(limit)

            if since:
                query = query.gte("created_at", since)

            result = query.execute()

            if result.data:
                self._remote_count = len(result.data)
                self._last_sync = datetime.utcnow()
                print(f"  [SupabaseSync] Pull: {len(result.data)} correcciones descargadas")
                return result.data
            return []

        except Exception as e:
            print(f"  [SupabaseSync] Error pull: {e}")
            return []

    # ── Merge ──

    def merge_into_learner(
        self,
        learner: Any,
        remote_corrections: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Fusiona correcciones remotas en un FormatLearner local.

        Para cada corrección remota:
        - Si el campo existe en el learner local, la agrega.
        - Si ya existe la misma corrección (mismo wrong_value), la omite.
        - Si hay conflicto (mismo wrong_value, diferente correct_value),
          la corrección local tiene prioridad.

        A diferencia de merge_into_learner v1, esta versión NO llama a
        learner.correct_field() (que hace _save() + push_to_cloud por cada
        corrección). En su lugar, modifica directamente los dicts internos
        del learner y llama a _save() una sola vez al final.

        Thread safety: usa el mismo lock que Realtime para evitar
        corrupción del pickle por escrituras concurrentes.

        Args:
            learner: Instancia de FormatLearner.
            remote_corrections: Lista de correcciones (opcional, hace pull si es None).

        Returns:
            Número de correcciones fusionadas.
        """
        if remote_corrections is None:
            remote_corrections = self.pull_corrections()

        if not remote_corrections:
            return 0

        merged = 0
        with self._save_lock:
            existing = learner.get_corrections()

            for corr in remote_corrections:
                field_name = corr.get("field_name", "").strip()
                wrong_value = corr.get("wrong_value", "").strip()
                correct_value = corr.get("correct_value", "").strip()

                if not field_name or not correct_value:
                    continue

                # Verificar si ya existe localmente
                if field_name in existing:
                    wrong_norm = _normalize_text(wrong_value)
                    if wrong_norm in existing[field_name]:
                        continue  # Ya se registró

                # Registrar directamente en el learner (sin _save() ni push_to_cloud)
                wrong_norm = _normalize_text(wrong_value)
                learner.corrections[field_name][wrong_norm] = correct_value
                learner._correction_counts[field_name] += 1
                self._remote_corrections[field_name][wrong_norm] = correct_value
                merged += 1

            if merged > 0:
                # Guardar una sola vez al final
                # learner._save() ya tiene su propio try/except interno
                learner._save()
                print(f"  [SupabaseSync] Merge: {merged} correcciones fusionadas en learner (batch save)")

        return merged

    # ── Realtime subscription ──

    def _apply_correction_payload(
        self,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Procesa un payload de Realtime y aplica la corrección
        al FormatLearner registrado (si existe).

        Args:
            payload: Payload del evento postgres_changes.
                     Contiene { event_type, new, old, schema, table }.

        Returns:
            True si se aplicó correctamente.
        """
        try:
            event_type = payload.get("event_type", "").lower()
            if event_type not in ("insert", "update"):
                return False

            new_record = payload.get("new", {})
            if not new_record:
                return False

            field_name = str(new_record.get("field_name", "")).strip()
            wrong_value = str(new_record.get("wrong_value", "")).strip()
            correct_value = str(new_record.get("correct_value", "")).strip()

            if not field_name or not correct_value:
                return False

            # Aplicar directamente al learner registrado
            # Thread safety: el lock de _save() protege la escritura
            # concurrente del pickle desde el hilo de Realtime y el principal
            if self._realtime_learner is not None:
                with self._save_lock:
                    existing = self._realtime_learner.get_corrections()
                    wrong_norm = _normalize_text(wrong_value)

                    if field_name not in existing or wrong_norm not in existing[field_name]:
                        self._realtime_learner._corrections[field_name][wrong_norm] = correct_value
                        self._realtime_learner._correction_counts[field_name] += 1
                        self._realtime_learner._save()
                        self._remote_corrections[field_name][wrong_norm] = correct_value

            # Notificar callback externo si está registrado
            if self._realtime_callback is not None:
                user_email = str(new_record.get("user_email", "")).strip()
                try:
                    self._realtime_callback(field_name, wrong_value, correct_value, user_email)
                except Exception:
                    pass

            user_email_val = str(new_record.get("user_email", "")).strip()
            email_suffix = f" ({user_email_val})" if user_email_val else ""
            print(f"  \u26a1 [SupabaseSync] Realtime: {field_name} "
                  f"'{wrong_value}' -> '{correct_value}'{email_suffix}")
            return True

        except Exception as e:
            print(f"  [SupabaseSync] Error processing Realtime payload: {e}")
            return False

    def _realtime_listener_loop(self):
        """
        Bucle principal del hilo de Realtime.
        Mantiene la suscripción activa con reconexión automática.
        """
        while self._realtime_active:
            try:
                if not self._connected and not self._connect():
                    time.sleep(REALTIME_RECONNECT_INTERVAL)
                    continue

                # Crear canal Realtime
                channel = self._client.channel(REALTIME_CHANNEL_NAME)

                def on_change(payload):
                    if self._realtime_active:
                        self._apply_correction_payload(payload)

                channel.on(
                    "postgres_changes",
                    {
                        "event": "*",
                        "schema": "public",
                        "table": CONFIG.supabase.corrections_table,
                    },
                    on_change,
                )

                # subscribe() es síncrono en supabase-py
                channel.subscribe()
                self._realtime_sub = channel
                self._realtime_active = True
                print("  \u26a1 [SupabaseSync] Realtime suscrito a ocr_corrections")

                # Mantener el hilo vivo mientras la suscripción esté activa
                # channel.subscribe() ya es bloqueante, pero agregamos un
                # loop de keepalive por si la implementación retorna rápido
                while self._realtime_active:
                    time.sleep(1)

            except Exception as e:
                if self._realtime_active:
                    # Limpiar sub anterior antes de reconectar
                    if self._realtime_sub is not None:
                        try:
                            self._realtime_sub.unsubscribe()
                        except Exception:
                            pass
                        self._realtime_sub = None
                    print(f"  [SupabaseSync] Realtime error: {e}. "
                          f"Reconectando en {REALTIME_RECONNECT_INTERVAL}s...")
                    time.sleep(REALTIME_RECONNECT_INTERVAL)

    def subscribe_realtime(
        self,
        learner: Any = None,
        callback: Optional[Callable[[str, str, str], None]] = None,
    ) -> bool:
        """
        Inicia la suscripción Realtime a ocr_corrections en un hilo
        de fondo. Las correcciones se aplican en vivo al FormatLearner
        sin necesidad de reiniciar ni hacer pull.

        Args:
            learner: Instancia de FormatLearner para aplicar correcciones
                     automáticamente.
            callback: Función opcional (field_name, wrong_value, correct_value)
                      que se llama por cada corrección recibida.

        Returns:
            True si se inició la suscripción.
        """
        if self._realtime_active:
            print("  [SupabaseSync] Realtime ya está activo")
            return True

        self._realtime_learner = learner
        self._realtime_callback = callback
        self._realtime_active = True

        self._realtime_thread = threading.Thread(
            target=self._realtime_listener_loop,
            daemon=True,
            name="supabase-realtime",
        )
        self._realtime_thread.start()
        print(f"  \u26a1 [SupabaseSync] Realtime iniciado (thread={self._realtime_thread.name})")
        return True

    def unsubscribe_realtime(self):
        """
        Detiene la suscripción Realtime y limpia el hilo.
        """
        self._realtime_active = False
        if self._realtime_sub is not None:
            try:
                self._realtime_sub.unsubscribe()
            except Exception:
                pass
            self._realtime_sub = None
        if self._realtime_thread is not None:
            # No hacer join() en daemon thread — se limpia solo al salir
            self._realtime_thread = None
        self._realtime_learner = None
        self._realtime_callback = None
        print("  [SupabaseSync] Realtime detenido")

    @property
    def realtime_active(self) -> bool:
        return self._realtime_active

    # ── Stats ──

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas de sincronización."""
        return {
            "connected": self._connected,
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "remote_count": self._remote_count,
            "local_remote_cache": sum(
                len(v) for v in self._remote_corrections.values()
            ),
            "realtime_active": self._realtime_active,
            "realtime_learner_bound": self._realtime_learner is not None,
        }


# ═══════════════════════════════════════════════════════════════
#  Función de alto nivel
# ═══════════════════════════════════════════════════════════════

_global_sync: Optional[SupabaseSync] = None


def get_supabase_sync() -> SupabaseSync:
    """Retorna la instancia global de SupabaseSync."""
    global _global_sync
    if _global_sync is None:
        _global_sync = SupabaseSync()
    return _global_sync


def push_correction_to_cloud(
    field_name: str,
    wrong_value: str,
    correct_value: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> bool:
    """Función de alto nivel: envía una corrección a Supabase."""
    if not CONFIG.supabase.sync_enabled:
        return False
    sync = get_supabase_sync()
    return sync.push_correction(field_name, wrong_value, correct_value, user_id, user_email)


def pull_corrections_from_cloud() -> List[Dict[str, Any]]:
    """Función de alto nivel: descarga correcciones de Supabase."""
    if not CONFIG.supabase.sync_enabled:
        return []
    sync = get_supabase_sync()
    return sync.pull_corrections()


def merge_corrections_from_cloud(learner: Any) -> int:
    """Función de alto nivel: fusiona correcciones remotas en el learner."""
    if not CONFIG.supabase.sync_enabled:
        return 0
    sync = get_supabase_sync()
    return sync.merge_into_learner(learner)


def subscribe_realtime_to_learner(
    learner: Any,
    callback: Optional[Callable[[str, str, str], None]] = None,
) -> bool:
    """
    Función de alto nivel: activa Realtime y vincula un FormatLearner
    para recibir correcciones en vivo.

    Args:
        learner: Instancia de FormatLearner.
        callback: Callback opcional.

    Returns:
        True si se suscribió correctamente.
    """
    if not CONFIG.supabase.sync_enabled:
        return False
    sync = get_supabase_sync()
    return sync.subscribe_realtime(learner=learner, callback=callback)


def unsubscribe_realtime() -> bool:
    """
    Función de alto nivel: detiene Realtime.
    """
    if not CONFIG.supabase.sync_enabled:
        return False
    sync = get_supabase_sync()
    sync.unsubscribe_realtime()
    return True


if __name__ == "__main__":
    # Test básico
    print("=" * 60)
    print("  Supabase Corrections Sync Test")
    print("=" * 60)

    print(f"\nSupabase client: {'DISPONIBLE' if _HAS_SUPABASE else 'NO DISPONIBLE'}")
    print(f"Requests: {'DISPONIBLE' if _HAS_REQUESTS else 'NO DISPONIBLE'}")
    print(f"Sync enabled: {CONFIG.supabase.sync_enabled}")
    print(f"Supabase URL: {CONFIG.supabase.url}")
    print(f"Anon key set: {bool(CONFIG.supabase.anon_key)}")

    if CONFIG.supabase.sync_enabled and CONFIG.supabase.anon_key:
        sync = get_supabase_sync()
        print(f"Conectado: {sync.connected}")
        if sync.connected:
            print("Estadisticas:", sync.get_stats())
    else:
        print("\n⚠  Configura SUPABASE_URL y SUPABASE_ANON_KEY en utils/config.py")
        print("   para probar la sincronización real.")

    print("\nOK")
