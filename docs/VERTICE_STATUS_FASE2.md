# VÉRTICE — fase 2: auditoria e execução

Data de execução: 19/10/2026. Branch remota: `vertice/research-phase-1`.

## Verificado
- Repositório acessível: `lucasdmcoelho-byte/prometheus-research`; conector reportou permissões de leitura e escrita.
- Branch `vertice/research-phase-1` existe.
- ZIP local da fase 1 foi encontrado e extraído em `/mnt/data/vertice-research`. O diretório extraído não contém `.git`.
- Módulos centrais e documentação foram lidos do ZIP e da branch remota.
- Testes originais executados localmente: 13 passed.
- Testes adicionais de fronteira entre sessões inicialmente falharam e revelaram que controles e repiques podiam usar a abertura do pregão seguinte. As rotas foram corrigidas.
- Após correções, testes de fronteira, retornos por sessão e dimensionamento de risco: suíte de testes do pacote VÉRTICE extraído, 24 passed; a suíte completa do repositório Prometheus não foi executada nesta sessão.
- Chamadas HTTP a brapi.dev e query1.finance.yahoo.com falharam com `NameResolutionError`: hosts externos não resolvem no container. Nenhum OHLCV intradiário real foi baixado.
- `yfinance` não está instalado; `requests`, `pandas`, `numpy` e `pytest` estão disponíveis.

## Alterações remotas confirmadas
- `vertice/data_pipeline.py`: retornos intradiários reiniciam por data local B3 por padrão; opção explícita `session_aware=False` mantém lags entre datas.
- `vertice/controls.py`: eventos sem barra de entrada na mesma sessão são descartados; horizontes limitados à sessão.
- `vertice/rebounds.py`: entrada na barra seguinte rejeitada se pertencer a outra sessão.
- Commits: data_pipeline `efc3e0cb0707e8ebbc59b69fd4ec3137aeb016ee`; controls `f27442c696791fc2052c3f6d508c70ad07fba424`; rebounds `7803fcc45b3fca7a04da9f5e216a9bf52e1b697a`.
- Criado `scripts/fetch_intraday.py` para aquisição real via brapi/Yahoo, sem fallback sintético, e testes de regressão.
- Adicionado `vertice/risk.py`: dimensionamento de posição limitado por risco até stop e exposição bruta; cálculo de exposição bruta/líquida. Cenários de capital são hipotéticos, sem conexão a corretora.

## Fontes e cobertura
- brapi documenta candles intradiários de 1 minuto e até 7 dias de histórico intradiário; plano/endpoint determinam acesso: https://brapi.dev/faq/quais-sao-os-timeframes-disponiveis
- yfinance documenta limite de 60 dias para dados intradiários: https://github.com/ranaroussi/yfinance/blob/main/yfinance/multi.py
- B3 publica cotações históricas de mercado à vista, incluindo OHLC diário e número de negócios; isso não é, por si só, feed gratuito de candles de 1 minuto: https://www.b3.com.br/en_us/market-data-and-indices/data-services/market-data/historical-data/equities/historical-quote-data/
- A CLI de aquisição foi executada; falhou por DNS antes de receber resposta HTTP. Não se pode confirmar cobertura real do ticker nesta execução.

## Observações manuais (não são candles)
- 151 linhas; 142 com horário; 9 símbolos (8 ações + IBOV); 133 variações entre snapshots com horário.
- Correlações exploratórias entre retornos de snapshots e IBOV: 11 retornos alinhados por par. BBAS3 0,613; MOVI3 0,531; RENT3 0,480; MGLU3 0,431; HAPV3 0,412; VALE3 0,343; SMTO3 0,230; LREN3 0,183. Amostra muito pequena e irregular; não inferir precedência temporal, previsão ou causalidade.
- Extremos entre snapshots não são máximas/mínimas oficiais do pregão.
- Relatório reproduzível: `scripts/manual_snapshot_analysis.py`; saídas `reports/manual_snapshot_analysis.json` e `reports/manual_snapshot_interval_changes.csv`.

## Pendências científicas
- Nenhuma relação entre ativos foi testada com candles reais.
- Nenhuma hipótese de repique foi testada empiricamente.
- Nenhuma estratégia foi demonstrada lucrativa.
- Sem bid/ask, livro, negócios, execução, leilões, aluguel e custos efetivamente observados.


## Empacotamento
- `pyproject.toml` foi atualizado para incluir `vertice*` na descoberta de pacotes e declarar `pandas`, `numpy` e `requests`, necessários ao módulo quantitativo. A verificação de instalação editável foi realizada no pacote local extraído; não foi possível executar GitHub Actions a partir desta sessão.


## Proveniência do dataset manual
- O CSV de snapshots manual não foi commitado no repositório remoto. O pacote local distribuído contém `data/manual_observations_2026-10-19.csv`; ao executar o script num checkout remoto sem esse arquivo, passe `--input /caminho/para/arquivo.csv`. Isso evita que um dataset de origem manual seja confundido com dado oficial ou incluído silenciosamente no repositório.
- A qualidade do dataset manual foi calculada localmente: 151 linhas, 142 com horário, 9 sem horário, 9 símbolos, zero duplicações de símbolo+timestamp, zero preços ausentes/não positivos; gaps entre snapshots de 4 a 12 minutos, mediana 7.
