"""
策略基类 v1.0 - BaseStrategy ABC
=== 统一策略生命周期管理 ===

所有交易策略必须继承 BaseStrategy，实现抽象方法。
提供：参数校验、最小K线验证、元数据管理、信号生成标准化。

用法:
    from strategy_base import BaseStrategy, Signal

    class MyStrategy(BaseStrategy):
        name = '均线交叉'
        strategy_id = 'ma_cross'
        params = {'fast': 5, 'slow': 20}
        min_bars = 20

        def generate_signals(self, candles):
            ...

    strategy = MyStrategy()
    strategy.validate_params({'fast': 8})
    signals = strategy.run(candles)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime


@dataclass
class Signal:
    """标准化交易信号。"""
    type: str          # 'BUY' | 'SELL'
    index: int         # K线索引
    price: float = 0.0
    confidence: float = 1.0
    reason: str = ''


@dataclass
class StrategyMetadata:
    """策略元数据（版本、统计、适用市场）。"""
    strategy_id: str
    name: str
    version: str = '1.0.0'
    author: str = ''
    description: str = ''
    requires: List[str] = field(default_factory=list)  # 依赖的指标
    min_bars: int = 20
    suitable_regimes: List[str] = field(default_factory=list)  # 适合的市场周期
    tags: List[str] = field(default_factory=list)


class BaseStrategy(ABC):
    """
    策略抽象基类。
    
    子类必须实现：
    - generate_signals(candles) → List[Signal]
    
    子类可选覆盖：
    - validate() 参数校验
    - warmup() 预热逻辑
    - get_metadata() 元数据
    """

    # === 子类必须定义的类属性 ===
    strategy_id: str = 'base'
    name: str = 'Base Strategy'
    params: Dict[str, Any] = {}
    min_bars: int = 20
    requires: List[str] = []

    def __init__(self, **overrides):
        """
        初始化策略。
        
        Args:
            **overrides: 覆盖默认参数，如 MyStrategy(fast=8, slow=21)
        """
        self.active_params = {**self.__class__.params, **overrides}
        self._last_signals: List[Signal] = []
        self._run_count: int = 0
        self._total_signals: int = 0

    @abstractmethod
    def generate_signals(self, candles: List[Dict[str, Any]]) -> List[Signal]:
        """
        生成交易信号。（子类必须实现）
        
        Args:
            candles: K线数据列表，每项含 open/high/low/close/volume/time
        
        Returns:
            List[Signal]: 标准化信号列表
        """
        ...

    def validate(self) -> Tuple[bool, str]:
        """
        校验策略参数是否合法。
        
        Returns:
            (is_valid, error_message)
        """
        if not self.strategy_id or self.strategy_id == 'base':
            return False, "strategy_id 不能为空或使用默认值 'base'"
        if not self.name:
            return False, "name 不能为空"
        if self.min_bars < 1:
            return False, f"min_bars 必须 >= 1，当前值: {self.min_bars}"
        return True, "OK"

    def validate_params(self, override_params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        校验外部传入的参数是否合法。
        
        Args:
            override_params: 用户传入的参数
        
        Returns:
            (is_valid, error_message)
        """
        for k in override_params:
            if k not in self.params:
                return False, f"未知参数: {k}，有效参数: {list(self.params.keys())}"
        return True, "OK"

    def warmup(self, candles: List[Dict[str, Any]]) -> bool:
        """
        策略预热（初始化内部状态）。
        子类可选覆盖。
        
        Returns:
            bool: 预热是否成功
        """
        return len(candles) >= self.min_bars

    def run(self, candles: List[Dict[str, Any]], **kwargs) -> List[Signal]:
        """
        完整策略执行流程：warmup → generate_signals。
        
        Args:
            candles: K线数据
            **kwargs: 临时参数覆盖
        
        Returns:
            List[Signal]: 信号列表
        """
        if kwargs:
            self.active_params = {**self.active_params, **kwargs}

        if not self.warmup(candles):
            return []

        signals = self.generate_signals(candles)
        self._last_signals = signals
        self._run_count += 1
        self._total_signals += len(signals)
        return signals

    def get_metadata(self) -> StrategyMetadata:
        """获取策略元数据。"""
        return StrategyMetadata(
            strategy_id=self.strategy_id,
            name=self.name,
            description=self.__doc__ or '',
            requires=self.requires,
            min_bars=self.min_bars,
            suitable_regimes=getattr(self, 'suitable_regimes', []),
            tags=getattr(self, 'tags', []),
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取策略运行统计。"""
        return {
            'strategy_id': self.strategy_id,
            'run_count': self._run_count,
            'total_signals': self._total_signals,
            'last_signal_count': len(self._last_signals),
            'last_run_at': datetime.now().isoformat(),
            'active_params': self.active_params,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.strategy_id}, name={self.name})>"


# =============================================================================
# Backward-compatible re-exports from strategy_registry
# =============================================================================
# Imported here so existing code using 'from core_lib.strategy_base import
# register_strategy' continues to work. New code should import directly from
# core_lib.strategy_registry.

from core_lib.strategy_registry import (  # noqa: E402, F401
    register_strategy,
    simple_strategy_register,
    list_strategies,
    get_strategy,
    get_strategy_info,
    strategy_to_registry_entry,
)
