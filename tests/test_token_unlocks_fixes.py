"""
Regression lock for the Token Unlock Monitor (Batch L / #41).

Deep-math audit found token_unlocks.py NUMERICALLY CORRECT:
  - _classify_tier boundaries match the documented 2.4 / 1.0 / 0.3 tiers.
  - _apply_recipient_override bumps TEAM/INVESTOR up one tier, COMMUNITY/
    STAKING down, CRISIS capped (no bump above CRISIS).
  - _determine_market_read rules are internally consistent.
  - calculate_absorption_ratio returns inf for zero volume (handled by to_dict).
These tests LOCK that correct behavior so future edits can't regress it.
"""
import pytest
from engines.token_unlocks import (
    _classify_tier,
    _apply_recipient_override,
    _determine_market_read,
    calculate_absorption_ratio,
    process_unlock_event,
    UnlockTier,
    RecipientCategory,
    MarketRead,
)


def test_classify_tier_boundaries():
    assert _classify_tier(3.0) == UnlockTier.CRISIS
    assert _classify_tier(2.4) == UnlockTier.STRAIN      # strictly > 2.4 is CRISIS
    assert _classify_tier(1.0) == UnlockTier.STRAIN
    assert _classify_tier(0.5) == UnlockTier.DIGESTIBLE
    assert _classify_tier(0.3) == UnlockTier.DIGESTIBLE  # >= 0.3
    assert _classify_tier(0.1) == UnlockTier.TRIVIAL


def test_recipient_override():
    assert _apply_recipient_override(UnlockTier.DIGESTIBLE, RecipientCategory.TEAM) == UnlockTier.STRAIN
    assert _apply_recipient_override(UnlockTier.TRIVIAL, RecipientCategory.INVESTOR) == UnlockTier.DIGESTIBLE
    assert _apply_recipient_override(UnlockTier.STRAIN, RecipientCategory.INVESTOR) == UnlockTier.CRISIS
    assert _apply_recipient_override(UnlockTier.CRISIS, RecipientCategory.TEAM) == UnlockTier.CRISIS
    assert _apply_recipient_override(UnlockTier.CRISIS, RecipientCategory.COMMUNITY) == UnlockTier.STRAIN
    assert _apply_recipient_override(UnlockTier.STRAIN, RecipientCategory.STAKING) == UnlockTier.DIGESTIBLE


def test_market_read_rules():
    assert _determine_market_read(UnlockTier.CRISIS, 20.0, RecipientCategory.FORCED) == MarketRead.FORCED_SELLERS
    assert _determine_market_read(UnlockTier.CRISIS, 20.0, RecipientCategory.TEAM) == MarketRead.FADE_PUMP
    assert _determine_market_read(UnlockTier.DIGESTIBLE, -25.0, RecipientCategory.TEAM) == MarketRead.PRICED_IN
    # CRISIS with price down 10% (between -20 and +15) -> market asleep
    assert _determine_market_read(UnlockTier.CRISIS, -10.0, RecipientCategory.TEAM) == MarketRead.MARKET_ASLEEP
    assert _determine_market_read(UnlockTier.DIGESTIBLE, 5.0, RecipientCategory.COMMUNITY) == MarketRead.ABSORBABLE


def test_absorption_ratio_inf_and_classification():
    assert calculate_absorption_ratio(100.0, 0.0) == float("inf")
    ev = process_unlock_event(
        "ARB", "Arbitrum", "2026-06-02",
        unlock_usd=95_000_000, avg_daily_volume_usd=25_000_000,
        supply_pct=2.8, recipient="team", pattern="cliff", price_30d_pct=-12.0,
    )
    assert ev.absorption_ratio == pytest.approx(95_000_000 / 25_000_000)
    assert ev.tier == UnlockTier.CRISIS           # 3.8x -> CRISIS (team keeps CRISIS)
    assert ev.market_read == MarketRead.MARKET_ASLEEP
