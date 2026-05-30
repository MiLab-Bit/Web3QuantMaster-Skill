"""
DCC-GARCH 多变量波动率与动态相关性 — src/core_lib/risk_engine/dcc_garch.py
===========================================================================
Dynamic Conditional Correlation GARCH — models time-varying covariance between
multiple assets for portfolio risk management.

Architecture:
    depend on: numpy, scipy (optimize)
    part of:  core_lib.risk_engine
    used by:  engines/risk_check, mcp handlers
"""
from __future__ import annotations

import numpy as np
from typing import List, Dict, Tuple, Optional, Any


class GarchEstimator:
    """Univariate GARCH(1,1) parameter estimation via MLE."""

    def __init__(self):
        self.omega: float = 0.0
        self.alpha: float = 0.0
        self.beta: float = 0.0
        self._fitted: bool = False

    def fit(self, returns: np.ndarray) -> Dict[str, float]:
        """Fit GARCH(1,1) to return series.

        GARCH(1,1): σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
        """
        returns = np.asarray(returns, dtype=np.float64).flatten()
        n = len(returns)
        if n < 30:
            raise ValueError(f"Need at least 30 observations, got {n}")

        # Initial variance estimate
        init_var = np.var(returns[returns != 0]) if np.any(returns != 0) else 1e-6

        # Bounded MLE via grid search + refinement
        best_ll = -np.inf
        best_params = (0.01 * init_var, 0.1, 0.8)

        for omega_ratio in [0.001, 0.01, 0.05, 0.1]:
            for alpha in [0.05, 0.1, 0.15, 0.2, 0.25]:
                beta = max(0.7, min(0.9, 0.99 - alpha - 0.01))
                omega = omega_ratio * init_var

                var_series = self._forecast_variance(returns, omega, alpha, beta)
                ll = self._log_likelihood(returns, var_series)
                if ll > best_ll:
                    best_ll = ll
                    best_params = (omega, alpha, beta)

        self.omega, self.alpha, self.beta = best_params
        self._fitted = True
        return {"omega": self.omega, "alpha": self.alpha, "beta": self.beta}

    def forecast_variance(self, returns: np.ndarray) -> np.ndarray:
        """Compute conditional variance series."""
        if not self._fitted:
            self.fit(returns)
        return self._forecast_variance(returns, self.omega, self.alpha, self.beta)

    def forecast_next(self, last_return: float, last_var: float) -> float:
        """One-step-ahead variance forecast."""
        if not self._fitted:
            return float(np.nan)
        return self.omega + self.alpha * (last_return ** 2) + self.beta * last_var

    def _forecast_variance(
        self, returns: np.ndarray, omega: float, alpha: float, beta: float
    ) -> np.ndarray:
        n = len(returns)
        var = np.full(n, omega / (1 - alpha - beta + 1e-10))
        for t in range(1, n):
            var[t] = omega + alpha * (returns[t-1] ** 2) + beta * var[t-1]
        return var

    def _log_likelihood(self, returns: np.ndarray, var: np.ndarray) -> float:
        mask = var > 1e-10
        if not np.any(mask):
            return -np.inf
        ll = -0.5 * np.sum(np.log(2 * np.pi * var[mask]) + (returns[mask] ** 2) / var[mask])
        return float(ll)


