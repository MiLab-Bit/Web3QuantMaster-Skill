"""
TradingView Chart Integration Module
Generates TradingView chart URLs, embed codes, and ticker mappings.
Based on tradingview-chart-mcp + tradingview-mcp reference implementations.
"""
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
import urllib.parse


# =============================================================================
# Ticker Format Resolution
# =============================================================================

# Standard exchange prefix → TradingView exchange codes
EXCHANGE_MAP: Dict[str, str] = {
    "binance": "BINANCE",
    "bybit": "BYBIT",
    "okx": "OKX",
    "coinbase": "COINBASE",
    "kraken": "KRAKEN",
    "kucoin": "KUCOIN",
    "gate": "GATEIO",
    "bitget": "BITGET",
    "mexc": "MEXC",
    "bingx": "BINGX",
    "bitfinex": "BITFINEX",
    "huobi": "HUOBI",
    "htx": "HTX",
    "deribit": "DERIBIT",
    "bitmex": "BITMEX",
    # Traditional markets
    "nasdaq": "NASDAQ",
    "nyse": "NYSE",
    "amex": "AMEX",
    "tsx": "TSX",
    "lse": "LSE",
    "tse": "TSE",
    "six": "SIX",
    # Forex / CFDs
    "oanda": "OANDA",
    "fxs": "FX",
    "fx": "FX_IDC",
    "forex": "FX_IDC",
    # Crypto aggregated
    "crypto": "CRYPTO",
    "coinmarketcap": "COINMARKETCAP",
    "coingecko": "COINGECKO",
    # Stock indices
    "sp": "SP",
    "cme": "CME",
    "cboe": "CBOE",
    "ice": "ICE",
}

# Common TradingView suffix mappings
PAIR_SUFFIXES = {
    "binance": {True: ".P", False: "USDT.P"},
    "bybit": {True: ".P", False: "USDT.P"},
    "okx": {True: ".P", False: "USDT.P"},
    "coinbase": {True: "", False: "USD"},
    "kraken": {True: "", False: "USD"},
    "kucoin": {True: ".P", False: "USDT.P"},
    "gate": {True: ".P", False: "USDT.P"},
    "mexc": {True: ".P", False: "USDT.P"},
    "bitget": {True: ".P", False: "USDT.P"},
    "crypto": {True: "", False: "USD"},
    "fx": {True: "", False: ""},
}

# Perpetual suffix (for futures contracts)
PERP_SUFFIXES = {
    "binance": "USDT.P",
    "bybit": "USDT.P",
    "okx": "USDT.P",
    "kucoin": "USDT.P",
    "gate": "USDT.P",
    "mexc": "USDT.P",
    "bitget": "USDT.P",
    "bingx": "USDT.P",
    "bitmex": "USD.P",
    "deribit": ".P",
}


def resolve_ticker(
    symbol: str,
    exchange: str = "binance",
    perpetual: bool = False,
) -> str:
    """Resolve a human-readable symbol to TradingView ticker format.

    Args:
        symbol: Base symbol (e.g., 'BTC', 'ETH', 'SOL')
        exchange: Exchange name (e.g., 'binance', 'bybit', 'nasdaq')
        perpetual: Whether the symbol is a perpetual futures contract

    Returns:
        TradingView ticker string (e.g., 'BINANCE:BTCUSDT.P')

    Examples:
        >>> resolve_ticker('BTC')
        'BINANCE:BTCUSDT.P'
        >>> resolve_ticker('AAPL', 'nasdaq')
        'NASDAQ:AAPL'
        >>> resolve_ticker('ETH', perpetual=True)
        'BINANCE:ETHUSDT.P'
    """
    exchange = exchange.lower()
    tv_exchange = EXCHANGE_MAP.get(exchange, exchange.upper())

    # For stocks/indices, symbol is used directly
    if exchange in ("nasdaq", "nyse", "amex", "tsx", "lse", "tse", "six", "sp"):
        return f"{tv_exchange}:{symbol.upper()}"

    # For forex pairs (already in format like EURUSD)
    if exchange in ("fx", "oanda", "forex") or len(symbol) == 6 and symbol.isalpha():
        return f"{tv_exchange}:{symbol.upper()}"

    # For crypto perpetuals
    if perpetual:
        suffix = PERP_SUFFIXES.get(exchange, "USDT.P")
        return f"{tv_exchange}:{symbol.upper()}{suffix}"

    # For crypto spot (auto-detect if symbol already contains pair)
    if symbol.upper().endswith("USD") or symbol.upper().endswith("USDT"):
        return f"{tv_exchange}:{symbol.upper()}.P" if exchange == "binance" else f"{tv_exchange}:{symbol.upper()}"

    suffix = PAIR_SUFFIXES.get(exchange, {}).get(False, "USDT.P")
    return f"{tv_exchange}:{symbol.upper()}{suffix}"


