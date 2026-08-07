"""
OCR Backends — Implementaciones concretas
============================================
Backends que implementan OCRBackend para distintos motores:
  - PaddleBackend:      PaddleOCR estándar
  - PaddleVEBackend:    PaddleOCR + post-procesamiento Venezuela
  - TesseractBackend:   Tesseract OCR vía pytesseract
  - EasyOCRBackend:     EasyOCR (Python puro, funciona en plataformas gratuitas)
  - DocTRBackend:       docTR (Document Text Recognition) — opcional
  - SuryaBackend:       Surya OCR — opcional
"""

import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from utils.config import CONFIG
from ocr.backend_base import OCRBackend, BackendMetadata, WordResult


# ═══════════════════════════════════════════════════════════════
#  Constructor de PaddleOCR a prueba de versión
# ═══════════════════════════════════════════════════════════════
#
# PaddleOCR ha roto su firma de constructor entre versiones más de una
# vez (ej: 'use_gpu' fue removido en releases recientes a favor de
# 'device'; 'show_log' y 'use_angle_cls' también han cambiado de nombre
# en algunas versiones). Pasar un kwarg que la versión instalada no
# reconoce lanza TypeError/ValueError y tumba el backend completo — es
# justo lo que le pasó a un usuario real con "Unknown argument: use_gpu".
#
# En vez de hardcodear los nombres de parámetros, se introspecciona la
# firma REAL de PaddleOCR.__init__ (o de PaddleOCR() si usa **kwargs
# dinámicos con un dict de defaults) y solo se pasan los argumentos que
# esa instalación específica realmente acepta.

def _build_paddleocr_instance(_PaddleOCR):
    """
    Crea una instancia de PaddleOCR intentando pasar solo los kwargs que
    la versión instalada realmente soporta, con reintentos progresivos.
    """
    import inspect

    desired = {
        "lang": CONFIG.ocr.lang,
        "use_angle_cls": CONFIG.ocr.paddle_use_angle_cls,
        "use_textline_orientation": CONFIG.ocr.paddle_use_angle_cls,  # nombre nuevo en 3.x
        "show_log": False,
        "use_gpu": False,       # nombre viejo (<=2.x)
        "device": "cpu",        # nombre nuevo (3.x+)
        "enable_mkldnn": False,
    }

    # 1) Intentar filtrar por la firma real del constructor
    try:
        sig = inspect.signature(_PaddleOCR.__init__)
        valid_params = set(sig.parameters.keys())
        accepts_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if accepts_kwargs:
            # El constructor acepta **kwargs libres — probablemente valida
            # internamente, así que se intenta con todo y se cae al plan B
            # si falla.
            filtered = dict(desired)
        else:
            filtered = {k: v for k, v in desired.items() if k in valid_params}
        return _PaddleOCR(**filtered)
    except Exception as e1:
        pass

    # 2) Reintento progresivo: ir quitando argumentos de uno en uno hasta
    # que alguna combinación funcione (cubre el caso de que la
    # introspección de firma no fue confiable, ej. decoradores que
    # ocultan la firma real).
    candidate_kwargs = [
        {"lang": CONFIG.ocr.lang},
        {"lang": CONFIG.ocr.lang, "use_angle_cls": CONFIG.ocr.paddle_use_angle_cls},
        {"lang": CONFIG.ocr.lang, "device": "cpu"},
        {},
    ]
    last_err = None
    for kwargs in candidate_kwargs:
        try:
            return _PaddleOCR(**kwargs)
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("No se pudo inicializar PaddleOCR con ninguna combinación de argumentos")


def _run_paddle_inference(ocr_instance, image):
    """
    Ejecuta la inferencia de PaddleOCR sea cual sea la API que tenga la
    versión instalada, y siempre devuelve el resultado normalizado al
    formato clásico que el resto del código ya sabe parsear: una lista
    envolvente con una lista de líneas, cada línea [bbox_4_puntos,
    (texto, confianza)].

    PaddleOCR 3.x renombró el método principal de .ocr() a .predict() y
    cambió la forma del resultado (de listas anidadas a diccionarios con
    'rec_texts'/'rec_scores'/'rec_polys') — sin este adaptador, cualquier
    instalación en una versión nueva rompe con AttributeError en cuanto
    se intenta usar .ocr().
    """
    # 1) API clásica (PaddleOCR <=2.x): .ocr(image)
    if hasattr(ocr_instance, "ocr"):
        try:
            raw = ocr_instance.ocr(image)
            if raw:
                return raw
        except (AttributeError, TypeError):
            pass
        except Exception:
            pass

    # 2) API nueva (PaddleOCR 3.x): .predict(image)
    if hasattr(ocr_instance, "predict"):
        try:
            raw = ocr_instance.predict(image)
            return _normalize_paddle_predict_result(raw)
        except Exception:
            pass

    return []


