"""
Supabase Client - Conexión a Supabase
=====================================
Cliente para interactuar con Supabase (Postgres, Auth, Realtime).
"""
import os
from supabase import create_client

# Variables de entorno
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# Cliente global
supabase = None


def get_supabase_client():
    """
    Retorna el cliente Supabase inicializado.
    
    Returns:
        Cliente Supabase o None si no está configurado.
    """
    global supabase
    
    if supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            print("⚠️ Supabase no configurado: faltan variables SUPABASE_URL y SUPABASE_KEY")
            return None
        
        try:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            print("✅ Cliente Supabase inicializado")
        except Exception as e:
            print(f"❌ Error inicializando Supabase: {e}")
            return None
    
    return supabase


def is_configured() -> bool:
    """Verifica si Supabase está configurado."""
    return bool(SUPABASE_URL and SUPABASE_KEY)
