"""Strategy engine — generates and evaluates parameterized strategy combinations.

By combining 11 signal types × multiple parameter variants × combination sizes of 2-4,
this engine produces hundreds of thousands of unique trading strategies.
"""

from dataclasses import dataclass, field
from itertools import combinations
import hashlib
import json

import pandas as pd

from src.strategies.signals import (
    SIGNAL_GENERATORS,
    Signal,
    Direction,
)


@dataclass
class Strategy:
    id: str
    name: str
    signals_config: list[dict]
    min_agreement: int  # minimum signals that must agree for a trade
    direction_bias: Direction | None = None  # None = follow signals

    def describe(self) -> str:
        parts = [f"Strategy: {self.name} (id={self.id})"]
        parts.append(f"  Min agreement: {self.min_agreement}/{len(self.signals_config)}")
        for sc in self.signals_config:
            parts.append(f"  - {sc['generator']} with params {sc['params']}")
        return "\n".join(parts)


@dataclass
class StrategyResult:
    strategy: Strategy
    signals_fired: list[Signal]
    direction: Direction
    confidence: float  # 0.0 to 1.0
    reasons: list[str]


def _make_strategy_id(signals_config: list[dict], min_agreement: int) -> str:
    payload = json.dumps({"s": signals_config, "m": min_agreement}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


class StrategyEngine:
    """Generates and evaluates a massive set of parameterized trading strategies."""

    def __init__(self, combo_sizes: tuple[int, ...] = (2, 3, 4)):
        self.combo_sizes = combo_sizes
        self._strategies: list[Strategy] | None = None

    def generate_strategies(self) -> list[Strategy]:
        """Generate all strategy combinations. Returns list of Strategy objects."""
        if self._strategies is not None:
            return self._strategies

        # Build flat list of (generator_name, params) tuples
        all_signal_variants: list[dict] = []
        for gen_name, gen_info in SIGNAL_GENERATORS.items():
            for params in gen_info["params"]:
                all_signal_variants.append({"generator": gen_name, "params": params})

        strategies = []
        for combo_size in self.combo_sizes:
            for combo in combinations(range(len(all_signal_variants)), combo_size):
                signals_config = [all_signal_variants[i] for i in combo]

                # For each combo, create strategies with different min_agreement thresholds
                for min_agree in range(2, combo_size + 1):
                    sid = _make_strategy_id(signals_config, min_agree)
                    name_parts = [sc["generator"] for sc in signals_config]
                    name = f"{'_'.join(name_parts[:2])}+{combo_size-2}more_agree{min_agree}"

                    strategies.append(
                        Strategy(
                            id=sid,
                            name=name,
                            signals_config=signals_config,
                            min_agreement=min_agree,
                        )
                    )

        self._strategies = strategies
        return strategies

    def count_strategies(self) -> int:
        """Count total strategies without generating them all (fast)."""
        n_variants = sum(len(g["params"]) for g in SIGNAL_GENERATORS.values())
        total = 0
        for size in self.combo_sizes:
            n_combos = _n_choose_k(n_variants, size)
            agreements = size - 1  # from 2 to size
            total += n_combos * agreements
        return total

    def evaluate(self, strategy: Strategy, df: pd.DataFrame) -> StrategyResult:
        """Evaluate a strategy against current market data."""
        signals_fired: list[Signal] = []

        for sc in strategy.signals_config:
            gen_info = SIGNAL_GENERATORS[sc["generator"]]
            fn = gen_info["fn"]
            signal = fn(df, **sc["params"])
            if signal is not None:
                signals_fired.append(signal)

        if not signals_fired:
            return StrategyResult(
                strategy=strategy,
                signals_fired=[],
                direction=Direction.NEUTRAL,
                confidence=0.0,
                reasons=["No signals fired"],
            )

        # Count directions
        long_signals = [s for s in signals_fired if s.direction == Direction.LONG]
        short_signals = [s for s in signals_fired if s.direction == Direction.SHORT]

        long_score = sum(s.strength for s in long_signals)
        short_score = sum(s.strength for s in short_signals)
        total_signals = len(signals_fired)

        # Determine direction based on agreement
        if len(long_signals) >= strategy.min_agreement and long_score > short_score:
            direction = Direction.LONG
            confidence = long_score / total_signals
        elif len(short_signals) >= strategy.min_agreement and short_score > long_score:
            direction = Direction.SHORT
            confidence = short_score / total_signals
        else:
            direction = Direction.NEUTRAL
            confidence = 0.0

        reasons = [s.reason for s in signals_fired]

        return StrategyResult(
            strategy=strategy,
            signals_fired=signals_fired,
            direction=direction,
            confidence=min(1.0, confidence),
            reasons=reasons,
        )

    def evaluate_top_n(
        self, df: pd.DataFrame, strategies: list[Strategy] | None = None, top_n: int = 50
    ) -> list[StrategyResult]:
        """Evaluate strategies and return top N by confidence, excluding neutrals."""
        if strategies is None:
            strategies = self.generate_strategies()

        results = []
        for strat in strategies:
            result = self.evaluate(strat, df)
            if result.direction != Direction.NEUTRAL and result.confidence > 0.3:
                results.append(result)

        results.sort(key=lambda r: r.confidence, reverse=True)
        return results[:top_n]


def _n_choose_k(n: int, k: int) -> int:
    if k > n:
        return 0
    result = 1
    for i in range(min(k, n - k)):
        result = result * (n - i) // (i + 1)
    return result
