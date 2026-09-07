# Prontidão para canal educativo — 2026-08-26

## Resultado honesto

O PROMETHEUS está apto a produzir **rascunhos educativos com revisão humana obrigatória**, usando dados oficiais rastreáveis quando disponíveis. Ele **não está apto a ser apresentado como sistema de recomendação, sinal de trading, ou research comercial plenamente homologado**.

O pacote `2.1.0rc2` foi construído duas vezes de forma reproduzível: os ZIPs-fonte e wheels das duas construções possuem hashes idênticos. A suíte atual encerrou com `246 passed`. Os hashes do build pertencem ao manifesto externo, para evitar auto-referência circular do arquivo dentro do próprio ZIP-fonte.

Na estação atual, a política Windows bloqueia a DLL de `pandas` usada por quatro arquivos de teste que importam pandas/yfinance diretamente (`test_prediction_cycle`, `test_yfinance_cache`, `test_b3_cotahist`, `test_cli_exit_codes`). O maior subconjunto independente dessa limitação encerrou com `232 passed` em 2026-08-30; os testes novos de macro point-in-time, exportação educativa e auditoria de release estão nele. Isso não substitui uma suíte integral em ambiente homologado.

O auditor de release integral continua em `FAIL`. Isto é correto: há artefatos legados não entregáveis no diretório de validação, fluxo comercial de exemplo sem bundles atuais, e o backtest `PROMETHEUS_POINT_IN_TIME` ainda não possui as 30 observações independentes exigidas. Um `MOMENTUM_BASELINE` não é substituto dessa validação. Nesta execução, cobertura de catálogo, catálogo de instrumentos, RAD point-in-time e reprodutibilidade de build passaram; portfólio de relatórios, fluxo comercial e backtest continuam pendentes.

Em 2026-08-30, o auditor passou a apontar por padrão para os artefatos `2.1.0rc2` e para o portfólio multissetorial mais recente, eliminando a referência residual à `rc1`. A reexecução resultou em `FAIL` legítimo: os três snapshots arquivados agora recebem `SCORE_DATA_CONTRADICTION` porque seus scores macro e setorial não apresentam a evidência exigida pelo gate atual; não devem ser reutilizados como conteúdo de canal. O backtest do motor próprio continua com zero observações resolvidas e `INSUFFICIENT_EVIDENCE`.

Os manifests de release atuais ficam em `dist/release_current_a/` e `dist/release_current_b/`; ambos são produzidos pelo mesmo builder determinístico e devem ser os argumentos implícitos do auditor. Não use diretórios `launch_final_*` como referência operacional: eles são tentativas históricas de build.

## O que foi reforçado neste corte

- A retenção de conteúdo de IPE agora prioriza release/apresentação trimestral sobre avisos corporativos mais recentes, preservando a ordem pública de metadados.
- O módulo de saúde distingue métricas de operadora das métricas de provedor integrado. Não reutiliza, por exemplo, uma base combinada de saúde+odonto como se fosse somente saúde.
- Identificadores de fonte passam a ser deduplicados durante re-enriquecimento; o registro de claims não pode mais apontar duas evidências diferentes para o mesmo `source_id` posicional.
- Um original IPE que não pôde ser baixado é marcado `METADATA_ONLY_UNAVAILABLE`. Ele gera warning e permanece no inventário, mas não bloqueia o relatório se não sustentar uma afirmação; se sustentar, a ausência de hash/evidência continua bloqueando.
- O caso real RDOR3 (corte 2026-08-25) recuperou 7 de 15 KPIs com hash do PDF oficial, período e protocolo: leitos, ocupação, pacientes-dia, procedimentos, hospitais, beneficiários combinados e sinistralidade consolidada.
- O PDF executivo de RDOR3 foi renderizado e inspecionado visualmente; a tabela de KPI passou a exibir unidades humanas e mantém os campos ausentes como `INSUFFICIENT_DATA`.
- O handoff `scripts/export_educational_brief.py` recusa cortes com blockers, auditoria de claims falha, data source `DEGRADED` ou corte ausente; ele não cria recomendação nem publicação automática.
- A seleção da SELIC para o score macro agora exige `point_in_time_eligible`; uma observação posterior ao corte não pode criar score macro direcional nem elevar a cobertura do research.
- Quando a coleta falha para todos os tickers, o CLI grava, se solicitado, somente `prometheus.collection_failure.v1` com `DATA_COLLECTION_FAILED` e `deliverable: false`; ele não deixa mais um JSON vazio parecer um research válido.
- `scripts/preflight_environment.py` separa dependência nativa, acesso de escrita ao cache e conectividade BCB antes da coleta; `NOT_READY` é diagnóstico operacional, não sinal para usar fallback silencioso.

## Regra operacional para o canal

1. Use apenas PDF cujo gate esteja `APPROVAL_REQUIRED` ou `APPROVED`, sem blockers, e que tenha um revisor humano nominal.
2. Não publique preço-alvo, indicação de compra/venda, prazo de retorno, stop, tamanho de posição ou promessa de desempenho.
3. Transforme apenas fatos com fonte/período visíveis em conteúdo. Interpretação deve aparecer como interpretação; lacunas devem aparecer como limitação.
4. Se a fonte estiver `DEGRADED`, não transforme o corte em post factual: aguarde fonte primária ou publique somente aviso operacional aprovado por humano.
5. Preserve o PDF, manifesto, JSON de auditoria e hash no arquivo editorial antes de publicar qualquer derivado.

### Handoff de conteúdo educativo

O comando `python scripts/export_educational_brief.py --report-json <relatorio.json> --output <brief.json>` cria um handoff JSON compacto para o editor. Ele não escreve posts nem recomendações: só projeta fatos numéricos que tenham fonte, período, data de publicação e hash, e somente se o gate editorial do research não possuir blockers, a auditoria de claims tiver passado e a fonte primária não estiver degradada.

Mesmo quando o handoff é elegível, seu estado é `HUMAN_EDITORIAL_REVIEW_REQUIRED`. Todo texto, arte e adaptação devem continuar sujeitos às cinco regras acima. O comando sai com código `2` quando o research não é elegível; este é o comportamento esperado para relatórios bloqueados, incompletos ou degradados.

## Bloqueios para afirmação de prontidão comercial plena

- Backtest point-in-time do próprio PROMETHEUS com amostra independente suficiente, IC e benchmark setorial.
- Três ou mais relatórios atuais aprováveis, em setores distintos, com bundles comerciais entregues e verificáveis.
- Parecer jurídico brasileiro sobre conteúdo, distribuição, conflitos, LGPD, termos de venda e enquadramento de research.
- Processo de pagamentos, suporte, retenção, correções e pilotos com clientes reais.

Esses bloqueios não devem ser removidos por configuração ou por texto de marketing.
