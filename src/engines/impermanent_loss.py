"""
Impermanent Loss Calculator — src/engines/impermanent_loss.py (v3.5.0)

Calculate impermanent loss for Uniswap V2/V3 LP positions.
Compare LP returns vs simple HODL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Optional
import math


@dataclass
class ILResult:
    """Impermanent loss analysis result."""
    price_ratio: float            # current_price / entry_price
    il_pct: float                 # impermanent loss (%)
    lp_return_pct: float          # LP total return including fees
    hodl_return_pct: float        # HODL return
    outperformance_pct: float     # LP - HODL (positive = LP better)
    fees_earned_pct: float = 0.0  # estimated fee income
    recommendation: str = ""

    def summary(self) -> str:
        return (
            f"价格变化: {((self.price_ratio-1)*100):+.1f}%  |  "
            f"无常损失: {self.il_pct:.2f}%  |  "
            f"LP收益: {self.lp_return_pct:+.2f}%  |  "
            f"HODL: {self.hodl_return_pct:+.2f}%  |  "
            f"${self.recommendation}"
        )


def calc_impermanent_loss(
    entry_price_a: float,
    entry_price_b: float,
    current_price_a: float,
    current_price_b: float,
    fee_apr: float = 0.0,
    days: int = 30,
) -> ILResult:
    """Calculate impermanent loss for Uniswap V2-style AMM.

    IL formula: IL = 2 * sqrt(r) / (1 + r) - 1
    where r = price_ratio (current / entry)

    Args:
        entry_price_a: Entry price of token A (in quote, e.g. USDC)
        entry_price_b: Entry price of token B
        current_price_a: Current price of token A
        current_price_b: Current price of token B
        fee_apr: Pool fee APR as decimal (e.g. 0.15 = 15%)
        days: Holding period in days

    Returns:
        ILResult with detailed comparison
    """
    # Price ratio using A/B pair price
    entry_pair_price = entry_price_a / max(entry_price_b, 1e-8)
    current_pair_price = current_price_a / max(current_price_b, 1e-8)
    price_ratio = current_pair_price / max(entry_pair_price, 1e-8)

    # Uniswap V2 IL formula
    sqrt_r = math.sqrt(price_ratio)
    lp_value_ratio = 2 * sqrt_r / (1 + price_ratio)
    il_pct = (lp_value_ratio - 1.0) * 100  # negative = loss

    # HODL return: equally weighted at entry
    hodl_pct = ((price_ratio - 1.0) / 2.0) * 100  # 50/50 portfolio return

    # Fee income estimate
    fee_period = days / 365
    fees_earned = fee_apr * fee_period * 100

    # LP total return
    lp_return = il_pct + fees_earned

    # Outperformance
    outperformance = lp_return - hodl_pct

    # Recommendation
    if outperformance > 5:
        rec = "LP优于持有——无常损失被手续费覆盖"
    elif outperformance > 0:
        rec = "LP略优于持有——手续费刚好覆盖无常损失"
    elif outperformance > -5:
        rec = "LP小幅跑输——考虑退出LP"
    else:
        rec = "LP严重跑输——立即退出LP，无常损失吞噬手续费"

    return ILResult(
        price_ratio=round(price_ratio, 4),
        il_pct=round(il_pct, 3),
        lp_return_pct=round(lp_return, 3),
        hodl_return_pct=round(hodl_pct, 3),
        outperformance_pct=round(outperformance, 3),
        fees_earned_pct=round(fees_earned, 3),
        recommendation=rec,
    )


def calc_il_breakeven(price_change_pct: float) -> float:
    """Calculate minimum fee APR needed to break even for a given price change.

    Args:
        price_change_pct: Price change from entry (e.g. +50 = +50%, -30 = -30%)

    Returns:
        Required annual fee APR (as decimal) to break even
    """
    r = 1.0 + price_change_pct / 100.0
    sqrt_r = math.sqrt(r)
    lp_ratio = 2 * sqrt_r / (1 + r)
    il_pct = abs(lp_ratio - 1.0) * 100

    # Annualize: need IL / holding_period * 365/30
    # Assume 30-day holding
    return round(il_pct * 12.17 / 100, 4)  # 365/30 ≈ 12.17


def il_table(price_changes: Optional[list] = None) -> str:
    """Generate impermanent loss reference table."""
    if price_changes is None:
        price_changes = [-90, -70, -50, -30, -10, 0, 10, 50, 100, 200, 500]

    lines = ["═══ 无常损失参考表 ═══"]
    lines.append(f"{'价格变化':>8}  {'无常损失':>8}  {'所需FeeAPR':>10}  {'备注'}")
    lines.append("-" * 55)

    for pc in price_changes:
        r = 1.0 + pc / 100.0
        sqrt_r = math.sqrt(max(r, 1e-8))
        il = (2 * sqrt_r / (1 + r) - 1.0) * 100
        breakeven = abs(il) * 12.17

        note = ""
        if abs(il) < 0.5:
            note = "几乎无损"
        elif abs(il) < 5:
            note = "轻度损失"
        elif abs(il) < 20:
            note = "显著损失"
        else:
            note = "严重损失"

        lines.append(
            f"  {pc:>+5.0f}%  {il:>8.2f}%  "
            f"{breakeven:>8.1f}% APR  {note}"
        )

    lines.append("")
    lines.append("公式: IL = 2×√r / (1+r) - 1  (r = 当前价/入场价)")
    lines.append("参考: Uniswap V2 白皮书")
    return "\n".join(lines)
