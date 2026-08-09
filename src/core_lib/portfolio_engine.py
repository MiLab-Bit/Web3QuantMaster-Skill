"""
组合优化器 v1.0 - Portfolio Optimizer
=== MPT高效前沿 + Black-Litterman + Risk Parity ===

功能：
1. 协方差矩阵估计（样本 + Ledoit-Wolf shrinkage）
2. 高效前沿计算（numpy向量化）
3. 三种优化模式：最大夏普 / 最小方差 / Risk Parity
4. Black-Litterman 模型（融合主观观点）
5. 约束：仅做多 / 权重上下限 / 总和=1

用法:
    from portfolio_optimizer import PortfolioOptimizer

    opt = PortfolioOptimizer(returns_matrix)        # shape: (T, N)
    weights = opt.max_sharpe()
    weights = opt.min_variance()
    weights = opt.risk_parity()
    weights = opt.black_litterman(P, Q, omega)      # 主观观点
    frontier = opt.efficient_frontier(n_points=50)

参考:
- Markowitz, H. (1952). Portfolio Selection
- Ledoit, O. & Wolf, M. (2004). Honey, I Shrunk the Sample Covariance Matrix
- Black, F. & Litterman, R. (1992). Global Portfolio Optimization
"""
import math
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field

try:
    from scipy.optimize import minimize as _sp_minimize
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False


@dataclass
class OptimizationResult:
    """组合优化结果。"""
    weights: np.ndarray
    expected_return: float
    volatility: float
    sharpe: float
    asset_names: List[str] = field(default_factory=list)
    method: str = ''
    constraints: Dict[str, Any] = field(default_factory=dict)