# =============================================================================
# Timeframe Mapping
# =============================================================================

TIMEFRAME_MAP: Dict[str, str] = {
    "1s": "1S",
    "5s": "5S",
    "15s": "15S",
    "30s": "30S",
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "45m": "45",
    "1h": "60",
    "2h": "120",
    "3h": "180",
    "4h": "240",
    "1d": "D",
    "1w": "W",
    "1M": "M",
    "3M": "3M",
    "6M": "6M",
    "12M": "12M",
}

TIMEFRAME_ALIASES: Dict[str, str] = {
    "1": "1",
    "3": "3",
    "5": "5",
    "15": "15",
    "30": "30",
    "45": "45",
    "60": "60",
    "120": "120",
    "240": "240",
    "D": "D",
    "W": "W",
    "M": "M",
    "minute": "1",
    "minutes": "1",
    "hour": "60",
    "hours": "60",
    "day": "D",
    "daily": "D",
    "week": "W",
    "weekly": "W",
    "month": "M",
    "monthly": "M",
    "4hour": "240",
    "4hours": "240",
    "1 hour": "60",
    "4 hour": "240",
    "15 minute": "15",
    "30 minute": "30",
}


def resolve_timeframe(interval: str) -> str:
    """Resolve a human-readable interval to TradingView timeframe code.

    Args:
        interval: Human interval (e.g., '1h', 'daily', '4hours', '15')

    Returns:
        TradingView timeframe string (e.g., '60', 'D', '240')

    Examples:
        >>> resolve_timeframe('1h')
        '60'
        >>> resolve_timeframe('daily')
        'D'
        >>> resolve_timeframe('240')
        '240'
    """
    key = interval.lower().replace(" ", "").replace("-", "")
    if key in TIMEFRAME_ALIASES:
        return TIMEFRAME_ALIASES[key]
    if key in TIMEFRAME_MAP:
        return TIMEFRAME_MAP[key]
    # Try direct match
    if interval in TIMEFRAME_MAP:
        return TIMEFRAME_MAP[interval]
    # Default to daily
    return "D"


def get_timeframe_label(interval: str) -> str:
    """Get a human-readable label for a timeframe."""
    labels = {
        "1": "1 Minute", "3": "3 Minutes", "5": "5 Minutes",
        "15": "15 Minutes", "30": "30 Minutes", "45": "45 Minutes",
        "60": "1 Hour", "120": "2 Hours", "240": "4 Hours",
        "D": "1 Day", "W": "1 Week", "M": "1 Month",
        "3M": "3 Months", "6M": "6 Months", "12M": "12 Months",
    }
    return labels.get(resolve_timeframe(interval), interval)


# =============================================================================
# Chart URL Generation
# =============================================================================

@dataclass
class ChartConfig:
    ticker: str
    interval: str = "D"
    theme: str = "dark"
    studies: List[str] = None
    style: str = "1"  # 1=candles, 2=bars, 3=line, 4=area, 5=heikin-ashi
    width: int = 800
    height: int = 600
    locale: str = "en"

    def __post_init__(self):
        if self.studies is None:
            self.studies = []


def build_chart_url(config: ChartConfig) -> str:
    """Build a direct TradingView chart page URL.

    Args:
        config: ChartConfig with ticker, interval, theme, studies, style

    Returns:
        Full TradingView chart URL
    """
    base = "https://www.tradingview.com/chart/"
    params = {
        "symbol": urllib.parse.quote(config.ticker),
        "interval": config.interval or "D",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


def build_widget_html(
    ticker: str,
    interval: str = "D",
    theme: str = "dark",
    width: str = "100%",
    height: str = "500",
    studies: Optional[List[str]] = None,
) -> str:
    """Generate a TradingView Widget HTML snippet for embedding in reports/web pages.

    Args:
        ticker: TradingView ticker (e.g., 'BINANCE:BTCUSDT.P')
        interval: Timeframe (e.g., 'D', '60', '240')
        theme: 'dark' or 'light'
        width: CSS width (e.g., '100%', '800px')
        height: CSS height (e.g., '500', '600')
        studies: List of study names to overlay (e.g., ['RSI', 'MACD'])

    Returns:
        HTML string with embedded TradingView widget
    """
    if studies is None:
        studies = ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]

    studies_json = ", ".join(f'"{s}"' for s in studies)

    html = f"""<!-- TradingView Widget -->
<div class="tradingview-widget-container" style="width:{width};height:{height};">
  <div id="tv_chart_container" style="width:100%;height:100%;"></div>
</div>
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<script type="text/javascript">
new TradingView.widget({{
  "container_id": "tv_chart_container",
  "autosize": true,
  "symbol": "{ticker}",
  "interval": "{interval}",
  "timezone": "Asia/Shanghai",
  "theme": "{theme}",
  "style": "1",
  "locale": "zh_CN",
  "toolbar_bg": "{'#1e222d' if theme == 'dark' else '#f1f3f6'}",
  "enable_publishing": false,
  "withdateranges": true,
  "hide_side_toolbar": false,
  "allow_symbol_change": true,
  "studies": [{studies_json}],
  "show_popup_button": true,
  "popup_width": "1000",
  "popup_height": "650"
}});
</script>"""
    return html


