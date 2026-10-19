"""Summarize user-reported snapshots; not a continuous-market backtest."""
from argparse import ArgumentParser
from pathlib import Path
from vertice.manual_observations import load_manual_snapshots, snapshot_returns

def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="CSV containing timestamp_local,symbol,price,source,observation_type,notes")
    parser.add_argument("--output", help="Optional path to save interval changes as CSV")
    args = parser.parse_args()
    x = load_manual_snapshots(args.input)
    y = snapshot_returns(x)
    timed = y[y.timestamp.notna()].dropna(subset=["delta"]).copy()
    print(f"rows={len(y)} timed_rows={int(y.timestamp.notna().sum())} symbols={y.symbol.nunique()}")
    report = timed.assign(abs_delta=lambda z: z.delta.abs()).nlargest(12, "abs_delta")
    print(report[["timestamp_local","symbol","previous_price","price","delta","return_pct","minutes_since_previous"]].to_string(index=False))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        y.to_csv(args.output, index=False)

if __name__ == "__main__":
    main()