def _normalize_paddle_predict_result(raw):
    """Convierte el resultado de .predict() (PaddleOCR 3.x) al formato
    clásico [[ [bbox, (texto, confianza)], ... ]] que usa el resto del código."""
    if not raw:
        return []
    lines = []
    for page in raw:
        try:
            texts = page.get("rec_texts") or page.get("texts") or []
            scores = page.get("rec_scores") or page.get("scores") or []
            polys = page.get("rec_polys") or page.get("dt_polys") or page.get("polys") or []
        except AttributeError:
            # por si 'page' no es dict-like sino un objeto con atributos
            texts = getattr(page, "rec_texts", []) or []
            scores = getattr(page, "rec_scores", []) or []
            polys = getattr(page, "rec_polys", None) or getattr(page, "dt_polys", []) or []
        for i, text in enumerate(texts):
            score = scores[i] if i < len(scores) else 0.5
            poly = polys[i] if i < len(polys) else [[0, 0], [0, 0], [0, 0], [0, 0]]
            # Asegurar que poly sean listas de [x,y] planas (a veces vienen como np.array)
            try:
                poly = [[float(pt[0]), float(pt[1])] for pt in poly]
            except Exception:
                poly = [[0, 0], [0, 0], [0, 0], [0, 0]]
            lines.append([poly, (str(text), float(score))])
    return [lines]


# ═══════════════════════════════════════════════════════════════
#  BACKEND 1: PaddleOCR Estándar
# ═══════════════════════════════════════════════════════════════

class PaddleBackend(OCRBackend):
    """
    Backend de PaddleOCR estándar.
    Reconocimiento multilingüe con soporte para 80+ idiomas.
    """

    def _build_metadata(self) -> BackendMetadata:
        available = False
        error = ""
        version = ""
        try:
            import paddleocr
            version = getattr(paddleocr, "__version__", "desconocida")
            available = True
        except ImportError:
            error = "paddleocr no instalado. pip install paddleocr paddlepaddle"
        return BackendMetadata(
            name="paddle",
            display_name="PaddleOCR",
            version=version,
            description="PaddleOCR estándar multilingüe",
            requires_gpu=False,
            languages=("es", "en", "pt", "fr", "de"),
            dependencies=("paddleocr", "paddlepaddle"),
            available=available,
            init_error=error,
        )

    def initialize(self):
        if self._initialized:
            return
        try:
            import os as _os
            _os.environ["FLAGS_oneDNN_enabled"] = "0"

            from paddleocr import PaddleOCR as _PaddleOCR
            self._ocr = _build_paddleocr_instance(_PaddleOCR)
            self._initialized = True
        except ImportError as e:
            self._metadata.available = False
            self._metadata.init_error = str(e)
            raise
        except Exception as e:
            # PaddleOCR cambia su firma de constructor entre versiones
            # (ej: 'use_gpu' fue removido en releases recientes en favor de
            # 'device'). _build_paddleocr_instance() ya introspecciona la
            # firma real e intenta evitar esto, pero si aun así falla,
            # se reporta como no disponible en vez de tumbar todo el
            # pipeline OCR — el sistema debe poder caer a otro backend.
            self._metadata.available = False
            self._metadata.init_error = f"Error inicializando PaddleOCR: {e}"
            raise

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        self.ensure_initialized()

        threshold = confidence_threshold if confidence_threshold is not None \
            else CONFIG.ocr.confidence_threshold

        results = _run_paddle_inference(self._ocr, image)
        if not results:
            return []

        if isinstance(results, list) and results and isinstance(results[0], list):
            lines = results[0]
        else:
            lines = results

        words = []
        for line in lines:
            if line is None:
                continue
            try:
                if len(line) == 3:
                    bbox, text, confidence = line
                elif len(line) == 2:
                    bbox, (text, confidence) = line
                else:
                    continue
            except (ValueError, TypeError):
                continue

            if not isinstance(confidence, (int, float)) or confidence < 0:
                continue
            if confidence < threshold:
                continue

            text = str(text).strip()
            if not text:
                continue

            x1 = float(min(p[0] for p in bbox))
            y1 = float(min(p[1] for p in bbox))
            x2 = float(max(p[0] for p in bbox))
            y2 = float(max(p[1] for p in bbox))

            words.append((text, (x1, y1, x2, y2), float(confidence)))

        words.sort(key=lambda w: (w[1][1], w[1][0]))
        return words


