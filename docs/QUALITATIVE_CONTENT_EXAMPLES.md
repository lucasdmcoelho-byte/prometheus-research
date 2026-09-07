# Conteúdo qualitativo — exemplos V1

## V5 — autoria direta via agente (caminho offline)

Há dois caminhos de geração: (a) a integração via API em `prometheus/llm_content.py`,
que requer `ANTHROPIC_API_KEY`, e (b) autoria direta pelo agente/Codex a partir do
pacote factual exportado. Nos dois casos, os mesmos validadores determinísticos
rodam sobre a saída; fatos e fontes permanecem no metadado separado.

### CURY3 — post curto

No primeiro trimestre de 2026, a Cury colocou R$ 2,65 bilhões em lançamentos e
registrou R$ 2,30 bilhões em vendas líquidas. Foram 8.001 unidades lançadas e
7.786 vendidas, com velocidade de vendas de 45,1% no período. Esses números
desenham uma operação em que crédito imobiliário, renda e ritmo comercial andam
juntos.

O ponto de atenção está na ponte entre o movimento comercial e a execução: os
distratos somaram R$ 229,3 milhões no trimestre, enquanto o ticket médio ficou em
R$ 325,4 mil por unidade. A leitura útil é acompanhar como decisões de produto,
financiamento e execução transformam esse volume em resultado — e onde juros,
atrasos ou distratos podem interromper essa sequência.

### CURY3 — roteiro de vídeo (60–90s)

**[0–15s | FALA]** R$ 2,65 bilhões em lançamentos no primeiro trimestre de 2026:
é assim que a história recente da Cury começa.

**[15–35s | CORTE]** No mesmo período, foram R$ 2,30 bilhões em vendas líquidas,
8.001 unidades lançadas e 7.786 vendidas. A velocidade de vendas foi de 45,1%.

**[35–55s | FALA]** Mas volume não encerra a conversa. Os distratos chegaram a
R$ 229,3 milhões, com ticket médio de R$ 325,4 mil por unidade.

**[55–75s | CORTE]** O modelo combina crédito imobiliário, renda e velocidade de
vendas; juros, atrasos e distratos são as tensões que precisam ser observadas.

**[75–90s | ENCERRAMENTO]** A pergunta é simples: quais decisões de execução
fazem esses números continuarem coerentes nos próximos documentos?

### CURY3 — pergunta do momento

Se a Cury lançou R$ 2,65 bilhões e vendeu R$ 2,30 bilhões líquidos no primeiro
trimestre de 2026, como crédito, renda e velocidade de vendas ajudam a explicar
essa diferença — e que evidências nos documentos seguintes mostrariam se os
distratos de R$ 229,3 milhões estão mudando a qualidade desse crescimento?

### Fontes factuais do V5

As afirmações numéricas acima vêm dos KPIs operacionais do pacote
`output/qualitative_v5/CURY3_facts_package.json`, todos referentes a 2026-Q1 e
com hash/protocolo CVM preservados no campo `sources`. O contexto de negócio,
drivers e riscos vem da taxonomia setorial registrada no mesmo pacote.

## V6 — autoria direta, empresa sem KPI validado (ITUB4)

### Pacote de fatos

O pacote legível está em `output/qualitative_v6/ITUB4_facts_package.json`.
Ele contém zero KPIs operacionais validados; o campo `validated_kpis` está vazio
e a limitação correspondente é preservada. Os fatos disponíveis são a
classificação pública de ITUB4 como Bancos e o registro das séries oficiais
`selic_target` e `usd_brl`, com suas fontes e datas.

### Post curto

O corte de 24 de agosto de 2026 coloca duas lentes sobre o Itaú Unibanco: o
pacote registra as séries oficiais de Selic e dólar/real, enquanto o banco opera
no encontro entre captação, crédito e risco. É nessa ponte que a história
específica do Itaú precisa ser lida: decisões de concessão e funding respondem
ao ambiente monetário, mas a qualidade dessa resposta não pode ser reduzida a
um número que o pacote não valida.

O que está documentado é o contexto; o que permanece em aberto é como cada
escolha do banco aparece nos seus indicadores operacionais. A pergunta concreta
para os próximos documentos é quais evidências mostram a transmissão desse
cenário para a execução do Itaú, sem transformar hipótese em resultado.

