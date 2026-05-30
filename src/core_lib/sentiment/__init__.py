"""
Sentiment Analysis Module - core_lib/sentiment/
================================================
Market sentiment analysis, fear & greed index, narrative tracking,
and market intelligence aggregation.

Migrated from scripts/sentiment/ (Phase E-4).
"""

from core_lib.sentiment.fear_greed import (
    FearGreedClient,
    get_fear_greed_index,
    get_fear_greed_history,
    get_fear_greed_signal,
)

from core_lib.sentiment.sentiment_analyzer import (
    SentimentAnalyzer,
    SentimentResult,
    sentiment_adjust_signal,
)

from core_lib.sentiment.market_intelligence import (
    MarketIntelligence,
)

from core_lib.sentiment.narrative_tracker import (
    NarrativeSignal,
    NarrativeReport,
    NarrativeTracker,
    print_narrative_report,
)

from core_lib.sentiment.web_research import (
    WebResearcher,
)

__all__ = [
    # Fear & Greed
    'FearGreedClient',
    'get_fear_greed_index',
    'get_fear_greed_history',
    'get_fear_greed_signal',
    # Sentiment Analyzer
    'SentimentAnalyzer',
    'SentimentResult',
    'sentiment_adjust_signal',
    # Market Intelligence
    'MarketIntelligence',
    # Narrative Tracker
    'NarrativeSignal',
    'NarrativeReport',
    'NarrativeTracker',
    'print_narrative_report',
    # Web Research
    'WebResearcher',
]