class PortfolioOptimizer:
    """
    投资组合优化器。
    
    输入: returns_matrix — (T, N) 矩阵，每列为一个资产的收益率序列
    """

    def __init__(self, returns: np.ndarray, asset_names: Optional[List[str]] = None,
                 risk_free_rate: float = 0.0):
        """
        Args:
            returns: (T, N) 收益率矩阵
            asset_names: 资产名称列表
            risk_free_rate: 年化无风险利率
        """
        if returns.ndim != 2:
            raise ValueError("returns 必须是 (T, N) 二维矩阵")
        self.returns = returns
        self.T, self.N = returns.shape
        self.risk_free_rate = risk_free_rate
        self.asset_names = asset_names or [f'Asset_{i}' for i in range(self.N)]
        
        self._mu = None
        self._cov = None
        self._shrinkage_cov = None

    @property
    def mu(self) -> np.ndarray:
        """年化预期收益率向量 (N,)。"""
        if self._mu is None:
            self._mu = np.mean(self.returns, axis=0) * 252  # 年化
        return self._mu

    @property
    def cov(self) -> np.ndarray:
        """年化协方差矩阵 (N, N) — Ledoit-Wolf shrinkage。"""
        if self._shrinkage_cov is None:
            sample_cov = np.cov(self.returns.T) * 252
            self._shrinkage_cov = self._ledoit_wolf_shrinkage(sample_cov)
        return self._shrinkage_cov

    def _ledoit_wolf_shrinkage(self, sample_cov: np.ndarray) -> np.ndarray:
        """
        Ledoit-Wolf 协方差收缩估计。
        收缩目标 = 常数相关性矩阵（比单位矩阵更合理的 shrinkage target）。
        """
        # 常数相关性目标
        vols = np.sqrt(np.diag(sample_cov))
        avg_corr = 0.0
        n = self.N
        if n > 1:
            corr = sample_cov / np.outer(vols, vols)
            tril = np.tril(corr, -1)
            avg_corr = tril.sum() / (n * (n - 1) / 2)
        
        target = np.outer(vols, vols) * avg_corr
        np.fill_diagonal(target, sample_cov.diagonal())
        
        # Ledoit-Wolf shrinkage intensity (简化版)
        shrinkage = max(0.0, min(1.0, 1.0 / (1.0 + self.T / (n ** 2))))
        
        return shrinkage * target + (1 - shrinkage) * sample_cov

    def _portfolio_stats(self, w: np.ndarray) -> Tuple[float, float, float]:
        """计算组合的 收益/波动/夏普。"""
        ret = w @ self.mu
        vol = np.sqrt(w @ self.cov @ w)
        sharpe = (ret - self.risk_free_rate) / vol if vol > 1e-10 else 0
        return ret, vol, sharpe

    # ── scipy-backed long-only solvers (fallback to clip when unavailable) ──
    def _long_only_min_variance(self) -> Optional[np.ndarray]:
        """True long-only global minimum-variance weights via QP (SLSQP)."""
        if not HAS_SCIPY:
            return None
        n = self.N
        cov = self.cov
        cons = ({'type': 'eq', 'fun': lambda w: float(np.sum(w)) - 1.0},)
        bounds = [(0.0, 1.0)] * n
        w0 = np.ones(n) / n
        res = _sp_minimize(lambda w: float(w @ cov @ w), w0,
                           method='SLSQP', bounds=bounds, constraints=cons)
        if not getattr(res, 'success', False):
            return None
        w = np.clip(res.x, 0.0, 1.0)
        s = w.sum()
        return w / s if s > 0 else None

    def _long_only_max_sharpe(self) -> Optional[np.ndarray]:
        """True long-only maximum-Sharpe weights via SLSQP."""
        if not HAS_SCIPY:
            return None
        n = self.N
        cov = self.cov
        mu = self.mu
        rf = self.risk_free_rate
        cons = ({'type': 'eq', 'fun': lambda w: float(np.sum(w)) - 1.0},)
        bounds = [(0.0, 1.0)] * n
        w0 = np.ones(n) / n

        def _neg_sharpe(w):
            ret = float(w @ mu)
            vol = max(float(w @ cov @ w), 1e-12) ** 0.5
            return -(ret - rf) / vol

        res = _sp_minimize(_neg_sharpe, w0, method='SLSQP',
                           bounds=bounds, constraints=cons)
        if not getattr(res, 'success', False):
            return None
        w = np.clip(res.x, 0.0, 1.0)
        s = w.sum()
        return w / s if s > 0 else None

    def max_sharpe(self, bounds: Tuple[float, float] = (0.0, 1.0)) -> OptimizationResult:
        """
        最大夏普比率组合（仅做多，长期约束最优）。
        """
        w = self._long_only_max_sharpe() if HAS_SCIPY else None
        if w is None:
            # Fallback: 无约束切线闭式解 + 仅做多裁剪
            inv_cov = np.linalg.inv(self.cov)
            excess = self.mu - self.risk_free_rate
            w_raw = inv_cov @ excess
            w_raw = np.maximum(w_raw, 0)
            w = w_raw / w_raw.sum() if w_raw.sum() > 0 else np.ones(self.N) / self.N
            w = np.clip(w, bounds[0], bounds[1])
            w /= w.sum()

        ret, vol, sharpe = self._portfolio_stats(w)
        return OptimizationResult(
            weights=w, expected_return=ret, volatility=vol, sharpe=sharpe,
            asset_names=self.asset_names, method='max_sharpe',
            constraints={'bounds': bounds}
        )

    def min_variance(self, bounds: Tuple[float, float] = (0.0, 1.0)) -> OptimizationResult:
        """
        最小方差组合（仅做多，长期约束最优）。
        """
        w = self._long_only_min_variance() if HAS_SCIPY else None
        if w is None:
            # Fallback: 无约束 GMV 闭式解 + 仅做多裁剪
            inv_cov = np.linalg.inv(self.cov)
            ones = np.ones(self.N)
            w_raw = inv_cov @ ones
            w = w_raw / w_raw.sum()
            w = np.clip(w, bounds[0], bounds[1])
            w /= w.sum()

        ret, vol, sharpe = self._portfolio_stats(w)
        return OptimizationResult(
            weights=w, expected_return=ret, volatility=vol, sharpe=sharpe,
            asset_names=self.asset_names, method='min_variance',
            constraints={'bounds': bounds}
        )

    def risk_parity(self, bounds: Tuple[float, float] = (0.01, 1.0), max_iter: int = 100) -> OptimizationResult:
        """
        Risk Parity（等风险贡献）。
        使用牛顿法迭代求解：使得每个资产的风险贡献相等。
        """
        w = np.ones(self.N) / self.N
        
        for _ in range(max_iter):
            sigma_w = self.cov @ w
            port_vol = np.sqrt(w @ sigma_w)
            if port_vol < 1e-10:
                break
            
            # 边际风险贡献
            mrc = sigma_w / port_vol
            # 风险贡献
            rc = w * mrc
            # 目标：rc_i = 1/N
            target_rc = port_vol / self.N
            
            # 梯度下降
            grad = 2 * (rc - target_rc) / port_vol
            w -= 0.1 * grad
            w = np.clip(w, bounds[0], bounds[1])
            w /= w.sum()
        
        ret, vol, sharpe = self._portfolio_stats(w)
        return OptimizationResult(
            weights=w, expected_return=ret, volatility=vol, sharpe=sharpe,
            asset_names=self.asset_names, method='risk_parity'
        )

    def black_litterman(self, P: np.ndarray, Q: np.ndarray, 
                        omega: Optional[np.ndarray] = None,
                        tau: float = 0.05, bounds: Tuple[float, float] = (0.0, 1.0)) -> OptimizationResult:
        """
        Black-Litterman 模型：融合主观观点与市场均衡收益。
        
        Args:
            P: (K, N) 观点矩阵，每行一个观点，如 [1, -1, 0, ...] 表示 Asset1 比 Asset2 好
            Q: (K,) 观点期望收益向量
            omega: (K, K) 观点不确定性矩阵，默认 diag(diag(P @ cov @ P') * tau)
            tau: 市场均衡收益的不确定性缩放因子
        
        Example:
            观点："BTC 年化收益 30%，ETH 20%"
            P = np.array([[1, 0], [0, 1]])  # 每个资产一个观点
            Q = np.array([0.30, 0.20])
        """
        K = len(Q)
        pi = self.mu  # 市场均衡收益（用历史均值代理）
        
        if omega is None:
            omega = np.diag(np.diag(P @ self.cov @ P.T)) * tau
        
        # Black-Litterman 后验收益
        tau_cov = tau * self.cov
        middle = np.linalg.inv(np.linalg.inv(tau_cov) + P.T @ np.linalg.inv(omega) @ P)
        posterior_mu = middle @ (np.linalg.inv(tau_cov) @ pi + P.T @ np.linalg.inv(omega) @ Q)
        
        # 后验协方差
        posterior_cov = self.cov + middle
        
        # 用后验参数做最大夏普优化
        inv_cov = np.linalg.inv(posterior_cov)
        excess = posterior_mu - self.risk_free_rate
        w_raw = inv_cov @ excess
        w_raw = np.maximum(w_raw, 0)
        w = w_raw / w_raw.sum() if w_raw.sum() > 0 else np.ones(self.N) / self.N
        w = np.clip(w, bounds[0], bounds[1])
        w /= w.sum()
        
        ret = w @ posterior_mu
        vol = np.sqrt(w @ posterior_cov @ w)
        sharpe = (ret - self.risk_free_rate) / vol if vol > 1e-10 else 0
        
        return OptimizationResult(
            weights=w, expected_return=ret, volatility=vol, sharpe=sharpe,
            asset_names=self.asset_names, method='black_litterman',
            constraints={'tau': tau, 'n_views': K, 'bounds': bounds}
        )

    def efficient_frontier(self, n_points: int = 50) -> Dict[str, np.ndarray]:
        """
        计算 Markowitz 高效前沿（仅风险资产、仅做多）。

        使用两基金定理（two-fund theorem），使每个返回的组合 *真实* 拥有其
        标注的目标波动率。旧实现基于切点组合的闭式解，并不追踪目标波动率
        （对所有目标波动率都返回同一个恒定波动率），已修正。

        返回 {'returns', 'volatilities', 'weights', 'target_vols',
              'max_sharpe', 'min_variance'}
        """
        min_vol_result = self.min_variance()
        max_sharpe_result = self.max_sharpe()

        inv_cov = np.linalg.inv(self.cov)
        ones = np.ones(self.N)
        mu = self.mu

        A = float(ones @ inv_cov @ ones)
        B = float(ones @ inv_cov @ mu)
        D = A * float(mu @ inv_cov @ mu) - B ** 2

        # 两基金（在 Σ 意义下正交）：
        #   g = Σ⁻¹1 / A            —— 全局最小方差组合（方差 = 1/A）
        #   d = Σ⁻¹μ − (B/A)Σ⁻¹1     —— 与 g 正交的前沿基金（1'd = 0, g'Σd = 0）
        # 任意前沿组合 w(λ) = g + λ·d，方差 = 1/A + λ²·(D/A)（因 g'Σd = 0）。
        g = inv_cov @ ones / A
        d = inv_cov @ mu - (B / A) * (inv_cov @ ones)
        g_var = 1.0 / A

        # 可行波动率区间：从最小方差到仅做多可达的最大夏普波动率
        # （超出该区间的前沿需要杠杆/做空，仅做多约束下无法精确命中目标波动率）
        vol_min = max(float(min_vol_result.volatility), math.sqrt(g_var), 1e-6)
        vol_max = max(float(max_sharpe_result.volatility), vol_min * 1.1)
        target_vols = np.linspace(vol_min, vol_max, n_points)

        frontier_rets: List[float] = []
        frontier_vols: List[float] = []
        frontier_w = np.zeros((n_points, self.N))

        for i, target_vol in enumerate(target_vols):
            target_var = target_vol ** 2
            disc = A * target_var - 1.0  # = A·(target_var − 1/A)
            if disc <= 0:
                w = g.copy()
            else:
                lam = math.sqrt(disc / D) if D > 1e-12 else 0.0
                w = g + lam * d
            w = np.maximum(w, 0.0)
            w_sum = w.sum()
            if w_sum > 0:
                w = w / w_sum

            frontier_w[i] = w
            ret_opt, vol_opt, _ = self._portfolio_stats(w)
            frontier_rets.append(ret_opt)
            frontier_vols.append(vol_opt)

        return {
            'returns': np.array(frontier_rets),
            'volatilities': np.array(frontier_vols),
            'weights': frontier_w,
            'target_vols': target_vols,
            'max_sharpe': (max_sharpe_result.volatility, max_sharpe_result.expected_return),
            'min_variance': (min_vol_result.volatility, min_vol_result.expected_return),
        }


