# Sector Intelligence rollout

Source: CVM FCA `Setor_Atividade`, resolved point-in-time from the local 2026
FCA archive against the 508-identity B3 catalog. The archive resolves 351
distinct CVM issuers; multiple tickers/classes of one issuer are deliberately
not treated as independent companies.

## Dedicated-module priority by issuer count

| Priority | Official CVM activity group | Issuers | Existing module |
|---:|---|---:|---|
| 1 | Comércio (Atacado e Varejo) | 35 | No |
| 2 | Construção Civil, Mat. Constr. e Decoração | 32 | Yes (real_estate) |
| 3 | Energia Elétrica | 24 | No |
| 4 | Máquinas, Equipamentos, Veículos e Peças | 19 | No |
| 5 | Bancos | 18 | No |
| 6 | Serviços Transporte e Logística | 17 | No |
| 7 | Metalurgia e Siderurgia | 14 | No |
| 8 | Têxtil e Vestuário | 14 | No |
| 9 | Comunicação e Informática | 10 | No |
| 10 | Agricultura (Açúcar, Álcool e Cana) | 10 | No |
| 11 | Serviços médicos | 10 | Yes (healthcare) |
| 12 | Saneamento, Serviços Água e Gás | 10 | No |

Holding classifications (`Emp. Adm. Part.`) are kept distinct in the CVM
taxonomy and must not be silently assigned the operating KPIs of the controlled
company. Their dedicated treatment requires an explicit holding module or the
generic fallback.

## Coverage estimate

The local catalog does not contain point-in-time market capitalization, so an
80%-of-market-cap estimate cannot be made honestly from this input. Counts are
an issuer-coverage prioritization, not a capital-weighted claim. A reproducible
capital-weighted ranking requires a dated B3 market-cap snapshot joined by
CNPJ/CVM code before estimating the 80% threshold.
