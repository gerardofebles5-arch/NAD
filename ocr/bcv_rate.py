"""
πNAD — Multi-Currency Exchange Rate Provider
==============================================
Obtiene tasas de cambio para múltiples divisas (USD, EUR, COP, ARS, VES/BS)
con mecanismos de fallback multi-fuente, caché local y soporte de consenso.

Monedas soportadas:
  - BS / VES (Bolívares venezolanos)
  - USD (Dólares estadounidenses)
  - EUR (Euros)
  - COP (Pesos colombianos)
  - ARS (Pesos argentinos)

Fuentes (orden configurable via exchange_sources_enabled):
  1. exchangerate.host — API multi-moneda (EUR, COP, ARS, VES)
  2. dolarapi.com — API venezolana (BS oficial + paralelo)
  3. dolarvzla.com — CDN estático VE (rápido, sin rate limit)
  4. pydolarve.org — API venezolana (BS oficial + paralelo)
  5. bcv.gob.ve — Scraping directo del sitio oficial BCV
  6. cotizave.com — API profesional VE (requiere API key)
  7. Config fallback — Tasas por defecto offline

Consenso: cuando 2+ fuentes responden, se usa el promedio.

Uso:
    from ocr.bcv_rate import CurrencyRateProvider
    provider = CurrencyRateProvider()
    rates = provider.get_all_rates()
    rate_usd_bs = provider.get_rate("BS")  # 60.50
    converted = provider.convert(100, "USD", "BS")  # 6050.0
"""

import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from urllib.request import Request, urlopen
from urllib.error import URLError

from utils.config import CONFIG


# ──────────────────────────────────────────────
#  Constantes de moneda
# ──────────────────────────────────────────────

# Símbolos y códigos ISO para cada moneda soportada
CURRENCY_INFO = {
    "BS":  {"symbol": "Bs.", "code": "VES", "name": "Bolívares",     "decimals": 2, "locale": "ve"},
    "VES": {"symbol": "Bs.", "code": "VES", "name": "Bolívares",     "decimals": 2, "locale": "ve"},
    "USD": {"symbol": "$",   "code": "USD", "name": "Dólares",       "decimals": 2, "locale": "us"},
    "EUR": {"symbol": "€",   "code": "EUR", "name": "Euros",         "decimals": 2, "locale": "eu"},
    "COP": {"symbol": "$",   "code": "COP", "name": "Pesos Colomb.", "decimals": 0, "locale": "co"},
    "ARS": {"symbol": "$",   "code": "ARS", "name": "Pesos Argent.", "decimals": 2, "locale": "ar"},
}

# Aliases: nombres alternativos que pueden aparecer en facturas
CURRENCY_ALIASES = {
    "BS":    ["BS", "Bs", "Bs.", "BOLIVAR", "BOLÍVAR", "BOLIVARES", "BOLÍVARES", "VES"],
    "USD":   ["USD", "$", "DOLAR", "DÓLAR", "DOLARES", "DÓLARES", "DIVISAS", "AMERICANO"],
    "EUR":   ["EUR", "€", "EURO", "EUROS", "EU"],
    "COP":   ["COP", "COL", "PESO", "PESOS"],
    "ARS":   ["ARS", "ARG", "PESO ARG", "PESOS ARG"],
}


# ──────────────────────────────────────────────
#  Proveedor de tasas multi-moneda
# ──────────────────────────────────────────────

