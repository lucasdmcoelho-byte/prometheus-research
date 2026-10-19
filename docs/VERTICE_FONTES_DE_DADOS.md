# VÉRTICE — auditoria inicial de fontes

Consulta documental realizada em 19/10/2026. Cobertura e condições comerciais devem ser confirmadas antes de usar dados em pesquisa ou redistribuição.

## B3 oficial
- Histórico: https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/
- A página lista cotações históricas do mercado à vista e boletins por pregão. A documentação consultada não confirma um feed gratuito completo de candles de 1 minuto para todas as ações; granularidade, formato, custo e licença devem ser confirmados para o produto específico.

## brapi.dev
- Histórico: https://brapi.dev/docs/acoes/historico
- Timeframes: https://brapi.dev/faq/quais-sao-os-timeframes-disponiveis
- A documentação lista OHLC, volume e intervalos intradiários. A FAQ indica janela curta para intraday; limites dependem do plano e a rota histórica pode exigir autenticação. Verificar cobertura por ticker, fuso, limites e termos.

## Yahoo Finance / yfinance
- Implementação do histórico: https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py
- O código documenta intervalos intradiários e limitação de histórico recente. A cobertura pode variar e não é fonte oficial de execução B3.

## Status de acesso
A documentação foi localizada, mas o ambiente de execução não conseguiu resolver hosts externos ao tentar baixar dados. Nenhuma série OHLCV real foi obtida. A base manual da conversa não é usada como candle nem como backtest.

## Requisitos de aprovação
1. MGLU3 e ativos de controle no mesmo intervalo.
2. Timestamp/fuso verificáveis, OHLCV e tratamento de leilões/lacunas documentados.
3. Origem, data de extração, frequência, licença e checksum preservados.
4. Exportação local CSV e ausência de credenciais no repositório.
