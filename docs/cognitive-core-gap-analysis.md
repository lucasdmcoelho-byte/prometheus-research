# PROMETHEUS Cognitive Core — Technical Gap Analysis

Date of inspection: 2026-08-18  
Scope: read-only inspection of the current repository. No production logic, schema, dependency, migration, or UI change is part of this analysis.

The target loop is:

`Evidence → Belief → Prediction → Outcome → Postmortem → Learning → Future reasoning`

The central conclusion is that PROMETHEUS already has useful implementations for most of the nouns in this loop, but not the durable causal chain between them. The safest path is to consolidate the existing models, journal, replay, pipeline, and delivery ledger rather than introduce a parallel “cognitive” application.

## 1. Current architecture

PROMETHEUS is a Python 3.11 application organized around a synchronous CLI and a mutable report dictionary.

| Layer | Current implementation | Architectural role |
|---|---|---|
| Entry point and commercial orchestration | `main.py` | Parses CLI input, builds adapters, invokes the pipeline, enriches peers, generates PDF, and invokes the delivery workflow. |
| Identity | `prometheus/instrument_catalog.py`, `prometheus/coverage_registry.py`, `config/instrument_catalog.json` | Validates ticker/CVM code/CNPJ/company identity and eligibility. The instrument catalog is content-hashed and versionable. |
| Acquisition | `prometheus/adapters.py`, `prometheus/cvm_client.py`, `prometheus/cvm_documents.py`, `prometheus/cvm_disclosures.py`, `prometheus/macro_client.py`, `prometheus/news_feed.py` | Collects market, official financial, document, macro, and news evidence. Official data preserves publication dates, versions, raw rows, URLs, and hashes in many important paths. |
| Point-in-time and normalization | `prometheus/engines.py`, CVM/B3 adapters | Rejects metadata newer than a cutoff and converts provider values into normalized features. Most detailed point-in-time selection is performed inside the adapters; `PointInTimeLayer` is an additional top-level guard. |
| Deterministic analysis | `prometheus/fundamental_engine.py`, `prometheus/thesis_engine.py`, `prometheus/risk_engine.py`, `prometheus/expectation_engine.py`, `prometheus/pricing_engine.py`, `prometheus/catalyst_engine.py`, `prometheus/regime_engine.py`, `prometheus/valuation_engine.py` | Produces heuristic scores, risks, catalysts, regime context, and valuation. |
| Thesis lifecycle | `prometheus/thesis_state_engine.py`, `prometheus/thesis_breaker_engine.py`, `prometheus/models.py` | Creates `ThesisResult`, computes velocity/state, applies breakers, and advances an in-memory thesis version. |
| Research and evidence | `prometheus/research.py`, `prometheus/evidence_engine.py`, `prometheus/business_quality.py` | Builds source records, claim records, sector context, contradiction summaries, and conservative qualitative interpretations. |
| Peer enrichment | `prometheus/automatic_peers.py`, `prometheus/peer_analysis.py` | Selects comparable peers, recalculates valuation, creates sources/claims, and also performs multi-report relative comparison. Both mutate report dictionaries. |
| Predictions, outcomes, and calibration | `prometheus/prediction_engine.py`, `prometheus/outcome_engine.py`, `prometheus/calibration_engine.py`, `prometheus/backtest_engine.py` | Provides primitives for falsifiable predictions, resolution, Brier calibration, and point-in-time backtests. These are not a durable production feedback loop. |
| Memory and replay | `prometheus/journal_engine.py`, `prometheus/replay_engine.py`, `prometheus/knowledge_store.py`, `prometheus/continuous_feed.py` | Stores mutable JSON snapshots or in-memory lists. These stores have different payloads and purposes and do not share a canonical event schema. |
| Editorial and delivery governance | `prometheus/editorial_gate.py`, `prometheus/reporting.py`, `prometheus/delivery_workflow.py` | Blocks incomplete/look-ahead research, renders the PDF, and records commercial order transitions and artifact hashes. The delivery ledger is the strongest append-only component in the repository. |

There is no application database, ORM, database model layer, or migration framework. `prometheus/models.py` contains mutable dataclasses, while persistence is JSON, JSONL, cached source files, and generated artifacts. There is also no production LLM integration or agent framework. Current scoring, classifications, narratives, and report assembly are deterministic Python logic, even where their output is qualitative.

## 2. Current research data flow

The main generation path is:

