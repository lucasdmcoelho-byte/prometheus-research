# VÉRTICE — auditoria inicial de fontes

Consulta documental realizada em 19/10/2026. Cobertura e condições comerciais devem ser confirmadas antes de usar dados em pesquisa ou redistribuição.

## B3 oficial
- Histórico: https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/
- A página lista cotações históricas do mercado à vista e boletins por pregão. O boletim oficial de pesquisa por pregão informa restrições expressas contra coleta automatizada dessa página. Não fazer scraping dessa página; usar downloads e produtos oficiais nos termos aplicáveis.
- Fonte: página histórica B3 e aviso da página de pesquisa por pregão.

## brapi.dev
- Histórico: https://brapi.dev/docs/acoes/historico
- Timeframes: https://brapi.dev/faq/quais-sao-os-timeframes-disponiveis
- A documentação v2 descreve candles OHLCV e intervalos de 1m, 2m, 5m, 15m, etc. A FAQ especifica até 7 dias para intraday; planos têm limites diferentes para histórico diário e acesso. A API documenta token Bearer; alguns tickers/rotas antigas podem funcionar sem token, mas não presumir que o endpoint histórico v2 funcione sem autenticação.
- É uma opção de prototipagem, sujeita à cobertura do ticker, limites, disponibilidade, preço e termos.

## Yahoo Finance / yfinance
- Implementação do histórico: https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py
- O código documenta intervalos intradiários e informa que intraday não se estende além dos últimos 60 dias. A cobertura pode variar e não é fonte oficial de execução B3.

## Status de acesso
A documentação foi localizada, mas o ambiente de execução não conseguiu resolver hosts externos ao tentar baixar dados. Nenhuma série OHLCV real foi obtida. A base manual da conversa não é usada como candle nem como backtest.

## Requisitos de aprovação
1. MGLU3 e ativos de controle no mesmo intervalo.
2. Timestamp/fuso verificáveis, OHLCV e tratamento de leilões/lacunas documentados.
3. Origem, data de extração, frequência, licença e checksum preservados.
4. Exportação local CSV e ausência de credenciais no repositório.
