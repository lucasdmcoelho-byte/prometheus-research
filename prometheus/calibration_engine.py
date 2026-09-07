from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple
import math

from prometheus.models import Prediction, PredictionOutcome, CalibrationBucket, CalibrationReport


class CalibrationEngine:
    def __init__(self, min_sample: int = 5):
        self.min_sample = min_sample

    def _normalize_confidence(self, conf: float) -> float:
        if conf is None:
            return 0.0
        # support both 0-1 and 0-100
        if conf > 1.0:
            conf = conf / 100.0
        return min(max(float(conf), 0.0), 1.0)

    def calculate(self, outcomes: List[PredictionOutcome], predictions: Dict[str, Prediction]) -> CalibrationReport:
        # select only resolved CORRECT/INCORRECT/PARTIAL
        scored: List[Tuple[Prediction, PredictionOutcome, float]] = []
        for o in outcomes:
            if o.status in {"CORRECT", "INCORRECT", "PARTIAL"}:
                p = predictions.get(o.prediction_id)
                if not p:
                    continue
                conf = self._normalize_confidence(p.confidence)
                scored.append((p, o, conf))

        if not scored:
            return CalibrationReport(total=0, brier_score=None, buckets=[], notes="No resolved predictions")

        # brier score
        s = 0.0
        n = 0
        for p, o, conf in scored:
            if o.status == "CORRECT":
                y = 1.0
            elif o.status == "PARTIAL":
                y = 0.5
            else:
                y = 0.0
            s += (conf - y) ** 2
            n += 1
        brier = s / n if n > 0 else None

        # Exhaustive confidence buckets; no resolved prediction disappears.
        ranges = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
        buckets: List[CalibrationBucket] = []
        for low, high in ranges:
            bucket_items = [(p, o, conf) for p, o, conf in scored if conf >= low and conf < high]
            sample_size = len(bucket_items)
            correct = sum(1 for (_p, o, _c) in bucket_items if o.status == "CORRECT")
            partial = sum(1 for (_p, o, _c) in bucket_items if o.status == "PARTIAL")
            accuracy = ((correct + 0.5 * partial) / sample_size) if sample_size > 0 else None
            low_conf = sample_size < self.min_sample
            label = f"{int(low*100)}-{int((high if high<=1 else 1.0)*100)}"
            buckets.append(CalibrationBucket(bucket=label, sample_size=sample_size, correct=correct, accuracy=accuracy, low_stat_confidence=low_conf))

        return CalibrationReport(total=n, brier_score=brier, buckets=buckets)