class CurrencyRateProvider:
    """
    Proveedor de tasas de cambio multi-moneda con caché y fallback.

    Todas las tasas están expresadas como UNIDADES por USD.
    Ej: EUR=0.92 significa 1 USD = 0.92 EUR.
        BS=60.50 significa 1 USD = 60.50 BS.

    Características:
      - Multi-fuente con fallback automático
      - Caché en memoria + archivo local
      - TTL configurable (default: 6 horas)
      - Conversión entre cualquier par de monedas soportadas
      - Formateo localizado por moneda
    """

    CACHE_FILE = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "cache",
        "exchange_rates.json",
    )

    def __init__(self, cache_ttl_seconds: int = 21600):  # 6h por defecto
        self.cache_ttl = cache_ttl_seconds
        self._cache: Optional[Dict] = None
        self._last_fetch: Optional[float] = None

        # Asegurar directorio de caché
        os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)

    # ── Propiedades de acceso rápido ──

    @property
    def oficial(self) -> float:
        """Tasa oficial BS/USD (compatibilidad con código anterior)."""
        return self.get_rate("BS")

    @property
    def paralelo(self) -> Optional[float]:
        """Tasa del mercado paralelo BS/USD (compatibilidad)."""
        rates = self.get_all_rates()
        return rates.get("paralelo_ves")

    # ── Métodos principales ──

    def get_rate(self, currency: str) -> float:
        """
        Retorna la tasa de cambio para una moneda (UNIDADES por USD).

        Args:
            currency: 'BS', 'USD', 'EUR', 'COP', 'ARS'.

        Returns:
            float: Unidades de la moneda por 1 USD.
                   Ej: BS=60.50, EUR=0.92, COP=4100.0
        """
        rates = self.get_all_rates()
        curr = currency.upper()

        # BS y VES son la misma moneda
        if curr in ("BS", "VES"):
            return rates.get("BS", rates.get("VES", CONFIG.ocr.bcv_default_rate))

        return rates.get(curr, 1.0)

    def get_rate_date(self) -> str:
        """Retorna la fecha de la última tasa obtenida."""
        rates = self.get_all_rates()
        return rates.get("date", "")

    def get_all_rates(self) -> Dict:
        """
        Obtiene todas las tasas disponibles para todas las monedas.

        Orden de búsqueda:
          1. Caché en memoria (si no ha expirado)
          2. Caché en archivo local (si no ha expirado)
          3. API online → ExchangeRate.host (multi-moneda)
          4. Fuentes específicas (BCV, pydolarve)
          5. Fallback a configuración

        Returns:
            Dict con keys: USD, EUR, COP, ARS, BS, VES, date, source, ...
        """
        # 1. Caché en memoria
        if self._is_cache_valid():
            return self._cache

        # 2. Caché en archivo
        file_cache = self._load_file_cache()
        if file_cache and self._is_file_cache_valid(file_cache):
            self._cache = file_cache["rates"]
            self._last_fetch = file_cache.get("timestamp", 0)
            return self._cache

        # 3. Intentar fuentes online
        rates = self._fetch_all_online()

        # 4. Fallback a configuración
        if not rates or "USD" not in rates:
            rates = self._build_default_rates()

        # Asegurar que VES/BS estén presentes
        if "BS" not in rates and "VES" in rates:
            rates["BS"] = rates["VES"]
        elif "VES" not in rates and "BS" in rates:
            rates["VES"] = rates["BS"]

        # Añadir metadatos si no están
        if "date" not in rates:
            rates["date"] = datetime.now().strftime("%d/%m/%Y")
        if "source" not in rates:
            rates["source"] = "config_default"

        # Guardar en caché
        self._cache = rates
        self._last_fetch = time.time()
        self._save_file_cache(rates)

        return rates

    def _build_default_rates(self) -> Dict:
        """Construye tasas por defecto desde la configuración JSON."""
        default_rates = {}
        try:
            raw = CONFIG.ocr.currency_default_rates
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            default_rates.update(parsed)
        except (json.JSONDecodeError, TypeError):
            pass

        # Garantizar BS/USD desde config si no está en el JSON
        if "BS" not in default_rates and "VES" not in default_rates:
            default_rates["BS"] = CONFIG.ocr.bcv_default_rate
        if "USD" not in default_rates:
            default_rates["USD"] = 1.0

        default_rates["date"] = datetime.now().strftime("%d/%m/%Y")
        default_rates["source"] = "config_default"
        default_rates["note"] = "Usando tasas por defecto (sin conexión)"
        return default_rates

    def _is_cache_valid(self) -> bool:
        """Verifica si la caché en memoria es válida."""
        if self._cache is None or self._last_fetch is None:
            return False
        return (time.time() - self._last_fetch) < self.cache_ttl

    def _is_file_cache_valid(self, file_cache: Dict) -> bool:
        """Verifica si la caché en archivo es válida."""
        ts = file_cache.get("timestamp", 0)
        return (time.time() - ts) < self.cache_ttl

    # ── Fetch online — multi-fuente con consenso ──

    def _fetch_all_online(self) -> Optional[Dict]:
        """
        Obtiene tasas desde TODAS las fuentes disponibles y calcula consenso.

        Orden de fuentes (configurable via CONFIG.ocr.exchange_sources_enabled):
          1. exchangerate.host — multi-moneda (EUR, COP, ARS, VES)
          2. dolarapi.com — BCV oficial + paralelo
          3. dolarvzla.com — CDN estático (rápido, sin rate limit)
          4. pydolarve.org — BCV oficial + paralelo
          5. bcv.gob.ve — Scraping directo sitio oficial
          6. cotizave.com — API profesional (requiere key)

        Returns:
            Dict con tasas consolidadas o None si todo falla.
        """
        sources_enabled = CONFIG.ocr.exchange_sources_enabled or (
            "exchangerate", "dolarapi", "dolarvzla", "pydolarve", "bcv_scrape", "cotizave"
        )

        source_map = {
            "exchangerate": self._fetch_from_exchangerate,
            "dolarapi": self._fetch_from_dolarapi,
            "dolarvzla": self._fetch_from_dolarvzla,
            "pydolarve": self._fetch_from_pydolarve,
            "bcv_scrape": self._fetch_bcv_usd,
            "cotizave": self._fetch_from_cotizave,
        }

        # Recopilar resultados de todas las fuentes
        source_results = {}
        source_names_ok = []

        for src_name in sources_enabled:
            fetcher = source_map.get(src_name)
            if fetcher is None:
                continue

            print(f"  [FX] Consultando fuente: {src_name}...")
            try:
                result = fetcher()
                if result and result.get("BS", result.get("VES", 0)) > 0:
                    source_results[src_name] = result
                    source_names_ok.append(src_name)
                    print(f"  [FX]   ✓ {src_name}: BS={result.get('BS', result.get('VES', '?'))}")
            except Exception as e:
                print(f"  [FX]   ✗ {src_name}: {e}")
                continue

        # Si no hay resultados, retornar None
        if not source_results:
            return None

        # ── Consenso: promediar tasas BS/VES entre fuentes ──
        merged = self._merge_source_results(source_results, source_names_ok)
        return merged

    def _merge_source_results(
        self,
        source_results: Dict[str, Dict],
        source_names: List[str],
    ) -> Dict:
        """
        Fusiona resultados de múltiples fuentes usando promedio simple.

        Para BS/VES: promedio de todas las fuentes que respondieron.
        Para EUR/COP/ARS: se toma de exchangerate si está disponible.
        Para paralelo: promedio de fuentes que reportan paralelo.
        """
        bs_values = []
        ves_values = []
        paralelo_values = []
        best_date = ""
        used_sources = []
        extra_rates = {}  # EUR, COP, ARS desde exchangerate

        for src_name in source_names:
            data = source_results[src_name]
            used_sources.append(data.get("source", src_name))

            # BS / VES
            bs = data.get("BS") or data.get("VES")
            if bs and isinstance(bs, (int, float)) and 1 < bs < 1000:
                bs_values.append(bs)

            # Paralelo
            paralelo = data.get("paralelo_ves") or data.get("paralelo")
            if paralelo and isinstance(paralelo, (int, float)) and 1 < paralelo < 1000:
                paralelo_values.append(paralelo)

            # Fecha más reciente
            d = data.get("date", "")
            if d and d > best_date:
                best_date = d

            # EUR, COP, ARS (solo desde exchangerate)
            for curr in ("EUR", "COP", "ARS"):
                if curr in data and isinstance(data[curr], (int, float)) and data[curr] > 0:
                    if curr not in extra_rates:
                        extra_rates[curr] = data[curr]

        # Calcular promedios
        result = {"USD": 1.0}

        if bs_values:
            avg_bs = round(sum(bs_values) / len(bs_values), 2)
            result["BS"] = avg_bs
            result["VES"] = avg_bs
            result["source_count"] = len(bs_values)

            # Calcular spread (diferencia entre fuentes)
            if len(bs_values) > 1:
                spread = max(bs_values) - min(bs_values)
                result["source_spread"] = round(spread, 2)

        if paralelo_values:
            result["paralelo_ves"] = round(sum(paralelo_values) / len(paralelo_values), 2)

        # Añadir EUR, COP, ARS si están disponibles
        result.update(extra_rates)
        if "EUR" not in result:
            result["EUR"] = 0.92  # fallback
        if "COP" not in result:
            result["COP"] = 4100.0
        if "ARS" not in result:
            result["ARS"] = 980.0

        result["date"] = best_date or datetime.now().strftime("%d/%m/%Y")
        result["source"] = "+".join(used_sources[:3])  # primeras 3 fuentes
        result["source_list"] = used_sources

        return result

    # ── Fuente 1: ExchangeRate.host (multi-moneda) ──

    def _fetch_from_exchangerate(self) -> Optional[Dict]:
        """
        Obtiene tasas multi-moneda desde ExchangeRate API.

        URL: https://api.exchangerate.host/latest?base=USD&symbols=VES,EUR,COP,ARS
        """
        try:
            url = CONFIG.ocr.exchange_api_url
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            })
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            if not data.get("success") and "rates" not in data:
                return None

            rates_data = data.get("rates", data)
            result = {
                "USD": 1.0,
                "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
                "source": "exchangerate_host",
            }

            api_map = {
                "VES": "VES",
                "EUR": "EUR",
                "COP": "COP",
                "ARS": "ARS",
            }

            for api_code, our_code in api_map.items():
                if api_code in rates_data:
                    rate = float(rates_data[api_code])
                    if 0 < rate < 1_000_000:
                        result[our_code] = round(rate, 6)

            if "VES" not in result:
                result["VES"] = CONFIG.ocr.bcv_default_rate
            if "BS" not in result:
                result["BS"] = result.get("VES", CONFIG.ocr.bcv_default_rate)

            if len(result) >= 3:
                return result

        except (URLError, ValueError, json.JSONDecodeError, OSError) as e:
            print(f"  [FX] Error exchangerate.host: {e}")

        return None

    # ── Fuente 2: DolarApi.com (API venezolana) ──

    def _fetch_from_dolarapi(self) -> Optional[Dict]:
        """
        Obtiene tasas desde ve.dolarapi.com.

        Endpoints:
          Oficial:  /v1/dolares/oficial
          Paralelo: /v1/dolares/paralelo

        Respuesta: {"moneda":"USD","casa":"oficial","nombre":"BCV",
                     "compra":0,"venta":51.50,"fechaActualizacion":"..."}
        """
        base = CONFIG.ocr.dolarapi_url.rstrip("/")
        result = {"source": "dolarapi_com"}
        success = False

        for endpoint, key_name in [("/oficial", "oficial"), ("/paralelo", "paralelo")]:
            url = f"{base}{endpoint}"
            try:
                req = Request(url, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                })
                with urlopen(req, timeout=8) as response:
                    data = json.loads(response.read().decode("utf-8"))

                venta = data.get("venta") or data.get("promedio")
                if venta and isinstance(venta, (int, float)) and 1 < venta < 1000:
                    if key_name == "oficial":
                        result["BS"] = round(venta, 2)
                        result["VES"] = round(venta, 2)
                        success = True
                    elif key_name == "paralelo":
                        result["paralelo_ves"] = round(venta, 2)

                date_str = data.get("fechaActualizacion", "")
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        result["date"] = dt.strftime("%d/%m/%Y")
                    except (ValueError, TypeError):
                        pass

            except (URLError, ValueError, json.JSONDecodeError, OSError) as e:
                print(f"  [FX] Error dolarapi.com/{key_name}: {e}")

        if success:
            return result
        return None

    # ── Fuente 3: DolarVZLA.com (CDN estático) ──

    def _fetch_from_dolarvzla(self) -> Optional[Dict]:
        """
        Obtiene tasas desde rates.dolarvzla.com (CDN, sin rate limit).

        Respuesta: {"price": 51.50, "change": 0.5, "updated_at": "..."}
        """
        try:
            req = Request(CONFIG.ocr.dolarvzla_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            })
            with urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))

            price = data.get("price")
            if price and isinstance(price, (int, float)) and 1 < price < 1000:
                result = {
                    "BS": round(price, 2),
                    "VES": round(price, 2),
                    "source": "dolarvzla_com",
                }

                # Paralelo ~3% spread estimado (dolarvzla no ofrece paralelo directo)
                result["paralelo_ves"] = round(price * 1.03, 2)

                date_str = data.get("updated_at", "")
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        result["date"] = dt.strftime("%d/%m/%Y")
                    except (ValueError, TypeError):
                        pass

                return result

        except (URLError, ValueError, json.JSONDecodeError, OSError) as e:
            print(f"  [FX] Error dolarvzla.com: {e}")

        return None

    # ── Fuente 4: PyDolarVE.org (API venezolana) ──

    def _fetch_from_pydolarve(self) -> Optional[Dict]:
        """
        Obtiene tasas desde pydolarve.org/api/v1/dollar.

        Params: ?page=bcv  (BCV oficial)
                ?page=paralelo  (paralelo)

        Respuesta BCV: {"price": 51.50, "title": "BCV", "updated_at": "..."}
        """
        base = CONFIG.ocr.pydolarve_url.rstrip("/")
        result = {"source": "pydolarve_org"}
        success = False

        for page, key_name in [("bcv", "oficial"), ("paralelo", "paralelo")]:
            url = f"{base}?page={page}"
            try:
                req = Request(url, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                })
                with urlopen(req, timeout=8) as response:
                    data = json.loads(response.read().decode("utf-8"))

                # Formato: {"price": 51.50, "title": "BCV", ...}
                price = None
                if isinstance(data, dict):
                    price = data.get("price") or data.get("promedio")
                    # Buscar en sub-objetos
                    if not price:
                        for sub in data.values():
                            if isinstance(sub, dict) and "price" in sub:
                                price = float(sub["price"])
                                break

                if price and isinstance(price, (int, float)) and 1 < price < 1000:
                    if key_name == "oficial":
                        result["BS"] = round(price, 2)
                        result["VES"] = round(price, 2)
                        success = True
                    elif key_name == "paralelo":
                        result["paralelo_ves"] = round(price, 2)

            except (URLError, ValueError, json.JSONDecodeError, OSError) as e:
                print(f"  [FX] Error pydolarve.org/{page}: {e}")

        if success:
            return result
        return None

    # ── Fuente 5: BCV Scraping (sitio oficial) ──

    def _fetch_bcv_usd(self) -> Optional[Dict]:
        """
        Scraping del sitio oficial del BCV para tasa BS/USD.

        URL: https://www.bcv.org.ve/tasas-cambio
        """
        try:
            req = Request(
                CONFIG.ocr.bcv_api_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                },
            )
            with urlopen(req, timeout=10) as response:
                html = response.read().decode("utf-8", errors="ignore")

            # Buscar tasa en div id="dolar"
            rate_match = re.search(
                r'<div[^>]*id\s*=\s*["\']?dolar["\']?[^>]*>.*?([\d.,]+)\s*</div>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            if rate_match:
                raw = rate_match.group(1).strip()
                rate = float(raw.replace(",", "."))
                if 1 < rate < 1000:
                    return {
                        "BS": round(rate, 2),
                        "VES": round(rate, 2),
                        "paralelo_ves": round(rate * 1.03, 2),
                        "source": "bcv_gob_ve",
                        "date": datetime.now().strftime("%d/%m/%Y"),
                    }

            # Fallback: patrón alternativo en texto
            alt_match = re.search(r"([\d.,]+)\s*Bs\.?\s*(?:por|/)?\s*USD", html)
            if alt_match:
                raw = alt_match.group(1).strip()
                rate = float(raw.replace(",", "."))
                if 1 < rate < 1000:
                    return {
                        "BS": round(rate, 2),
                        "VES": round(rate, 2),
                        "paralelo_ves": round(rate * 1.03, 2),
                        "source": "bcv_gob_ve_alt",
                        "date": datetime.now().strftime("%d/%m/%Y"),
                    }

        except (URLError, ValueError, OSError) as e:
            print(f"  [FX] Error bcv.gob.ve: {e}")

        return None

    # ── Fuente 6: Cotizave.com (API profesional, requiere key) ──

    def _fetch_from_cotizave(self) -> Optional[Dict]:
        """
        Obtiene tasas desde api.cotizave.com.

        Requiere API key configurada en CONFIG.ocr.cotizave_api_key.
        Respuesta: {"data": {"USD_VES": {"rate": 51.50, ...}}}
        """
        api_key = CONFIG.ocr.cotizave_api_key
        if not api_key:
            return None  # No configurada

        try:
            req = Request(CONFIG.ocr.cotizave_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "X-API-Key": api_key,
            })
            with urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))

            # Navegar estructura: data.USD_VES.rate
            rates_data = data.get("data", data)
            for key in ["USD_VES", "USDVES", "ves", "VES"]:
                if key in rates_data:
                    entry = rates_data[key]
                    rate = entry.get("rate") or entry.get("price") or entry.get("venta")
                    if rate and isinstance(rate, (int, float)) and 1 < rate < 1000:
                        return {
                            "BS": round(rate, 2),
                            "VES": round(rate, 2),
                            "source": "cotizave_com",
                            "date": datetime.now().strftime("%d/%m/%Y"),
                        }

        except (URLError, ValueError, json.JSONDecodeError, OSError) as e:
            print(f"  [FX] Error cotizave.com: {e}")

        return None

    # ── Conversión entre monedas ──

    def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
    ) -> float:
        """
        Convierte un monto entre cualquier par de monedas soportadas.

        Usa USD como moneda puente: FROM → USD → TO

        Args:
            amount: Monto a convertir.
            from_currency: 'BS', 'USD', 'EUR', 'COP', 'ARS'.
            to_currency: 'BS', 'USD', 'EUR', 'COP', 'ARS'.

        Returns:
            Monto convertido (redondeado a 2 decimales).
        """
        if from_currency.upper() == to_currency.upper():
            return round(amount, 2)

        rates = self.get_all_rates()
        from_rate = self._get_rate_for_currency(rates, from_currency)
        to_rate = self._get_rate_for_currency(rates, to_currency)

        if from_rate <= 0 or to_rate <= 0:
            return 0.0

        # Convertir FROM → USD → TO
        usd_amount = amount / from_rate
        return round(usd_amount * to_rate, 2)

    def _get_rate_for_currency(self, rates: Dict, currency: str) -> float:
        """Obtiene la tasa para una moneda desde el dict de tasas."""
        curr = currency.upper()
        if curr in ("BS", "VES"):
            return rates.get("BS", rates.get("VES", CONFIG.ocr.bcv_default_rate))
        return rates.get(curr, 1.0)

    def convert_to_all(
        self,
        amount: float,
        from_currency: str,
    ) -> Dict[str, float]:
        """
        Convierte un monto a todas las monedas soportadas.

        Args:
            amount: Monto a convertir.
            from_currency: Moneda de origen.

        Returns:
            Dict: { "USD": 100.0, "EUR": 92.0, "BS": 6050.0, "COP": 410000.0, "ARS": 98000.0 }
        """
        rates = self.get_all_rates()
        from_rate = self._get_rate_for_currency(rates, from_currency)
        if from_rate <= 0:
            return {}

        usd_amount = amount / from_rate
        result = {}
        for curr in CONFIG.ocr.enabled_currencies:
            to_rate = self._get_rate_for_currency(rates, curr)
            result[curr] = round(usd_amount * to_rate, 2)

        return result

    # ── Formateo ──

    def format_amount(
        self,
        amount: float,
        currency: str = "USD",
        include_symbol: bool = True,
    ) -> str:
        """
        Formatea un monto con el símbolo y formato local de la moneda.

        Args:
            amount: Monto numérico.
            currency: 'BS', 'USD', 'EUR', 'COP', 'ARS'.
            include_symbol: Si True, incluye el símbolo.

        Returns:
            str: "Bs. 1.250,00", "$ 500.00", "€ 92,00", "$ 4.100", "$ 980,00"
        """
        curr = currency.upper()
        info = CURRENCY_INFO.get(curr, CURRENCY_INFO["USD"])
        locale = info["locale"]
        decimals = info["decimals"]

        if locale == "ve" or (locale == "co" and curr == "COP"):
            # VE: 1.250,00  |  COP: 4.100 (sin decimales)
            formatted = f"{amount:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        elif locale == "eu":
            # EUR: 1.250,00
            formatted = f"{amount:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        elif locale == "ar":
            # ARS: 1.250,00
            formatted = f"{amount:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            # USD: 1,250.00
            formatted = f"{amount:,.{decimals}f}"

        if include_symbol:
            return f"{info['symbol']} {formatted}"
        return formatted

    # ── Caché en archivo ──

    def _load_file_cache(self) -> Optional[Dict]:
        """Carga la caché desde archivo."""
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _save_file_cache(self, rates: Dict):
        """Guarda la caché en archivo."""
        try:
            cache_data = {
                "timestamp": time.time(),
                "rates": rates,
            }
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def invalidate_cache(self):
        """Invalida la caché forzando una recarga en la próxima llamada."""
        self._cache = None
        self._last_fetch = None
        try:
            if os.path.exists(self.CACHE_FILE):
                os.remove(self.CACHE_FILE)
        except OSError:
            pass