```text
CLI ticker/as_of
  → validated instrument mapping
  → adapter fetch (CVM/B3/market/macro/documents)
  → point-in-time metadata check
  → normalization and features
  → fundamental/thesis/expectation/catalyst/regime/pricing/risk scores
  → mutable ThesisResult + breakers
  → in-memory Prediction objects
  → DecisionResult
  → research source records and initial valuation
  → claim ledger + business-quality interpretations
  → editorial gate
  → JournalEngine snapshot + ReplayEngine snapshot
  → automatic peer enrichment and valuation replacement
  → optional multi-report peer-analysis replacement
  → PDF deep-copy, score reconciliation, QA, and fresh editorial gate
  → release bundle and append-only commercial delivery ledger
```

Important sequencing consequences:

- `PrometheusEngine.evaluate()` records the journal and replay **before** `main.py` runs automatic peers, cross-report peer analysis, PDF QA, and the final editorial gate.
- `automatic_peers.enrich_automatic_peers()` mutates `research.peer_analysis`, appends sources and claims, replaces valuation, and re-runs the gate.
- `peer_analysis.enrich_peer_analysis()` can then overwrite `research.peer_analysis` in place. It does not itself re-run the gate.
- `reporting.generate_report()` deep-copies the current report, adds score reconciliation and QA, re-runs the gate, and returns another report snapshot. `main.py` replaces its previous result with this PDF snapshot, but the earlier journal/replay records remain unchanged.
- `DeliveryWorkflow` stores the exact bundled analysis and PDF hash used for commercial review. It does not store the earlier cognitive transitions that produced that analysis.
- The production generation path creates predictions, but it does not durably resolve them, create postmortems, calculate updated calibration, or feed an approved learning artifact into a future thesis.
- `BacktestEngine` implements a separate historical path. It invokes the point-in-time pipeline for signals, then creates its own dated price-return `Prediction` and `PredictionOutcome` objects and calculates calibration. Those records are not the same lifecycle as the predictions created by `PredictionEngine` during normal research.

## 3. Existing relevant components

| Cognitive concern | Existing component | Current capability | Current limitation |
|---|---|---|---|
| Research/theses | `ThesisResult`, `ThesisStateEngine`, `ThesisBreakerEngine`, `ResearchEngine` | Score, direction, state, lifecycle, drivers, breakers, contradiction matrix, and report narrative. | No immutable belief version linked to the exact evidence/claims and policy that produced it. |
| Evidence and sources | `SourceMetadata`, normalized source rows, research source dictionaries, `EvidenceEngine` claims | Field-level availability, raw/normalized values, units, periods, URLs, hashes, claim classification, formula and assumptions. | Three competing evidence representations; source IDs are often assigned late and by list order; `ThesisEvidence` usually lacks a resolvable source/claim link. |
| Agents/LLMs | None | Avoids hidden model behavior and keeps current calculation paths deterministic. | No governed judgment boundary for a future LLM. Adding one directly to the pipeline would make reasoning unreplayable unless its inputs, outputs, model, prompt, and citations are recorded. |
| Scoring/confidence | Thesis weights, final score, risk/decision scores, data-quality confidence, source confidence, prediction confidence | Deterministic formulas are present and many are emitted as calculated sources. | Confidence uses incompatible scales and meanings; score weights/policies are not versioned per belief; prediction confidence is not a defined outcome probability. |
| Memory | `JournalEngine`, `ReplayEngine`, `KnowledgeStore` | Can save/load local JSON snapshots and replay a list through a handler. | Mutable, unversioned, unhashed cognitive storage with no canonical record type or transactional semantics. |
| Predictions | `PredictionEngine`, `Prediction` | Generates explicit metric/operator/threshold/horizon predictions with a snapshot. | Random IDs, wall-clock timestamps, no resolver contract/version, no durable registry, and weak evidence linkage. |
| Outcomes | `OutcomeEngine`, `PredictionOutcome` | Resolves due predictions and blocks historical resolution without an explicit point-in-time resolver. | Resolution is not persisted, source-provenanced, or truly idempotent; the prediction status is not updated by comparison. |
| Research events | Journal entries, replay records, delivery events | Some chronological records exist. | Only delivery transitions are typed events. There is no evidence/belief/prediction/outcome/postmortem event taxonomy. |
| Audit/history | Editorial gate, release bundle, delivery hash chain | Strong commercial artifact and approval audit, including named-human constraints and live bundle revalidation. | Cognitive history before the bundle is neither append-only nor hash-chained. |
| Database models | None; dataclasses in `models.py` | Lightweight in-process types. | No durable identity, constraints, concurrency, migrations, or queryable relationships. `JournalEntry` is defined but not used by `JournalEngine`. |
| Provenance | CVM/B3 rows and hashes, source records, claim audit | Strong provenance for many published report numbers. | Provenance terminates at the report claim; it does not continue through belief, prediction, outcome, postmortem, and learning. |
| Learning/feedback | `CalibrationEngine`, backtest calibration | Brier score and confidence buckets; confidence intervals and non-overlapping samples in backtest. | Not connected to normal prediction resolution, postmortem, policy approval, or future reasoning. |
| Orchestration | `PrometheusEngine.evaluate()` plus `main.py` | Produces a usable commercial draft and coordinates many deterministic engines. | Orchestration is split across two modules and several in-place enrichers; no single transition owner or commit point exists. |

