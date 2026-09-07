from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


class BCBSeriesClient:
    """Point-in-time client for Banco Central do Brasil SGS series."""

    BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
    SERIES = {
        "selic_target": {"code": 432, "unit": "percent_per_year", "availability": "same_day_effective"},
        "ipca": {"code": 433, "unit": "percent_month", "availability": "current_snapshot_only"},
        "usd_brl": {"code": 1, "unit": "BRL_per_USD", "availability": "same_day_effective"},
        "economic_activity": {"code": 24363, "unit": "index", "availability": "current_snapshot_only"},
    }

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        self.cache_dir = Path(cache_dir) / "bcb" if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(
        self,
        code: int,
        start_date: dt.date,
        end_date: dt.date,
        as_of: Optional[dt.datetime] = None,
    ) -> List[Dict[str, Any]]:
        payload: List[tuple[Dict[str, Any], str, str]] = []
        for year in range(start_date.year, end_date.year + 1):
            range_start = dt.date(year, 1, 1)
            range_end = dt.date(year, 12, 31)
            params = urllib.parse.urlencode({
                "formato": "json",
                "dataInicial": range_start.strftime("%d/%m/%Y"),
                "dataFinal": range_end.strftime("%d/%m/%Y"),
            })
            url = f"{self.BASE_URL.format(code=int(code))}?{params}"
            year_payload = self._load_year(int(code), year, url)
            digest = hashlib.sha256(
                json.dumps(year_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            payload.extend((item, url, digest) for item in year_payload)
        cutoff = (as_of or dt.datetime.combine(end_date, dt.time.max)).date()
        observations = []
        retrieved_at = dt.datetime.utcnow().replace(microsecond=0)
        definition = next((item for item in self.SERIES.values() if item["code"] == int(code)), {})
        availability_policy = definition.get("availability", "current_snapshot_only")
        current_snapshot_eligible = cutoff >= retrieved_at.date()
        for item, source_url, source_sha256 in payload:
            observation_date = dt.datetime.strptime(item["data"], "%d/%m/%Y").date()
            if observation_date < start_date or observation_date > end_date or observation_date > cutoff:
                continue
            point_in_time_eligible = (
                availability_policy == "same_day_effective" or current_snapshot_eligible
            )
            publication_date = (
                observation_date.isoformat()
                if availability_policy == "same_day_effective"
                else retrieved_at.isoformat() + "Z" if point_in_time_eligible
                else None
            )
            observations.append({
                "date": observation_date.isoformat(),
                "value": float(str(item["valor"]).replace(",", ".")),
                "source": "Banco Central do Brasil - SGS",
                "source_url": source_url,
                "source_sha256": source_sha256,
                "publication_date": publication_date,
                "series_code": int(code),
                "availability_policy": availability_policy,
                "point_in_time_eligible": point_in_time_eligible,
                "retrieved_at": retrieved_at.isoformat() + "Z",
                "availability_limitation": (
                    None if point_in_time_eligible else
                    "SGS exposes the observation period but not a historical publication vintage; value excluded from historical scoring."
                ),
            })
        return sorted(observations, key=lambda item: item["date"])

    def _load_year(self, code: int, year: int, url: str) -> List[Dict[str, Any]]:
        if self.cache_dir is None:
            return self._download_json(url)
        cache_path = self.cache_dir / f"sgs_{code}_{year}.json"
        cache_is_fresh = (
            cache_path.exists()
            and (year < dt.date.today().year or time.time() - cache_path.stat().st_mtime < 86400)
        )
        if cache_is_fresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        payload = self._download_json(url)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def latest_selic(self, as_of: Optional[dt.datetime] = None) -> Optional[Dict[str, Any]]:
        cutoff = as_of or dt.datetime.utcnow()
        observations = self.fetch(
            code=self.SERIES["selic_target"]["code"],
            start_date=cutoff.date() - dt.timedelta(days=45),
            end_date=cutoff.date(),
            as_of=cutoff,
        )
        if not observations:
            return None
        latest = dict(observations[-1])
        latest.update({
            "metric": "selic_target",
            "unit": self.SERIES["selic_target"]["unit"],
        })
        return latest

    def latest_indicators(self, as_of: Optional[dt.datetime] = None, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        cutoff = as_of or dt.datetime.utcnow()
        selected = names or list(self.SERIES)
        output = []
        for name in selected:
            definition = self.SERIES.get(name)
            if not definition:
                continue
            observations = self.fetch(
                code=definition["code"], start_date=cutoff.date() - dt.timedelta(days=120),
                end_date=cutoff.date(), as_of=cutoff,
            )
            if observations:
                latest = dict(observations[-1])
                latest.update({"metric": name, "unit": definition["unit"]})
                if latest.get("point_in_time_eligible", True):
                    output.append(latest)
                else:
                    output.append({
                        "metric": name, "unit": definition["unit"],
                        "status": "INSUFFICIENT_DATA",
                        "reference_date": latest.get("date"),
                        "series_code": definition["code"],
                        "point_in_time_eligible": False,
                        "reason": latest.get("availability_limitation"),
                        "source": latest.get("source"), "source_url": latest.get("source_url"),
                    })
        return output

    def _download_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": "PROMETHEUS/1.0 research@example.invalid"})
        with urllib.request.urlopen(request, timeout=30.0) as response:
            return json.loads(response.read().decode("utf-8"))
