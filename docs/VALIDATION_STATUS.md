# PROMETHEUS 2.1.0rc2 — estado de validação

Data: 2026-08-18.

## Resultado executivo

Esta versão é uma **release candidate técnica**, não uma release comercial homologada. O software falha de forma segura quando faltam dados e impede aprovação nominal de relatórios bloqueados. Isso é evidência de controle editorial, não evidência de qualidade preditiva ou autorização para venda pública.

## Evidências executadas

- suíte completa inicial: `192 passed`; após a ingestão FCA e as regressões associadas, `215 passed` em 2026-08-23;
- catálogo: 508 identidades exatas B3/CNPJ/CVM, sendo 484 elegíveis e 24 bloqueadas;
- EGIE3 real no corte de 2026-07-29: TTM `AVAILABLE`, receita TTM de R$ 13.255.663.000 reconciliada pela fórmula `YTD atual + FY anterior - YTD anterior` e protocolo DFP v2 `017329DFP311220250200155137-61`;
- gate EGIE3: `BLOCKED` somente por `VALUATION_INCOMPLETE`;
- workflow real: `REQUESTED → GENERATED → IN_REVIEW`; a tentativa de `APPROVED` saiu com código 2 e não alterou o ledger;
- integridade: ledger e hashes dos artefatos passaram; o bundle recusou aprovação pelo gate ao vivo;
- PDF: CURY3 (12), ITUB4 (11), PETR4 (12) e EGIE3 (13), totalizando 48 páginas renderizadas e inspecionadas;
- regressão visual corrigida: o rodapé agora é pintado depois do conteúdo, evitando que tabelas divididas entre páginas o cubram;
- ITUB4 real no corte de 2026-08-17: preço oficial B3 de R$ 39,00, 11.021.872.000 ações reconciliadas por lucro atribuível e EPS, patrimônio de R$ 228.026.000.000 e P/VP corrente de 1,89x;
- peers bancários: classe de instrumento priorizada, escala superior a 4x excluída e P/VP ajustado de forma explícita pelo ROE anualizado; base mecânica de R$ 38,65, com bear de R$ 30,92 e bull de R$ 46,38;
- gate ITUB4: `APPROVAL_REQUIRED`, sem blockers e com 59/59 afirmações verificadas;
- PDF ITUB4 atual: 13 páginas renderizadas e inspecionadas; metodologia de ajuste por ROE aparece nominalmente na narrativa;
- lote atual: ITUB4, EGIE3 e CURY3 com gate `APPROVAL_REQUIRED`, zero blockers, 180/180 afirmações verificadas e valuations disponíveis em três modelos setoriais distintos;
- PDFs atuais: 13 páginas por empresa, 39 páginas renderizadas e inspecionadas sem cortes, colisões ou gráficos ilegíveis;
- workflow positivo **simulado** para as três empresas: `REQUESTED → GENERATED → IN_REVIEW → APPROVED → DELIVERED`, ator `RC2 QA Simulation`, ledger com 15 entradas, artefatos e bundles `PASS`; nenhum arquivo foi enviado a cliente;
- auditor de portfólio: relatórios, portfólio multissetorial, fluxo comercial, cobertura, catálogo, RAD point-in-time e build reproduzível `PASS`; estado global `FAIL` exclusivamente pela amostra insuficiente do backtest completo;
- backtest: preços de sinal e resolução agora usam o COTAHIST oficial local, sem depender de Yahoo; o teste histórico abstém explicitamente quando a classificação setorial oficial só ficou disponível depois da data analisada;
- release: ZIP fonte, wheel e manifestos são produzidos por duas builds determinísticas e comparados por SHA-256;
- auditor comercial endurecido: exige pelo menos três relatórios atuais, três tickers e três modelos setoriais distintos antes de permitir `PASS`;
- ZIP original da área de trabalho é apenas fonte de leitura e seu hash deve permanecer `E0FAB1E8EF1EBDB968D127B14A4E8F4A57F39AF4AEFDFCF31A849091DD4BCC1D`.

## O que ainda impede homologação comercial

1. O modelo completo precisa produzir backtest `PROMETHEUS_POINT_IN_TIME` com janelas não sobrepostas, pelo menos 30 observações resolvidas, IC 95% e benchmark setorial. A fonte histórica FCA removeu as abstenções por classificação e valuation no controle real, mas o sinal permaneceu `no_trade/evidence_mixed`; a execução auditada continua com 0 observações resolvidas. Não é permitido aplicar o cadastro atual retroativamente.
2. O fluxo positivo passou em simulação multissetorial; ainda precisa ser repetido por um revisor humano real antes de uma entrega comercial.
3. Advogado, contador, meio de pagamento e clientes-piloto permanecem dependências externas.

Os PDFs presentes no pacote de validação estão tecnicamente elegíveis para revisão, mas não possuem aprovação humana comercial. Nenhum deve ser enviado a cliente sem essa etapa.

## Atualização de 2026-08-23 — classificação setorial histórica

### Diagnóstico exaustivo do universo local

O diagnóstico de disponibilidade percorreu todas as janelas de preço resolvíveis no COTAHIST local, e não apenas CURY3. O universo contém 484 instrumentos elegíveis no catálogo, 396 com cotações oficiais no arquivo de 2026 e 181.276 combinações ticker/data/horizonte nos horizontes de 5, 15, 30 e 60 dias. A tabela linha a linha está em `validation/backtest_abstention_windows.csv`; os agregados e hashes dos inputs estão em `validation/backtest_abstention_summary.json`.

Antes da ingestão do FCA, os dois blockers ocorriam juntos nas 181.276 janelas (100% cada):

