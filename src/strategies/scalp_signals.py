"""Ultra-fast scalping signals designed for sub-second crypto trading.

These signals operate on tick-level data, not candle-level.
Designed for 0.1%-0.5% moves with tight stop-losses.
"""

from dataclasses import dataclass
from enum import Enum

from src.trading.crypto_stream import ScalpContext


class ScalpDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class ScalpSignal:
    name: str
    direction: ScalpDirection
    strength: float  # 0.0 - 1.0
    urgency: float  # 0.0 - 1.0 (higher = act NOW)
    reason: str


def momentum_burst(ctx: ScalpContext, threshold: float = 0.0003) -> ScalpSignal | None:
    """Detect sudden price momentum bursts (> threshold in last 20 ticks)."""
    if abs(ctx.price_momentum) < threshold:
        return None
    direction = ScalpDirection.LONG if ctx.price_momentum > 0 else ScalpDirection.SHORT
    strength = min(1.0, abs(ctx.price_momentum) / (threshold * 3))
    return ScalpSignal(
        name="momentum_burst",
        direction=direction,
        strength=strength,
        urgency=0.9,
        reason=f"Price momentum {ctx.price_momentum:+.4%} over 20 ticks",
    )


def vwap_deviation(ctx: ScalpContext, threshold: float = 0.0002) -> ScalpSignal | None:
    """Price deviating from 1-minute VWAP — mean reversion signal."""
    if ctx.vwap_1m == 0 or ctx.last_price == 0:
        return None
    deviation = (ctx.last_price - ctx.vwap_1m) / ctx.vwap_1m

    if abs(deviation) < threshold:
        return None

    # Mean reversion: if price is above VWAP, expect it to come down
    direction = ScalpDirection.SHORT if deviation > 0 else ScalpDirection.LONG
    strength = min(1.0, abs(deviation) / (threshold * 4))
    return ScalpSignal(
        name="vwap_reversion",
        direction=direction,
        strength=strength,
        urgency=0.7,
        reason=f"Price {deviation:+.4%} from VWAP ({ctx.vwap_1m:.2f})",
    )


def spread_tightening(ctx: ScalpContext) -> ScalpSignal | None:
    """Tight spread + high tick velocity = breakout imminent."""
    if ctx.last_price == 0 or ctx.spread == 0:
        return None
    spread_pct = ctx.spread / ctx.last_price

    # Tight spread (< 0.02%) with high activity
    if spread_pct > 0.001 or ctx.tick_velocity < 0.5:
        return None

    direction = ScalpDirection.LONG if ctx.price_momentum > 0 else ScalpDirection.SHORT
    if ctx.price_momentum == 0:
        return None

    return ScalpSignal(
        name="spread_squeeze",
        direction=direction,
        strength=0.8,
        urgency=0.95,
        reason=f"Spread {spread_pct:.4%} + {ctx.tick_velocity:.1f} ticks/sec",
    )


def tick_acceleration(ctx: ScalpContext) -> ScalpSignal | None:
    """Rapid increase in tick velocity signals imminent move."""
    if len(ctx.ticks) < 10:
        return None

    # Compare velocity now vs 10 seconds ago
    import time
    now = time.time() * 1000
    ten_sec_ago = now - 10_000
    twenty_sec_ago = now - 20_000

    recent = len([t for t in ctx.ticks if t.timestamp > ten_sec_ago])
    older = len([t for t in ctx.ticks if twenty_sec_ago < t.timestamp <= ten_sec_ago])

    if older == 0 or recent <= older:
        return None

    acceleration = recent / max(older, 1)
    if acceleration < 1.3:
        return None

    direction = ScalpDirection.LONG if ctx.price_momentum > 0 else ScalpDirection.SHORT
    if ctx.price_momentum == 0:
        return None

    return ScalpSignal(
        name="tick_acceleration",
        direction=direction,
        strength=min(1.0, acceleration / 4),
        urgency=0.85,
        reason=f"Tick velocity {acceleration:.1f}x acceleration",
    )


def bid_ask_imbalance(ctx: ScalpContext) -> ScalpSignal | None:
    """Detect bid/ask pressure from spread positioning."""
    if ctx.last_bid == 0 or ctx.last_ask == 0 or ctx.last_price == 0:
        return None

    mid = (ctx.last_bid + ctx.last_ask) / 2
    if mid == 0:
        return None

    # If price is closer to ask, buyers are aggressive
    position_in_spread = (ctx.last_price - ctx.last_bid) / (ctx.last_ask - ctx.last_bid) if ctx.last_ask != ctx.last_bid else 0.5

    if 0.3 < position_in_spread < 0.7:
        return None  # No clear imbalance

    if position_in_spread >= 0.7:
        return ScalpSignal(
            name="bid_ask_imbalance",
            direction=ScalpDirection.LONG,
            strength=min(1.0, (position_in_spread - 0.5) * 4),
            urgency=0.75,
            reason=f"Aggressive buying — price at {position_in_spread:.0%} of spread",
        )
    else:
        return ScalpSignal(
            name="bid_ask_imbalance",
            direction=ScalpDirection.SHORT,
            strength=min(1.0, (0.5 - position_in_spread) * 4),
            urgency=0.75,
            reason=f"Aggressive selling — price at {position_in_spread:.0%} of spread",
        )


def micro_trend(ctx: ScalpContext, lookback: int = 5) -> ScalpSignal | None:
    """Detect micro-trend from last N ticks — consecutive price movement."""
    if len(ctx.ticks) < lookback:
        return None

    recent = list(ctx.ticks)[-lookback:]
    ups = sum(1 for i in range(1, len(recent)) if recent[i].price > recent[i - 1].price)
    downs = sum(1 for i in range(1, len(recent)) if recent[i].price < recent[i - 1].price)

    total_moves = ups + downs
    if total_moves < lookback * 0.6:
        return None

    if ups >= lookback * 0.7:
        pct = (recent[-1].price - recent[0].price) / recent[0].price if recent[0].price > 0 else 0
        return ScalpSignal(
            name="micro_uptrend",
            direction=ScalpDirection.LONG,
            strength=min(1.0, ups / lookback),
            urgency=0.8,
            reason=f"{ups}/{lookback} ticks up ({pct:+.4%})",
        )
    elif downs >= lookback * 0.7:
        pct = (recent[-1].price - recent[0].price) / recent[0].price if recent[0].price > 0 else 0
        return ScalpSignal(
            name="micro_downtrend",
            direction=ScalpDirection.SHORT,
            strength=min(1.0, downs / lookback),
            urgency=0.8,
            reason=f"{downs}/{lookback} ticks down ({pct:+.4%})",
        )
    return None


# All scalp signal generators
SCALP_SIGNALS = [
    momentum_burst,
    vwap_deviation,
    spread_tightening,
    tick_acceleration,
    bid_ask_imbalance,
    micro_trend,
]