# ═══════════════════════════════════════════════════════════════
#  BACKEND 2: PaddleOCR + Post-procesamiento Venezuela
# ═══════════════════════════════════════════════════════════════

class PaddleVEBackend(OCRBackend):
    """
    Backend de PaddleOCR con post-procesamiento especializado
    para facturas venezolanas (RIF, IVA, montos, NCF).
    """

    def _build_metadata(self) -> BackendMetadata:
        available = False
        error = ""
        version = ""
        try:
            import paddleocr
            version = getattr(paddleocr, "__version__", "desconocida")
            available = True
        except ImportError:
            error = "paddleocr no instalado. pip install paddleocr paddlepaddle"
        return BackendMetadata(
            name="paddle_ve",
            display_name="PaddleOCR Venezuela",
            version=version,
            description="PaddleOCR con post-procesamiento VE: RIF, IVA, montos, NCF",
            requires_gpu=False,
            languages=("es",),
            dependencies=("paddleocr", "paddlepaddle"),
            available=available,
            init_error=error,
        )

    def initialize(self):
        if self._initialized:
            return
        try:
            from ocr.paddle_ve import PaddleOCRVEEngine
            self._ve_engine = PaddleOCRVEEngine(
                lang=CONFIG.ocr.lang,
                use_angle_cls=CONFIG.ocr.paddle_use_angle_cls,
            )
            self._initialized = True
        except ImportError as e:
            self._metadata.available = False
            self._metadata.init_error = str(e)
            raise

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        self.ensure_initialized()
        return self._ve_engine.recognize(image, confidence_threshold)

    def get_stats(self) -> Dict:
        if self._initialized:
            return self._ve_engine.get_stats()
        return {}

    def reset_stats(self):
        if self._initialized:
            self._ve_engine.reset_stats()


# ═══════════════════════════════════════════════════════════════
#  BACKEND 3: Tesseract OCR
# ═══════════════════════════════════════════════════════════════

class TesseractBackend(OCRBackend):
    """
    Backend de Tesseract OCR vía pytesseract.
    Requiere Tesseract instalado como binario del sistema.
    """

    def _build_metadata(self) -> BackendMetadata:
        available = False
        error = ""
        version = ""
        try:
            import pytesseract
            # Configurar ruta del binario desde CONFIG o variable de entorno
            cmd_path = CONFIG.ocr.tesseract_cmd or os.environ.get('TESSERACT_CMD', '')
            if cmd_path and cmd_path != 'tesseract' and os.path.isfile(cmd_path):
                pytesseract.pytesseract.tesseract_cmd = cmd_path
            elif os.environ.get('TESSERACT_CMD', ''):
                pytesseract.pytesseract.tesseract_cmd = os.environ['TESSERACT_CMD']
            try:
                version = pytesseract.get_tesseract_version()
                version = str(version)
                available = True
            except Exception:
                error = "Tesseract no instalado como binario del sistema"
        except ImportError:
            error = "pytesseract no instalado. pip install pytesseract"
        return BackendMetadata(
            name="tesseract",
            display_name="Tesseract OCR",
            version=version,
            description="Tesseract OCR vía pytesseract",
            requires_gpu=False,
            languages=("spa", "eng", "por", "fra", "deu"),
            dependencies=("pytesseract", "tesseract-binario"),
            available=available,
            init_error=error,
        )

    def initialize(self):
        if self._initialized:
            return
        try:
            import pytesseract
            # Configurar ruta del binario desde CONFIG o variable de entorno
            cmd_path = CONFIG.ocr.tesseract_cmd or os.environ.get('TESSERACT_CMD', '')
            if cmd_path and cmd_path != 'tesseract' and os.path.isfile(cmd_path):
                pytesseract.pytesseract.tesseract_cmd = cmd_path
            elif os.environ.get('TESSERACT_CMD', ''):
                pytesseract.pytesseract.tesseract_cmd = os.environ['TESSERACT_CMD']
            # Verificar que Tesseract realmente funciona
            pytesseract.get_tesseract_version()
            self._initialized = True
        except Exception as e:
            self._metadata.available = False
            self._metadata.init_error = str(e)
            raise

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        self.ensure_initialized()

        import pytesseract

        threshold = confidence_threshold if confidence_threshold is not None \
            else CONFIG.ocr.confidence_threshold

        # Mapear código de idioma de CONFIG a código Tesseract
        lang_map = {"es": "spa", "en": "eng", "pt": "por", "fr": "fra", "de": "deu"}
        tesseract_lang = lang_map.get(CONFIG.ocr.lang, CONFIG.ocr.lang)

        data = pytesseract.image_to_data(
            image,
            lang=tesseract_lang,
            output_type=pytesseract.Output.DICT,
            config="--psm 6 --oem 1",  # PSM 6: Assume a single uniform block of text, OEM 1: LSTM only
        )

        words = []
        n = len(data["text"])
        for i in range(n):
            text = str(data["text"][i]).strip()
            conf = int(data["conf"][i]) / 100.0 if data["conf"][i] != -1 else 0.0
            if text and conf >= threshold:
                x, y, w, h = (
                    data["left"][i], data["top"][i],
                    data["width"][i], data["height"][i],
                )
                words.append((text, (float(x), float(y), float(x + w), float(y + h)), float(conf)))

        words.sort(key=lambda w: (w[1][1], w[1][0]))
        return words


