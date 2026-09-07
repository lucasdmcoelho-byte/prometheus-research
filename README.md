# PROMETHEUS Research

Serviço de research financeiro para ações brasileiras no fluxo `ticker → coleta point-in-time → análise → PDF → revisão → aprovação → entrega`.

Consulte [a metodologia](docs/METHODOLOGY.md) e [o runbook operacional](docs/OPERATIONS.md) antes de uso em ambiente controlado.

## Princípios

- Documentos CVM (ITR e DFP) são a fonte contábil primária.
- Dados só podem entrar numa análise depois da data em que foram recebidos/publicados.
- Cada métrica preserva fonte, período, versão e data de disponibilidade.
- Dados ausentes geram limitação explícita; não são substituídos silenciosamente por números atuais.
- Backtests distinguem o pipeline completo do baseline de momentum.
- O resultado é informativo e não constitui recomendação ou garantia de retorno.
- Qualquer consumidor downstream (incluindo futura camada de conteúdo/mídia) deve recusar um snapshot cujo `editorial_gate.deliverable` seja `false` ou que possua o blocker `SEMANTIC_CONTAMINATION`.

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
```

## Research atual e PDF

O catálogo versionado contém 508 correspondências completas entre ticker, ISIN, CNPJ e código CVM; 484 ações/units permanentes estão elegíveis e 24 códigos temporários permanecem bloqueados. O sistema não adivinha emissor por semelhança de nome. A cobertura operacional de um ticker ainda depende de haver documentos oficiais point-in-time suficientes para TTM, peers e valuation.

```powershell
prometheus-research --ticker CURY3 --report-json output\cury3.json --report-pdf output
```

O comando acima gera rascunho não entregável. O fluxo comercial sempre separa geração, revisão, aprovação e entrega:

```powershell
prometheus-research --ticker CURY3 --report-json output\cury3.json --report-pdf output `
  --order-ledger data\orders.jsonl --client-reference PEDIDO-001

# copie o order_id exibido pelo comando anterior
prometheus-research --workflow-action review --order-ledger data\orders.jsonl `
  --order-id ORD-... --actor "Nome do revisor"
prometheus-research --workflow-action approve --order-ledger data\orders.jsonl `
  --order-id ORD-... --actor "Nome do revisor" --workflow-notes "Checklist editorial concluído"
prometheus-research --workflow-action deliver --order-ledger data\orders.jsonl `
  --order-id ORD-... --actor "Operação" --workflow-notes "Entrega confirmada"
prometheus-research --workflow-action verify --order-ledger data\orders.jsonl --order-id ORD-...
```

Geração comercial não pode autoaprovar o próprio PDF. `approve` recalcula o gate ao vivo e valida o release bundle e os hashes; `deliver` verifica novamente os artefatos da versão atual.

Para reproduzir o conjunto de informações disponível ao fim de uma data específica:

```powershell
prometheus-research --ticker CURY3 --as-of 2026-08-16 --report-json output\cury3_20260816.json --report-pdf output
```

Notícias posteriores ao corte, ou sem horário de publicação verificável, não entram na análise histórica.

Para reprodução offline, `--market-snapshot` aceita observações de preço e campos opcionais com proveniência independente. O motor valida `effective_at` e `available_at` de cada campo, rejeita look-ahead e reconcilia fórmulas declaradas. A quantidade de ações é obtida preferencialmente de `composicao_capital` do ITR/DFP da CVM; market cap só é derivado automaticamente por `preço × ações em circulação` quando a companhia possui uma única classe de ações.

Para usar diretamente o histórico oficial da B3, informe o ZIP anual em `--b3-cotahist`. O parser aceita apenas mercado à vista, escolhe o último fechamento cuja disponibilidade conservadora antecede o corte e preserva os hashes do ZIP e do registro.

```powershell
prometheus-research --ticker EGIE3 --instrument-catalog config\instrument_catalog.json `
  --market-snapshot data\market_snapshot.json --as-of 2026-07-29 `
  --report-json output\egie3.json --report-pdf output
```

```powershell
prometheus-research --ticker ITUB4 --instrument-catalog config\instrument_catalog.json `
  --b3-cotahist data\COTAHIST_A2026.ZIP --as-of 2026-08-17 `
  --report-json output\itub4.json --report-pdf output