### Roteiro de vídeo (60–90s)

**[0–15s | FALA]** No corte de 24 de agosto de 2026, o Itaú Unibanco aparece
diante de duas séries oficiais: Selic e dólar/real.

**[15–35s | CORTE]** Para um banco cuja atividade passa por captação, crédito e
risco, essas variáveis ajudam a enquadrar as decisões que ficam nos bastidores.

**[35–55s | FALA]** Mas enquadrar não é medir: este pacote não traz KPI
operacional validado do Itaú.

**[55–75s | CORTE]** Por isso, a investigação começa pelas evidências que os
próximos documentos apresentarem sobre concessão, funding e qualidade do
crédito.

**[75–90s | ENCERRAMENTO]** A questão é: que documento transformaria esse
contexto em uma leitura verificável da execução do Itaú?

### Pergunta do momento

Quando Selic e dólar/real entram no mesmo quadro do Itaú Unibanco, quais decisões
de captação, crédito e risco deveríamos procurar nos documentos para separar
contexto macro de evidência específica do banco?

### Autoavaliação crítica

Revisei as três peças antes da validação. Não há número operacional, percentual,
tendência ou resultado atribuído ao Itaú que não esteja no pacote. As expressões
“duas séries oficiais” e “Selic e dólar/real” apenas reproduzem os fatos
qualitativos disponíveis; nenhuma delas sugere magnitude ou direção. A ausência
de KPI é declarada sem preencher o vazio com média setorial ou estimativa.

### Comparação com a versão anterior (V1/V3)

| Aspecto | Versão anterior | V6 direta |
|---|---|---|
| Abertura | Começava com fragmento quebrado de classificação setorial. | Começa com as duas séries macro registradas no corte e o nome do Itaú. |
| Honestidade sobre dados | Incluía nota técnica e alegava ausência de KPI no texto. | Não inventa KPI; explica o que o pacote permite e o que permanece aberto. |
| Especificidade | Texto genérico para qualquer banco. | Relaciona captação, crédito e risco às duas séries efetivamente registradas para ITUB4. |
| Linguagem | Continha processo/compliance e concatenação defeituosa. | Sem rótulos internos, sem processo e sem clichês banidos. |

As fontes completas de cada afirmação permanecem no pacote JSON; não são
exibidas como IDs dentro da narrativa.

## V7 — adaptações sociais do post V5 (CURY3)

### LinkedIn

R$ 2,65 bilhões em lançamentos e R$ 2,30 bilhões em vendas líquidas: a história recente da Cury começa nesse contraste.

No primeiro trimestre de 2026, foram 8.001 unidades lançadas e 7.786 vendidas, com velocidade de vendas de 45,1%. Crédito imobiliário, renda e ritmo comercial caminham juntos nessa operação.

Os distratos somaram R$ 229,3 milhões, enquanto o ticket médio ficou em R$ 325,4 mil por unidade. O ponto é acompanhar como decisões de produto, financiamento e execução transformam volume em resultado — e onde juros, atrasos ou distratos interrompem essa sequência.

Qual evidência dos próximos documentos você usaria para avaliar essa ponte entre movimento comercial e execução?

Conteúdo informativo e educacional; não é recomendação de investimento.

#MercadoImobiliário #B3 #InvestimentoImobiliário

### X (thread)

1/3 — R$ 2,65 bi em lançamentos e R$ 2,30 bi em vendas líquidas: a história da Cury começa nesse contraste.

2/3 — No 1T26: 8.001 unidades lançadas, 7.786 vendidas e VSO de 45,1%. Distratos: R$ 229,3 mi; ticket médio: R$ 325,4 mil.

3/3 — A pergunta é como crédito, renda e execução transformam volume em resultado — e onde juros, atrasos ou distratos interrompem a sequência. Conteúdo informativo, não recomendação.

### Instagram

R$ 2,65 bilhões em lançamentos. R$ 2,30 bilhões em vendas líquidas. É aqui que a história da Cury começa.

No 1º trimestre de 2026, foram 8.001 unidades lançadas e 7.786 vendidas, com velocidade de vendas de 45,1%. Os distratos somaram R$ 229,3 milhões e o ticket médio ficou em R$ 325,4 mil por unidade.

