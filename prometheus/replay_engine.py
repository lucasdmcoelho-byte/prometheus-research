import datetime
import json
from typing import Any, Dict, List, Optional

from prometheus.models import ThesisEvidence


class ReplayEngine:
    def __init__(self):
        self.records: List[Dict[str, Any]] = []

    def record(self, point_in_time_data: Dict[str, Any]) -> None:
        self.records.append(point_in_time_data)

    def save(self, file_path: str) -> None:
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(self.records, handle, ensure_ascii=False, indent=2)

    def load(self, file_path: str) -> None:
        with open(file_path, "r", encoding="utf-8") as handle:
            self.records = json.load(handle)

    def playback(self, handler: Any) -> List[Dict[str, Any]]:
        results = []
        for record in self.records:
            replayed = handler(record)
            results.append(replayed)
        return results

    def summarize(self) -> Dict[str, Any]:
        return {
            "record_count": len(self.records),
            "period_start": self.records[0].get("timestamp") if self.records else None,
            "period_end": self.records[-1].get("timestamp") if self.records else None,
        }