class DccGarch:
    """DCC-GARCH(1,1) model for dynamic conditional correlation.

    Two-step estimation:
        1. Fit univariate GARCH to each asset
        2. Fit DCC parameters to standardized residuals
    """

    def __init__(self):
        self._assets: List[str] = []
        self._garch_models: List[GarchEstimator] = []
        self._dcc_a: float = 0.0  # news parameter
        self._dcc_b: float = 0.0  # decay parameter
        self._Q_bar: Optional[np.ndarray] = None  # unconditional correlation
        self._fitted: bool = False

    def fit(self, returns: Dict[str, np.ndarray]) -> Dict[str, Any]:
        """Fit DCC-GARCH to multi-asset returns.

        Args:
            returns: Dict mapping asset name → return series (numpy array)

        Returns:
            Dict with model parameters and fit summary
        """
        self._assets = list(returns.keys())
        k = len(self._assets)
        if k < 2:
            raise ValueError(f"Need at least 2 assets, got {k}")

        # Ensure equal lengths
        min_len = min(len(r) for r in returns.values())
        ret_matrix = np.column_stack([
            np.asarray(returns[a][:min_len], dtype=np.float64)
            for a in self._assets
        ])

        # Step 1: Fit univariate GARCH for each asset
        self._garch_models = []
        std_residuals = np.zeros_like(ret_matrix)

        for i in range(k):
            garch = GarchEstimator()
            garch.fit(ret_matrix[:, i])
            self._garch_models.append(garch)

            var_i = garch.forecast_variance(ret_matrix[:, i])
            std_residuals[:, i] = np.where(
                var_i > 1e-10,
                ret_matrix[:, i] / np.sqrt(var_i),
                0.0
            )

        # Step 2: DCC parameters
        self._Q_bar = np.corrcoef(std_residuals.T)
        self._dcc_a, self._dcc_b = self._fit_dcc(std_residuals)

        # Compute final dynamic correlations
        corr_t = self._compute_dynamic_correlations(std_residuals)

        self._fitted = True

        return {
            "assets": self._assets,
            "garch_params": [
                {"omega": g.omega, "alpha": g.alpha, "beta": g.beta}
                for g in self._garch_models
            ],
            "dcc_a": self._dcc_a,
            "dcc_b": self._dcc_b,
            "unconditional_correlation": self._Q_bar.tolist() if self._Q_bar is not None else [],
            "avg_correlation": float(np.mean(np.abs(corr_t))),
            "n_observations": min_len,
        }

    def _fit_dcc(self, std_res: np.ndarray) -> Tuple[float, float]:
        """Fit DCC(1,1) parameters via quasi-MLE."""
        k = std_res.shape[1]
        T = std_res.shape[0]

        # Compute unconditional correlation
        Q_bar = np.corrcoef(std_res.T)

        # Grid search for DCC parameters
        best_ll = -np.inf
        best_a, best_b = 0.05, 0.9

        for a in np.linspace(0.01, 0.15, 5):
            b = min(0.95, 0.98 - a)
            Qt = Q_bar.copy()
            ll = 0.0
            for t in range(T):
                eta = std_res[t].reshape(-1, 1)
                Qt = (1 - a - b) * Q_bar + a * (eta @ eta.T) + b * Qt

                # Ensure PSD
                Qt = (Qt + Qt.T) / 2
                eigvals = np.linalg.eigvalsh(Qt)
                if np.min(eigvals) < 1e-8:
                    Qt += np.eye(k) * (1e-8 - np.min(eigvals))

                D = np.diag(1.0 / np.sqrt(np.maximum(np.diag(Qt), 1e-10)))
                Rt = D @ Qt @ D

                det = np.linalg.det(Rt)
                if det < 1e-10:
                    ll -= 100
                    continue
                try:
                    Rt_inv = np.linalg.inv(Rt)
                    ll += -0.5 * np.log(max(det, 1e-10)) - 0.5 * (eta.T @ Rt_inv @ eta)[0, 0]
                except np.linalg.LinAlgError:
                    ll -= 100

            if ll > best_ll:
                best_ll = ll
                best_a, best_b = a, b

        return best_a, best_b

    def _compute_dynamic_correlations(self, std_res: np.ndarray) -> np.ndarray:
        """Compute time-varying correlation matrices."""
        k = std_res.shape[1]
        T = std_res.shape[0]
        Q_bar = self._Q_bar if self._Q_bar is not None else np.eye(k)

        correlations = np.zeros(T)
        Qt = Q_bar.copy()

        for t in range(T):
            eta = std_res[t].reshape(-1, 1)
            Qt = (1 - self._dcc_a - self._dcc_b) * Q_bar + self._dcc_a * (eta @ eta.T) + self._dcc_b * Qt
            Qt = (Qt + Qt.T) / 2
            D = np.diag(1.0 / np.sqrt(np.maximum(np.diag(Qt), 1e-10)))
            Rt = D @ Qt @ D

            # Average pairwise correlation
            if k > 1:
                corr_vals = []
                for i in range(k):
                    for j in range(i + 1, k):
                        corr_vals.append(Rt[i, j])
                correlations[t] = np.mean(corr_vals)

        return correlations

    def forecast_covariance(
        self, returns: Dict[str, np.ndarray], horizon: int = 5
    ) -> Dict[str, Any]:
        """Forecast covariance matrix for risk management.

        Returns:
            Dict with 'covariance' (numpy array), 'correlation', 'volatilities'
        """
        if not self._fitted:
            return {"error": "Model not fitted. Call fit() first."}

        k = len(self._assets)
        min_len = min(len(r) for r in returns.values())
        ret_matrix = np.column_stack([
            np.asarray(returns[a][:min_len], dtype=np.float64)
            for a in self._assets
        ])

        # Forecast variance for each asset
        forecast_vars = np.zeros(k)
        for i in range(k):
            last_ret = ret_matrix[-1, i]
            var_series = self._garch_models[i].forecast_variance(ret_matrix[:, i])
            last_var = var_series[-1]

            var_f = last_var
            for _ in range(horizon):
                var_f = self._garch_models[i].omega + \
                        (self._garch_models[i].alpha + self._garch_models[i].beta) * var_f
            forecast_vars[i] = var_f

        # Forecast correlation (reverts to unconditional mean)
        Q_bar = self._Q_bar if self._Q_bar is not None else np.eye(k)
        std_res = np.zeros_like(ret_matrix)
        for i in range(k):
            v = self._garch_models[i].forecast_variance(ret_matrix[:, i])
            std_res[:, i] = np.where(v > 1e-10, ret_matrix[:, i] / np.sqrt(v), 0.0)

        Qt = Q_bar.copy()
        for t in range(min_len):
            eta = std_res[t].reshape(-1, 1)
            Qt = (1 - self._dcc_a - self._dcc_b) * Q_bar + self._dcc_a * (eta @ eta.T) + self._dcc_b * Qt

        Qt = (Qt + Qt.T) / 2
        D = np.diag(1.0 / np.sqrt(np.maximum(np.diag(Qt), 1e-10)))
        Rt = D @ Qt @ D

        # Forecast covariance = D * R * D
        D_forecast = np.diag(np.sqrt(forecast_vars))
        cov = D_forecast @ Rt @ D_forecast

        return {
            "assets": self._assets,
            "covariance": cov.tolist(),
            "correlation": Rt.tolist(),
            "volatilities": np.sqrt(forecast_vars).tolist(),
        }


def run_dcc_garch(
    returns: Dict[str, List[float]], horizon: int = 5
) -> Dict[str, Any]:
    """Convenience: fit DCC-GARCH and return forecast."""
    ret_arrays = {k: np.array(v) for k, v in returns.items()}
    model = DccGarch()
    fit_result = model.fit(ret_arrays)
    forecast = model.forecast_covariance(ret_arrays, horizon)
    return {"fit": fit_result, "forecast": forecast}


__all__ = [
    'GarchEstimator',
    'DccGarch',
    'run_dcc_garch',
]
