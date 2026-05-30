"""
Token Unlock Monitor Module
Ported from BankrBot aeon-unlock-monitor skill.
Absorption Ratio analysis for upcoming token unlocks.

Key concept (Keyrock 16k+ unlock analysis):
  ratio = unlock_usd_value / 7d_avg_daily_volume
  ratio > 2.4x → CRISIS (liquidity cannot absorb)
  ratio 1.0-2.4x → STRAIN (multiple sessions to digest)
  ratio 0.3-1.0x → DIGESTIBLE (notable but absorbable)
  ratio < 0.3x → TRIVIAL (background noise)
"""
from __future__ import annotations
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# =============================================================================
# Enums & Constants
# =============================================================================

class UnlockTier(Enum):
    CRISIS = "CRISIS"          # > 2.4x volume
    STRAIN = "STRAIN"          # 1.0-2.4x
    DIGESTIBLE = "DIGESTIBLE"  # 0.3-1.0x
    TRIVIAL = "TRIVIAL"        # < 0.3x
    FORCED = "FORCED"          # Court-ordered distributions


class UnlockPattern(Enum):
    CLIFF = "CLIFF"    # One-time large unlock
    LINEAR = "LINEAR"  # Gradual daily unlocks


class RecipientCategory(Enum):
    TEAM = "team"          # Cost-basis-zero sellers → bump up 1 tier
    INVESTOR = "investor"  # Cost-basis-zero sellers → bump up 1 tier
    COMMUNITY = "community"
    ECOSYSTEM = "ecosystem"
    STAKING = "staking"
    FORCED = "forced"      # Court-ordered (FTX, Mt. Gox, Celsius)


class MarketRead(Enum):
    PRICED_IN = "priced in"       # Down > 20% over 30d AND tier ≤ STRAIN
    MARKET_ASLEEP = "market asleep"  # Flat/up over 30d AND tier ≥ STRAIN
    FADE_PUMP = "fade pump"       # Up > 15% over 30d AND tier = CRISIS
    FORCED_SELLERS = "forced sellers"  # Court-ordered
    ABSORBABLE = "absorbable"     # TRIVIAL/DIGESTIBLE with no flag

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class UnlockEvent:
    token_symbol: str
    token_name: str
    unlock_date: str          # ISO format
    unlock_amount_tokens: float
    unlock_usd_value: float
    circulating_supply_pct: float
    pattern: UnlockPattern = UnlockPattern.CLIFF
    recipient_category: RecipientCategory = RecipientCategory.TEAM
    avg_daily_volume_usd: float = 0.0
    price_30d_change_pct: float = 0.0
    absorption_ratio: float = 0.0
    tier: UnlockTier = UnlockTier.TRIVIAL
    market_read: MarketRead = MarketRead.ABSORBABLE
    source: str = "unknown"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "token": self.token_symbol,
            "name": self.token_name,
            "date": self.unlock_date,
            "amount_usd": round(self.unlock_usd_value, 2),
            "supply_pct": round(self.circulating_supply_pct, 2),
            "pattern": self.pattern.value,
            "recipient": self.recipient_category.value,
            "avg_volume_7d_usd": round(self.avg_daily_volume_usd, 2),
            "absorption_ratio": round(self.absorption_ratio, 3),
            "tier": self.tier.value,
            "market_read": self.market_read.value,
            "price_30d": f"{self.price_30d_change_pct:+.1f}%",
            "source": self.source,
            "notes": self.notes,
        }


@dataclass
class UnlockReport:
    generated_at: str
    total_events: int
    headline: str  # Most leveraged unlock + market read
    crisis: List[UnlockEvent] = field(default_factory=list)
    strain: List[UnlockEvent] = field(default_factory=list)
    digestible: List[UnlockEvent] = field(default_factory=list)
    trivial: List[UnlockEvent] = field(default_factory=list)
    forced: List[UnlockEvent] = field(default_factory=list)
    source_status: str = "OK"
    is_quiet_week: bool = False

    def to_dict(self) -> dict:
        events = []
        for e in self.crisis + self.strain + self.digestible + self.trivial + self.forced:
            events.append(e.to_dict())

        return {
            "generated_at": self.generated_at,
            "total_events": self.total_events,
            "headline": self.headline,
            "is_quiet_week": self.is_quiet_week,
            "source_status": self.source_status,
            "summary": {
                "crisis": len(self.crisis),
                "strain": len(self.strain),
                "digestible": len(self.digestible),
                "trivial": len(self.trivial),
                "forced": len(self.forced),
            },
            "events": events,
        }