## 4. What already works

1. **Instrument identity is unusually disciplined.** `InstrumentCatalog` validates exact ticker/CNPJ/CVM relationships, eligibility, and content hashes rather than inferring an issuer by name similarity.
2. **Official evidence is substantially point-in-time aware.** CVM selection retains publication/receipt dates and filing versions; B3 market snapshots expose effective and availability timestamps; YFinance explicitly refuses historical fundamentals.
3. **Raw and normalized financial facts are often both preserved.** Important metrics include raw source rows, units, periods, calculations, source URLs, versions, and SHA-256 hashes.
4. **The report has a real claim ledger.** `EvidenceEngine` distinguishes facts, calculations, interpretations, estimates, risks, and limitations; calculations require formulas and estimates require assumptions.
5. **The editorial gate is a meaningful release control.** It rechecks claim/source resolution, numeric provenance, source dates, raw CVM hashes, TTM construction, historical formulas, peer comparability, valuation reconciliation, and document retention.
6. **The commercial ledger is append-only and verifiable.** `DeliveryWorkflow` uses sequence numbers, previous-entry hashes, artifact hashes, process locks, transition validation, human actor requirements, versions, and correction history.
7. **The PDF uses the supplied research snapshot rather than silently refetching data.** The generated release bundle embeds the exact analysis and identifies the exact PDF bytes.
8. **Predictions and outcomes exist as explicit types.** They are not merely prose: metric, operator, threshold, horizon, confidence, snapshot, observed value, status, and error are represented.
9. **Historical outcome resolution has a protective default.** `OutcomeEngine` refuses historical resolution when no point-in-time metric resolver is supplied.
10. **Backtesting includes important safeguards.** The point-in-time provider supplies an explicit cutoff, gate blockers cause abstention, future prices are kept out of signal snapshots, overlapping signals are separated from non-overlapping inference, and insufficient samples are labeled as such.
11. **Current LLM ambiguity is low.** No LLM or agent makes unrecorded research judgments in the inspected production code.

These capabilities should be reused. A Cognitive Core does not need to replace the CVM/B3 collection stack, the source/claim gate, valuation, PDF generation, or commercial ledger.

## 5. Duplicated or conflicting responsibilities

### Evidence schemas

- `SourceMetadata` and normalized field dictionaries describe provider evidence.
- `ThesisEvidence` describes engine-level claims but often has no `source_metadata` and never has a canonical claim/source ID.
- Research source dictionaries and EvidenceEngine claim dictionaries form the publishable evidence ledger.
- `ResearchEngine.classify_evidence()` can return `INFERENCE`, while `EvidenceEngine.CLAIM_TYPES` does not accept `INFERENCE`. The two vocabularies are not identical.
- `EvidenceEngine.build_metric_claims()` assigns missing source IDs by current list position and mutates source dictionaries while doing so.

### Thesis and state schemas

- `final_state` from `thesis_engine.get_state()` means score band (`STRONG BULL`, `BULL`, and so on).
- `ThesisResult.state` from `ThesisStateEngine` means change state (`ACCELERATING`, `STRENGTHENING`, `STABLE`, and so on).
- `ThesisResult.direction`, `status`, and `lifecycle` add overlapping status concepts without a single documented state machine.
- `JournalEngine` builds a one-step `thesis_history`, while `ThesisStateEngine` independently stores previous score/time/version in memory.

### Prediction and backtest schemas

