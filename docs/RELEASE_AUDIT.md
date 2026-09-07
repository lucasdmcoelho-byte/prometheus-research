# PROMETHEUS 2.1.0rc2 — auditoria de prontidão

Data da auditoria: 2026-08-18. Estado global atual: **RELEASE CANDIDATE — NÃO ENTREGÁVEL A CLIENTE SEM REVISÃO HUMANA**.

Esta matriz separa implementação, validação empírica e dependências externas. `PASS SOFTWARE` significa que o controle existe e possui teste executável. Só existe homologação comercial quando `scripts/audit_release.py` retorna `PASS` para relatórios, PDFs, ledger, bundles, cobertura, backtest do modelo completo e validação RAD atuais.

| # | Requisito | Estado honesto | Evidência e pendência |
|---|---|---|---|
| 1 | Identidade B3/CNPJ/CVM | PASS SOFTWARE + DADOS REAIS | Catálogo oficial com 508 identidades completas; 484 ações/units permanentes elegíveis e 24 instrumentos temporários bloqueados. A junção preserva ticker, ISIN, CNPJ B3, CNPJ CVM, código CVM, método e hashes. |
| 2 | Histórico, intermediários e TTM | PASS SOFTWARE + VALIDAÇÃO MULTISSETORIAL | Linhas brutas, unidades, períodos, versões e recebimento são preservados. TTM usa `YTD atual + FY anterior - YTD anterior`. ITUB4, EGIE3 e CURY3 foram reconciliadas com artefatos oficiais atuais. |
| 3 | Documentos oficiais point-in-time | PASS SOFTWARE; DISPONIBILIDADE EXTERNA PARCIAL | ITR/DFP agregados, RAD/ENET, FRE e IPE respeitam corte. Os primeiros documentos materiais são retidos com hash, tamanho, tipo e extração; excedentes ficam marcados como metadata-only. O ZIP DFP 2025 publicado pela CVM em 2026-08-17 está retido por hash; ausência de documentos específicos continua degradando explicitamente. |
| 4 | Módulos setoriais | PASS SOFTWARE | Saúde, imobiliário, financeiro, mineração, petróleo e gás, varejo, utilities, logística, telecom, materiais, agro/alimentos, educação, tecnologia/mídia, indústria e fallback geral. Cada modelo declara KPIs, drivers, riscos, macro, benchmark e métodos. |
| 5 | Peers automáticos | PASS SOFTWARE + VALIDAÇÃO MULTISSETORIAL | Mesmo `SETOR_ATIV` oficial, emissor único, período idêntico, classe de instrumento priorizada e escala máxima de 4x. Setores intensivos em balanço usam ativos para evitar circularidade com valuation; ITUB4, EGIE3 e CURY3 possuem ao menos dois peers elegíveis. Preços B3 e fatos CVM transportam hashes. |
| 6 | Valuation rastreável | PASS SOFTWARE + VALIDAÇÃO MULTISSETORIAL | P/VP ajustado por ROE anualizado para financeiros, EV/EBIT para setores intensivos em capital e P/L TTM nos demais. Os três relatórios atuais possuem cenários, fórmulas, premissas, fontes e limitações explícitas. Não são preços-alvo ou recomendação. |
| 7 | Negócio, moat, concorrência e governança | PASS SOFTWARE; REVISÃO HUMANA OBRIGATÓRIA | Business quality, FRE, capital allocation, riscos, catalisadores, contradições e thesis breakers. Moat sem evidência permanece `UNPROVEN`. A qualidade analítica final continua sendo responsabilidade do revisor nominal. |
| 8 | Notícias e macro | PASS SOFTWARE COM LIMITAÇÕES EXPLÍCITAS | IPE e notícias secundárias são separadas; manchete secundária não confirma evento. Selic/USD admitem uso histórico datado. Séries sem vintage de publicação conhecido ficam fora de score histórico e retornam `INSUFFICIENT_DATA`. |
| 9 | Técnicos determinísticos | PASS SOFTWARE | Preço não ajustado, SMA, RSI, volatilidade, volume e tendência entram só como contexto; não há entrada, saída, stop ou posição. |
| 10 | Registro de afirmações | PASS SOFTWARE | Ledger com FACT, CALCULATION, INTERPRETATION, ESTIMATE, RISK e LIMITATION. |
| 11 | Proveniência numérica | PASS SOFTWARE | Valor numérico exige unidade, período, disponibilidade e fonte; cálculo exige fórmula; estimativa exige premissas. Fatos CVM e componentes de peers exigem hash de artefato bruto. |
| 12 | Gate editorial | PASS SOFTWARE | Bloqueia look-ahead, fonte ou hash ausente, TTM incompleto, períodos incompatíveis, valuation inconsistente, contradição omitida, documento oficial não retido e QA inválido. Aprovação requer pessoa e notas. |
| 13 | PDF premium | PASS VISUAL MULTISSETORIAL | ITUB4, EGIE3 e CURY3 possuem 13 páginas cada; as 39 páginas exatas do lote auditado foram renderizadas e inspecionadas, sem cortes, colisões ou gráficos ilegíveis. |
| 14 | Fluxo comercial | PASS SOFTWARE + SIMULAÇÃO MULTISSETORIAL | As três empresas percorreram localmente `REQUESTED → GENERATED → IN_REVIEW → APPROVED → DELIVERED`; ledger com 15 entradas, hashes, artefatos e bundles passaram. O ator foi deliberadamente `RC2 QA Simulation`, portanto a evidência não substitui aprovação humana real nem representa envio a cliente. |
| 15 | Backtest walk-forward/OOS | IMPLEMENTADO; EVIDÊNCIA COMERCIAL AUSENTE | O motor impõe janelas não sobrepostas, amostra mínima 30, intervalo de confiança e benchmark. Preços de sinal e resolução usam o COTAHIST oficial. A execução diagnóstica abstém porque a classificação setorial disponível foi capturada depois da data testada; aplicar o mapa atual ao passado seria look-ahead. Faltam snapshots históricos verificáveis do cadastro e amostra suficiente. |
| 16 | Testes e E2E | 192 TESTES PASS; E2E MULTISSETORIAL PASS | Suíte completa verde. O auditor aprovou ITUB4, EGIE3 e CURY3, três modelos setoriais, 180 afirmações, 39 páginas e o fluxo simulado. Permanecem o backtest completo com amostra suficiente e a revisão humana real. |
| 17 | Release reproduzível | PASS SOFTWARE; RC REPRODUZÍVEL | Builder determinístico gera source ZIP, wheel e manifesto com SHA-256 e timestamp fixo. Duas builds limpas da RC são verificadas pelo auditor de release; a versão permanece RC enquanto a auditoria comercial global falhar. |
| 18 | Jurídico, contábil, privacidade e operação | DOCS INTERNOS; VALIDAÇÃO EXTERNA OBRIGATÓRIA | Conflitos, LGPD, retenção, correção e segregação de dados estão documentados. Advogado, contador, pagamento/fiscal e pilotos não podem ser certificados pelo software. |

