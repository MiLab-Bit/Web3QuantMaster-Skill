"""
Web3QuantMaster - Help Module (v3.5.0)

Display help information for all commands.
Split from main.py for better maintainability.
"""
from __future__ import annotations

from typing import Dict

from .registry import COMMANDS, SHORTCUTS


# =============================================================================
# Help Display
# =============================================================================

def show_help() -> None:
    """Display help information for all commands."""
    # Try to get version info
    try:
        from core_lib.config import VERSION, BUILD_DATE
    except Exception:
        VERSION = "3.5.0"
        BUILD_DATE = "2026-05-31"
    
    print("=" * 70)
    print(f"Web3QuantMaster v{VERSION} - 量化交易系统")
    print(f"Build: {BUILD_DATE} | Architecture: 5-layer (src/)")
    print("=" * 70)
    print()
    print("核心命令 (新架构):")
    print("-" * 70)
    
    for name, info in COMMANDS.items():
        print(f"  {name:<20} {info['help']}")
        if "usage" in info:
            print(f"{'':>22} 用法: {info['usage']}")
    
    print()
    print("快捷命令:")
    print("-" * 70)
    for short, full in SHORTCUTS.items():
        print(f"  {short:<10} → {full}")
    
    print()
    print("全局选项:")
    print("  --health     系统健康检查")
    print("  --json       JSON 输出")
    print("  -h, --help   帮助信息")
    print()
    print("架构层次:")
    print("  mcp/          → 协议层 (MCP server + handlers)")
    print("  engines/      → 组合引擎 (backtest/risk/paper_trade/alert/portfolio)")
    print("  strategies/   → 策略模块 (ma_cross/triple_ema/rsi/keltner)")
    print("  data/         → 数据抽象层 (client/fetcher/store/quality)")
    print("  core_lib/     → 领域逻辑 (indicators/risk/portfolio/config)")
    print()
    print("=" * 70)


def show_command_help(command: str) -> None:
    """Display help for a specific command.
    
    Args:
        command: Command name (e.g., 'backtest', 'risk-check')
    """
    if command in COMMANDS:
        info = COMMANDS[command]
        print(f"Command: {command}")
        print(f"Help: {info['help']}")
        if "usage" in info:
            print(f"Usage: {info['usage']}")
        if "examples" in info:
            print("Examples:")
            for ex in info["examples"]:
                print(f"  {ex}")
    else:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join(sorted(COMMANDS.keys()))}")


def list_commands() -> None:
    """Print list of all available commands."""
    print("Available commands:")
    for name, info in sorted(COMMANDS.items()):
        print(f"  {name:<25} {info['help']}")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "show_help",
    "show_command_help",
    "list_commands",
]