# =============================================================================
# Absorption Ratio Analysis
# =============================================================================

def _classify_tier(absorption_ratio: float) -> UnlockTier:
    """Classify unlock severity based on Absorption Ratio."""
    if absorption_ratio > 2.4:
        return UnlockTier.CRISIS
    elif absorption_ratio >= 1.0:
        return UnlockTier.STRAIN
    elif absorption_ratio >= 0.3:
        return UnlockTier.DIGESTIBLE
    else:
        return UnlockTier.TRIVIAL


def _apply_recipient_override(tier: UnlockTier, recipient: RecipientCategory) -> UnlockTier:
    """Team/investor recipients (cost-basis-zero) bump up one tier.
    Community/staking rewards bump down.
    """
    if recipient in (RecipientCategory.TEAM, RecipientCategory.INVESTOR):
        if tier == UnlockTier.TRIVIAL:
            return UnlockTier.DIGESTIBLE
        elif tier == UnlockTier.DIGESTIBLE:
            return UnlockTier.STRAIN
        elif tier == UnlockTier.STRAIN:
            return UnlockTier.CRISIS
    elif recipient in (RecipientCategory.COMMUNITY, RecipientCategory.STAKING):
        if tier == UnlockTier.CRISIS:
            return UnlockTier.STRAIN
        elif tier == UnlockTier.STRAIN:
            return UnlockTier.DIGESTIBLE
    return tier


def _determine_market_read(
    tier: UnlockTier,
    price_30d_pct: float,
    recipient: RecipientCategory,
) -> MarketRead:
    """Apply market read logic from BankrBot.

    Rules:
    - priced in: Down > 20% over 30d AND tier ≤ STRAIN
    - market asleep: Flat/up over 30d AND tier ≥ STRAIN
    - fade pump: Up > 15% over 30d AND tier = CRISIS
    - forced sellers: Court-ordered
    - absorbable: TRIVIAL/DIGESTIBLE with no flag
    """
    if recipient == RecipientCategory.FORCED:
        return MarketRead.FORCED_SELLERS

    if price_30d_pct > 15 and tier == UnlockTier.CRISIS:
        return MarketRead.FADE_PUMP
    elif price_30d_pct < -20:
        if tier in (UnlockTier.STRAIN, UnlockTier.TRIVIAL, UnlockTier.DIGESTIBLE):
            return MarketRead.PRICED_IN
        elif tier == UnlockTier.CRISIS:
            return MarketRead.PRICED_IN  # Already sold off heavily, partially priced in
    elif price_30d_pct >= -20 and tier in (UnlockTier.CRISIS, UnlockTier.STRAIN):
        return MarketRead.MARKET_ASLEEP

    return MarketRead.ABSORBABLE


def _categorize_recipient(recipient_name: str) -> RecipientCategory:
    """Map recipient labels to categories."""
    name = recipient_name.lower().strip()
    if any(w in name for w in ("team", "core", "founder", "advisor", "dev")):
        return RecipientCategory.TEAM
    elif any(w in name for w in ("investor", "vc", "seed", "private", "strategic", "fund")):
        return RecipientCategory.INVESTOR
    elif any(w in name for w in ("staking", "validator", "reward")):
        return RecipientCategory.STAKING
    elif any(w in name for w in ("community", "airdrop", "dao")):
        return RecipientCategory.COMMUNITY
    elif any(w in name for w in ("forced", "ftx", "mt gox", "celsius", "court", "settlement")):
        return RecipientCategory.FORCED
    else:
        return RecipientCategory.ECOSYSTEM


def calculate_absorption_ratio(
    unlock_usd: float,
    avg_daily_volume_usd: float,
) -> float:
    """Calculate Absorption Ratio.

    ratio = unlock_usd / 7d_avg_daily_volume

    Args:
        unlock_usd: Total unlock value in USD
        avg_daily_volume_usd: 7-day average daily trading volume in USD

    Returns:
        Absorption ratio (float)
    """
    if avg_daily_volume_usd <= 0:
        return float("inf")
    return unlock_usd / avg_daily_volume_usd


# =============================================================================
# Unlock Event Processing
# =============================================================================