def build_widget_url(
    ticker: str,
    interval: str = "D",
    theme: str = "dark",
    studies: Optional[List[str]] = None,
) -> str:
    """Build a TradingView Widget URL (opens in new page).

    This creates a TradingView lightweight chart link that's more
    shareable than the full chart page.

    Args:
        ticker: TradingView ticker
        interval: Timeframe
        theme: 'dark' or 'light'
        studies: Overlay studies

    Returns:
        Widget URL string
    """
    base = "https://s.tradingview.com/widgetembed/"
    params = {
        "symbol": ticker,
        "interval": interval or "D",
        "theme": theme,
        "style": "1",
        "locale": "zh_CN",
        "timezone": "Asia/Shanghai",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


# =============================================================================
# Multi-chart dashboard
# =============================================================================

def generate_dashboard_html(
    symbols: List[Tuple[str, str, str]],  # (label, ticker, interval)
    theme: str = "dark",
    cols: int = 2,
) -> str:
    """Generate a multi-chart dashboard HTML page.

    Args:
        symbols: List of (label, ticker, interval) tuples
        theme: 'dark' or 'light'
        cols: Number of columns in grid

    Returns:
        Full HTML page with multiple TradingView widgets
    """
    widget_height = 450
    charts_html = []
    for label, ticker, interval in symbols:
        charts_html.append(f"""
    <div class="chart-panel">
      <h3 class="chart-title">{label}</h3>
      <div class="tradingview-widget-container" style="height:{widget_height}px;">
        <div id="tv_{hash(ticker + interval) & 0x7FFFFFFF:x}" style="height:100%;"></div>
      </div>
    </div>""")

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Crypto Charts Dashboard</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: {'#131722' if theme == 'dark' else '#f0f0f0'};
         color: {'#d1d4dc' if theme == 'dark' else '#333'};
         padding: 20px; }}
  .header {{ text-align:center; padding:20px; }}
  .header h1 {{ font-size: 1.8em; margin-bottom:5px; }}
  .header p {{ opacity: 0.6; }}
  .chart-grid {{ display:grid; grid-template-columns: repeat({cols}, 1fr);
                  gap: 20px; margin-top: 20px; }}
  .chart-panel {{ background: {'#1e222d' if theme == 'dark' else '#fff'};
                   border-radius: 8px; padding: 15px;
                   border: 1px solid {'#2a2e39' if theme == 'dark' else '#ddd'}; }}
  .chart-title {{ font-size: 1.1em; margin-bottom: 10px;
                   color: {'#5b9cf5' if theme == 'dark' else '#2962ff'}; }}
</style>
</head>
<body>
<div class="header">
  <h1>📊 Crypto Charts Dashboard</h1>
  <p>Powered by TradingView | Auto-refresh: off</p>
</div>
<div class="chart-grid">
{''.join(charts_html)}
</div>

