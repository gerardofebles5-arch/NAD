#!/usr/bin/env python3
"""Script para probar los nuevos endpoints de Phase 1"""

import requests
import json
import urllib3

# Desactivar advertencias SSL para el certificado adhoc
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://127.0.0.1:5000"

def test_health():
    """Prueba endpoint /health"""
    print("\n=== Testing /health ===")
    try:
        response = requests.get(f"{BASE_URL}/health", verify=False, timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_sync_status():
    """Prueba endpoint /sync/status"""
    print("\n=== Testing /sync/status ===")
    try:
        response = requests.get(f"{BASE_URL}/sync/status", verify=False, timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_auth_validate():
    """Prueba endpoint /auth/validate con token inválido"""
    print("\n=== Testing /auth/validate (invalid token) ===")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/validate",
            json={"token": "invalid_token"},
            verify=False,
            timeout=5
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 401  # Debe fallar con token inválido
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_auth_user():
    """Prueba endpoint /auth/user sin autenticación"""
    print("\n=== Testing /auth/user (no auth) ===")
    try:
        response = requests.get(f"{BASE_URL}/auth/user", verify=False, timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print("Probando endpoints de Phase 1...")
    
    results = {
        "health": test_health(),
        "sync_status": test_sync_status(),
        "auth_validate": test_auth_validate(),
        "auth_user": test_auth_user(),
    }
    
    print("\n=== RESUMEN ===")
    for test, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test}: {status}")
    
    all_passed = all(results.values())
    print(f"\nResultado global: {'✅ TODAS LAS PRUEBAS PASARON' if all_passed else '❌ ALGUNAS PRUEBAS FALLARON'}")
