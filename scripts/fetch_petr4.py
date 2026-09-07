import yfinance as yf
import json

ticker = yf.Ticker("PETR4.SA")
info = ticker.info
out = {
    "symbol": "PETR4.SA",
    "regularMarketPrice": info.get("regularMarketPrice"),
    "previousClose": info.get("previousClose"),
    "marketCap": info.get("marketCap"),
    "forwardPE": info.get("forwardPE"),
    "trailingPE": info.get("trailingPE"),
    "dividendYield": info.get("dividendYield"),
    "volume": info.get("regularMarketVolume") or info.get("volume"),
}
print(json.dumps(out, ensure_ascii=False))
