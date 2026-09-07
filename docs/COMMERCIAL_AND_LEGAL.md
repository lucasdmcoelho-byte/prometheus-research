# Commercial and legal operating notes

PROMETHEUS produces impersonal research material from public information. It must not claim guaranteed accuracy or profitability, and it must not be positioned as individualized portfolio, tax or legal advice.

Before paid public launch, obtain Brazilian counsel's written review of the product wording, distribution model, analyst/research obligations, conflicts policy, terms of sale, refund policy, LGPD privacy notice, record retention and marketing claims. Software gates cannot substitute for that external legal determination.

Minimum customer-facing controls:

- identify publisher, report version, cut-off, issue date and reviewer;
- disclose methodology, sources, conflicts, limitations and material corrections;
- publish a correction/version policy and preserve prior hashes;
- collect only necessary client data and define retention/deletion rules;
- never sell an unapproved draft or silently replace a delivered report;
- use payment and invoicing providers only after business, tax and contractual setup is confirmed.

This file is an operational checklist, not legal advice or a final set of terms.

## Conflict-of-interest policy template

- Record whether publisher/reviewer or related persons hold the covered security, have commercial relationships with the issuer or received compensation connected to the report.
- Disclose material conflicts in the report; a conflict cannot be hidden by changing the score.
- Require a second reviewer or abstention when independence is compromised.
- Keep the declaration associated with the exact report hash and version.

## Privacy and LGPD operating template

- Use an opaque `client_reference`; do not place customer names, CPF, portfolio or suitability data in research JSON/PDF.
- Define controller, processors, purpose, legal basis, access roles and incident contact before launch.
- Restrict ledger and artifact access; encrypt backups and transport in production.
- Support correction, access and deletion requests subject to legal/audit retention duties.
- The FRE parser intentionally discards CPF and birth date from public governance records.

## Retention and correction template

- Provisional engineering baseline: retain delivered reports, approvals, source manifest and hashes for five years; counsel/accounting must confirm the final period.
- Preserve superseded versions; issue a correction notice identifying what changed, why, when and who approved it.
- Never alter an existing PDF after delivery. Generate a new version and hash.
- Record failed delivery and re-delivery attempts without storing unnecessary customer content.

## External launch dependencies

Software completion does not establish authorization to sell. Written external decisions are required for: Brazilian securities/research regulation and analyst obligations; company and tax/invoice setup; terms, privacy notice and retention; payment processor and chargeback/refund process; professional liability/cyber coverage as applicable; and pilot-customer feedback on clarity and willingness to pay.

The current package is a release candidate. Do not market it as fully validated or deliver the legacy visual samples while the current release audit is `FAIL`. Legal and accounting reviews are launch conditions in addition to, not replacements for, a passing technical/commercial audit.
