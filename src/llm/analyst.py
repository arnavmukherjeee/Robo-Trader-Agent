"""Claude LLM analyst — uses Claude to rank strategies and generate trade decisions."""

import json
from dataclasses import dataclass

import anthropic
from loguru import logger

from config.settings import settings
from src.strategies.engine import StrategyResult
from src.strategies.signals import Direction


@dataclass
class LLMTradeRecommendation:
    symbol: str
    direction: Direction
    confidence: float
    position_size_pct: float
    reasoning: str
    strategies_used: list[str]
    stop_loss_pct: float
    take_profit_pct: float


SYSTEM_PROMPT = """You are an expert quantitative trading analyst. You analyze technical signals
from multiple trading strategies and make trading decisions.

You will receive:
1. Current market data summary for a symbol
2. Top strategy results with their signals and confidence scores
3. Current portfolio state

Your job is to:
- Analyze the confluence of signals across strategies
- Determine whether to BUY, SELL, or HOLD
- Set position sizing (as % of portfolio, max 5%)
- Set stop-loss and take-profit levels
- Provide clear reasoning

IMPORTANT RULES:
- Never recommend more than 5% of portfolio in a single position
- Require at least 3 confirming signals before recommending a trade
- Factor in current market conditions and volatility
- Be conservative — preserving capital is priority #1
- Consider correlation between existing positions

Respond ONLY with valid JSON in this exact format:
{
    "action": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0-1.0,
    "position_size_pct": 0.0-0.05,
    "stop_loss_pct": 0.01-0.10,
    "take_profit_pct": 0.02-0.20,
    "reasoning": "string explaining your analysis"
}"""


class LLMAnalyst:
    """Uses Claude to make final trading decisions based on strategy signals."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = "claude-sonnet-4-20250514"  # Sonnet for speed + quality balance
        logger.info("LLM Analyst initialized")

    def analyze_symbol(
        self,
        symbol: str,
        strategy_results: list[StrategyResult],
        market_summary: dict,
        portfolio_state: dict,
    ) -> LLMTradeRecommendation | None:
        """Ask Claude to analyze strategy results and make a trade decision."""
        if not strategy_results:
            return None

        # Build the analysis prompt
        strategies_text = []
        for r in strategy_results[:20]:  # top 20 for context window
            strategies_text.append(
                f"- Strategy: {r.strategy.name}\n"
                f"  Direction: {r.direction.value}\n"
                f"  Confidence: {r.confidence:.2f}\n"
                f"  Signals: {len(r.signals_fired)} fired\n"
                f"  Reasons: {'; '.join(r.reasons[:5])}"
            )

        user_prompt = f"""Analyze {symbol} and recommend a trade action.

## Market Data Summary
- Symbol: {symbol}
- Current Price: ${market_summary.get('current_price', 'N/A')}
- 24h Change: {market_summary.get('price_change_pct', 'N/A')}%
- Volume Ratio (vs 20d avg): {market_summary.get('volume_ratio', 'N/A')}x
- ATR(14): {market_summary.get('atr', 'N/A')}
- RSI(14): {market_summary.get('rsi', 'N/A')}

## Top Strategy Results ({len(strategy_results)} strategies with signals)
{''.join(strategies_text)}

## Portfolio State
- Total Equity: ${portfolio_state.get('equity', 0):,.2f}
- Cash Available: ${portfolio_state.get('cash', 0):,.2f}
- Open Positions: {portfolio_state.get('num_positions', 0)}
- Current {symbol} Position: {portfolio_state.get('current_position', 'None')}

## Signal Summary
- Long signals: {sum(1 for r in strategy_results if r.direction == Direction.LONG)}
- Short signals: {sum(1 for r in strategy_results if r.direction == Direction.SHORT)}
- Avg confidence (long): {_avg_confidence(strategy_results, Direction.LONG):.2f}
- Avg confidence (short): {_avg_confidence(strategy_results, Direction.SHORT):.2f}

Provide your JSON recommendation:"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            content = response.content[0].text.strip()
            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            decision = json.loads(content)

            if decision["action"] == "HOLD":
                logger.info(f"LLM recommends HOLD for {symbol}: {decision['reasoning'][:100]}")
                return None

            direction = Direction.LONG if decision["action"] == "BUY" else Direction.SHORT

            return LLMTradeRecommendation(
                symbol=symbol,
                direction=direction,
                confidence=float(decision["confidence"]),
                position_size_pct=float(decision["position_size_pct"]),
                reasoning=decision["reasoning"],
                strategies_used=[r.strategy.name for r in strategy_results[:5]],
                stop_loss_pct=float(decision["stop_loss_pct"]),
                take_profit_pct=float(decision["take_profit_pct"]),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response for {symbol}: {e}")
            return None
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error for {symbol}: {e}")
            return None

    def analyze_portfolio_risk(self, positions: list[dict], account: dict) -> str:
        """Ask Claude to assess overall portfolio risk."""
        prompt = f"""Analyze this trading portfolio for risk:

## Account
- Equity: ${account.get('equity', 0):,.2f}
- Cash: ${account.get('cash', 0):,.2f}

## Positions
{json.dumps(positions, indent=2)}

Provide a brief risk assessment (3-5 bullet points) covering:
1. Concentration risk
2. Correlation risk
3. Suggested rebalancing actions
4. Overall risk rating (LOW/MEDIUM/HIGH/CRITICAL)"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system="You are a portfolio risk analyst. Be concise and actionable.",
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except anthropic.APIError as e:
            logger.error(f"Portfolio risk analysis failed: {e}")
            return "Risk analysis unavailable"


def _avg_confidence(results: list[StrategyResult], direction: Direction) -> float:
    filtered = [r for r in results if r.direction == direction]
    if not filtered:
        return 0.0
    return sum(r.confidence for r in filtered) / len(filtered)
