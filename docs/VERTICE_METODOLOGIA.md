# VÉRTICE — metodologia inicial

## Tese e hipóteses
O projeto testa se trajetórias intradiárias e relações entre ativos contêm informação preditiva condicional. H1: a trajetória contém informação além do fechamento; H2: repiques definidos ex ante têm distribuição condicional diferente; H3: retornos defasados de um ativo melhoram a previsão de outro; H4: relações mudam por horário/regime; H5: algum sinal mantém expectativa líquida positiva após custos.

## Definições
- Retorno em h barras: close[t] / close[t-h] - 1; variação absoluta: close[t] - close[t-h].
- Amplitude de sessão: (max(high)-min(low))/first_open.
- Correlação defasada: corr(r_A[t], r_B[t+h]); h positivo significa que A antecede B por h barras, não causalidade.
- MFE long: max(future_high)/entry - 1; MAE long: min(future_low)/entry - 1.
- Sinal experimental de repique: fechamento abaixo do pico observado numa janela passada por limiar configurável e retorno positivo mínimo frente ao fechamento anterior. Entrada simulada apenas na abertura da barra seguinte.
- Se stop e alvo forem tocados na mesma barra OHLC, assumir stop primeiro por padrão.
- Expectativa líquida é média dos retornos líquidos após custos explícitos.

## Validação
Usar divisão cronológica, modelos-base, teste fora da amostra, sensibilidade a custos e parâmetros, e registro de resultados negativos. Não usar mínimos/máximos retrospectivos como informação disponível no instante do sinal. Uma semana serve para validar o pipeline, não para demonstrar vantagem.

## Limites
OHLCV não revela fila, sequência intrabar, lado agressor nem execução garantida. O modelo de custos simplificado não cobre automaticamente execução parcial, aluguel, tributos ou impacto de mercado. Correlação não demonstra causalidade.
