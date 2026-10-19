"""Fetch real intraday OHLCV from brapi or Yahoo Finance when network permits.

Examples:
  python scripts/fetch_intraday.py --provider brapi --symbols MGLU3 --range 1d --interval 1m --output data/raw/mglu3_1m.csv
  python scripts/fetch_intraday.py --provider yahoo --symbols MGLU3.SA '^BVSP' --period 5d --interval 1m --output data/raw/mglu3_ibov_1m.csv

No synthetic bars are generated. Failures are explicit. Respect provider terms,
coverage, authentication and rate limits. Intraday history is provider-limited.
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd


def fetch_brapi(symbols: list[str], period: str, interval: str) -> pd.DataFrame:
    import requests
    token = os.getenv("BRAPI_TOKEN")
    url = "https://brapi.dev/api/quote/" + ",".join(symbols)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(url, params={"range": period, "interval": interval}, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()
    records = []
    for item in payload.get("results", []):
        symbol = item.get("symbol") or item.get("requestedSymbol")
        for bar in item.get("historicalDataPrice", []) or []:
            ts = pd.to_datetime(bar.get("date"), unit="s", utc=True, errors="coerce")
            if pd.isna(ts):
                continue
            records.append({"timestamp": ts, "symbol": symbol,
                **{k: bar.get(k) for k in ("open", "high", "low", "close", "volume")},
                "source": "brapi", "provider_symbol": item.get("requestedSymbol")})
    if not records:
        raise RuntimeError(f"brapi returned no historical bars; response keys={list(payload.keys())}; payload excerpt={json.dumps(payload)[:800]}")
    return pd.DataFrame(records)


def fetch_yahoo(symbols: list[str], period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf
    frames = []
    for symbol in symbols:
        data = yf.download(symbol, period=period, interval=interval, auto_adjust=False,
                           progress=False, prepost=False, threads=False)
        if data.empty:
            continue
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        data = data.rename(columns={"Open":"open", "High":"high", "Low":"low", "Close":"close", "Volume":"volume"})
        data.index = pd.to_datetime(data.index, utc=True)
        data.index.name = "timestamp"
        data = data.reset_index()
        data["symbol"], data["source"], data["provider_symbol"] = symbol, "yfinance/Yahoo Finance", symbol
        frames.append(data[["timestamp", "symbol", "open", "high", "low", "close", "volume", "source", "provider_symbol"]])
    if not frames:
        raise RuntimeError("Yahoo Finance returned no bars for requested symbols/period/interval")
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=["brapi", "yahoo"], required=True)
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--range", default="1d", help="brapi range, e.g. 1d, 5d, 7d")
    ap.add_argument("--period", default="5d", help="Yahoo period; intraday history is provider-limited")
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    try:
        data = fetch_brapi(args.symbols, args.range, args.interval) if args.provider == "brapi" else fetch_yahoo(args.symbols, args.period, args.interval)
        data = data.sort_values(["symbol", "timestamp"], kind="stable").drop_duplicates(["symbol", "timestamp"], keep="last")
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True); data.to_csv(output, index=False)
        metadata = {"provider": args.provider, "symbols_requested": args.symbols,
            "symbols_returned": sorted(data.symbol.dropna().unique().tolist()), "rows": len(data),
            "start_utc": str(data.timestamp.min()), "end_utc": str(data.timestamp.max()),
            "interval_requested": args.interval, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "output": str(output.resolve()), "synthetic": False}
        output.with_suffix(output.suffix + ".metadata.json").write_text(json.dumps(metadata, indent=2))
        print(json.dumps(metadata, indent=2)); return 0
    except Exception as exc:
        print(f"DATA_ACQUISITION_FAILED provider={args.provider} error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
