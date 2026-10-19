# VÉRTICE — status da fase 1 (19/10/2026)

## Executado e verificado
- Repositório lucasdmcoelho-byte/prometheus-research encontrado; acesso de escrita confirmado e branch vertice/research-phase-1 criada.
- Pipeline OHLCV, métricas de trajetória, correlação defasada, detector de repiques, grupo de controle de drawdown com separação por sessão, avaliação simples e custos implementados.
- 13 testes unitários passaram no ambiente local.
- Registro manual de preços da conversa organizado em CSV local, explicitamente marcado como observação manual e não OHLCV.

## Executado com limitações
- Análise descritiva de 136 observações manuais de 8 ações, em horários espaçados e sem volume. Calculam-se diferenças apenas entre observações com horário conhecido; preços de fechamento sem horário exato são preservados sem inventar timestamp.
- Maior variação observada entre snapshots inclui RENT3 de R$ 50,77 para R$ 50,93 (+0,315% entre observações separadas por 10 minutos); não é movimento contínuo nem evidência de previsão.

## Não calculado
Nenhum backtest real, expectativa líquida, profit factor, drawdown, correlação defasada ou significância estatística foi calculado com dados históricos OHLCV. Esses resultados permanecem não calculados, não zero.

## Bloqueios
- Sem série OHLCV intradiária histórica real nesta execução.
- Sem bid/ask, livro de ofertas, negócios, volume por intervalo ou dados de execução.
- Host externo não resolveu no ambiente de container; chamadas de download não chegaram ao provedor.

## Próxima ação
Importar candles de 1 minuto OHLCV para MGLU3, benchmark e RENT3/MOVI3/BBAS3/VALE3 sincronizados. Executar quality report, teste de repiques, teste incremental e validação cronológica com custos.