# ──────────────────────────────────────────────
#  Funciones de utilidad (formateo rápido)
# ──────────────────────────────────────────────

def format_amount_with_currency(
    amount: float,
    currency: str = "USD",
    include_symbol: bool = True,
) -> str:
    """
    Formatea un monto con su símbolo de moneda (función rápida).

    Args:
        amount: Monto numérico.
        currency: 'BS', 'USD', 'EUR', 'COP', 'ARS'.
        include_symbol: Si True, incluye el símbolo.

    Returns:
        str formateado.
    """
    provider = get_currency_provider()
    return provider.format_amount(amount, currency, include_symbol)


def convert_currency(
    amount: float,
    from_currency: str,
    to_currency: str,
    rate: Optional[float] = None,
) -> float:
    """
    Convierte un monto entre monedas.

    Si se proporciona 'rate', usa ese valor directamente (solo BS↔USD).
    Si no, usa el proveedor multi-moneda para cualquier par.

    Args:
        amount: Monto a convertir.
        from_currency: Moneda origen.
        to_currency: Moneda destino.
        rate: Tasa directa (opcional, solo BS↔USD).

    Returns:
        Monto convertido.
    """
    from_c = from_currency.upper()
    to_c = to_currency.upper()

    # Si son la misma moneda
    if from_c == to_c:
        return round(amount, 2)

    # Si es BS↔USD con tasa explícita (compatibilidad)
    if rate is not None and from_c in ("BS", "USD") and to_c in ("BS", "USD"):
        if from_c == "USD" and to_c in ("BS", "VES"):
            return round(amount * rate, 2)
        elif from_c in ("BS", "VES") and to_c == "USD":
            return round(amount / rate, 2) if rate > 0 else 0.0

    # Multi-moneda vía provider
    provider = get_currency_provider()
    return provider.convert(amount, from_currency, to_currency)


