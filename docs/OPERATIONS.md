# Operação e quality gates

## Execução reproduzível

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
prometheus-research --ticker CURY3 --as-of 2026-08-16 --report-json output\cury3.json --report-pdf output
```

O PDF sempre nasce como rascunho. `--require-deliverable` não é aceito durante a geração e a geração comercial não pode usar `--reviewer` para autoaprovar. Use `--order-ledger` para registrar pedido, PDF, release bundle e hashes; depois execute ações separadas.

Para separar geração, revisão, aprovação e confirmação de entrega, gere primeiro sem `--reviewer`. O pedido fica em `GENERATED`; depois opere o mesmo `order_id`:

```powershell
prometheus-research --workflow-action review --order-ledger data\orders.jsonl --order-id ORD-... --actor "Maria Analista"
prometheus-research --workflow-action approve --order-ledger data\orders.jsonl --order-id ORD-... --actor "Maria Analista" --workflow-notes "Checklist editorial concluído"
prometheus-research --workflow-action deliver --order-ledger data\orders.jsonl --order-id ORD-... --actor "Operação" --workflow-notes "Envio ao cliente confirmado"
prometheus-research --workflow-action verify --order-ledger data\orders.jsonl --order-id ORD-...
```

O ledger usa lock entre processos, sequência global, hash da entrada anterior, hash canônico da entrada atual e `fsync`. Um snapshot obsoleto não pode criar uma bifurcação. `IN_REVIEW`, `APPROVED`, `DELIVERED` e correções exigem ator nominal; aprovação e entrega exigem notas. Artefatos são vinculados à versão, e aprovação/entrega falham se o PDF, o JSON de release, o ticker, o corte, a versão, o QA ou qualquer SHA-256 divergir.

O diretório `.cache/prometheus` guarda ZIPs da CVM, cache anual do BCB e dados auxiliares. O ano corrente é atualizado diariamente; anos encerrados são tratados como imutáveis.

### Pré-voo do ambiente

Antes de gerar, validar ou publicar um corte, rode:

```powershell
python scripts\preflight_environment.py --cache-dir .cache\prometheus --check-network
```

O resultado `READY` confirma imports de `pandas`, `yfinance`, `reportlab` e `pypdf`, escrita no cache e conectividade mínima com o BCB. `NOT_READY` não deve ser contornado com dados inventados ou publicação de relatório antigo. Corrija a dependência/DLL ou a conectividade e repita o pré-voo. O comando não coleta research e não altera snapshots; apenas cria e remove um arquivo de prova no diretório de cache.

Arquivos oficiais IPE selecionados para análise são retidos no cache com SHA-256, tamanho, media type e texto extraído quando legível. O limite operacional atual inclui conteúdo dos 12 primeiros documentos materiais por consulta; os demais continuam inventariados como `METADATA_ONLY_OUT_OF_SCOPE`. Documento incluído sem arquivo bruto bloqueia o gate; PDF escaneado ou erro de extração gera revisão visual obrigatória.

### Contingência oficial RAD/ENET

Se um ZIP anual ITR/DFP estiver ausente no Portal de Dados Abertos, exporte a página completa do resultado da consulta oficial RAD e atualize o índice atômico:

```powershell
python scripts\build_rad_index.py rad_egie_2026.html --output .cache\prometheus\rad_document_index.json --captured-at 2026-08-17T12:00:00 --merge
```

O parser descarta linhas sem data válida, sequência ou protocolo e aceita apenas ITR/DFP. O cliente seleciona a última versão entregue até `as_of`, abre a página ENET em sessão com cookies e armazena as tabelas estruturadas em `.cache/prometheus/rad/<sequência>/`. Preserve o HTML de consulta exportado e seu SHA-256 junto do lote operacional. Uma captura posterior pode indexar documentos antigos porque a seleção usa a data oficial de entrega; o campo atual de status não é usado para reconstruir o passado.

## Catálogo amplo de instrumentos B3

Use uma tabela de vínculo revisada com as colunas `ticker,cvm_code,cnpj,company_name,ticker_source_date` e, preferencialmente, `b3_corporation_name,isin`. Baixe e preserve o ZIP oficial point-in-time BVBG.028.02 da B3. Gere o catálogo somente depois de validar ticker/nome/ISIN contra a B3 e código CVM/CNPJ/razão social/situação ativa contra a CVM:

```powershell
python scripts\import_instrument_catalog.py --instruments b3_reviewed.csv --b3-instruments-zip IN260814.zip --cvm-registry cad_cia_aberta.csv --ticker-source "B3 BVBG.028.02" --output config\instrument_catalog.json
prometheus-research --ticker PETR4 --instrument-catalog config\instrument_catalog.json
```

O ZIP bruto e seu SHA-256 devem ser retidos com a release. O importador de CSV revisado continua disponível como contingência. Para a rotina automática, use também a base ISIN oficial, que fornece o CNPJ ausente no BVBG.028.02; ausência ou ambiguidade resulta em rejeição, não em correspondência aproximada.

Construção automática recomendada com duas fontes oficiais B3:

```powershell
python scripts\build_b3_catalog.py --b3-instruments-zip pesquisa-pregao.zip --b3-isin-zip isinp.zip --cvm-registry cad_cia_aberta.csv --output config\instrument_catalog.json --audit-output instrument_catalog_audit.json
```

A base ISIN oficial fornece `ISIN → emissor → CNPJ`; o BVBG.028.02 fornece `ticker → ISIN`; o cadastro CVM fornece `CNPJ → código CVM`. Somente ações e units de classes permanentes recebem `research_eligible=true`. Instrumentos temporários permanecem no catálogo auditável, mas não entram no mapa usado pela CLI.

Qualquer divergência rejeita o catálogo inteiro; não há correspondência aproximada por nome. O catálogo inclui hash canônico, fonte do ticker e data da fonte. Sua renovação deve fazer parte da rotina operacional antes de atender um ticker novo.

## Gate de release

- Suíte determinística integralmente verde.
- Build de wheel sem dependências baixadas durante o build.
- Research real com fundamentos CVM e Selic BCB.
- Todas as datas de publicação menores ou iguais ao `analysis_as_of`.
- JSON e PDF derivados do mesmo snapshot.
- PDF renderizado e inspecionado em todas as páginas.
- Nenhum cenário numérico fictício quando faltam premissas.
- `qa_status` diferente de `error`; score reconstruído exatamente.
- Claims numéricos com fonte, unidade, período e disponibilidade; cálculo com fórmula e estimativa com premissas.
- Matriz de contradições presente e peers com ao menos dois períodos compatíveis.
- Backtest comercial usa `PROMETHEUS_POINT_IN_TIME`, janelas não sobrepostas, pelo menos 30 resultados resolvidos, intervalo de confiança e benchmark setorial; baseline de momentum nunca comprova o modelo.
- Hashes SHA-256 publicados para os artefatos.
- `scripts/audit_release.py` retorna `PASS` para todos os artefatos atuais; nenhum resultado antigo é aceito por exceção.

## Falhas e degradação

- Sem código CVM: falha explícita; configure `--cvm-map` ou faça opt-out consciente com `--allow-secondary-fundamentals`.
- Sem documento oficial elegível no corte: falha explícita.
- Sem Selic: o pipeline continua, registra a ausência e usa o comportamento macro-base.
- Sem notícia: sentimento neutro; nenhuma manchete é fabricada.
- Sem peers compatíveis ou premissas de valuation: `INSUFFICIENT_DATA`.
- Snapshot de mercado offline: cada campo pode declarar `value`, `unit`, `effective_at`, `available_at`, `source`, `source_url`, `source_sha256` e `formula` dentro de `fields`. Datas posteriores ao corte, valores estruturais não positivos, fórmulas desconhecidas e reconciliações inconsistentes são bloqueados.
- Composição de capital: o pipeline lê o quadro oficial incluído nos ZIPs ITR/DFP, seleciona a última versão publicada até o corte e subtrai ações em tesouraria. Não substitua esse quadro por quantidade atual ao reproduzir uma análise histórica.
- Setor e peers: preserve o `cad_cia_aberta.csv` observado em cada data. Um arquivo de cadastro posterior ao corte é recusado para classificação histórica. Com catálogo amplo, os peers são selecionados automaticamente pelo mesmo `SETOR_ATIV`, um ticker por emissor, proximidade de escala e período compatível; cada critério fica no JSON.
- Sem DFP anterior no ZIP agregado: tente o índice RAD oficial. Sem documento estruturado elegível no corte, TTM recebe `INSUFFICIENT_DATA` ou `PARTIAL`; annualização linear é fallback rotulado, nunca TTM falso.
- Sem amostra estatística: `INSUFFICIENT_SAMPLE`.
- Série macro histórica sem timestamp de publicação/vintage: `INSUFFICIENT_DATA`; a observação atual pode ser exibida com timestamp de coleta, mas não entra retroativamente no score.
- Notícia secundária: fato limitado à publicação da manchete; o evento subjacente permanece `SECONDARY_REPORT_UNVERIFIED` até fonte primária.

## Correções e versões

Relatório entregue não é sobrescrito silenciosamente. Registre `CORRECTION_REQUESTED` com motivo; a geração seguinte incrementa `version`, calcula novos hashes e passa novamente por revisão/aprovação. Preserve o ledger JSONL e os artefatos anteriores conforme a política de retenção aprovada.

## Solução de problemas

- `HTTP 404` em arquivo anual CVM: confirme o índice oficial e use somente o fallback RAD/ENET documentado; não use espelho não aprovado. Sem sequência/protocolo verificáveis, o pipeline degrada para insuficiência explícita.
- Yahoo lento: peers usam preço/market cap com timeout; registros indisponíveis não entram na mediana.
- `INVALID_TEXT_ENCODING`: texto secundário corrompido é removido e denominação CVM tem prioridade.
- `PDF_QA_ERROR`: corrija reconciliação ou conteúdo antes de fornecer revisor.
- Wheel sem dependências: instale o wheel normalmente para resolver dependências; `--no-deps` só é válido em ambiente que já as possua.

## Monitoramento

Em produção, capture duração, status das fontes, idade do cache, quantidade de métricas oficiais, data contábil, cobertura de sinais e exceções por ticker. Não descarte silenciosamente erros de fonte no processo supervisor.

## Estado desta release candidate

`2.1.0rc2` não é uma homologação comercial. ITUB4, EGIE3 e CURY3 passaram pela validação técnica atual com B3/CVM e por um workflow multissetorial explicitamente simulado, mas isso não substitui revisor humano nem backtest do modelo completo com amostra suficiente. Consulte `RELEASE_AUDIT.md`.