# ══════════════════════════════════════════════════
# Module-level convenience functions
# ══════════════════════════════════════════════════

def black_litterman(market_weights: np.ndarray, cov_matrix: np.ndarray,
                    P: np.ndarray, Q: np.ndarray, tau: float = 0.05,
                    omega: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Black-Litterman model: blend market equilibrium with subjective views.

    Args:
        market_weights: (N,) implied market weights (e.g. from market cap)
        cov_matrix: (N, N) covariance matrix of asset returns
        P: (K, N) view matrix, each row is a view (e.g. [1, -1, 0] = Asset1 > Asset2)
        Q: (K,) expected return vector for each view
        tau: uncertainty scalar for market equilibrium (default 0.05)
        omega: (K, K) view uncertainty matrix, default tau * P @ cov @ P.T

    Returns:
        dict with keys: implied_returns, posterior_returns, posterior_cov, weights
    """
    N = len(market_weights)
    pi = cov_matrix @ market_weights  # implied excess returns

    if omega is None:
        omega = np.diag(np.diag(P @ cov_matrix @ P.T)) * tau

    tau_cov = tau * cov_matrix
    middle = np.linalg.inv(np.linalg.inv(tau_cov) + P.T @ np.linalg.inv(omega) @ P)
    posterior_mu = middle @ (np.linalg.inv(tau_cov) @ pi + P.T @ np.linalg.inv(omega) @ Q)
    posterior_cov = cov_matrix + middle

    # Maximize Sharpe with posterior
    inv_posterior = np.linalg.inv(posterior_cov)
    w_raw = inv_posterior @ posterior_mu
    w_raw = np.maximum(w_raw, 0)
    w = w_raw / w_raw.sum() if w_raw.sum() > 0 else np.ones(N) / N

    return {
        'implied_returns': pi,
        'posterior_returns': posterior_mu,
        'posterior_cov': posterior_cov,
        'weights': w,
    }


def optimize_portfolio(returns: np.ndarray, method: str = 'max_sharpe',
                       risk_free_rate: float = 0.0,
                       asset_names: Optional[List[str]] = None) -> OptimizationResult:
    """Convenience function: optimize portfolio with one call.

    Args:
        returns: (T, N) returns matrix
        method: 'max_sharpe', 'min_variance', or 'risk_parity'
        risk_free_rate: annualized risk-free rate
        asset_names: optional asset names

    Returns:
        OptimizationResult
    """
    opt = PortfolioOptimizer(returns, asset_names=asset_names,
                            risk_free_rate=risk_free_rate)
    if method == 'max_sharpe':
        return opt.max_sharpe()
    elif method == 'min_variance':
        return opt.min_variance()
    elif method == 'risk_parity':
        return opt.risk_parity()
    else:
        raise ValueError(f"Unknown method: {method}. Use 'max_sharpe', 'min_variance', or 'risk_parity'")