| Motivo | 5 dias | 15 dias | 30 dias | 60 dias | Total |
|---|---:|---:|---:|---:|---:|
| `SECTOR_CLASSIFICATION_UNAVAILABLE_POINT_IN_TIME` | 50.692 | 48.049 | 44.732 | 37.803 | 181.276 |
| `VALUATION_INCOMPLETE` | 50.692 | 48.049 | 44.732 | 37.803 | 181.276 |

Portanto, nenhum dos dois era isoladamente dominante. A indisponibilidade setorial era a causa a montante: o resolver caía corretamente em `general`, não formava um universo exato de peers e, por consequência, o valuation permanecia incompleto. A frequência observada de `VALUATION_INCOMPLETE` era igual, não menor.

O CSV é uma enumeração exaustiva dos gates de disponibilidade, não uma substituição pelo backtest completo. Executar o pipeline integral nas 181.276 janelas seria redundante e impraticável (o controle real pós-FCA consumiu 273 segundos por sinal porque reconstrói demonstrações e dezenas de peers). As decisões, blockers editoriais adicionais e resultados resolvidos continuam sendo medidos apenas pelo motor real.

### Investigação das fontes oficiais

- O conjunto **Cias Abertas: Informação Cadastral** da CVM informa expressamente que representa o último dia útil e tem atualização diária. Ele não é um histórico e não pode ser retroagido: https://dados.cvm.gov.br/dataset/cia_aberta-cad
- O conjunto **Formulário Cadastral (FCA)** possui histórico desde 2010 e conteúdo estruturado por versão. O arquivo `fca_cia_aberta_geral` contém `Setor_Atividade`, `Codigo_CVM`, `Data_Referencia`, `Versao` e `ID_Documento`; o arquivo índice contém `DT_RECEB` e `LINK_DOC`: https://dados.cvm.gov.br/dataset/cia_aberta-doc-fca
- O conjunto **Formulário de Referência (FRE)** também possui histórico desde 2010 e descreve atividades do emissor, mas as tabelas estruturadas publicadas não fornecem uma classificação setorial canônica com vigência. Converter narrativa de atividades em setor exigiria julgamento e não foi usado: https://dados.cvm.gov.br/dataset/cia_aberta-doc-fre
- A B3 publica uma classificação setorial corrente e declara atualização semanal: https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/acoes/consultas/classificacao-setorial/
- A B3 informa que a classificação é revisada periodicamente quando mudam os produtos/serviços relevantes, mas a consulta pública encontrada não fornece snapshots históricos nem início/fim de vigência por CNPJ: https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/acoes/consultas/criterio-de-classificacao/

Conclusão: não existe, nas consultas oficiais examinadas, uma série pública versionada da taxonomia setorial B3 com intervalo de vigência. Existe, porém, uma fonte oficial viável para o campo de atividade setorial da CVM: cada versão do FCA. Essa fonte é adequada ao resolver já usado pelo PROMETHEUS, que mapeia `Setor_Atividade` da CVM para o modelo setorial interno.

### Regra temporal implementada

O PROMETHEUS seleciona a última versão do FCA cuja `DT_RECEB` seja menor ou igual ao cutoff e cuja `Data_Referencia` não esteja no futuro. A classificação só passa a valer para o motor em `DT_RECEB`, nunca retroativamente em `Data_Referencia`. A validade termina na próxima versão recebida conhecida. Cada resultado preserva ano, versão, ID do documento, URL do documento, URL do ZIP e SHA-256 do ZIP bruto.

Arquivos oficiais usados na validação:

| Ano | SHA-256 do ZIP FCA |
|---|---|
| 2024 | `b3be3910cee26598143556f8c6758bb79c7ab98a8069931e473b46e924a9debc` |
| 2025 | `5f1986b16d3376272cbbf864bbffb1c1b71ec11bac11a0dde03980026fd33ad3` |
| 2026 | `ac9566113e0bee866d4018bfca744e29e8094b0ecf6df20982202e3b2897056d` |

Não existe fallback para aplicar a classificação corrente em datas anteriores à disponibilidade do snapshot. Se nenhum FCA estiver disponível até o cutoff, o resultado continua `INSUFFICIENT_DATA`.

### Resultado real após a ingestão

No mesmo sinal CURY3 de 2026-06-01, o motor completo passou a produzir:

- classificação FCA point-in-time `AVAILABLE`;
- peer analysis `AVAILABLE`, com quatro múltiplos elegíveis;
- valuation `AVAILABLE`;
- gate editorial `APPROVAL_REQUIRED`, sem blockers;
- `abstention_reasons: []`.

Foi corrigida uma inconsistência de ordem revelada por esse teste: o bridge de `business_quality` era calculado antes de o enriquecimento de peers substituir o valuation. Agora ele é recalculado contra o mesmo valuation pós-enriquecimento antes do gate; nenhuma fórmula ou limiar foi alterado.

Apesar disso, o sinal continuou `no_trade` porque a decisão determinística foi `evidence_mixed`. Assim, o backtest executado ainda possui **0 observações resolvidas de 30 mínimas**. A correção dos dados removeu os blockers setorial e de valuation, mas não constitui evidência de validação preditiva nem autoriza marcar o release como `PASS`.

### Auditoria final sem supressões

`scripts/audit_release.py` foi executado sem supressões contra os artefatos finais. O resultado em `validation/release_audit_post_fca.json` é **FAIL**, exclusivamente porque o bloco `backtest` permanece `FAIL` com 0 previsões e 0 observações resolvidas de 30 mínimas. Relatórios, portfólio multissetorial, fluxo comercial, cobertura, catálogo, RAD point-in-time e release reproduzível estão `PASS`.

A suíte integral terminou com `215 passed in 111.41s`. Duas builds limpas produziram hashes idênticos para o ZIP fonte e para o wheel; os hashes canônicos constam nos manifestos finais da release.
