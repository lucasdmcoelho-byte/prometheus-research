"""PROMETHEUS package initializer."""

from .continuous_feed import ContinuousFeed
from .data_engine import get_asset_data, get_fundamental_data, validate_ticker
from .fundamental_engine import calculate_fundamental_score
from .knowledge_store import KnowledgeStore
from .qualitative_content import CompanyContextEngine, QualitativeContentGenerator
from .storyteller_voice import StorytellerVoiceEngine
from .news_feed import NewsFeed
from .pipeline import PrometheusEngine
from .thesis_engine import WEIGHTS as THESIS_WEIGHTS, calculate_score, get_state
from .data_quality import calculate_data_quality, normalize_percentage, normalize_ratio, validate_numeric
from .catalyst_engine import CatalystEngine
from .expectation_engine import ExpectationEngine
from .regime_engine import RegimeEngine
from .journal_engine import JournalEngine
from .replay_engine import ReplayEngine
from .reporting import generate_report
from .research import ResearchEngine
from .backtest_engine import BacktestEngine, PortfolioBacktestEngine, backtest

__all__ = [
    "ContinuousFeed",
    "get_asset_data",
    "get_fundamental_data",
    "validate_ticker",
    "calculate_fundamental_score",
    "KnowledgeStore",
    "CompanyContextEngine",
    "QualitativeContentGenerator",
    "StorytellerVoiceEngine",
    "NewsFeed",
    "PrometheusEngine",
    "calculate_score",
    "get_state",
    "THESIS_WEIGHTS",
    "calculate_data_quality",
    "normalize_percentage",
    "normalize_ratio",
    "validate_numeric",
    "CatalystEngine",
    "ExpectationEngine",
    "RegimeEngine",
    "JournalEngine",
    "ReplayEngine",
    "generate_report",
    "ResearchEngine",
    "BacktestEngine",
    "PortfolioBacktestEngine",
    "backtest",
]
