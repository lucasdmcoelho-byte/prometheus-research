# Registro de hipóteses — VÉRTICE

| ID | Hipótese | Variáveis | Teste | Critério de rejeição | Estado |
|---|---|---|---|---|---|
| H1 | Trajetória contém informação além do fechamento diário | OHLC intradiário, horários | Retornos futuros, MFE/MAE e comparação com referência | Sem melhoria estável sobre referência simples | Aberta; sem teste empírico real |
| H2 | Repiques definidos ex ante têm distribuição condicional diferente | Retornos, drawdown, horizonte | Detector de eventos e controles semelhantes sem sinal | Diferença desaparece fora da amostra ou após custos | Código implementado; sem OHLCV real |
| H3 | Ativo A melhora previsão de B | Retornos sincronizados, defasagens, IBOV | Correlação cruzada e teste OOS incremental | Sem redução consistente de erro OOS | Código implementado; sem série sincronizada |
| H4 | Relações variam por regime/horário | Volatilidade, hora, índice | Avaliação por subperíodo/regime pré-definido | Efeito não robusto a janelas e períodos | Pendente |
| H5 | Algum sinal gera expectativa líquida positiva | Trades simulados, custos, slippage | Backtest cronológico com custos e drawdown | Expectativa OOS não positiva ou incerteza alta | Backtest-base implementado; sem evidência |
| H6 | Horário altera distribuição | Timestamp e retornos | Comparação por blocos horários | Diferenças não replicáveis | Pendente |
| H7 | Volume melhora previsão de repique | Volume e retorno | Modelo-base vs. modelo com volume | Sem melhoria OOS | Pendente |
| H8 | Força relativa contém informação incremental | Retorno ativo, IBOV, setor | Retornos residuais e previsão incremental | Sem melhoria OOS | Parcialmente implementado |
| H9 | Pares reduzem risco | Retornos, betas, custos de short/aluguel | Simulação conjunta e cenários de correlação adversa | Exposição/perdas não melhoram robustamente | Pendente |
| H10 | Notícias/fatores fundamentais melhoram sinal | Timestamp de publicação e variáveis | Modelo incremental sem vazamento temporal | Sem melhoria OOS | Pendente |
| H11 | Resultado persiste com execução realista | Bid/ask, volume, slippage, taxas | Sensibilidade de custos e teste prospectivo | Lucro some em custos plausíveis | Pendente |

Mudanças metodológicas devem gerar nova versão/linha, não sobrescrever o histórico.
