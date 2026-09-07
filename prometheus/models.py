from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


COGNITIVE_EVENT_SCHEMA = "prometheus.cognitive_event"
COGNITIVE_EVENT_SCHEMA_VERSION = 1
CANONICAL_RESEARCH_EVENT_TYPES = frozenset({
    "EVIDENCE_SNAPSHOT_RECORDED",
    "BELIEF_VERSION_RECORDED",
    "PREDICTION_RECORDED",
    "OUTCOME_RECORDED",
    "POSTMORTEM_RECORDED",
    "LEARNING_RELEASE_RECORDED",
    # Compatibility adapters. They preserve the current JournalEngine API
    # without pretending that legacy snapshots already satisfy newer models.
    "JOURNAL_ENTRY_RECORDED",
    "PREDICTION_UPDATE_RECORDED",
})


@dataclass
class SourceMetadata:
    source: str
    timestamp: datetime
    publication_date: Optional[datetime]
    effective_date: Optional[datetime]
    ticker: str
    period: Optional[str]
    unit: Optional[str]
    confidence: Optional[float]
    revision_status: Optional[str]
    raw: Optional[Dict[str, Any]] = field(default_factory=dict)


@dataclass
class DataPoint:
    metadata: SourceMetadata
    value: Optional[float]
    normalized: Optional[float]
    interpretation: Optional[str]


@dataclass
class AssetProfile:
    ticker: str
    company_name: Optional[str]
    sector: Optional[str]
    industry: Optional[str]
    currency: Optional[str]
    exchange: Optional[str]
    business_summary: Optional[str]
    country: Optional[str]
    source_metadata: Optional[SourceMetadata] = None


@dataclass
class FinancialStatement:
    revenue_growth: Optional[DataPoint]
    earnings_growth: Optional[DataPoint]
    profit_margin: Optional[DataPoint]
    roe: Optional[DataPoint]
    debt_to_equity: Optional[DataPoint]
    cash_flow: Optional[DataPoint] = None
    dividend_yield: Optional[DataPoint] = None
    payout_ratio: Optional[DataPoint] = None
    net_debt: Optional[DataPoint] = None
    ebitda_margin: Optional[DataPoint] = None
    roic: Optional[DataPoint] = None
    period: Optional[str] = None
    source_metadata: Optional[SourceMetadata] = None


@dataclass
class MarketSnapshot:
    price: Optional[float]
    previous_close: Optional[float]
    price_change: Optional[float]
    price_change_percent: Optional[float]
    market_cap: Optional[float]
    beta: Optional[float]
    forward_pe: Optional[float]
    trailing_pe: Optional[float]
    enterprise_value: Optional[float]
    shares_outstanding: Optional[float]
    dividend_yield: Optional[float]
    fifty_two_week_change: Optional[float]
    fifty_two_week_low: Optional[float]
    fifty_two_week_high: Optional[float]
    source_metadata: Optional[SourceMetadata] = None
    field_metadata: Dict[str, SourceMetadata] = field(default_factory=dict)


@dataclass
class ThesisEvidence:
    claim: str
    evidence_type: str
    confidence: float
    details: str
    timestamp: datetime
    source_metadata: Optional[SourceMetadata] = None


@dataclass
class ThesisBreaker:
    id: str
    name: str
    description: str
    category: str
    condition: str
    threshold: Optional[float]
    current_value: Optional[float]
    distance_to_threshold: Optional[float]
    severity: str
    impact_score: float
    status: str
    triggered: bool
    evidence: Optional[ThesisEvidence]
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ThesisResult:
    thesis_id: str
    ticker: str
    score: float
    state: str
    direction: str
    velocity: float
    acceleration: float
    confidence: float
    age_days: Optional[int]
    status: str
    lifecycle: str
    drivers: List[str] = field(default_factory=list)
    prediction_ids: List[str] = field(default_factory=list)
    thesis_breakers: List[ThesisBreaker] = field(default_factory=list)
    pricing_status: str = "UNKNOWN"
    pricing_confidence: float = 0.0
    pricing_details: Optional[str] = None
    evidence: List[ThesisEvidence] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Prediction:
    prediction_id: str
    thesis_id: str
    ticker: str
    metric: str
    operator: str
    threshold: Any
    horizon_days: int
    created_at: datetime
    confidence: float
    catalyst: Optional[str]
    status: str = "PENDING"
    snapshot: Optional[Dict[str, Any]] = None


@dataclass
class PredictionOutcome:
    prediction_id: str
    actual_value: Optional[float]
    resolved_at: Optional[datetime]
    status: str
    error: Optional[Any]
    snapshot: Optional[Dict[str, Any]] = None


@dataclass
class CalibrationBucket:
    bucket: str
    sample_size: int
    correct: int
    accuracy: Optional[float]
    low_stat_confidence: bool = False


@dataclass
class CalibrationReport:
    total: int
    brier_score: Optional[float]
    buckets: List[CalibrationBucket]
    by_sector: Dict[str, Any] = field(default_factory=dict)
    by_thesis_type: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None


@dataclass
class DecisionResult:
    action: str
    reasoning: str
    score: float
    confidence: float
    factors: Dict[str, Any]
    evidence: List[ThesisEvidence]
    timestamp: datetime


@dataclass
class JournalEntry:
    ticker: str
    point_in_time: datetime
    asset_profile: AssetProfile
    financials: FinancialStatement
    market_snapshot: MarketSnapshot
    thesis: ThesisResult
    decision: DecisionResult
    report: Dict[str, Any]
    tags: List[str]
    timestamp: datetime


@dataclass(frozen=True)
class ResearchEvent:
    """Canonical immutable envelope for PROMETHEUS cognitive history.

    Temporal contract:

    * ``effective_as_of`` is the latest instant whose evidence may influence
      the payload.
    * ``occurred_at`` is when the represented domain transition occurred.
    * ``recorded_at`` is when PROMETHEUS durably appended the event.

    A valid event satisfies ``effective_as_of <= occurred_at <= recorded_at``.
    Replay of what PROMETHEUS actually knew at a cutoff additionally requires
    ``recorded_at <= cutoff`` so a later backfill cannot appear retroactively.
    Timestamps are canonical UTC strings ending in ``Z``.
    """

    schema: str
    schema_version: int
    event_id: str
    event_type: str
    research_case_id: str
    ticker: str
    ledger_sequence: int
    aggregate_version: int
    causation_id: Optional[str]
    correlation_id: str
    idempotency_key: str
    effective_as_of: str
    occurred_at: str
    recorded_at: str
    actor_type: str
    actor_id: str
    producer: str
    producer_version: str
    policy_version: Optional[str]
    input_event_ids: tuple[str, ...]
    input_artifact_hashes: tuple[str, ...]
    payload: Dict[str, Any]
    previous_event_hash: Optional[str]
    event_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "research_case_id": self.research_case_id,
            "ticker": self.ticker,
            "ledger_sequence": self.ledger_sequence,
            "aggregate_version": self.aggregate_version,
            "causation_id": self.causation_id,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "effective_as_of": self.effective_as_of,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "policy_version": self.policy_version,
            "input_event_ids": list(self.input_event_ids),
            "input_artifact_hashes": list(self.input_artifact_hashes),
            "payload": self.payload,
            "previous_event_hash": self.previous_event_hash,
            "event_hash": self.event_hash,
        }
