# VÉRTICE — execução local

## Requisitos
Python 3.11+ recomendado; pandas, numpy e pytest. Este módulo não envia ordens.

## Importar dados OHLCV
O CSV deve conter: timestamp, symbol, open, high, low, close, volume. Timestamps devem incluir offset/fuso; timestamps sem fuso serão rejeitados, a menos que seja informado explicitamente.

Exemplo:
```python
from vertice.data_pipeline import load_ohlcv_csv, quality_report, add_returns
bars = load_ohlcv_csv("data/ohlcv.csv")
print(quality_report(bars).to_dict())
features = add_returns(bars, horizons=(1, 3, 5, 10))
```

## Testes
No checkout do repositório:
```bash
python -m pytest -q
```

## Pesquisa de repiques
Use vertice.rebounds.ReboundConfig para fixar a janela, drawdown, bounce e horizonte. A entrada simulada ocorre na abertura da barra seguinte. Use vertice.controls.detect_drawdown_controls para construir um grupo de eventos de drawdown sem o critério de recuperação e forward_event_outcomes para comparar retornos futuros. A comparação inicial não faz matching estatístico de volatilidade; adicione controles por regime antes de qualquer conclusão.

## Limites
A implementação é um protótipo de pesquisa. O modelo de custo é simplificado; candles OHLC não permitem reconstruir fila, execução parcial nem sequência intrabar. Nenhum parâmetro padrão foi validado como lucrativo.
