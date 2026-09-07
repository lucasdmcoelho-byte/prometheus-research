# PROMETHEUS — versão para portfólio

PROMETHEUS é um motor experimental de inteligência de empresas brasileiras:
organiza dados point-in-time, preserva fontes e transforma evidência em análise
explicável e auditável.

## O que já existe

- pipeline Python de coleta, normalização, fontes e análise;
- catálogo de instrumentos B3/CVM;
- KPIs operacionais reais para incorporadoras quando há documento oficial;
- gate editorial, proveniência, claims e hash de auditoria;
- geração de PDF premium e export JSON;
- camada qualitativa para posts, roteiros e perguntas;
- testes automatizados e testes de regressão.

## Demonstração validada

O exemplo local de CURY3 contém 16/18 KPIs operacionais rastreáveis, com documento
oficial da CVM, período e hash preservados. O PDF é um artefato de demonstração,
não uma recomendação de investimento.

## Estado honesto

Este repositório é um **MVP técnico/portfólio**, não uma promessa de retorno nem
um serviço regulado. O backtest point-in-time ainda não possui amostra estatística
mínima; a cobertura de KPI varia por setor; fontes externas podem ficar
indisponíveis; e qualquer entrega a cliente exige revisão humana e avaliação
jurídica independente.

## Como executar

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
```

Para uma execução real, use apenas dados e credenciais obtidos legalmente e
preserve o corte point-in-time. Consulte `docs/METHODOLOGY.md`,
`docs/OPERATIONS.md` e `docs/COMMERCIAL_AND_LEGAL.md`.

## Contato profissional

Ao apresentar este projeto em uma candidatura, descreva-o como um sistema de
pesquisa automatizada com rastreabilidade, validação e revisão humana. Não diga
que ele cobre todos os setores, possui track record ou fornece recomendação
personalizada — essas afirmações não são sustentadas pelos testes atuais.