## Evidência que invalida a homologação anterior

`tmp/rc2_validation/multisector/release_audit.json` retorna `FAIL` exclusivamente pelo backtest:

- os três relatórios atuais, portfólio, fluxo, cobertura, catálogo, RAD e release build passam;
- o backtest usa `PROMETHEUS_POINT_IN_TIME`, porém os quatro sinais avaliados foram abstenções e não produziram a amostra mínima de 30 observações resolvidas, IC 95% ou comparação válida com benchmark.

Esses artefatos não devem ser copiados para uma pasta chamada `FINAL`, enviados a cliente ou descritos como `PASS`.

## Condições objetivas para sair de RC

1. Repetir pedido → geração → revisão → aprovação → entrega com revisor humano real; a simulação RC2 já verificou cadeia, artefatos e bundle.
2. Produzir backtest `PROMETHEUS_POINT_IN_TIME` com janelas não sobrepostas, pelo menos 30 observações resolvidas, IC 95% e benchmark pertinente.
3. Executar `scripts/audit_release.py` e obter `PASS` sem suppressions.
4. Gerar duas builds limpas idênticas com o código atual, instalar o wheel em ambiente novo e repetir testes/smoke.
5. Obter as decisões externas listadas em `COMMERCIAL_AND_LEGAL.md` antes de venda pública.

## Dependências externas ao software

- advogado brasileiro: enquadramento regulatório, publicidade, termos, responsabilidade, conflitos, LGPD e retenção;
- contador: semântica/apresentação das métricas, estrutura empresarial, emissão fiscal e retenção documental;
- meio de pagamento: cobrança, conciliação, reembolso e chargeback;
- clientes-piloto: clareza, taxa de correção, prazo, suporte e disposição a pagar.

O PROMETHEUS não promete rentabilidade, não personaliza recomendação e não pode entregar relatório sem revisão humana nominal.
