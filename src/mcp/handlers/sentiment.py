"""MCP handlers for Sentiment Analysis"""
import sys
import os
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from typing import Dict, Any, List
from datetime import datetime
from core_lib.sentiment.analyzer import (
    CryptoSentimentAnalyzer,
    sentiment_analyze_text,
    sentiment_analyze_bulk,
    sentiment_fear_greed,
)


# ── 情绪分析 Handlers ─────────────────────────────────────────────────

def sentiment_text(text: str) -> Dict[str, Any]:
    """Analyze sentiment of a single text"""
    return sentiment_analyze_text(text)


def sentiment_bulk(texts: List[str]) -> Dict[str, Any]:
    """Analyze sentiment of multiple texts"""
    return sentiment_analyze_bulk(texts)


def fear_greed_index(sentiment_score: float, volatility: float = 0.5) -> Dict[str, Any]:
    """Calculate Fear & Greed Index"""
    return sentiment_fear_greed(sentiment_score, volatility)


# ── RL Trading Handler ────────────────────────────────────────────────

def rl_train_agent(
    prices: List[float],
    volumes: List[float],
    num_episodes: int = 100,
    learning_rate: float = 0.01,
) -> Dict[str, Any]:
    """Train RL trading agent

    Args:
        prices: Historical price series
        volumes: Historical volume series
        num_episodes: Training episodes
        learning_rate: Q-Learning learning rate

    Returns:
        Training results {avg_reward, best_reward, total_states, sharpe_ratio}
    """
    try:
        from engines.rl.agent import QLearningAgent, TradingEnv

        agent = QLearningAgent({"learning_rate": learning_rate})
        env = TradingEnv({
            "prices": prices,
            "volumes": volumes,
        })

        results = agent.train(env, num_episodes)

        # Get env results
        env_results = env.get_results()

        return {
            "status": "ok",
            "training": results,
            "backtest": env_results,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def rl_predict(
    agent_path: str,
    current_state: Dict[str, float],
) -> Dict[str, Any]:
    """Use trained RL agent to predict action

    Args:
        agent_path: Path to saved Q-Table JSON
        current_state: Current market state {momentum_5, momentum_10, volume_change, volatility, rsi, macd, position}

    Returns:
        {action, action_name, confidence, q_values}
    """
    try:
        from engines.rl.agent import QLearningAgent
        import json

        agent = QLearningAgent()
        agent.load(agent_path)

        action = agent.get_action(current_state, training=False)
        state_key = agent._state_to_key(current_state)
        q_values = agent.q_table.get(state_key, {0: 0, 1: 0, 2: 0, 3: 0})

        action_names = {0: "hold", 1: "buy", 2: "sell", 3: "stop_loss_take_profit"}

        # Confidence = normalized Q-value difference
        max_q = max(q_values.values())
        second_q = sorted(q_values.values(), reverse=True)[1] if len(q_values) > 1 else 0
        confidence = (max_q - second_q) / (max(abs(max_q), abs(second_q)) + 1e-6)

        return {
            "status": "ok",
            "action": action,
            "action_name": action_names.get(action, "unknown"),
            "confidence": round(confidence, 4),
            "q_values": q_values,
            "state": state_key,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Handler Registry ─────────────────────────────────────────────────

HANDLERS = {
    "sentiment_word": sentiment_word,
    "sentiment_bulk": sentiment_bulk,
    "fear_greed_index": fear_greed_index,
    "rl_train_agent": rl_train_agent,
    "rl_predict": rl_predict,
}

TOOLS = [
    {
        "name": "sentiment_word",
        "description": "Analyze sentiment of a single text (tweet, news, reddit post)",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to analyze"},
            },
            "required": ["text"],
        },
        "handler": sentiment_word,
    },
    {
        "name": "sentiment_bulk",
        "description": "Analyze sentiment of multiple texts with aggregate statistics",
        "input_schema": {
            "type": "object",
            "properties": {
                "texts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of texts to analyze",
                },
            },
            "required": ["texts"],
        },
        "handler": sentiment_bulk,
    },
    {
        "name": "fear_greed_index",
        "description": "Calculate Fear & Greed Index (0-100) from sentiment score",
        "input_schema": {
            "type": "object",
            "properties": {
                "sentiment_score": {"type": "number", "description": "Sentiment score (-1 to 1)"},
                "volatility": {"type": "number", "description": "Market volatility (0-1, default: 0.5)"},
            },
            "required": ["sentiment_score"],
        },
        "handler": fear_greed_index,
    },
    {
        "name": "rl_train_agent",
        "description": "Train Q-Learning trading agent on historical data",
        "input_schema": {
            "type": "object",
            "properties": {
                "prices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Historical price series",
                },
                "volumes": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Historical volume series",
                },
                "num_episodes": {"type": "integer", "description": "Training episodes (default: 100)"},
                "learning_rate": {"type": "number", "description": "Learning rate (default: 0.01)"},
            },
            "required": ["prices", "volumes"],
        },
        "handler": rl_train_agent,
    },
    {
        "name": "rl_predict",
        "description": "Use trained RL agent to predict optimal action",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_path": {"type": "string", "description": "Path to saved Q-Table JSON"},
                "current_state": {
                    "type": "object",
                    "description": "Current market state",
                    "properties": {
                        "momentum_5": {"type": "number"},
                        "momentum_10": {"type": "number"},
                        "volume_change": {"type": "number"},
                        "volatility": {"type": "number"},
                        "rsi": {"type": "number"},
                        "macd": {"type": "number"},
                        "position": {"type": "integer"},
                    },
                },
            },
            "required": ["agent_path", "current_state"],
        },
        "handler": rl_predict,
    },
]