# ═══════════════════════════════════════════════════════════════
#  BACKEND 4: EasyOCR (Python puro, funciona en plataformas gratuitas)
# ═══════════════════════════════════════════════════════════════

_HAS_EASYOCR = False
try:
    import easyocr
    _HAS_EASYOCR = True
except ImportError:
    pass


class EasyOCRBackend(OCRBackend):
    """
    Backend de EasyOCR.
    Usa PyTorch para OCR, no requiere binarios del sistema.
    Ideal para deployment en plataformas gratuitas.
    """

    def _build_metadata(self) -> BackendMetadata:
        available = _HAS_EASYOCR
        error = "" if _HAS_EASYOCR else "easyocr no instalado. pip install easyocr"
        version = ""
        if _HAS_EASYOCR:
            try:
                import easyocr
                version = getattr(easyocr, "__version__", "desconocida")
            except Exception:
                pass
        return BackendMetadata(
            name="easyocr",
            display_name="EasyOCR",
            version=version,
            description="EasyOCR: PyTorch-based OCR (Python puro)",
            requires_gpu=False,
            languages=("es", "en", "fr", "de", "pt"),
            dependencies=("easyocr", "torch", "torchvision"),
            available=available,
            init_error=error,
        )

    def initialize(self):
        if self._initialized:
            return
        if not _HAS_EASYOCR:
            self._metadata.available = False
            self._metadata.init_error = "easyocr no instalado"
            raise ImportError("easyocr no instalado. pip install easyocr")
        try:
            # EasyOCR reader: usa GPU si está disponible, sino CPU
            self._reader = easyocr.Reader(
                [CONFIG.ocr.lang],
                gpu=False,  # Forzar CPU para plataformas gratuitas
                verbose=False
            )
            self._initialized = True
        except Exception as e:
            self._metadata.available = False
            self._metadata.init_error = str(e)
            raise

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        self.ensure_initialized()

        threshold = confidence_threshold if confidence_threshold is not None \
            else CONFIG.ocr.confidence_threshold

        # EasyOCR espera RGB. OpenCV es BGR.
        if image.shape[2] == 3:
            import cv2
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image

        # Ejecutar inferencia
        results = self._reader.readtext(image_rgb)

        words = []
        for (bbox, text, conf) in results:
            text = text.strip()
            conf = float(conf)
            if not text or conf < threshold:
                continue

            # EasyOCR bbox: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            # Convertir a formato estándar (x, y, w, h)
            x_coords = [p[0] for p in bbox]
            y_coords = [p[1] for p in bbox]
            x = int(min(x_coords))
            y = int(min(y_coords))
            w = int(max(x_coords) - x)
            h = int(max(y_coords) - y)

            words.append(WordResult(
                text=text,
                confidence=conf,
                bbox=(x, y, w, h),
            ))

        return words