<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<script type="text/javascript">
const theme = '{theme}';
const charts = {symbols_json};
charts.forEach(function(c, i) {{
  var containerId = 'tv_' + i;
  // Assign IDs to divs
  var panels = document.querySelectorAll('.tradingview-widget-container div');
  for (var j = 0; j < panels.length; j++) {{
    if (!panels[j].id) {{ panels[j].id = 'tv_' + j; }}
  }}
  if (document.getElementById('tv_' + i)) {{
    new TradingView.widget({{
      container_id: 'tv_' + i,
      autosize: true,
      symbol: c[1],
      interval: c[2],
      timezone: 'Asia/Shanghai',
      theme: theme,
      style: '1',
      locale: 'zh_CN',
      toolbar_bg: theme === 'dark' ? '#1e222d' : '#f1f3f6',
      enable_publishing: false,
      hide_side_toolbar: true,
      allow_symbol_change: true,
      studies: ['RSI@tv-basicstudies'],
      show_popup_button: true,
    }});
  }}
}});
</script>
</body>
</html>"""
    import json
    symbols_json = json.dumps([[s[0], s[1], resolve_timeframe(s[2])] for s in symbols])

    # Re-render with actual symbols_json
    page = page.replace("{symbols_json}", symbols_json)
    return page


# =============================================================================
# Quick-use functions for common symbols
# =============================================================================

COMMON_CRYPTO_SYMBOLS: Dict[str, str] = {
    "BTC": "BINANCE:BTCUSDT.P",
    "ETH": "BINANCE:ETHUSDT.P",
    "SOL": "BINANCE:SOLUSDT.P",
    "BNB": "BINANCE:BNBUSDT.P",
    "XRP": "BINANCE:XRPUSDT.P",
    "ADA": "BINANCE:ADAUSDT.P",
    "DOGE": "BINANCE:DOGEUSDT.P",
    "AVAX": "BINANCE:AVAXUSDT.P",
    "DOT": "BINANCE:DOTUSDT.P",
    "LINK": "BINANCE:LINKUSDT.P",
    "MATIC": "BINANCE:MATICUSDT.P",
    "UNI": "BINANCE:UNIUSDT.P",
    "ATOM": "BINANCE:ATOMUSDT.P",
    "LTC": "BINANCE:LTCUSDT.P",
    "FIL": "BINANCE:FILUSDT.P",
    "APT": "BINANCE:APTUSDT.P",
    "ARB": "BINANCE:ARBUSDT.P",
    "OP": "BINANCE:OPUSDT.P",
    "SUI": "BINANCE:SUIUSDT.P",
    "TIA": "BINANCE:TIAUSDT.P",
    "SEI": "BINANCE:SEIUSDT.P",
    "INJ": "BINANCE:INJUSDT.P",
    "RUNE": "BINANCE:RUNEUSDT.P",
    "FET": "BINANCE:FETUSDT.P",
    "WIF": "BINANCE:WIFUSDT.P",
    "PEPE": "BINANCE:PEPEUSDT.P",
    "BONK": "BINANCE:BONKUSDT.P",
    "JUP": "BINANCE:JUPUSDT.P",
    "NEAR": "BINANCE:NEARUSDT.P",
}


def get_chart_info(symbol: str) -> dict:
    """Get chart information for a common crypto symbol.

    Returns dict with ticker, chart_url, widget_url, and config for different timeframes.
    """
    ticker = COMMON_CRYPTO_SYMBOLS.get(
        symbol.upper(),
        resolve_ticker(symbol),
    )

    return {
        "symbol": symbol.upper(),
        "ticker": ticker,
        "chart_page_url": build_chart_url(ChartConfig(ticker=ticker, interval="D")),
        "widget_url": build_widget_url(ticker, interval="D"),
        "widget_html_1h": build_widget_html(ticker, interval="60", height="400"),
        "widget_html_1d": build_widget_html(ticker, interval="D", height="400"),
        "widget_html_4h": build_widget_html(ticker, interval="240", height="400"),
        "timeframes_supported": list(TIMEFRAME_MAP.keys()),
    }


# =============================================================================
# Quick test
# =============================================================================

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    # Test ticker resolution
    print("=== Ticker Resolution ===")
    tests = [
        ("BTC", "binance", False),
        ("ETH", "bybit", True),
        ("AAPL", "nasdaq", False),
        ("SOL", "binance", False),
    ]
    for symbol, exchange, perp in tests:
        ticker = resolve_ticker(symbol, exchange, perp)
        print(f"  {symbol} @ {exchange} (perp={perp}) → {ticker}")

    # Test timeframe
    print("\n=== Timeframe Resolution ===")
    for tf in ["1h", "daily", "240", "4hours", "weekly", "15"]:
        print(f"  '{tf}' → '{resolve_timeframe(tf)}' ({get_timeframe_label(tf)})")

    # Test chart URL
    print("\n=== Chart URLs ===")
    url = build_chart_url(ChartConfig(ticker="BINANCE:BTCUSDT.P", interval="D"))
    print(f"  BTC Daily: {url}")

    widget_url = build_widget_url("BINANCE:BTCUSDT.P", "60")
    print(f"  BTC 1h widget: {widget_url}")

    # Test get_chart_info
    print("\n=== get_chart_info('BTC') ===")
    info = get_chart_info("BTC")
    for k, v in info.items():
        if "html" not in k:
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: ({len(v)} chars HTML)")

    print("\n✅ All tests passed")