- `PredictionEngine` predicts the persistence of internal scores such as `thesis_score`, `score_fundamental`, and `expectation_gap`.
- `BacktestEngine` constructs a separate `Prediction` for future price return and then serializes it into another record dictionary with additional fields.
- The backtest reconstructs `Prediction` and `PredictionOutcome` objects from those dictionaries solely to call calibration.
- Normal research predictions, backtest predictions, and journal prediction dictionaries therefore compete without a shared registry or lifecycle.

### Audit and memory schemas

- Journal JSON, replay JSON, knowledge JSON, backtest result JSON, final report JSON, release bundle JSON, and delivery JSONL all store overlapping snapshots.
- Only the release bundle and delivery ledger have strong integrity semantics.
- `JournalEntry` in `models.py` does not match or govern the dictionaries written by `JournalEngine`.

### Orchestration and report mutation

- `PrometheusEngine.evaluate()` is the analysis orchestrator, but `main.py` performs required peer enrichment, cross-report comparison, PDF finalization, and delivery orchestration afterward.
- `automatic_peers.py` and `peer_analysis.py` both own `research.peer_analysis`; the latter can replace the richer former result.
- `DecisionEngine._collect_evidence()` extends the thesis evidence list in place. Because risk evidence was already placed in that list by the pipeline, it can duplicate risk evidence and mutate the thesis as a side effect of deciding.
- `ThesisStateEngine.apply_breakers()`, `EvidenceEngine.build_metric_claims()`, `KnowledgeStore.add()`, peer enrichers, and `JournalEngine.update_prediction()` all mutate caller-owned state.
- PDF generation correctly deep-copies the report, but that creates another version whose relationship to the pre-PDF journal/replay snapshot is implicit rather than recorded.

## 6. Current source(s) of truth

There is no single source of truth for the research lifecycle.

| Domain | De facto source of truth | Qualification |
|---|---|---|
| Instrument identity | Hashed instrument catalog | Strong and explicit. |
| Raw official evidence | CVM/B3 cached/downloaded artifacts and embedded raw rows/hashes | Strong where retained, but distributed across caches and report payloads. |
| Research during evaluation | Mutable `report` dictionary | Temporary and modified by several modules. |
| Client-review analysis | `analysis` inside the current-version release bundle | Strongest final research snapshot because the bundle is verified against the PDF and delivery order. |
| Commercial order state | Latest verified `DeliveryWorkflow` ledger entry | Append-only and hash-chained; authoritative for delivery, not reasoning. |
| Thesis history | In-memory `ThesisStateEngine` plus optional journal JSON | Neither is durable or fully reproducible. |
| Predictions and outcomes | In-memory objects, journal dictionaries, or backtest result dictionaries | No authoritative registry. |
| Memory/replay | Whichever JSON file was explicitly saved or loaded | No schema/version/hash or canonical ownership. |

The release bundle should remain authoritative for “what was reviewed and delivered.” A future Cognitive Core needs a separate but linked authority for “how the belief evolved.” That authority should consolidate `JournalEngine` and `ReplayEngine`; it should not replace or duplicate the commercial delivery ledger.

## 7. Governance weaknesses

- Belief creation, revision, invalidation, prediction creation, outcome resolution, and learning have no actor, authorization, or approval record.
- Cognitive records have no schema version, producer version, scoring-policy version, causation ID, correlation ID, or idempotency key.
- Journal and replay files have no hash chain, file lock, atomic append, or corruption verification. `JournalEngine.save()` rewrites the whole file.
- `JournalEngine.update_prediction()` edits prior prediction dictionaries and erases the former state instead of recording a new outcome event.
- There is no correction/supersession protocol for evidence, beliefs, predictions, or outcomes. Filing versions exist at the source layer but not at the cognitive layer.
- `PredictionEngine.generate()` failures are swallowed by a broad exception in the pipeline, leaving an empty prediction list without a structured failure event.
- Outcome fetch failures can collapse into “metric unavailable” without retaining exception class, resolver version, attempted sources, or a diagnostic trace.
- A gate result can become stale after in-place report mutation. PDF generation re-runs it, but a non-PDF JSON path may retain a gate calculated before the last peer mutation.
- Human review applies to the final deliverable, not to promotion of a calibration result or changed reasoning policy.
- There is no retention/access policy encoded for cognitive records, although commercial/legal documentation exists outside the implementation.

## 8. Missing Cognitive Core capabilities

The following capabilities are absent or incomplete:

1. **Research case identity:** one durable ID tying ticker, issuer identity, cutoff, request/order, and all later events together.
2. **Immutable evidence snapshot:** a stable manifest of exactly which source versions and normalized facts were eligible at the cutoff.
3. **Belief version:** an immutable thesis revision with parent version, evidence/claim links, score-policy version, effective cutoff, recorded time, and reason for change.
4. **Evidence-to-belief graph:** explicit support, contradiction, limitation, and invalidation edges rather than unlinked strings and list counts.
5. **Canonical research event envelope:** typed, ordered, idempotent events for evidence, belief, prediction, outcome, postmortem, and learning.
6. **Prediction contract:** unambiguous target definition, unit, observation window, resolver name/version, availability rule, success rule, and belief version.
7. **Durable prediction registry:** unique lifecycle ownership and prevention of duplicate or conflicting resolution.
8. **Provenanced outcome observation:** source IDs, observation timestamp, availability timestamp, resolver version, raw/normalized value, and correction handling.
9. **Postmortem record:** expected versus actual, error decomposition, evidence that changed, invalid assumptions, data problems, reasoning problems, and reviewer conclusion.
10. **Learning artifact:** an immutable, cohort-specific calibration or policy candidate linked to the outcomes used to produce it.
11. **Learning governance:** minimum sample, out-of-sample validation, reviewer approval, effective-from date, rollback, and prohibition on rewriting historical beliefs.
12. **Deterministic replay:** reconstruction of every belief from a frozen evidence snapshot, code/policy versions, and recorded transition inputs.
13. **Read projections:** current belief, report, timeline, calibration, and replay derived from the same event history rather than separately written stores.
14. **Concurrency/idempotency controls:** safe repeated generation, resolution, correction, and multi-process use.
15. **Judgment provenance:** if an LLM is added later, a record of provider/model/version, prompt/template version, deterministic settings, input hashes, output, citations, validation, and human disposition.

## 9. Data/provenance risks

- Source provenance is strong at the published-number layer but does not have a root manifest that hashes the complete eligible evidence set for a belief.
- Many source records receive sequential IDs only when claims are built. Reordering or inserting sources can change identity even when the underlying source is unchanged.
- `ThesisEvidence` is frequently derived from metrics but contains only prose, confidence, and timestamp. It cannot normally be resolved back to the metric source or publishable claim.
- The report mixes dataclasses and dictionaries until serialization; field contracts are enforced inconsistently.
- The same logical object is serialized differently in journal, replay, report, bundle, and backtest output.
- `retrieved_at`, `created_at`, `timestamp`, `point_in_time`, `analysis_as_of`, `publication_date`, `effective_date`, and `resolved_at` exist, but their semantics are not governed by one temporal model.
- The journal/replay snapshots precede final peer enrichment and PDF QA, so they cannot prove what the human reviewed.
- `ContinuousFeed` labels records as `source: yfinance` even though its injected `data_engine` can return a report assembled from other sources.
- Point-in-time validation is distributed. The top-level `PointInTimeLayer` checks top metadata objects, while nested official facts rely on adapter filtering and the later editorial gate. A future event writer must validate the complete evidence manifest before committing a belief.
- Release bundles protect final artifacts, but reports saved outside that path are not content-addressed or tamper-evident.

## 10. Scoring/confidence risks

- Confidence has incompatible representations: floats from 0–1 in model dataclasses, percentages from 0–100 in data-quality/fundamental results, and labels such as `low/medium/high` in source and claim records.
- The semantic meaning also changes: source reliability, data completeness, thesis confidence, pricing confidence, regime confidence, and prediction confidence are treated as though they were comparable.
- `PredictionEngine` copies `ThesisResult.confidence`, which is derived from fundamental confidence/data quality, into prediction confidence. `CalibrationEngine` then treats it as a probability of correctness for Brier scoring. Those are not currently the same quantity.
- Missing inputs often receive neutral or positive defaults (`sector=70`, missing expectation input paths, `valuation=50`, sentiment `50`, and risk component defaults). The editorial gate can block delivery later, but predictions and internal states are created before the gate decides whether evidence is sufficient.
- The final score combines an already weighted thesis score with expectation, catalyst, regime, and pricing components. Some components share inputs or include one another, creating possible correlated double counting.
- Scoring weights and heuristic thresholds are code constants but are not stamped with a policy/model version in `ThesisResult`, predictions, journal records, or backtests.
- `risk_score` is actually a safety score (`1 - aggregate_risk`), which is easy to invert accidentally in future consumers.
- The score-band `final_state` and velocity-based `ThesisResult.state` use the same word “state” for different concepts.
- Current normal predictions mostly forecast persistence of PROMETHEUS’s own scores, not externally observable business outcomes. That can create circular success criteria and weak learning value.
- Calibration has no implemented sector/thesis-type projections despite fields existing on `CalibrationReport`, and the live minimum sample default is small. Backtest correctly labels small independent samples insufficient, but that evidence is not connected to live learning.
- No belief uncertainty interval, sensitivity to missing evidence, or explicit prior/base rate is stored.