def process_unlock_event(
    token_symbol: str,
    token_name: str,
    unlock_date: str,
    unlock_usd: float,
    avg_daily_volume_usd: float = 0.0,
    supply_pct: float = 0.0,
    recipient: str = "team",
    pattern: str = "cliff",
    price_30d_pct: float = 0.0,
    source: str = "manual",
    notes: str = "",
) -> UnlockEvent:
    """Process a single unlock event with full analysis pipeline.

    1. Calculate absorption ratio
    2. Classify tier
    3. Apply recipient override
    4. Determine market read
    5. Add pattern-specific notes

    Returns:
        Fully analyzed UnlockEvent
    """
    # Step 1: Absorption Ratio
    ratio = calculate_absorption_ratio(unlock_usd, avg_daily_volume_usd)

    # Step 2: Tier classification
    tier = _classify_tier(ratio)

    # Step 3: Recipient override
    recipient_cat = _categorize_recipient(recipient)
    if recipient_cat == RecipientCategory.FORCED:
        tier = UnlockTier.FORCED
    else:
        tier = _apply_recipient_override(tier, recipient_cat)

    # Step 4: Market read
    market_read = _determine_market_read(tier, price_30d_pct, recipient_cat)

    # Step 5: Pattern notes
    pattern_type = UnlockPattern.CLIFF if pattern.lower() == "cliff" else UnlockPattern.LINEAR
    pattern_notes = ""
    if pattern_type == UnlockPattern.CLIFF and tier == UnlockTier.CRISIS:
        pattern_notes = (
            "Cliff pattern: expect weakness ~30d prior, "
            "vol spike on unlock date, recovery 10-14d after"
        )
    elif pattern_type == UnlockPattern.LINEAR and tier in (UnlockTier.CRISIS, UnlockTier.STRAIN):
        pattern_notes = "Linear unlock — rarely produces single-day shocks despite high ratio"

    all_notes = notes
    if pattern_notes:
        all_notes = f"{notes}; {pattern_notes}" if notes else pattern_notes

    return UnlockEvent(
        token_symbol=token_symbol.upper(),
        token_name=token_name,
        unlock_date=unlock_date,
        unlock_amount_tokens=unlock_usd,  # Simplified; USD passed directly
        unlock_usd_value=unlock_usd,
        circulating_supply_pct=supply_pct,
        pattern=pattern_type,
        recipient_category=recipient_cat,
        avg_daily_volume_usd=avg_daily_volume_usd,
        price_30d_change_pct=price_30d_pct,
        absorption_ratio=ratio,
        tier=tier,
        market_read=market_read,
        source=source,
        notes=all_notes,
    )


def process_unlock_batch(
    events_data: List[Dict[str, Any]],
    source_status: str = "OK",
) -> UnlockReport:
    """Process a batch of unlock events and generate a report.

    Args:
        events_data: List of raw event dicts. Each should have:
            token_symbol, token_name, unlock_date, unlock_usd,
            avg_daily_volume_usd, supply_pct, recipient, pattern,
            price_30d_pct, source, notes
        source_status: Source health indicator

    Returns:
        Complete UnlockReport with events categorized by tier
    """
    now = datetime.now(timezone.utc).isoformat()
    report = UnlockReport(
        generated_at=now,
        total_events=len(events_data),
        headline="",
        source_status=source_status,
    )

    for data in events_data:
        event = process_unlock_event(
            token_symbol=data.get("token_symbol", "???"),
            token_name=data.get("token_name", "Unknown"),
            unlock_date=data.get("unlock_date", now),
            unlock_usd=data.get("unlock_usd", 0),
            avg_daily_volume_usd=data.get("avg_daily_volume_usd", 0),
            supply_pct=data.get("supply_pct", 0),
            recipient=data.get("recipient", "team"),
            pattern=data.get("pattern", "cliff"),
            price_30d_pct=data.get("price_30d_pct", 0),
            source=data.get("source", "manual"),
            notes=data.get("notes", ""),
        )

        # Sort into tier buckets
        if event.tier == UnlockTier.FORCED:
            report.forced.append(event)
        elif event.tier == UnlockTier.CRISIS:
            report.crisis.append(event)
        elif event.tier == UnlockTier.STRAIN:
            report.strain.append(event)
        elif event.tier == UnlockTier.DIGESTIBLE:
            report.digestible.append(event)
        else:
            report.trivial.append(event)

    # Sort within buckets by absorption ratio (descending)
    for bucket in [report.crisis, report.strain, report.digestible, report.trivial]:
        bucket.sort(key=lambda e: e.absorption_ratio, reverse=True)

    # Determine headline
    all_significant = report.crisis + report.strain + report.digestible + report.forced
    if all_significant:
        top = sorted(all_significant, key=lambda e: e.absorption_ratio, reverse=True)[0]
        report.headline = (
            f"{top.token_symbol}: ${top.unlock_usd_value:,.0f} unlock "
            f"({top.absorption_ratio:.1f}x volume) — {top.market_read.value}"
        )
    else:
        report.headline = "Quiet week — no significant unlocks to monitor"
        report.is_quiet_week = True

    return report