# ═══════════════════════════════════════════════════════════════
#  BACKEND 5: docTR (Document Text Recognition) — OPCIONAL
# ═══════════════════════════════════════════════════════════════

_HAS_DOCTR = False
try:
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor
    _HAS_DOCTR = True
except ImportError:
    pass


class DocTRBackend(OCRBackend):
    """
    Backend de docTR (Document Text Recognition).
    Usa modelos deep learning modernos (DBNet + CRNN + Transformer).

    Requiere: pip install python-doctr
    """

    def _build_metadata(self) -> BackendMetadata:
        available = _HAS_DOCTR
        error = "" if _HAS_DOCTR else "docTR no instalado. pip install python-doctr[torch]"
        version = ""
        if _HAS_DOCTR:
            try:
                import doctr
                version = getattr(doctr, "__version__", "desconocida")
            except Exception:
                pass
        return BackendMetadata(
            name="doctr",
            display_name="docTR",
            version=version,
            description="docTR: DBNet + CRNN + Transformer",
            requires_gpu=True,
            languages=("es", "en", "fr", "de", "pt"),
            dependencies=("python-doctr", "torch"),
            available=available,
            init_error=error,
        )

    def initialize(self):
        if self._initialized:
            return
        if not _HAS_DOCTR:
            self._metadata.available = False
            self._metadata.init_error = "python-doctr no instalado"
            raise ImportError("python-doctr no instalado. pip install python-doctr[torch]")
        try:
            # docTR predictor: detección + reconocimiento
            self._predictor = ocr_predictor(
                det_arch="db_resnet50",
                reco_arch="crnn_vgg16_bn",
                pretrained=True,
            )
            self._initialized = True
        except Exception as e:
            self._metadata.available = False
            self._metadata.init_error = str(e)
            raise

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        self.ensure_initialized()

        threshold = confidence_threshold if confidence_threshold is not None \
            else CONFIG.ocr.confidence_threshold

        # docTR espera RGB. OpenCV es BGR.
        if image.shape[2] == 3:
            import cv2
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image

        # Crear documento desde array numpy
        doc = DocumentFile.from_images(image_rgb)
        result = self._predictor(doc)

        words = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    for word in line.words:
                        text = word.value.strip()
                        conf = float(word.confidence)
                        if not text or conf < threshold:
                            continue

                        # docTR usa geometría (xmin, ymin, xmax, ymax) normalizada
                        geom = word.geometry
                        h, w = image.shape[:2]
                        x1 = float(geom[0][0] * w)
                        y1 = float(geom[0][1] * h)
                        x2 = float(geom[1][0] * w)
                        y2 = float(geom[1][1] * h)

                        words.append((text, (x1, y1, x2, y2), conf))

        words.sort(key=lambda w: (w[1][1], w[1][0]))
        return words


# ═══════════════════════════════════════════════════════════════
#  BACKEND 5: Surya OCR — OPCIONAL
# ═══════════════════════════════════════════════════════════════

_HAS_SURYA = False
try:
    from surya.ocr import run_ocr
    from surya.model.recognition.model import RecognitionModel
    from surya.model.recognition.processor import RecognitionProcessor
    from surya.model.detection.model import DetectionModel
    from surya.model.detection.processor import DetectionProcessor
    _HAS_SURYA = True
except ImportError:
    pass


