import yfinance as yf
import json

tickers = ["PETR4.SA","PRIO3.SA","ENAT3.SA","RRRP3.SA","BRDT3.SA","UGPA3.SA"]
out = {}
for t in tickers:
    try:
        tk = yf.Ticker(t)
        info = tk.info
        out[t] = {
            "regularMarketPrice": info.get("regularMarketPrice"),
            "previousClose": info.get("previousClose"),
            "marketCap": info.get("marketCap"),
            "forwardPE": info.get("forwardPE"),
            "trailingPE": info.get("trailingPE"),
            "dividendYield": info.get("dividendYield"),
            "volume": info.get("regularMarketVolume") or info.get("volume"),
        }
    except Exception as e:
        out[t] = {"error": str(e)}
print(json.dumps(out, ensure_ascii=False))
