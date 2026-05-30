"""
市场情绪 - Fear & Greed Index
使用 Alternative.me API（免费，无需 Key）
"""
import json, logging, time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FearGreedClient:
    """Fear & Greed Index client"""
    BASE_URL = 'https://api.alternative.me/fng'

    def _fetch(self, path, params=None):
        import urllib.request, urllib.parse, urllib.error
        url = f"{self.BASE_URL}{path}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.warning(f"FearGreed fetch failed: {e}")
            return None

    def get_current(self) -> Dict[str, Any]:
        """Get current Fear & Greed Index"""
        data = self._fetch('/')
        if not data or 'data' not in data:
            return {'error': 'Failed to fetch', 'value': None, 'classification': 'UNKNOWN'}
        item = data['data'][0]
        return {
            'value': int(item.get('value', 0)),
            'value_classification': item.get('value_classification', 'Unknown'),
            'timestamp': item.get('timestamp', ''),
            'time_until_update': item.get('time_until_update', ''),
        }

    def get_multi_day(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get multi-day FGI history"""
        limit = min(days, 2000)
        data = self._fetch('/', {'limit': str(limit)})
        if not data or 'data' not in data:
            return []
        results = []
        for item in data['data']:
            results.append({
                'value': int(item.get('value', 0)),
                'classification': item.get('value_classification', 'Unknown'),
                'timestamp': item.get('timestamp', ''),
            })
        return results

    def get_classification(self, value: int) -> str:
        """Classify FGI value"""
        if value <= 25:
            return 'Extreme Fear'
        elif value <= 45:
            return 'Fear'
        elif value <= 55:
            return 'Neutral'
        elif value <= 75:
            return 'Greed'
        else:
            return 'Extreme Greed'

    def analyze_extremes(self, days: int = 365) -> Dict[str, Any]:
        """Analyze extreme FGI occurrences"""
        history = self.get_multi_day(days)
        if not history:
            return {'error': 'No data'}

        extreme_fear = [h for h in history if h['value'] <= 25]
        extreme_greed = [h for h in history if h['value'] >= 75]

        avg_7d = 0
        if len(history) >= 7:
            avg_7d = sum(h['value'] for h in history[-7:]) / 7

        avg_30d = 0
        if len(history) >= 30:
            avg_30d = sum(h['value'] for h in history[-30:]) / 30

        return {
            'period_days': days,
            'data_points': len(history),
            'extreme_fear_days': len(extreme_fear),
            'extreme_greed_days': len(extreme_greed),
            'avg_7d': round(avg_7d, 1),
            'avg_30d': round(avg_30d, 1),
            'current_avg': avg_7d,
            'extreme_fear_dates': [h['timestamp'] for h in extreme_fear[-5:]],
            'extreme_greed_dates': [h['timestamp'] for h in extreme_greed[-5:]],
        }

    def compute_signal(self) -> Dict[str, Any]:
        """Generate trading signal from FGI"""
        current = self.get_current()
        if 'error' in current:
            return {'signal': 'NO_DATA', 'reason': 'Failed to fetch FGI'}

        val = current['value']
        if val <= 15:
            signal = 'STRONG_BUY'
            reason = 'Extreme Fear - potential bottom'
        elif val <= 30:
            signal = 'BUY'
            reason = 'Fear - contrarian opportunity'
        elif val <= 45:
            signal = 'LEAN_BUY'
            reason = 'Moderate Fear'
        elif val <= 55:
            signal = 'NEUTRAL'
            reason = 'Neutral market sentiment'
        elif val <= 70:
            signal = 'LEAN_SELL'
            reason = 'Moderate Greed'
        elif val <= 85:
            signal = 'SELL'
            reason = 'Greed - potential top'
        else:
            signal = 'STRONG_SELL'
            reason = 'Extreme Greed - potential bubble'

        return {
            'signal': signal,
            'value': val,
            'classification': current['value_classification'],
            'reason': reason,
        }


# Convenience functions
def get_fear_greed_index() -> Dict[str, Any]:
    """Get current Fear & Greed Index"""
    return FearGreedClient().get_current()


def get_fear_greed_history(days: int = 30) -> List[Dict[str, Any]]:
    """Get FGI history for N days"""
    return FearGreedClient().get_multi_day(days)


def get_fear_greed_signal() -> Dict[str, Any]:
    """Get trading signal from FGI"""
    return FearGreedClient().compute_signal()