O que observar: como crédito, renda, produto e execução transformam esse movimento em resultado — e onde juros, atrasos ou distratos podem interromper a sequência.

Qual documento você consultaria primeiro para acompanhar essa ponte?

Conteúdo informativo e educacional; não é recomendação de investimento.

#IncorporadorasB3 #MercadoImobiliário #Investimentos #MercadoFinanceiro #B3 #ConstruçãoCivil #Cury3

Sugestão de carrossel: Slide 1 — contraste de lançamentos e vendas líquidas;
Slide 2 — unidades e velocidade de vendas; Slide 3 — distratos e ticket médio;
Slide 4 — pergunta sobre a ponte entre movimento comercial e execução.

As versões foram validadas contra o mesmo pacote factual V5. LinkedIn e Instagram passaram; os três posts da thread X passaram e têm, respectivamente, 105, 120 e 181 caracteres.

Esta camada é aditiva e exige revisão humana. Ela não altera o Thesis Score,
o gate editorial ou os parsers de KPI. Cada marcador `[id]` aponta para uma
fonte no quadro da respectiva peça; fatos, contexto e limitações permanecem
separados.

## CURY3 — post curto (real estate, com KPI validado)

**Texto gerado**

> Mapa de negócio: Cury (CURY3)
>
> A Cury está classificada publicamente no setor de construção e incorporação
> [classification]. Um evento reportado foi a prévia operacional 1T26
> [news-1]. O cenário macro inclui a série oficial Selic [macro-1]. KPI
> validado: VSO = 0,406 no período 2026-Q1 [kpi-vso].
>
> Por que isso importa? O modelo se relaciona a crédito imobiliário, renda e
> velocidade de vendas. A exposição relevante inclui juros, inflação e
> emprego, além de riscos de distratos, atrasos e execução.
>
> A posição competitiva deve ser entendida pela capacidade de executar esse
> modelo e transformar decisões operacionais em resultados, sem confundir
> contexto com dado auditado.

**Fontes das afirmações factuais**

| ID | Fonte | Data/período | Rastreabilidade |
|---|---|---|---|
| classification | Classificação CVM/B3 do snapshot | corte 2026-08-30 | registro de classificação do snapshot |
| news-1 | CVM IPE / KnowledgeStore | 2026-04-09 | URL do documento e SHA-256 do feed |
| macro-1 | Banco Central — SGS, Selic | 2026-08-30 | URL da série e SHA-256 do artefato |
| kpi-vso | CVM IPE — Release de Resultados 1T26 | 2026-Q1 | URL e SHA-256 `b1e08c3f28f138129bf9a22bc7afc78184811c6f137f627d0530147dfc81e3f5` |

## ITUB4 — roteiro de vídeo (setor sem parser operacional validado)

**Texto gerado**

> [0–10s | FALA] Hoje, o mapa de Itaú Unibanco (ITUB4) começa por um fato:
> Itaú Unibanco está classificado publicamente no setor de bancos
> [classification].
>
> [10–30s | CORTE] O modelo bancário se relaciona a spread, crescimento de
> crédito e captação. A exposição relevante inclui Selic, crescimento de
> crédito e inadimplência.
>
> [30–55s | FALA] A pergunta útil não é adivinhar o mercado, e sim entender
> quais decisões operacionais e riscos podem alterar a execução desse modelo.
>
> [55–75s | CORTE] Não há KPI operacional validado e rastreável para esta
> empresa neste snapshot; o roteiro não usa números operacionais específicos.
>
> [75–90s | ENCERRAMENTO] Este é contexto educacional: fatos e interpretação
> estão separados, e a revisão humana vem antes de publicar.

**Fontes**

| ID | Fonte | Uso |
|---|---|---|
| classification | Classificação CVM/B3 no snapshot | fato sobre o setor |
| macro-1 | Banco Central — SGS, Selic | fato macro contextual |

Limitação: nenhum KPI setorial operacional foi promovido a fato, pois o
extrator validado cobre apenas `real_estate` e `healthcare`.

## EGIE3 — pergunta do momento (evento macro)

**Texto gerado**