# ──────────────────────────────────────────────
#  Backward compatibility aliases
# ──────────────────────────────────────────────

# BCVRateProvider fue renombrado a CurrencyRateProvider en v1.1
BCVRateProvider = CurrencyRateProvider


def get_bcv_provider() -> CurrencyRateProvider:
    """Retorna el proveedor multi-moneda (alias de get_currency_provider)."""
    return get_currency_provider()


# ──────────────────────────────────────────────
#  Singleton global (inicialización lazy)
# ──────────────────────────────────────────────

_global_provider: Optional[CurrencyRateProvider] = None


def get_currency_provider() -> CurrencyRateProvider:
    """Retorna la instancia global del proveedor multi-moneda."""
    global _global_provider
    if _global_provider is None:
        _global_provider = CurrencyRateProvider(
            cache_ttl_seconds=CONFIG.ocr.bcv_cache_ttl,
        )
    return _global_provider


def get_bcv_rate() -> float:
    """Retorna la tasa BS/USD oficial actual (compatibilidad)."""
    return get_currency_provider().get_rate("BS")


def get_bcv_rates() -> Dict:
    """Retorna todas las tasas disponibles (compatibilidad)."""
    return get_currency_provider().get_all_rates()


# ──────────────────────────────────────────────
#  Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  πNAD Multi-Currency Exchange Rate — Prueba")
    print("=" * 60)

    provider = CurrencyRateProvider(cache_ttl_seconds=0)

    print("\n📡 Obteniendo tasas de cambio...")
    rates = provider.get_all_rates()
    print(f"\nResultado:")
    for k, v in rates.items():
        if isinstance(v, float):
            print(f"  {k:12s}: {v:>10.4f}")
        else:
            print(f"  {k:12s}: {v}")

    print(f"\n💰 Tasas (unidades por USD):")
    for curr in ["BS", "USD", "EUR", "COP", "ARS"]:
        rate = provider.get_rate(curr)
        print(f"  1 USD = {rate:>10.4f} {curr}")

    print(f"\n🔄 Conversiones desde $100 USD:")
    conv = provider.convert_to_all(100, "USD")
    for curr, val in conv.items():
        print(f"  $100 USD → {provider.format_amount(val, curr)}")

    print(f"\n🔄 Conversiones desde Bs. 5.000:")
    conv = provider.convert_to_all(5000, "BS")
    for curr, val in conv.items():
        print(f"  Bs. 5.000 → {provider.format_amount(val, curr)}")

    print(f"\n📝 Formatos:")
    for curr in ["BS", "USD", "EUR", "COP", "ARS"]:
        print(f"  {provider.format_amount(1234.56, curr)}")