## 11. Look-ahead bias risks

### Existing protections

- CVM clients select filings and versions available by the cutoff.
- Point-in-time B3/market adapters reject observations whose effective or available time exceeds the cutoff.
- YFinance refuses to serve historical fundamentals.
- News is filtered by publication/collection time.
- Editorial checks reject sources, TTM rows, and historical rows published after `analysis_as_of`.
- Historical outcomes require an injected point-in-time resolver.
- Backtest signal snapshots omit future price fields, use a dated pipeline cutoff, abstain on gate blockers, and distinguish overlapping from non-overlapping evidence.
- Historical sector classification gaps cause explicit backtest abstention rather than reuse of the current classification.

### Remaining risks

- `ThesisStateEngine` ignores the pipeline `as_of` and uses `datetime.utcnow()` plus process-local previous evaluations. Historical velocity, acceleration, age, IDs, and transition state therefore depend on execution order and wall-clock runtime.
- `PredictionEngine` also uses the wall clock. A prediction generated from a historical belief can be timestamped at the replay date instead of the belief cutoff.
- `JournalEngine` records the current wall clock as `point_in_time`, not the report cutoff.
- Normal outcome resolution fetches current live data when no historical cutoff is supplied. The resulting outcome has no source or availability record proving what was observable at resolution time.
- `main.py` can move `analysis_as_of` forward after live automatic-peer enrichment so that a later peer observation fits the report. This may be reasonable for a live draft, but it changes the research cutoff rather than recording a new evidence/belief version.
- Stateful engines are reused across backtest dates without an immutable prior-belief lookup. Rerunning dates in a different order can alter thesis transition fields.
- Backtest output says “frozen scoring rules,” but the exact code/config/policy hash is not stored with each signal. Running later code over the same historical data can produce a different result without a formal model-version boundary.
- The default momentum backtest is correctly labeled separately, but its predictions must never be interpreted as validation of the full research model.
- Any future learning process that aggregates outcomes without preserving the policy version and historical classification/source availability will introduce survivorship and look-ahead leakage.

## 12. Recommended minimal architecture

Do not begin with a new agent framework, a second report schema, or a database migration. Consolidate the existing pipeline around one append-only cognitive timeline and keep the final commercial ledger as its linked delivery boundary.

```text
Existing adapters + point-in-time controls
        ↓
EvidenceSnapshot (existing source records + claim records + manifest hash)
        ↓
BeliefVersion (existing ThesisResult, made immutable and evidence-linked)
        ↓
PredictionContract (existing Prediction, with resolver and policy identity)
        ↓
OutcomeObservation (existing PredictionOutcome, with source provenance)
        ↓
Postmortem
        ↓
LearningRelease (calibration/policy artifact; reviewed and effective-dated)
        ↓
Future BeliefVersion references the approved LearningRelease

Every transition → one append-only JournalEngine event stream
Event projections → current report, replay, timeline, calibration
DeliveryWorkflow → references research_case_id, belief_version_id, and artifact hashes
```

### Canonical event envelope

The minimal envelope should include:

- `event_id`, `event_type`, `schema_version`
- `research_case_id`, `ticker`, issuer identity/catalog hash
- `sequence`, `causation_id`, `correlation_id`, `idempotency_key`
- `effective_as_of`, `occurred_at`, `recorded_at`
- `actor_type`, `actor_id`, `producer`, `producer_version`, `policy_version`
- `input_event_ids`, `input_artifact_hashes`
- typed `payload`
- `previous_event_hash`, `event_hash`

The first event types need only cover the current loop: `EVIDENCE_SNAPSHOT_RECORDED`, `BELIEF_VERSION_RECORDED`, `PREDICTION_RECORDED`, `OUTCOME_RECORDED`, `POSTMORTEM_RECORDED`, and `LEARNING_RELEASE_RECORDED`. Corrections should be new superseding events, never edits.

### Reuse boundaries

