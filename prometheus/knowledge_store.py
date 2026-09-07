import json
import os
from typing import Any, Dict, List


class KnowledgeStore:
    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def add(self, record: Dict[str, Any]) -> None:
        ticker = record.get("ticker")
        if isinstance(ticker, str):
            record["ticker"] = ticker.strip().upper()
        self.records.append(record)

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self.records)

    def get_by_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        if not isinstance(ticker, str):
            return []
        normalized = ticker.strip().upper()
        return [record for record in self.records if record.get("ticker") == normalized]

    def get_summary(self) -> Dict[str, Any]:
        by_ticker: Dict[str, int] = {}
        for record in self.records:
            ticker = record.get("ticker", "UNKNOWN")
            by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
        return {"total_records": len(self.records), "by_ticker": by_ticker}

    def save_to_file(self, file_path: str) -> None:
        directory = os.path.dirname(file_path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(self.records, handle, ensure_ascii=False, indent=2)

    def load_from_file(self, file_path: str) -> None:
        if not os.path.exists(file_path):
            return

        with open(file_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, list):
            raise ValueError("Knowledge store JSON must contain a list of records.")

        self.records = payload
