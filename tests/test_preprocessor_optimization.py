"""
Test de Optimización de ImagePreprocessor
========================================
Verifica si la optimización redujo el tiempo de procesamiento.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import time


def test_preprocessor_performance():
    """Prueba el rendimiento del ImagePreprocessor optimizado."""
    print("=" * 60)
    print("TEST: Optimización de ImagePreprocessor")
    print("=" * 60)
    
    try:
        from core.image_preprocessor import ImagePreprocessor
        
        # Crear imagen de prueba
        img = np.random.randint(0, 255, (1000, 800, 3), dtype=np.uint8)
        
        preprocessor = ImagePreprocessor()
        
        # Medir tiempo
        start = time.time()
        for _ in range(10):
            processed = preprocessor.process(img)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 10
        
        print(f"\nTiempo promedio: {avg_time:.2f}ms (10 iteraciones)")
        print(f"Shape original: {img.shape}")
        print(f"Shape procesado: {processed.shape}")
        
        if avg_time < 2000:
            print(f"\n[SUCCESS] Optimización exitosa: {avg_time:.2f}ms < 2000ms")
            return True
        else:
            print(f"\n[WARNING] Aún lento: {avg_time:.2f}ms > 2000ms")
            return False
            
    except Exception as e:
        print(f"\n[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_preprocessor_performance()
    exit(0 if success else 1)
