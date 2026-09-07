# Mapa de acoplamento setorial

## Origem de verdade e validação

`prometheus/sector_models.py` concentra modelos, KPIs, drivers, riscos e o
vocabulário publicado por setor. `prometheus/semantic_consistency.py` consome
esse contrato para detectar vocabulário de outro setor. `EditorialGate` aplica
a validação ao texto renderizado, KPIs, riscos e claims `INTERPRETATION`.

## Acoplamentos identificados

| Módulo | Estado | Impacto e tratamento |
| --- | --- | --- |
| `operational_kpis.py` | Parcialmente específico por setor | Possui parsers label-anchored para `real_estate` e `healthcare`; os demais modelos preservam `NOT_APPLICABLE` até haver documento e padrão auditável. Não há fallback imobiliário. |
| `peer_universe.py` | Universo mantido | Saúde contém seis emissores compatíveis. Elegibilidade de múltiplo exige preço, capital e período point-in-time, por isso não é forçada por lista. |
| `thesis_engine.py` | Conservador | Setor sem histórico verificável é neutro e o componente indisponível é explicitamente renormalizado no score. |
| `reporting.py` | Apresentação compartilhada | Texto de tese usa `sector_model` do snapshot; o gate bloqueia nome/ticker/setor divergentes antes de publicação. |

## Known issues

1. A expansão de parsers operacionais para os demais setores deve ser baseada em documentos oficiais retidos e padrões explicitamente testados; não deve reutilizar regex de incorporadoras.
2. A elegibilidade de peer para valuation permanece limitada por market cap histórico verificável, não por ausência de nomes no universo.
3. Lint e type-check devem ser obrigatórios no CI; o ambiente local usado nesta validação não conseguiu instalar essas ferramentas.
