from __future__ import annotations

import math
import statistics
from typing import Any, Dict, Iterable


class TechnicalEngine:
    """Deterministic price context; never emits trade orders or stop-loss advice."""

    def evaluate(self, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        history = list(rows)
        closes = [float(row["close"]) for row in history if row.get("close") is not None]
        volumes = [float(row["volume"]) for row in history if row.get("volume") is not None]
        if len(closes) < 50:
            return {"status": "INSUFFICIENT_DATA", "required_observations": 50, "observations": len(closes)}
        sma20 = statistics.fmean(closes[-20:])
        sma50 = statistics.fmean(closes[-50:])
        sma200 = statistics.fmean(closes[-200:]) if len(closes) >= 200 else None
        gains, losses = [], []
        for previous, current in zip(closes[-15:-1], closes[-14:]):
            change = current - previous
            gains.append(max(change, 0.0)); losses.append(max(-change, 0.0))
        average_gain, average_loss = statistics.fmean(gains), statistics.fmean(losses)
        rsi14 = 100.0 if average_loss == 0 else 100.0 - (100.0 / (1.0 + average_gain / average_loss))
        returns = [(b / a) - 1.0 for a, b in zip(closes[-31:-1], closes[-30:]) if a]
        volatility = statistics.stdev(returns) * math.sqrt(252) if len(returns) >= 2 else None
        average_volume = statistics.fmean(volumes[-20:]) if len(volumes) >= 20 else None
        volume_ratio = volumes[-1] / average_volume if average_volume else None
        trend = "UP" if closes[-1] > sma20 > sma50 else "DOWN" if closes[-1] < sma20 < sma50 else "MIXED"
        return {
            "status": "AVAILABLE", "close": closes[-1], "sma20": round(sma20, 6),
            "sma50": round(sma50, 6), "sma200": round(sma200, 6) if sma200 else None,
            "rsi14": round(rsi14, 4), "annualized_volatility": round(volatility, 6) if volatility is not None else None,
            "volume_ratio_20d": round(volume_ratio, 4) if volume_ratio is not None else None,
            "trend_context": trend,
            "interpretation_policy": "Contexto descritivo; não define entrada, saída, stop ou tamanho de posição.",
        }