```

Comparáveis são calculados quando `--tickers` contém ao menos duas empresas do mesmo setor com o mesmo período contábil. Métricas de períodos ou setores distintos não são misturadas:

```powershell
prometheus-research --tickers AAA3 BBB3 --cvm-map config\cvm_codes.json --report-pdf output
```

Para outro ativo, forneça um mapa explícito de ticker para código CVM:

```powershell
prometheus-research --ticker ABCD3 --cvm-map config\cvm_codes.json --report-pdf output
```

O uso de fundamentos secundários exige opt-out explícito:

```powershell
prometheus-research --ticker ABCD3 --allow-secondary-fundamentals
```

## Backtest point-in-time

O modo padrão executa o pipeline completo. Sinais neutros são registrados como `no_trade` e não contaminam a taxa de acerto.

```powershell
prometheus-research --backtest CURY3 --start 2025-01-01 --end 2025-12-31 --horizon 30 --backtest-model prometheus --report-json output\backtest.json
```

O baseline pode ser solicitado para comparação:

```powershell
prometheus-research --backtest CURY3 --start 2025-01-01 --end 2025-12-31 --horizon 30 --backtest-model momentum-baseline
```

## Fontes e cache

- Cadastro CVM: `cad_cia_aberta.csv`.
- ITR/DFP: arquivos anuais do Portal de Dados Abertos da CVM.
- RAD/ENET: fallback estruturado por documento para DFP/ITR quando um ZIP anual ainda não estiver disponível; versão, sequência, protocolo, data de entrega e tabelas brutas ficam no cache.
- Mercado: Yahoo Finance, identificado como fonte secundária.
- Macro: Banco Central do Brasil (Selic 432, IPCA 433, USD/BRL 1 e atividade 24363).
- IPE/FRE: documentos, governança, capital, auditores e partes relacionadas da CVM.
- Cache padrão: `.cache/prometheus`, com atualização diária dos arquivos CVM.

O fallback RAD usa `.cache/prometheus/rad_document_index.json`. O índice é construído de uma exportação HTML completa da consulta oficial e aceita somente DFP/ITR com sequência e protocolo exatos; não há inferência por nome:

```powershell
python scripts\build_rad_index.py consulta_rad.html --output .cache\prometheus\rad_document_index.json --captured-at 2026-08-17T12:00:00 --merge
```

Na primeira leitura de uma sequência, as tabelas estruturadas BPA, BPP, DRE e DFC são preservadas em `.cache/prometheus/rad/<sequência>/`. Colunas comparativas mantêm seu período efetivo e são usadas como `PENULTIMO` somente para o período anterior correspondente. Documentos IPE usados na análise também retêm o arquivo original, SHA-256, tamanho, tipo e resultado de extração; excedentes ficam explicitamente fora do escopo de conteúdo e continuam no inventário.

Para ampliar a cobertura sem inferir identidades, carregue um catálogo versionado com `--instrument-catalog catalog.json`. Cada registro preserva ticker, código CVM, CNPJ, razão social, fonte do ticker e data da fonte; o hash do conteúdo é validado antes da coleta. Depois da configuração, a operação continua exigindo somente o ticker.

Para uma construção ampla inteiramente baseada em identificadores oficiais, use `scripts/build_b3_catalog.py`. Ele cruza o BVBG.028.02 com a base ISIN completa da B3 (`ISIN → CNPJ`) e então com o cadastro de companhias abertas da CVM (`CNPJ → código CVM`). A junção é exata, preserva os hashes dos dois snapshots e não usa similaridade de nomes. Direitos, recibos e códigos temporários ficam registrados para auditoria, mas são marcados como não elegíveis para geração automática de research.

## Validação

A suíte atual possui 192 testes e cobre normalização de unidades, versões/reapresentações CVM, cortes point-in-time, proveniência por campo e por hash, COTAHIST oficial da B3 para relatório e walk-forward, escala da composição acionária reconciliada por EPS, taxonomia bancária, seleção setorial de escala dos peers, propriedades de scoring, calibração, backtest, concorrência do ledger, geração de PDF, rodapés desenhados após tabelas paginadas e ausência de refetch na exportação.

Cenários de valuation não são fabricados: o motor usa P/VP para financeiros, EV/EBIT para setores intensivos em capital e P/L TTM nos demais, sempre com ao menos dois peers elegíveis ou premissa explícita atribuída. EV/EBIT não é rotulado como EV/EBITDA. Caso falte base rastreável, registra `INSUFFICIENT_DATA`. Nenhum score ou relatório constitui garantia de retorno ou substitui adequação, liquidez, tributação e risco individual do investidor.

## Release

```powershell
python scripts\build_release.py dist
```

O processo cria ZIP fonte determinístico, wheel puro Python e manifesto SHA-256 sem depender de uma toolchain externa de build. Consulte também `docs/RESEARCH_SPEC.md`, `docs/EDITORIAL_CHECKLIST.md`, `docs/COMMERCIAL_AND_LEGAL.md` e `docs/RELEASE_AUDIT.md`. A homologação dos artefatos pode ser repetida com `python scripts/audit_release.py`.

A versão atual é `2.1.0rc2`. ITUB4, EGIE3 e CURY3 possuem validação técnica atual sem blockers usando CVM + COTAHIST B3, três modelos setoriais e valuations rastreáveis; os 39 PDF-páginas atuais foram renderizados e inspecionados. A aprovação e entrega registradas nesta RC usam ator explicitamente simulado e não substituem revisão humana comercial. A release não deve ser descrita como comercialmente homologada enquanto o backtest point-in-time não atingir a amostra mínima e `scripts/audit_release.py` não retornar `PASS` para o conjunto completo exigido.