> Pergunta do momento: como a exposição da Engie Brasil Energia ao setor de
> energia elétrica se conecta ao dado macro oficial de Selic [macro-1], e por
> que empresas do mesmo setor podem tomar decisões diferentes diante do mesmo
> contexto?
>
> Ponto de reflexão: separe o fato público, a transmissão econômica possível
> e aquilo que ainda não foi validado no snapshot.

**Fontes**

| ID | Fonte | Data |
|---|---|---|
| classification | Classificação CVM/B3 no snapshot | corte 2026-08-30 |
| macro-1 | Banco Central — SGS, Selic | 2026-08-30; SHA-256 `33b81be2657179cfad5a8b52a1291bb94093d554b02f1a41adca5b442599c4b3` |

## Resultado da validação

Os três formatos passam por bloqueio determinístico de linguagem direcional,
checagem de fonte por claim e checagem de ausência de KPI quando não há
validação. Todo material é marcado `human_review_required: true`.

\newpage

# V2 — Storyteller Voice

Os exemplos abaixo usam exatamente os mesmos snapshots e fontes da V1, agora
passando pela camada `StorytellerVoiceEngine`. Metadados de revisão e limitações
continuam fora do texto narrado.

## CURY3 — post curto

> Um número coloca Cury no centro da conversa: KPI validado: lançamentos =
> 2646800000.0 BRL no período 2026-Q1. [kpi-lançamentos]
>
> É aí que o contexto ganha importância: no contexto de construção e
> incorporação, o modelo de negócio se relaciona a crédito imobiliário, renda
> e velocidade de vendas. A exposição relevante inclui Selic, IPCA e emprego,
> além dos riscos de juros, distratos e atrasos.
>
> Cury não é apenas o nome de um setor: é uma história de decisões, execução e
> riscos concretos. O que vale acompanhar é como a empresa responde a esse
> contexto, distinguindo o que foi documentado do que continua sendo uma
> pergunta aberta.

Fontes usadas: `[kpi-lançamentos]` → CVM IPE, Release de Resultados 1T26,
2026-Q1, hash bruto `b1e08c3f28f138129bf9a22bc7afc78184811c6f137f627d0530147dfc81e3f5`.

## ITUB4 — roteiro de vídeo (sem KPI validado)

> [0–10s | FALA] Existe uma tensão interessante em Itaú Unibanco (ITUB4):
> como transformar seu modelo de bancos em execução que se sustenta? O
> snapshot descreve a empresa como Itaú Unibanco está classificada publicamente
> no setor Bancos. [classification]
> [10–30s | CORTE] É aí que o contexto ganha importância: no contexto de
> bancos e serviços financeiros, o modelo de negócio se relaciona a spread,
> crescimento de crédito e captação. A exposição relevante inclui Selic,
> crescimento de crédito e inadimplência. Ainda não dá para confirmar por um
> número oficial quanto dessa dinâmica já virou resultado operacional.
> [30–55s | FALA] Em Itaú Unibanco, a pergunta humana é o que precisa acontecer
> nos bastidores para essa história continuar fazendo sentido.
> [55–75s | CORTE] O fato está na fonte citada; a interpretação é uma lente
> para pensar o negócio, não uma promessa sobre o mercado.
> [75–90s | ENCERRAMENTO] Qual parte dessa história você investigaria primeiro?

Fontes usadas: `[classification]` → classificação CVM/B3 no snapshot, corte
2026-08-30. Nenhum número operacional foi incluído porque não há KPI validado.

## EGIE3 — pergunta do momento

> O que a história de Engie Brasil Energia revela sobre selic_target: por que
> esta empresa, com seu modelo de energia elétrica, enfrenta essa tensão de um
> jeito próprio? [macro-1]
>
> A pergunta não é adivinhar o próximo movimento, mas identificar quais
> decisões e evidências separariam narrativa de realidade.

Fontes usadas: `[macro-1]` → Banco Central do Brasil — SGS, Selic,
2026-08-30, SHA-256
`33b81be2657179cfad5a8b52a1291bb94093d554b02f1a41adca5b442599c4b3`.

## Validação V2

Os três formatos V2 passam pela mesma validação de fonte, números e linguagem
direcional da V1. A camada adicional também rejeita termos de processo, como
`human_review_required`, “revisão humana”, “o roteiro não usa” e “conteúdo
educacional”, no texto voltado ao público. O metadado `human_review_required`
continua presente na peça para o fluxo editorial.

