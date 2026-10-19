# VÉRTICE — fase 2: auditoria e execução

Data de execução: 19/10/2026. Branch: `vertice/research-phase-1`.

## Verificado
- Repositório acessível: `lucasdmcoelho-byte/prometheus-research`; permissões reportadas pelo conector incluem leitura e escrita.
- Branch `vertice/research-phase-1` existe.
- ZIP local da fase 1 existe em `/mnt/data/vertice-research-phase1.zip`; extraído em `/mnt/data/vertice-research`. O diretório extraído não contém .git.
- Os módulos centrais e documentação foram lidos do ZIP e os módulos centrais foram lidos da branch remota.
- Testes originais executados localmente: 13 passed.
- Três testes adicionais de fronteira entre sessões inicialmente falharam; as falhas revelaram que o resultado de controles podia usar a abertura do pregão seguinte e que a avaliação de repiques podia entrar no pregão seguinte. As duas rotas foram corrigidas.
- Depois das correções e dos novos testes, suíte local: 19 passed.
- Chamadas HTTP reais a brapi.dev e query1.finance.yahoo.com falharam com NameResolutionError: hosts externos não resolvem no container. Nenhum dado intradiário real foi baixado.
- yfinance não está instalado no ambiente; requests, pandas, numpy e pytest estão disponíveis.

## Alterações remotas confirmadas
- `vertice/data_pipeline.py`: retornos intradiários agora reiniciam por data local B3 por padrão; opção explícita `session_aware=False` mantém lags através de datas.
- `vertice/controls.py`: eventos sem barra de entrada na mesma sessão são descartados; horizontes são limitados à sessão.
- `vertice/rebounds.py`: entrada na barra seguinte é rejeitada se ela pertencer a outra sessão.
- Commits retornados pelo GitHub:
  - data_pipeline.py: `efc3e0cb0707e8ebbc59b69fd4ec3137aeb016ee`
  - controls.py: `f27442c696791fc2052c3f6d508c70ad07fba424`
  - rebounds.py: `7803fcc45b3fca7a04da9f5e216a9bf52e1b697a`

## Aquisição
- Criado CLI `scripts/fetch_intraday.py` para brapi/Yahoo, com saída CSV e metadata; sem fallback sintético.
- A aquisição foi tentada diretamente com requests e falhou por resolução DNS; a CLI ainda não pôde ser validada contra resposta real do provedor.
- brapi: docs públicas descrevem candles intradiários; histórico e autenticação variam por endpoint/plano. Yahoo/yfinance tem limite de histórico intradiário recente. B3 oferece produtos históricos oficiais, mas não foi obtido produto intradiário autorizado nesta execução.
- Sem dados OHLCV reais: não calcular backtest, MFE/MAE empíricos, relações defasadas ou expectativa líquida.

## Resultados manuais (não são histórico de candles)
- 151 linhas; 142 com horário; 9 símbolos (8 ações + IBOV); 133 variações entre snapshots com horário.
- Correlação exploratória de retornos de snapshots com IBOV, somente 9 timestamps alinhados: BBAS3 0,613; MOVI3 0,531; RENT3 0,480; MGLU3 0,431; HAPV3 0,412; VALE3 0,343; SMTO3 0,230; LREN3 0,183. Amostra minúscula, timestamps esparsos, sem inferência ou conclusão preditiva.
- Mínimo/máximo dos snapshots não é máximo/mínimo oficial do pregão.

## Pendências científicas
- Nenhuma relação entre ativos foi testada com candles reais.
- Nenhuma hipótese de repique foi testada empiricamente.
- Nenhuma estratégia foi demonstrada lucrativa.
- Execução parcial, bid/ask, livro, leilões, aluguel e taxas de execução não estão modelados por evidência observada.