- Reuse research source and claim records as the content of `EvidenceSnapshot`; do not create a second evidence system.
- Reuse `ThesisResult` as the starting payload for `BeliefVersion`; clarify state fields and add immutable lineage rather than replacing the thesis engine.
- Reuse `Prediction` and `PredictionOutcome`; add the missing contracts and provenance.
- Refactor `JournalEngine` into the authoritative cognitive append log using the hash-chain and locking patterns already proven in `DeliveryWorkflow`.
- Turn `ReplayEngine` into a read projection over that log rather than another independently written store.
- Keep `KnowledgeStore` as an ingestion/feed cache, not as belief memory.
- Keep `DeliveryWorkflow` authoritative for orders, human approval, correction, and delivery. Link it to cognitive IDs; do not merge commercial and reasoning state machines.
- Keep all deterministic engines pure. If an LLM is introduced later, place it behind an explicit judgment adapter whose execution becomes evidence, not an unlogged mutation.
- Start with JSONL to avoid a premature database migration. Define a repository interface only when a second persistence implementation is actually required.

## 13. Migration strategy

This is a future migration plan; no migration was performed during this analysis.

### Phase 0 — Freeze semantics and fixtures

- Define the temporal meanings of `effective_as_of`, `publication/available_at`, `occurred_at`, `recorded_at`, and `resolved_at`.
- Define confidence types and scales separately for source reliability, evidence sufficiency, belief strength, and forecast probability.
- Freeze representative current report, journal, replay, prediction, backtest, bundle, and delivery fixtures.
- Assign explicit versions to scoring policy, source schema, claim schema, and sector model.

### Phase 1 — Append-only compatibility layer

- Upgrade `JournalEngine` to append canonical, hash-chained events while preserving its current public read/query behavior through a projection.
- Emit adapters from existing source/claim, thesis, prediction, and decision objects. Do not change score calculations yet.
- Propagate the supplied `as_of` into thesis, prediction, and journal effective times.
- Record one final research snapshot event only after peer enrichment and the final gate commit point.
- Dual-write legacy output and events until parity tests prove equivalence.

### Phase 2 — Canonical prediction lifecycle

- Register every prediction once with a measurement/resolver contract.
- Resolve it through an idempotent outcome command that appends a source-provenanced outcome event.
- Produce a postmortem event without changing the historical prediction or belief.
- Make backtest and normal research use the same prediction/outcome contracts while retaining distinct prediction types/cohorts.

### Phase 3 — Learning and replay

- Calculate calibration and error analysis from event projections grouped by policy, sector, thesis type, horizon, and target definition.
- Create reviewed, versioned `LearningRelease` artifacts; never update weights automatically from unapproved outcomes.
- Rebuild current belief history, replay, and calibration from the event log and compare them with frozen fixtures.
- Deprecate direct JSON mutation in journal/replay only after read parity is demonstrated.

### Phase 4 — Optional persistence migration

- Add a database implementation only if concurrency, volume, retention, or query requirements exceed JSONL.
- Backfill legacy reports, journals, bundles, and backtests as explicitly marked `legacy_import` events with preserved original hashes and unknown fields, not reconstructed certainty.
- Keep the event contract storage-agnostic so a database does not become a second cognitive schema.

## 14. Prioritized implementation plan

### P0 — Establish trustworthy lineage without changing analysis

1. Define and test the canonical research case/event contract and temporal semantics.
2. Make `JournalEngine` an append-only, schema-versioned, hash-chained cognitive ledger by reusing `DeliveryWorkflow` integrity patterns.
3. Propagate `as_of` into thesis IDs/state timing, prediction creation, journal records, and the final research commit.
4. Introduce immutable `BeliefVersion` lineage around the existing `ThesisResult`, linked to exact source/claim IDs, evidence manifest hash, and scoring-policy version.
5. Centralize transition ownership in the existing orchestration path: engines return values; only the orchestrator commits state.
6. Remove hidden in-place cognitive mutations, including prior journal edits, duplicated risk evidence, and competing peer-analysis overwrites.
7. Record the post-enrichment, post-gate report as the committed belief projection; retain the release bundle as the separately approved deliverable snapshot.
8. Add regression tests for idempotent append, hash verification, deterministic replay, event ordering, stale writes, cutoff propagation, and source→claim→belief→prediction linkage.

P0 deliberately does **not** change weights, add an LLM, add a database, or implement automatic learning.

### P1 — Complete prediction, outcome, and postmortem lifecycle