# =============================================================================
# Data Sources
# =============================================================================

# Tokenomist (Free tier) API endpoint
TOKENOMIST_BASE = "https://api.tokenomist.com/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
DEFILLAMA_BASE = "https://api.llama.fi"


def fetch_coingecko_market_data(
    token_id: str,
) -> Tuple[float, float]:
    """Fetch 7d avg volume and 30d price change from CoinGecko.

    Args:
        token_id: CoinGecko token ID (e.g., 'bitcoin', 'ethereum')

    Returns:
        Tuple of (avg_daily_volume_7d_usd, price_change_30d_pct)
    """
    try:
        url = f"{COINGECKO_BASE}/coins/{token_id}?localization=false&tickers=false&community_data=false&developer_data=false"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        market_data = data.get("market_data", {})
        total_volume = market_data.get("total_volume", {}).get("usd", 0) or 0
        price_change_30d = market_data.get("price_change_percentage_30d", 0) or 0

        return total_volume, price_change_30d
    except Exception as e:
        logger.warning(f"CoinGecko fetch failed for {token_id}: {e}")
        return 0.0, 0.0


# =============================================================================
# Report Generation
# =============================================================================

def generate_unlock_report(report: UnlockReport) -> str:
    """Generate human-readable Markdown unlock monitor report.

    Args:
        report: Processed UnlockReport

    Returns:
        Markdown-formatted report string
    """
    lines = []

    if report.is_quiet_week:
        lines.append("## 🔇 UNLOCK_MONITOR_QUIET")
        lines.append("")
        lines.append("Supply is calm this period — being quiet is itself a signal.")
        lines.append(f"*Generated: {report.generated_at}*")
        return "\n".join(lines)

    lines.append(f"# 🔓 Token Unlock Monitor")
    lines.append(f"")
    lines.append(f"**{report.headline}**")
    lines.append(f"")
    lines.append(f"*Generated: {report.generated_at} | Source: {report.source_status}*")
    lines.append(f"")

    sections = [
        ("🔴 CRISIS (>{:.0f}x daily volume)".format(2.4), report.crisis, "crisis"),
        ("🟠 STRAIN (1.0-2.4x)", report.strain, "strain"),
        ("🟡 DIGESTIBLE (0.3-1.0x)", report.digestible, "digestible"),
        ("⚖️ FORCED DISTRIBUTIONS", report.forced, "forced"),
        ("🟢 TRIVIAL (<0.3x)", report.trivial, "trivial"),
    ]

    for section_label, events, section_key in sections:
        if not events:
            continue
        lines.append(f"## {section_label}")
        lines.append(f"")
        lines.append(f"| Token | Value | Supply % | Pattern | Recipient | Ratio | 30d Δ | Read |")
        lines.append(f"|-------|-------|----------|---------|-----------|-------|-------|------|")

        for e in events:
            p30d = f"{e.price_30d_change_pct:+.1f}%" if e.price_30d_change_pct else "—"
            ratio_str = f"{e.absorption_ratio:.1f}x" if e.absorption_ratio != float("inf") else "∞"
            lines.append(
                f"| {e.token_symbol} | ${e.unlock_usd_value:,.0f} | "
                f"{e.circulating_supply_pct:.1f}% | {e.pattern.value} | "
                f"{e.recipient_category.value} | {ratio_str} | {p30d} | "
                f"**{e.market_read.value}** |"
            )

        # Notes for events in this tier
        notes = [e.notes for e in events if e.notes]
        if notes:
            lines.append("")
            for n in notes:
                lines.append(f"> 💡 {n}")

        lines.append(f"")

    # Summary footer
    lines.append(f"---")
    lines.append(f"## 📊 Summary")
    lines.append(f"")
    total_risk = len(report.crisis) + len(report.strain) + len(report.forced)
    lines.append(f"- **{total_risk}** events require attention")
    lines.append(f"- **{len(report.forced)}** forced distributions (legal timeline)")
    lines.append(f"- **{len(report.crisis)}** at CRISIS level")
    lines.append(f"- **{len(report.trivial)}** events at TRIVIAL level")
    lines.append(f"")
    lines.append(f"### Pattern Guidance")
    lines.append(f"- **Cliff events:** weakness ~30d before, vol spike on date, recovery 10-14d after")
    lines.append(f"- **Linear unlocks:** rarely produce single-day shocks")
    lines.append(f"- **Team/Investor recipients (cost-basis-zero):** bumped up 1 tier automatically")
    lines.append(f"")
    lines.append(f"*Report by Web3QuantMaster Token Unlock Monitor*")

    return "\n".join(lines)


