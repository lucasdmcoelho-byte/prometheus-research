# Metodologia PROMETHEUS

## Escopo

O PROMETHEUS produz research informativo para ações brasileiras. Ele não executa ordens, não avalia a adequação do produto ao investidor e não promete retorno.

## Hierarquia e corte temporal

1. Demonstrações ITR/DFP e documentos IPE/FRE da CVM são fontes primárias.
2. A série SGS 432 do Banco Central é a fonte da meta Selic.
3. Observações de mercado identificadas (incluindo Yahoo Finance) são fontes secundárias para preço, volume e capitalização; preços históricos usam `Close` não ajustado para não incorporar retroativamente eventos corporativos futuros.
4. Notícias são evidência secundária e só entram quando possuem data de publicação válida. Uma manchete prova apenas que a fonte publicou aquele texto; o evento subjacente não vira fato sem fonte primária.

O corte `as_of` é aplicado à disponibilidade, não apenas ao período contábil. Reapresentações com `DT_RECEB` posterior ao corte são excluídas. Cada métrica oficial preserva período, versão, data de recebimento e URL do documento. Quando o pacote anual aberto está temporariamente ausente, o fallback RAD/ENET seleciona a última versão cuja entrega já ocorrera no corte e preserva sequência e protocolo. O estado atual `Ativo/Inativo` não é usado como filtro histórico, pois pode ter mudado depois do corte.

## Unidades e fundamentos

- Crescimentos, margens e ROE usam razão decimal internamente (`0,20 = 20%`).
- Dívida/patrimônio usa múltiplo (`0,70 = 0,70x`).
- Valores contábeis são normalizados para reais conforme `ESCALA_MOEDA`.
- Fluxo de caixa operacional vem da DFC oficial quando os fundamentos CVM estão habilitados.
- Ações em circulação usam `QT_ACAO_TOTAL_CAP_INTEGR - QT_ACAO_TOTAL_TESOURO` da composição de capital do ITR/DFP elegível no corte. Período, versão, protocolo e fórmula são preservados.
- Market cap calculado usa `preço observado × ações em circulação` apenas para emissor de classe única. Emissores com ON e PN exigem capitalização observada por classe ou fonte consolidada; o motor não aplica a fórmula simplificada.
- TTM intermediário usa `YTD atual + DFP anterior - YTD anterior`; `DT_FIM_EXERC` define o período efetivo das colunas de fluxo e a coluna comparativa só é aceita no período anterior que ela representa. Se qualquer componente faltar, não é rotulado como TTM.
- Dados ausentes não são imputados silenciosamente.

## Score e decisão

Os componentes são limitados ao intervalo 0–100. O score da tese usa os pesos documentados no relatório. O score final combina tese, expectation gap, catalisadores, regime e confiança de pricing. A decisão usa score, risco, confiança e evidências; estado neutro produz observação/abstenção, não uma previsão direcional forçada.

O score é uma síntese de evidências, não uma probabilidade de retorno nem um preço-alvo. O campo legado `decision.action` usa apenas `evidence_favorable`, `evidence_mixed` ou `evidence_adverse`; esses estados descrevem a evidência e não significam comprar, manter, reduzir ou vender.

## Research e contradições

O relatório inclui fontes rastreáveis, drivers favoráveis, evidências contrárias, riscos, limitações e contexto setorial. Preço, market cap, ações e enterprise value entram no registro de fontes como qualquer outra afirmação numérica. Fatos reportados pela CVM são `FACT` de fonte primária; crescimentos, margens e razões derivados dessas linhas são `CALCULATION` e exigem a fórmula explícita. A classificação setorial usa `SETOR_ATIV` do cadastro CVM somente quando o snapshot do cadastro já existia no corte. Sem classificação elegível, o texto usa apenas monitores genéricos e não herda KPIs de outro setor.

Os candidatos a peer exigem o mesmo valor oficial de `SETOR_ATIV`, eliminam classes duplicadas do mesmo emissor e são ranqueados por distância logarítmica de market cap ou, na ausência deste, de ativos totais CVM. O cálculo final só aceita períodos contábeis idênticos, disponibilidade conhecida e ao menos dois múltiplos elegíveis. Financeiros usam P/VP; mineração, óleo e gás, utilities, materiais, logística e indústria usam EV/EBIT; os demais usam P/L TTM. EV/EBIT calcula `enterprise value = market cap + dívida líquida` e depois `(TTM EBIT × múltiplo - dívida líquida) / ações`. EBIT nunca é rotulado como EBITDA. Sem base e premissas explícitas, cenários numéricos recebem `INSUFFICIENT_DATA`.

O macro histórico exige não só a data de observação, mas a data em que aquela observação se tornou disponível. Selic e USD/BRL entram quando essa disponibilidade é conhecida. IPCA e atividade sem vintage/publicação preservada ficam fora do score histórico e são marcados `INSUFFICIENT_DATA`; a leitura atual pode usar o timestamp de coleta, sem retroagir.

## Backtest e calibração

Cada sinal histórico reconstrói o pipeline com `as_of` no fim do pregão. O histórico de preços posterior é usado somente para resolver o resultado, nunca como entrada do sinal. O audit trail registra todas as fontes e datas usadas.

Previsões sobrepostas podem ser exibidas como diagnóstico no nível de sinal, mas não sustentam validação comercial independente. O protocolo comercial usa uma subamostra de janelas não sobrepostas. O relatório estatístico apresenta cobertura, abstenção, hit rate, intervalo de Wilson de 95%, retorno médio, erro-padrão, Brier score e comparação com benchmark. Sharpe e drawdown de carteira pertencem ao `PortfolioBacktestEngine`, que impede duplicação de capital.

Uma amostra não sobreposta com menos de 30 previsões resolvidas recebe `INSUFFICIENT_SAMPLE`. Ausência de sinais direcionais produz cobertura zero e não é convertida artificialmente em acerto. Resultado de `MOMENTUM_BASELINE` é comparador, nunca evidência de validação do `PROMETHEUS_POINT_IN_TIME`. O provedor do modelo completo recalcula o gate em cada corte e se abstém quando existe blocker.

## PDF

O PDF é construído exclusivamente do snapshot já avaliado. A exportação não busca novamente fundamentos, mercado ou séries históricas. Gráficos que exigem séries temporais só são exibidos quando essas séries fazem parte do snapshot e preservam o mesmo corte temporal.

## Limitações operacionais

- Disponibilidade e estabilidade de serviços públicos e secundários.
- Cobertura de códigos CVM explicitamente validados.
- Ausência de dados de consenso, microestrutura, tributação e suitability.
- Sentimento lexical de notícias é indicativo e tem baixa confiança.
- Resultados históricos não garantem desempenho futuro.
- Disponibilidade pública de pacotes CVM e documentos RAD pode impedir temporariamente TTM, peers e valuation; isso bloqueia entrega em vez de reduzir silenciosamente o padrão.
