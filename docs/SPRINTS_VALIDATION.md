# Validação dos Sprints de Integridade

## Evidência executada

- Sprint 1: o gate editorial bloqueia `SEMANTIC_CONTAMINATION` no texto publicado e em claims de interpretação. A execução sequencial CURY3 → HAPV3 no corte 2026-08-23 não apresentou esse blocker.
- Sprint 2: o catálogo setorial é a fonte de vocabulário do gate. O extrator de saúde produziu beneficiários, ticket médio e sinistralidade a partir do release oficial retido da HAPV3. O conjunto compatível de saúde contém RDOR3, SAUD3, DASA3, FLRY3, ONCO3 e MATD3; somente RDOR3 possuía market cap histórico verificado, portanto valuation continua abstendo corretamente.
- Sprint 3: componentes indisponíveis são removidos e seus pesos são renormalizados. O snapshot expõe `score_availability.evidence_coverage`. A validação final mostrou 80% para CURY3 e HAPV3, com `valuation_margin` indisponível. Notícias carregam categoria, materialidade, direção, duração esperada e confiança determinísticas. Cada geração expõe Research Report e Audit Appendix a partir do mesmo snapshot.

## Resultado final real

No corte 2026-08-23, CURY3 não teve blockers. HAPV3 teve somente `VALUATION_INCOMPLETE`; esse blocker é intencional e não deve ser removido sem pelo menos dois comparáveis com evidência de mercado e período verificáveis.

Uma validação sequencial adicional CURY3 → HAPV3 → PETR4 no mesmo corte não encontrou `SEMANTIC_CONTAMINATION` nos três snapshots. PETR4 foi classificada como `oil_gas` e permaneceu bloqueada somente por `VALUATION_INCOMPLETE`.

| Ticker | KPIs disponíveis | Peers compatíveis | Peers elegíveis para múltiplo | Cobertura de evidência |
| --- | ---: | ---: | ---: | ---: |
| CURY3 | 16/18 | 6 | 3 | 80% |
| HAPV3 | 4/8 | 6 | 1 | 80% |
| PETR4 | 0/0 (sem parser setorial publicado) | 4 | 0 | 80% |

## Ferramentas de qualidade

Os testes focados dos sprints passaram. O ambiente desta validação não contém `mypy` ou `ruff`; uma instalação isolada também não concluiu e foi encerrada sem alterar o ambiente global. Resultados de lint/type-check não foram alegados. Antes de uma release externa, instale as dependências de desenvolvimento e execute esses validadores em CI.