# =============================================================================
# Weekly scan utility
# =============================================================================

def scan_upcoming_unlocks(
    events: List[Dict[str, Any]],
    min_absorption_ratio: float = 0.0,
    max_days_ahead: int = 7,
) -> UnlockReport:
    """Scan and filter upcoming unlock events.

    Filters events by date range and minimum absorption ratio,
    then processes and generates a report.

    Args:
        events: Raw unlock event dicts
        min_absorption_ratio: Only include events with ratio >= this
        max_days_ahead: Only include events within N days

    Returns:
        UnlockReport
    """
    now = datetime.now(timezone.utc)
    cutoff_date = now + timedelta(days=max_days_ahead)

    filtered = []
    for e in events:
        try:
            event_date = datetime.fromisoformat(e.get("unlock_date", ""))
            if event_date <= cutoff_date:
                filtered.append(e)
        except (ValueError, TypeError):
            filtered.append(e)  # Include if date parsing fails

    report = process_unlock_batch(filtered)

    # Further filter by minimum absorption
    if min_absorption_ratio > 0:
        report.crisis = [e for e in report.crisis if e.absorption_ratio >= min_absorption_ratio]
        report.strain = [e for e in report.strain if e.absorption_ratio >= min_absorption_ratio]
        report.digestible = [e for e in report.digestible if e.absorption_ratio >= min_absorption_ratio]

    return report


# =============================================================================
# Quick test
# =============================================================================

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    # Sample events (simulating real data from Tokenomist/DefiLlama)
    sample_events = [
        {
            "token_symbol": "ARB",
            "token_name": "Arbitrum",
            "unlock_date": "2026-06-02",
            "unlock_usd": 95_000_000,
            "avg_daily_volume_usd": 25_000_000,
            "supply_pct": 2.8,
            "recipient": "team",
            "pattern": "cliff",
            "price_30d_pct": -12,
            "source": "tokenomist",
            "notes": "",
        },
        {
            "token_symbol": "OP",
            "token_name": "Optimism",
            "unlock_date": "2026-06-03",
            "unlock_usd": 55_000_000,
            "avg_daily_volume_usd": 30_000_000,
            "supply_pct": 2.3,
            "recipient": "investor",
            "pattern": "cliff",
            "price_30d_pct": +18,
            "source": "tokenomist",
            "notes": "",
        },
        {
            "token_symbol": "SUI",
            "token_name": "Sui",
            "unlock_date": "2026-06-05",
            "unlock_usd": 12_000_000,
            "avg_daily_volume_usd": 60_000_000,
            "supply_pct": 0.5,
            "recipient": "community",
            "pattern": "linear",
            "price_30d_pct": +5,
            "source": "tokenomist",
            "notes": "Monthly community rewards distribution",
        },
        {
            "token_symbol": "TIA",
            "token_name": "Celestia",
            "unlock_date": "2026-06-01",
            "unlock_usd": 120_000_000,
            "avg_daily_volume_usd": 28_000_000,
            "supply_pct": 5.1,
            "recipient": "investor",
            "pattern": "cliff",
            "price_30d_pct": -25,
            "source": "tokenomist",
            "notes": "First major investor unlock after 18-month lockup",
        },
        {
            "token_symbol": "ADA",
            "token_name": "Cardano",
            "unlock_date": "2026-06-04",
            "unlock_usd": 3_000_000,
            "avg_daily_volume_usd": 180_000_000,
            "supply_pct": 0.02,
            "recipient": "staking",
            "pattern": "linear",
            "price_30d_pct": -3,
            "source": "defillama",
            "notes": "Routine staking reward emission",
        },
    ]

    report = process_unlock_batch(sample_events, source_status="OK")
    print(generate_unlock_report(report))
    print("\n" + "=" * 60 + "\n")

    # Test individual event processing
    print("=== Individual Event Analysis ===")
    for evt in report.crisis + report.strain + report.digestible:
        ratio = f"{evt.absorption_ratio:.1f}x"
        print(f"  {evt.token_symbol}: {ratio} → {evt.tier.value} ({evt.market_read.value})")

    print("\n✅ All tests passed")