1. Add a canonical prediction target/resolver registry with explicit versioning and availability rules.
2. Persist outcomes append-only with complete source provenance and correction/supersession semantics.
3. Implement structured postmortems and reviewer disposition.
4. Make normal research and backtest predictions share the canonical contract while remaining separate cohorts.
5. Normalize confidence semantics and prevent Brier scoring of non-probability confidence values.
6. Consolidate evidence classifications and source identity; replace order-derived source IDs with stable content/business keys.
7. Consolidate automatic and cross-report peer analysis under one owner and one gate commit.
8. Turn replay, current-belief history, and calibration into projections over the event log.

### P2 — Governed learning and scale

1. Produce cohort-aware calibration and learning candidates with minimum samples, confidence intervals, out-of-sample checks, and policy lineage.
2. Require named approval, effective-from date, rollback, and audit notes before a learning release can affect future reasoning.
3. Add an explicit judgment record and deterministic validation boundary if/when LLM analysis is introduced.
4. Add a database repository only when justified by measured operational needs.
5. Add operational monitoring for unresolved predictions, overdue postmortems, event-chain failures, projection drift, and policy/version skew.

## 15. Files/modules likely to require changes

No files in this list were changed as part of this analysis.

| Priority | File/module | Likely future change |
|---|---|---|
| P0 | `prometheus/models.py` | Clarify immutable evidence/belief/prediction/outcome contracts, IDs, temporal fields, and confidence types; reconcile or remove the unused `JournalEntry` contract after compatibility is proven. |
| P0 | `prometheus/journal_engine.py` | Become the append-only cognitive event ledger and expose legacy-compatible projections instead of rewriting/mutating history. |
| P0 | `prometheus/pipeline.py` | Propagate cutoff and policy identity, stop swallowing unrecorded prediction failures, emit canonical transitions, and define a clear analysis commit point. |
| P0 | `main.py` | Move required enrichment/finalization behind one orchestrated commit and link the committed belief to the release bundle/order. |
| P0 | `prometheus/thesis_state_engine.py` | Replace process-local/wall-clock history with prior immutable belief input and effective-as-of timing; return new versions instead of mutating. |
| P0 | `prometheus/prediction_engine.py` | Use belief/evidence lineage, supplied effective time, deterministic/idempotent identity, target definition, and policy/resolver version. |
| P0 | `prometheus/outcome_engine.py` | Make resolution idempotent and source-provenanced; append outcomes rather than relying on mutable prediction status. |
| P0 | `prometheus/decision_engine.py` | Eliminate evidence-list side effects and retain explicit input lineage. |
| P0 | `prometheus/evidence_engine.py` | Stabilize source/claim identity and avoid mutating source lists during claim construction. |
| P0 | `tests/test_prometheus.py`, `tests/test_prediction_cycle.py`, new focused event-ledger tests | Assert temporal determinism, immutability, lineage, idempotency, replay, and look-ahead invariants. |
| P1 | `prometheus/research.py` | Unify claim classification vocabulary and make contradiction/support relations evidence-linked rather than string-count based. |
| P1 | `prometheus/replay_engine.py` | Read and project canonical events instead of owning an independent mutable record list. |
| P1 | `prometheus/calibration_engine.py` | Accept only forecast probabilities with declared target cohorts; project calibration by policy/sector/type/horizon. |
| P1 | `prometheus/backtest_engine.py` | Use canonical prediction/outcome contracts and stamp code/config/policy/evidence identities on every historical signal. |
| P1 | `prometheus/automatic_peers.py`, `prometheus/peer_analysis.py` | Consolidate ownership, preserve richer provenance, and prevent one in-place enrichment from silently replacing another. |
| P1 | `prometheus/editorial_gate.py` | Validate cognitive lineage and the final committed snapshot in addition to the current report/source invariants. |
| P1 | `prometheus/reporting.py` | Render a committed belief projection and record derived narrative/QA identity without creating an untracked cognitive version. |
| P1 | `prometheus/delivery_workflow.py` | Reference research case/belief/event IDs while remaining the separate commercial state authority. |
| P1 | `prometheus/knowledge_store.py`, `prometheus/continuous_feed.py` | Clarify ingestion-cache semantics, preserve true source identity, and prevent mutation from being mistaken for learned memory. |
| P2 | Persistence implementation, only if justified | Implement the already-frozen repository/event contract in a database; do not invent another domain schema. |

The recommended first implementation step is therefore narrow: freeze the canonical event/temporal contract and upgrade the existing `JournalEngine` into an append-only, hash-chained source of cognitive history, initially adapting current outputs without changing any analytical formula.
