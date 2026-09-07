# Fluxo operacional de aprovação

O fluxo usa o `DeliveryWorkflow` existente; não há estado paralelo.

1. **Pedido:** registrar ticker, cliente/referência não sensível e corte.
2. **Geração:** executar o pipeline e salvar JSON, PDF, fontes e hashes.
3. **Gate automático:** validar point-in-time, fontes, fórmulas, completude e
   coerência. `BLOCKED` nunca segue para entrega.
4. **Revisão humana:** revisor nominal confere corte, identidade, KPIs,
   limitações, tese/antítese, valuation, disclaimers e ausência de linguagem
   direcional. Reprovar se houver erro factual, fonte ausente, contradição ou
   dado não rastreável; registrar correção e gerar nova versão.
5. **Aprovação nominal:** registrar ator, declaração de conflito de interesses,
   notas e versão exata aprovada.
6. **Entrega:** somente artefatos aprovados são enviados ao cliente.
7. **Registro:** ledger append-only conserva pedido, transições, versão,
   hashes do JSON/PDF e eventuais correções.

Pendências externas (jurídico, LGPD, pagamento e piloto) não são substituídas
por este fluxo técnico.
