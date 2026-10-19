# Resultados VÉRTICE — fase 2

Data da auditoria: 19/10/2026. Dataset empírico disponível: snapshots manuais informados pelo usuário em 19/10/2026.

## Auditoria e testes
- Branch `vertice/research-phase-1` existe e os módulos centrais foram examinados.
- Testes da fase 1 reproduzidos localmente: 13 passed.
- Testes de regressão foram acrescentados após falhas reais revelarem risco de cruzamento de pregões. Com correções locais de retornos por sessão, eventos de controle, repiques e dimensionamento de risco, 22 testes do pacote VÉRTICE extraído passaram no ambiente local; a suíte completa do repositório Prometheus não foi executada nesta sessão.
- Alterações remotas confirmadas nos módulos `data_pipeline.py`, `controls.py`, `rebounds.py`; módulo `risk.py` e script de aquisição adicionados.

## Aquisição de dados reais
Tentativas de baixar dados de brapi.dev e Yahoo Finance falharam antes de obter resposta HTTP, por falha de resolução DNS no ambiente de execução. Nenhum arquivo OHLCV real foi obtido. `yfinance` não estava instalado. O script de aquisição foi criado para executar localmente, mas não foi validado contra uma resposta real de provedor nesta execução.

## Dados manuais processados
Arquivo: `data/manual_observations_2026-10-19.csv`.
- 151 linhas totais.
- 142 observações com timestamp.
- 9 símbolos: BBAS3, HAPV3, IBOV, LREN3, MGLU3, MOVI3, RENT3, SMTO3 e VALE3.
- 133 variações entre observações com horário; intervalos irregulares entre snapshots.
- 9 preços finais sem horário exato preservados sem atribuição artificial de timestamp.
- Relatório: `reports/manual_snapshot_analysis.json`; alterações entre snapshots: `reports/manual_snapshot_interval_changes.csv`.

Correlação de Pearson entre retornos de snapshots sincronizados e IBOV, 11 observações alinhadas por par: BBAS3 0,613; MOVI3 0,531; RENT3 0,480; MGLU3 0,431; HAPV3 0,412; VALE3 0,343; SMTO3 0,230; LREN3 0,183. São estatísticas descritivas de uma amostra pequena, irregular e não validada independentemente. Não medem lead-lag, capacidade preditiva, causalidade nem lucratividade.

## O que permanece não calculado
- Não há resultados de repiques com candles OHLCV reais.
- Não há MFE/MAE empírico, teste de continuação/falha, correlações defasadas intradiárias nem melhoria preditiva fora da amostra com dados reais.
- Não há backtest realista nem expectativa líquida, profit factor ou drawdown de estratégia.
- Não há evidência de que qualquer estratégia seja lucrativa.

## Artefatos de execução
- `scripts/fetch_intraday.py`: CLI para brapi/Yahoo; falha explicitamente se rede, autenticação ou resposta não permitir aquisição.
- `scripts/manual_snapshot_analysis.py`: reproduz a análise descritiva de snapshots.
- `vertice/risk.py`: dimensionamento por risco ao stop e limites de exposição long/short, sem envio de ordens.
- `docs/VERTICE_STATUS_FASE2.md`: registro da auditoria, correções e bloqueios.
