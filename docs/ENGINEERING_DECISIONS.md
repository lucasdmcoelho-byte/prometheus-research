# Engineering decisions

## Point-in-time first

Every observation is checked against the analysis cutoff. This prevents
look-ahead bias and makes historical reasoning reproducible.

## Explicit missing data

Missing or incompatible facts become `INSUFFICIENT_DATA`; the system does not
fill gaps with current values or plausible-looking estimates.

## Provenance as data

Sources, periods, publication timestamps, versions and SHA-256 hashes travel
with facts and claims so a reviewer can reconstruct why a sentence exists.

## Deterministic gates

Editorial and semantic checks run in Python and can block a report before a
human sees it. LLM output, when configured, cannot bypass those checks.

## Human approval

The delivery workflow separates generation, review, approval and delivery. This
is a safety boundary, not a cosmetic disclaimer.