# V3 — geração via LLM com gate

Os textos abaixo foram produzidos pelo contrato LLM (`LLMQualitativeGenerator`)
com o provedor local restrito, pois `ANTHROPIC_API_KEY` não estava configurada
nesta execução. Em produção, o adaptador usa Anthropic sem chave hardcoded. O
gate determinístico foi aplicado após a geração; todos passaram na primeira
tentativa (`generation_attempts: 1`). IDs de fonte permanecem somente no
metadado, nunca no texto visível.

## CURY3 — post curto

> Um número coloca Cury no centro da conversa: KPI validado: lançamentos = R$
> 2,65 bilhões no período 2026-Q1.
>
> O contexto ajuda a ler esse fato: no contexto de construção e incorporação,
> o modelo de negócio se relaciona a crédito imobiliário, renda e velocidade
> de vendas. A exposição relevante inclui juros básicos, inflação e emprego,
> além dos riscos de juros, distratos e atrasos.
>
> Cury é uma história de decisões, execução e riscos concretos. O que vale
> acompanhar é como a empresa responde a esse contexto, distinguindo o que foi
> documentado do que continua sendo uma pergunta aberta.

Fonte factual usada: KPI de lançamentos do Release de Resultados 1T26, CVM IPE,
2026-Q1, SHA-256
`b1e08c3f28f138129bf9a22bc7afc78184811c6f137f627d0530147dfc81e3f5`.

## ITUB4 — roteiro de vídeo

> [0–10s | FALA] Existe uma tensão interessante em Itaú Unibanco (ITUB4):
> como transformar seu modelo de bancos em execução que se sustenta? Os
> registros públicos descrevem a empresa como Itaú Unibanco está classificada
> publicamente no setor Bancos.
> [10–30s | CORTE] O contexto ajuda a ler esse fato: no contexto de bancos e
> serviços financeiros, o modelo de negócio se relaciona a spread, crescimento
> de crédito e captação. A exposição relevante inclui juros básicos,
> crescimento do crédito, inadimplência, além dos riscos de inadimplência,
> pressão de spread e liquidez. Ainda não dá para confirmar por um número
> oficial quanto dessa dinâmica já virou resultado operacional.
> [30–55s | FALA] Em Itaú Unibanco, a pergunta humana é o que precisa acontecer
> nos bastidores para essa história continuar fazendo sentido.
> [55–75s | CORTE] O que ainda falta entender é quais decisões mudariam essa
> história na prática.
> [75–90s | ENCERRAMENTO] Qual parte dessa história você investigaria primeiro?

Fonte factual usada: classificação CVM/B3 do snapshot, corte 2026-08-30.
Nenhum KPI operacional foi incluído.

## EGIE3 — pergunta do momento

> O que a história de Engie Brasil Energia revela sobre os juros básicos: por
> que esta empresa, com seu modelo de energia elétrica, enfrenta essa tensão de
> um jeito próprio?
>
> A pergunta não é adivinhar o próximo movimento, mas identificar quais
> decisões e evidências separariam narrativa de realidade.

Fonte factual usada: Banco Central do Brasil — SGS, série Selic, 2026-08-30,
SHA-256
`33b81be2657179cfad5a8b52a1291bb94093d554b02f1a41adca5b442599c4b3`.

## Resultado V3

Os três exemplos passaram no gate após uma tentativa. Números foram formatados
pela função central `format_human_number`; nomes de campos internos e IDs não
aparecem no texto; conteúdo com falha após três tentativas seria retornado apenas
como `generation_failed: true`, sem publicação do rascunho.

# V4 — geração real via API (bloqueada neste ambiente)

Esta seção não contém textos fabricados. Em 31/08/2026, `ANTHROPIC_API_KEY` não
estava definida no ambiente, portanto o gerador agora recusa a execução com
`RuntimeError` explícito. Não há texto, tabela de fontes ou log de resposta para
CURY3, ITUB4 ou EGIE3 que possa ser honestamente apresentado como saída real da
API. Após configurar a chave, cada peça deverá registrar `provider`, `model`,
`input_tokens`, `output_tokens`, `response_id` e `observed_at` em `api_call`.
