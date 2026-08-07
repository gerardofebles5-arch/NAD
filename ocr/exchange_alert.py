"""
πNAD — Exchange Rate Alert: Detección de cambios >5% y devaluación
=====================================================================
Monitorea la tasa de cambio BCV y otras divisas entre sesiones,
genera alertas cuando hay cambios significativos, y detecta patrones
de devaluación sostenida.

Características:
  - Historial persistente de tasas por sesión (archivo JSON)
  - Detección de cambios > umbral configurable (default: 5%)
  - Clasificación: info (<3%), warning (3-10%), critical (>10%)
  - Detección de tendencia devaluatoria (N sesiones consecutivas a la baja)
  - Alertas multi-moneda (BS, USD, EUR, COP, ARS)
  - Timeline visual: "Hace 2 sesiones → 60.50, Ahora → 63.85 (+5.5%)"

Uso:
    from ocr.exchange_alert import ExchangeAlert
    alert = ExchangeAlert()
    alerts = alert.check_session("BS")  # [(severity, msg), ...]
    alert.print_alerts(alerts)
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from utils.config import CONFIG


# ──────────────────────────────────────────────
#  Tipos de alerta
# ──────────────────────────────────────────────

ALERT_INFO = "info"       # Cambio leve (< umbral pero registrado)
ALERT_WARNING = "warning"  # Cambio moderado (entre 1x y 2x umbral)
ALERT_CRITICAL = "critical"  # Cambio severo (> 2x umbral) o devaluación

SEVERITY_LABELS = {
    ALERT_INFO: "ℹ️",
    ALERT_WARNING: "⚠️",
    ALERT_CRITICAL: "🚨",
}

SEVERITY_COLORS = {
    ALERT_INFO: (200, 200, 200),   # gris
    ALERT_WARNING: (0, 215, 255),  # amarillo (BGR)
    ALERT_CRITICAL: (0, 0, 255),   # rojo (BGR)
}


# ──────────────────────────────────────────────
#  Historial de sesiones
# ──────────────────────────────────────────────

class RateHistory:
    """
    Mantiene un historial persistente de tasas de cambio por sesión.

    Almacena:
      - timestamp: Unix timestamp de la sesión
      - date: Fecha legible de la sesión
      - rates: { "BS": 60.50, "EUR": 0.92, "COP": 4100, ... }
      - source: Origen de la tasa
    """

    HISTORY_FILE = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "cache",
        "rate_history.json",
    )

    def __init__(self, max_entries: int = 50):
        self.max_entries = max_entries
        os.makedirs(os.path.dirname(self.HISTORY_FILE), exist_ok=True)
        self._entries: List[Dict] = []
        self._load()

    # ── Persistencia ──

    def _load(self):
        """Carga el historial desde archivo."""
        try:
            if os.path.exists(self.HISTORY_FILE):
                with open(self.HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._entries = data.get("entries", [])
        except (json.JSONDecodeError, OSError):
            self._entries = []

    def _save(self):
        """Guarda el historial en archivo."""
        try:
            with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump({"entries": self._entries[-self.max_entries:]},
                          f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # ── Acceso ──

    @property
    def entries(self) -> List[Dict]:
        """Retorna todas las entradas del historial."""
        return list(self._entries)

    @property
    def last_entry(self) -> Optional[Dict]:
        """Retorna la última entrada (sesión anterior)."""
        return self._entries[-1] if self._entries else None

    @property
    def count(self) -> int:
        """Número de sesiones registradas."""
        return len(self._entries)

    # ── Registro ──

    def add_entry(self, rates: Dict):
        """Agrega una nueva entrada de tasas al historial."""
        entry = {
            "timestamp": time.time(),
            "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "rates": {k: v for k, v in rates.items()
                      if isinstance(v, (int, float))},
            "source": rates.get("source", "unknown"),
        }
        self._entries.append(entry)
        self._save()

    def get_last_rate(self, currency: str) -> Optional[float]:
        """Retorna la tasa de la última sesión para una moneda."""
        last = self.last_entry
        if last:
            rates = last.get("rates", {})
            if currency in ("BS", "VES"):
                return rates.get("BS", rates.get("VES"))
            return rates.get(currency)
        return None

    def get_rate_trend(self, currency: str, n: int = 5) -> List[float]:
        """
        Retorna las últimas N tasas registradas para una moneda
        (de más antigua a más reciente).

        Args:
            currency: Código de moneda.
            n: Número de entradas a recuperar.

        Returns:
            Lista de tasas (vacía si no hay suficientes datos).
        """
        values = []
        for entry in self._entries[-n:]:
            rates = entry.get("rates", {})
            if currency in ("BS", "VES"):
                val = rates.get("BS", rates.get("VES"))
            else:
                val = rates.get(currency)
            if val is not None:
                values.append(val)
        return values


# ──────────────────────────────────────────────
#  Motor de alertas
# ──────────────────────────────────────────────

class ExchangeAlert:
    """
    Motor de detección de cambios en tasas de cambio.

    Genera alertas cuando:
      - La tasa cambió más del umbral % entre sesiones
      - Hay una tendencia devaluatoria (N sesiones consecutivas bajando)
      - La tasa supera un máximo histórico
    """

    def __init__(
        self,
        threshold_pct: Optional[float] = None,
        devaluation_window: Optional[int] = None,
        history_max: Optional[int] = None,
    ):
        self.threshold_pct = threshold_pct or CONFIG.ocr.alert_threshold_pct
        self.devaluation_window = devaluation_window or CONFIG.ocr.alert_devaluation_window
        self.history = RateHistory(max_entries=history_max or CONFIG.ocr.alert_history_max)

    # ── Comparación entre sesiones ──

    def _compute_change(
        self,
        old_rate: float,
        new_rate: float,
    ) -> Tuple[float, str]:
        """
        Calcula el cambio porcentual entre dos tasas.

        Args:
            old_rate: Tasa anterior.
            new_rate: Tasa actual.

        Returns:
            (pct_change, direction) donde direction es 'up' o 'down'.
        """
        if old_rate <= 0:
            return 0.0, "up"

        pct = ((new_rate - old_rate) / old_rate) * 100.0
        direction = "up" if pct >= 0 else "down"
        return round(abs(pct), 2), direction

    def _classify_severity(self, pct_change: float) -> str:
        """
        Clasifica la severidad de un cambio porcentual.

        - info: < threshold
        - warning: threshold <= x < 2*threshold
        - critical: >= 2*threshold
        """
        if pct_change >= self.threshold_pct * 2:
            return ALERT_CRITICAL
        elif pct_change >= self.threshold_pct:
            return ALERT_WARNING
        else:
            return ALERT_INFO

    # ── Detecciones ──

    def check_rate_change(self, currency: str, new_rate: float) -> List[Tuple[str, str]]:
        """
        Compara la tasa actual con la última sesión registrada.

        Args:
            currency: Código de moneda ('BS', 'USD', 'EUR', etc.).
            new_rate: Tasa actual obtenida.

        Returns:
            Lista de (severity, mensaje).
        """
        alerts = []
        old_rate = self.history.get_last_rate(currency)

        if old_rate is None:
            # Primera medición — registrar pero sin alerta
            return [(ALERT_INFO, f"📊 Primera medición de {currency}: {new_rate:.4f}")]

        if old_rate == new_rate:
            return []

        pct, direction = self._compute_change(old_rate, new_rate)
        severity = self._classify_severity(pct)

        # Formatear dirección
        arrow = "📈" if direction == "up" else "📉"
        trend_word = "subió" if direction == "up" else "bajó"

        # Formatear montos
        old_str = f"{old_rate:.4f}" if old_rate < 10 else f"{old_rate:.2f}"
        new_str = f"{new_rate:.4f}" if new_rate < 10 else f"{new_rate:.2f}"

        msg = (
            f"{currency}: {trend_word} de {old_str} a {new_str} "
            f"({arrow} {pct:.1f}%)"
        )

        alerts.append((severity, msg))

        # Si es la moneda base (BS), generar alerta adicional con contexto
        if currency in ("BS", "VES") and severity in (ALERT_WARNING, ALERT_CRITICAL):
            # Cuánto se ha devaluado vs hace N sesiones
            trend_rates = self.history.get_rate_trend(currency, self.devaluation_window)
            if len(trend_rates) >= 2:
                total_pct = ((new_rate - trend_rates[0]) / trend_rates[0]) * 100.0
                if abs(total_pct) > self.threshold_pct:
                    alerts.append((
                        severity,
                        f"📊 Devaluación acumulada en {len(trend_rates)} sesiones: "
                        f"{abs(total_pct):.1f}% ({trend_rates[0]:.2f} → {new_rate:.2f})"
                    ))

        return alerts

    def check_devaluation_trend(self, currency: str, new_rate: float) -> List[Tuple[str, str]]:
        """
        Detecta tendencia devaluatoria: N sesiones consecutivas a la baja.

        Para BS/VES, una tendencia alcista en la tasa = devaluación
        (más Bolívares por USD = la moneda local pierde valor).

        Args:
            currency: Código de moneda.
            new_rate: Tasa actual.

        Returns:
            Lista de (severity, mensaje).
        """
        alerts = []
        trend_rates = self.history.get_rate_trend(currency, self.devaluation_window)
        trend_rates.append(new_rate)

        if len(trend_rates) < 3:
            return []  # Necesitamos al menos 2 sesiones anteriores + actual

        # Para BS: subida = devaluación. Para otras: bajada = devaluación
        is_bs = currency in ("BS", "VES")
        consecutive_drops = 0
        for i in range(1, len(trend_rates)):
            if is_bs:
                # BS: sube → se devalúa
                if trend_rates[i] > trend_rates[i - 1]:
                    consecutive_drops += 1
                else:
                    consecutive_drops = 0
            else:
                # Otras: baja → se devalúa
                if trend_rates[i] < trend_rates[i - 1]:
                    consecutive_drops += 1
                else:
                    consecutive_drops = 0

        # Umbral: si ha bajado N-1 de las últimas N sesiones
        if consecutive_drops >= max(2, self.devaluation_window - 2):
            pct_total = ((trend_rates[-1] - trend_rates[0]) / trend_rates[0]) * 100.0
            alerts.append((
                ALERT_CRITICAL,
                f"🚨 TENDENCIA DEVALUATORIA DETECTADA en {currency}: "
                f"{abs(pct_total):.1f}% en {len(trend_rates)} sesiones "
                f"({trend_rates[0]:.2f} → {trend_rates[-1]:.2f})"
            ))

        return alerts

    def check_all_currencies(
        self,
        current_rates: Dict,
    ) -> List[Tuple[str, str]]:
        """
        Ejecuta todas las comprobaciones para todas las monedas habilitadas.

        Args:
            current_rates: Dict con todas las tasas actuales.

        Returns:
            Lista de (severity, mensaje) ordenada por severidad.
        """
        all_alerts = []

        for curr in CONFIG.ocr.enabled_currencies:
            rate = None
            if curr in ("BS", "VES"):
                rate = current_rates.get("BS") or current_rates.get("VES")
            else:
                rate = current_rates.get(curr)

            if rate is None or rate <= 0:
                continue

            # 1. Cambio vs última sesión
            all_alerts.extend(self.check_rate_change(curr, rate))

            # 2. Tendencia devaluatoria
            all_alerts.extend(self.check_devaluation_trend(curr, rate))

        # 3. Registrar las tasas actuales en el historial
        # (Solo registrar si hay al menos una moneda con datos reales)
        has_real_data = any(
            curr in current_rates and isinstance(current_rates.get(curr), (int, float))
            for curr in CONFIG.ocr.enabled_currencies
        )
        if has_real_data:
            self.history.add_entry(current_rates)

        # Ordenar por severidad (critical primero)
        severity_order = {ALERT_CRITICAL: 0, ALERT_WARNING: 1, ALERT_INFO: 2}
        all_alerts.sort(key=lambda a: severity_order.get(a[0], 99))

        return all_alerts

    # ── Utilidades ──

    def print_alerts(self, alerts: List[Tuple[str, str]]):
        """Imprime alertas en consola con formato y color por severidad."""
        if not alerts:
            return

        print(f"\n{'='*60}")
        print("  📊 ALERTAS DE TASA DE CAMBIO")
        print(f"{'='*60}")

        for severity, msg in alerts:
            icon = SEVERITY_LABELS.get(severity, "📄")
            print(f"  {icon} {msg}")

        print(f"{'='*60}\n")

    @staticmethod
    def get_overlay_lines(
        alerts: List[Tuple[str, str]],
        max_lines: int = 2,
    ) -> List[Tuple[str, Tuple[int, int, int]]]:
        """
        Convierte alertas a líneas para overlay OpenCV.

        Args:
            alerts: Lista de (severity, mensaje).
            max_lines: Máximo de líneas a mostrar (prioriza critical > warning).

        Returns:
            Lista de (texto_abreviado, color_bgr).
        """
        lines = []

        # Priorizar: critical first, then warning
        priority = {ALERT_CRITICAL: 0, ALERT_WARNING: 1, ALERT_INFO: 2}
        sorted_alerts = sorted(alerts, key=lambda a: priority.get(a[0], 99))

        for severity, msg in sorted_alerts:
            if len(lines) >= max_lines:
                break

            color = SEVERITY_COLORS.get(severity, (200, 200, 200))
            icon = SEVERITY_LABELS.get(severity, "📄")

            # Abreviar mensaje para overlay (max ~60 chars)
            short = msg[:65] + "..." if len(msg) > 65 else msg
            lines.append((f"{icon} {short}", color))

        return lines

    def get_alert_summary(self, alerts: List[Tuple[str, str]]) -> Dict:
        """Resume las alertas para incluirlas en respuestas API."""
        summary = {
            "has_alerts": len(alerts) > 0,
            "count": len(alerts),
            "critical_count": sum(1 for s, _ in alerts if s == ALERT_CRITICAL),
            "warning_count": sum(1 for s, _ in alerts if s == ALERT_WARNING),
            "info_count": sum(1 for s, _ in alerts if s == ALERT_INFO),
            "alerts": [],
        }
        for severity, msg in alerts:
            summary["alerts"].append({
                "severity": severity,
                "message": msg,
            })
        return summary


# ──────────────────────────────────────────────
#  Singleton global
# ──────────────────────────────────────────────

_global_alert: Optional[ExchangeAlert] = None


def get_alert_engine() -> ExchangeAlert:
    """Retorna la instancia global del motor de alertas."""
    global _global_alert
    if _global_alert is None:
        _global_alert = ExchangeAlert()
    return _global_alert


def check_exchange_alerts(current_rates: Dict) -> List[Tuple[str, str]]:
    """
    Función rápida: ejecuta todas las comprobaciones y retorna alertas.

    Args:
        current_rates: Dict con tasas actuales (de CurrencyRateProvider.get_all_rates()).

    Returns:
        Lista de (severidad, mensaje).
    """
    engine = get_alert_engine()
    alerts = engine.check_all_currencies(current_rates)
    engine.print_alerts(alerts)
    return alerts


# ──────────────────────────────────────────────
#  Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  πNAD Exchange Rate Alert — Prueba")
    print("=" * 60)

    # Simular historial
    history = RateHistory()
    print(f"\n📋 Historial actual: {history.count} entradas")

    # Simular un cambio del 5.5%
    mock_rates = {
        "BS": 63.85,
        "USD": 1.0,
        "EUR": 0.91,
        "COP": 4150.0,
        "ARS": 990.0,
        "date": datetime.now().strftime("%d/%m/%Y"),
        "source": "test",
    }

    print(f"\n📡 Simulando alerta con BS = {mock_rates['BS']}...")
    alert = ExchangeAlert(threshold_pct=5.0)
    alerts = alert.check_all_currencies(mock_rates)
    alert.print_alerts(alerts)

    # Mostrar resumen
    summary = alert.get_alert_summary(alerts)
    print(f"\n📊 Resumen: {summary['count']} alertas "
          f"({summary['critical_count']} críticas, "
          f"{summary['warning_count']} warnings)")

    print(f"\n🖥️ Líneas para overlay:")
    for line, color in alert.get_overlay_lines(alerts):
        print(f"  {line}  (color: {color})")
