import datetime
import time
from typing import Any, Callable, Dict, List

from prometheus.knowledge_store import KnowledgeStore

DataEngineCallable = Callable[[str], Dict[str, Any]]


class ContinuousFeed:
    def __init__(
        self,
        tickers: List[str],
        data_engine: DataEngineCallable,
        knowledge_store: KnowledgeStore,
        interval_seconds: int = 60,
    ) -> None:
        self.tickers = [ticker.strip().upper() for ticker in tickers]
        self.data_engine = data_engine
        self.knowledge_store = knowledge_store
        self.interval_seconds = interval_seconds
        self._running = False

    def collect_once(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for ticker in self.tickers:
            timestamp = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            data = self.data_engine(ticker)
            record = {
                "timestamp": timestamp,
                "ticker": ticker,
                "source": "yfinance",
                "data": data,
                "status": "COLLECTED",
            }
            self.knowledge_store.add(record)
            records.append(record)

        for record in records:
            print(f"\nTimestamp: {record['timestamp']}")
            print(f"Ticker: {record['ticker']}")
            print(f"Source: {record['source']}")
            print(f"Status: {record['status']}")

        return records

    def start(self, iterations: int = 0) -> None:
        self._running = True
        cycle = 0
        print("========================================")
        print("PROMETHEUS CONTINUOUS FEED")
        print("========================================")
        try:
            while self._running:
                self.collect_once()
                cycle += 1
                if iterations > 0 and cycle >= iterations:
                    break
                print("\nAguardando próxima coleta...")
                time.sleep(self.interval_seconds)
        except KeyboardInterrupt:
            print("\nPROMETHEUS FEED STOPPED")
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