class SuryaBackend(OCRBackend):
    """
    Backend de Surya OCR.
    Modelo multilingüe de última generación basado en transformadores.

    Requiere: pip install surya-ocr
    """

    def _build_metadata(self) -> BackendMetadata:
        available = _HAS_SURYA
        error = "" if _HAS_SURYA else "surya-ocr no instalado. pip install surya-ocr"
        version = ""
        if _HAS_SURYA:
            try:
                import surya
                version = getattr(surya, "__version__", "desconocida")
            except Exception:
                pass
        return BackendMetadata(
            name="surya",
            display_name="Surya OCR",
            version=version,
            description="Surya OCR: transformer multilingüe",
            requires_gpu=True,
            languages=("es", "en", "fr", "de", "pt", "it", "nl"),
            dependencies=("surya-ocr", "torch"),
            available=available,
            init_error=error,
        )

    def initialize(self):
        if self._initialized:
            return
        if not _HAS_SURYA:
            self._metadata.available = False
            self._metadata.init_error = "surya-ocr no instalado"
            raise ImportError("surya-ocr no instalado. pip install surya-ocr")
        try:
            # Los modelos se descargan automáticamente en la primera ejecución
            self._det_processor = DetectionProcessor()
            self._det_model = DetectionModel()
            self._rec_model = RecognitionModel()
            self._rec_processor = RecognitionProcessor()
            self._initialized = True
        except Exception as e:
            self._metadata.available = False
            self._metadata.init_error = str(e)
            raise

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        self.ensure_initialized()

        threshold = confidence_threshold if confidence_threshold is not None \
            else CONFIG.ocr.confidence_threshold

        # Surya espera PIL Image o ruta
        from PIL import Image
        import cv2

        if image.shape[2] == 3:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image

        pil_image = Image.fromarray(image_rgb)

        # Mapear idioma CONFIG a código Surya
        lang_map = {"es": "es", "en": "en", "pt": "pt", "fr": "fr", "de": "de",
                    "it": "it", "nl": "nl"}
        surya_langs = [lang_map.get(CONFIG.ocr.lang, "es")]

        # Ejecutar OCR
        predictions = run_ocr(
            [pil_image],
            [surya_langs],
            self._det_model,
            self._det_processor,
            self._rec_model,
            self._rec_processor,
        )

        words = []
        if predictions and len(predictions) > 0:
            for pred in predictions[0]:
                text = pred.text.strip()
                conf = pred.confidence if hasattr(pred, 'confidence') else 0.9
                if not text or conf < threshold:
                    continue

                # Surya devuelve bbox en formato [x1, y1, x2, y2] normalizado (0-1)
                h, w = image.shape[:2]
                bbox = pred.bbox
                x1 = float(bbox[0] * w)
                y1 = float(bbox[1] * h)
                x2 = float(bbox[2] * w)
                y2 = float(bbox[3] * h)

                words.append((text, (x1, y1, x2, y2), float(conf)))

        words.sort(key=lambda w: (w[1][1], w[1][0]))
        return words


# ═══════════════════════════════════════════════════════════════
#  BACKEND 6: EasyOCR — OPCIONAL
# ═══════════════════════════════════════════════════════════════

_HAS_EASYOCR = False
try:
    import easyocr
    _HAS_EASYOCR = True
except ImportError:
    pass


class EasyOCRBackend(OCRBackend):
    """
    Backend de EasyOCR.
    Reconocimiento basado en CRNN + attention. Soporta 80+ idiomas.
    Fácil de instalar: pip install easyocr
    """

    def _build_metadata(self) -> BackendMetadata:
        available = _HAS_EASYOCR
        error = "" if _HAS_EASYOCR else "easyocr no instalado. pip install easyocr"
        version = ""
        return BackendMetadata(
            name="easyocr",
            display_name="EasyOCR",
            version=version,
            description="EasyOCR: CRNN + attention, 80+ idiomas",
            requires_gpu=False,
            languages=("es", "en", "pt", "fr", "de", "it", "nl"),
            dependencies=("easyocr", "torch"),
            available=available,
            init_error=error,
        )

    def initialize(self):
        if self._initialized:
            return
        if not _HAS_EASYOCR:
            self._metadata.available = False
            self._metadata.init_error = "easyocr no instalado"
            raise ImportError("easyocr no instalado. pip install easyocr")
        try:
            # gpu=False porque en CPU ya es rápido
            self._reader = easyocr.Reader(
                [CONFIG.ocr.lang],
                gpu=False,
            )
            self._initialized = True
        except Exception as e:
            self._metadata.available = False
            self._metadata.init_error = str(e)
            raise

    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        self.ensure_initialized()

        threshold = confidence_threshold if confidence_threshold is not None \
            else CONFIG.ocr.confidence_threshold

        results = self._reader.readtext(image)

        words = []
        for bbox, text, confidence in results:
            text = str(text).strip()
            if not text or confidence < threshold:
                continue

            x1 = float(min(p[0] for p in bbox))
            y1 = float(min(p[1] for p in bbox))
            x2 = float(max(p[0] for p in bbox))
            y2 = float(max(p[1] for p in bbox))

            words.append((text, (x1, y1, x2, y2), float(confidence)))

        words.sort(key=lambda w: (w[1][1], w[1][0]))
        return words
