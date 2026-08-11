"""
IV Rank 计算（隐含波动率排名）
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# IV Rank 阈值
IV_RANK_BUY = 30   # IV Rank < 30 → 买方优势（适合买期权）
IV_RANK_SELL = 70  # IV Rank > 70 → 卖方优势（适合卖期权）


def calc_iv_rank(option_chain: List[Dict], spot: float) -> Tuple[float, str]:
    """
    计算 IV Rank（隐含波动率排名）

    IV Rank = (当前 IV - 近 30 天最低 IV) / (近 30 天最高 IV - 近 30 天最低 IV) × 100%

    返回: (iv_rank, signal)
    signal:
      'BUY_IV'  (<30%) — IV 被低估，适合买期权（买 Vega）
      'SELL_IV' (>70%) — IV 被高估，适合卖期权（卖 Vega）
      'NEUTRAL'
    """
    if not option_chain:
        return 50.0, 'NEUTRAL'

    # 用当前链的 ATM IV 作为代理
    atm_strikes = [c.get('_strike', 0) for c in option_chain]
    if not atm_strikes:
        return 50.0, 'NEUTRAL'

    # 找到 ATM 附近的期权
    nearest = min(atm_strikes, key=lambda s: abs(s - spot))
    atm_option = next((c for c in option_chain
                       if c.get('_strike', 0) == nearest and
                       abs(c.get('_strike', 0) - spot) / spot < 0.05), None)

    if atm_option is None:
        return 50.0, 'NEUTRAL'

    atm_iv = atm_option.get('_iv', 80)

    # 模拟 HV 历史范围（Deribit 历史数据接口较复杂，用简化估算）
    # 加密货币 HV 通常在 40%~150% 范围
    hv_low = 40.0   # 近 30 天最低年化波动率（估算）
    hv_high = 150.0  # 近 30 天最高年化波动率（估算）

    # Deribit ATM 期权的 IV 通常比 HV 高 20-30%
    proxy_low = hv_low * 1.2
    proxy_high = hv_high * 1.3

    iv_rank = (atm_iv - proxy_low) / (proxy_high - proxy_low) * 100
    iv_rank = max(0.0, min(100.0, iv_rank))

    if iv_rank < IV_RANK_BUY:
        signal = 'BUY_IV'
    elif iv_rank > IV_RANK_SELL:
        signal = 'SELL_IV'
    else:
        signal = 'NEUTRAL'

    return iv_rank, signal
