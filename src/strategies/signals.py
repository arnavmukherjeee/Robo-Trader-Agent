"""Signal definitions — atomic buy/sell conditions that strategies compose."""

from enum import Enum
from dataclasses import dataclass
import pandas as pd
import numpy as np


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


@dataclass
class Signal:
    name: str
    direction: Direction
    strength: float  # 0.0 to 1.0
    reason: str


def rsi_oversold(df: pd.DataFrame, period: int = 14, threshold: float = 30) -> Signal | None:
    col = f"rsi_{period}"
    if col not in df.columns or df[col].iloc[-1] is None or np.isnan(df[col].iloc[-1]):
        return None
    val = df[col].iloc[-1]
    if val < threshold:
        return Signal(
            name=f"RSI({period}) oversold",
            direction=Direction.LONG,
            strength=min(1.0, (threshold - val) / threshold),
            reason=f"RSI({period}) = {val:.1f} < {threshold}",
        )
    return None


def rsi_overbought(df: pd.DataFrame, period: int = 14, threshold: float = 70) -> Signal | None:
    col = f"rsi_{period}"
    if col not in df.columns or df[col].iloc[-1] is None or np.isnan(df[col].iloc[-1]):
        return None
    val = df[col].iloc[-1]
    if val > threshold:
        return Signal(
            name=f"RSI({period}) overbought",
            direction=Direction.SHORT,
            strength=min(1.0, (val - threshold) / (100 - threshold)),
            reason=f"RSI({period}) = {val:.1f} > {threshold}",
        )
    return None


def macd_crossover_bull(df: pd.DataFrame) -> Signal | None:
    if "macd_diff" not in df.columns or len(df) < 2:
        return None
    curr = df["macd_diff"].iloc[-1]
    prev = df["macd_diff"].iloc[-2]
    if np.isnan(curr) or np.isnan(prev):
        return None
    if prev < 0 and curr > 0:
        return Signal(
            name="MACD bullish crossover",
            direction=Direction.LONG,
            strength=min(1.0, abs(curr) * 10),
            reason=f"MACD diff crossed above zero: {prev:.4f} -> {curr:.4f}",
        )
    return None


def macd_crossover_bear(df: pd.DataFrame) -> Signal | None:
    if "macd_diff" not in df.columns or len(df) < 2:
        return None
    curr = df["macd_diff"].iloc[-1]
    prev = df["macd_diff"].iloc[-2]
    if np.isnan(curr) or np.isnan(prev):
        return None
    if prev > 0 and curr < 0:
        return Signal(
            name="MACD bearish crossover",
            direction=Direction.SHORT,
            strength=min(1.0, abs(curr) * 10),
            reason=f"MACD diff crossed below zero: {prev:.4f} -> {curr:.4f}",
        )
    return None


def sma_crossover(
    df: pd.DataFrame, fast: int = 50, slow: int = 200
) -> Signal | None:
    fast_col, slow_col = f"sma_{fast}", f"sma_{slow}"
    if fast_col not in df.columns or slow_col not in df.columns or len(df) < 2:
        return None
    curr_fast, curr_slow = df[fast_col].iloc[-1], df[slow_col].iloc[-1]
    prev_fast, prev_slow = df[fast_col].iloc[-2], df[slow_col].iloc[-2]
    if any(np.isnan(v) for v in [curr_fast, curr_slow, prev_fast, prev_slow]):
        return None

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return Signal(
            name=f"SMA({fast}/{slow}) golden cross",
            direction=Direction.LONG,
            strength=0.8,
            reason=f"SMA {fast} crossed above SMA {slow}",
        )
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return Signal(
            name=f"SMA({fast}/{slow}) death cross",
            direction=Direction.SHORT,
            strength=0.8,
            reason=f"SMA {fast} crossed below SMA {slow}",
        )
    return None


def bollinger_squeeze(df: pd.DataFrame, period: int = 20, threshold: float = 0.02) -> Signal | None:
    col = f"bb_width_{period}"
    if col not in df.columns:
        return None
    val = df[col].iloc[-1]
    if np.isnan(val):
        return None
    if val < threshold:
        return Signal(
            name=f"BB({period}) squeeze",
            direction=Direction.NEUTRAL,
            strength=min(1.0, (threshold - val) / threshold),
            reason=f"BB width {val:.4f} < {threshold} — volatility squeeze, breakout imminent",
        )
    return None


def bollinger_breakout(df: pd.DataFrame, period: int = 20) -> Signal | None:
    upper_col = f"bb_upper_{period}"
    lower_col = f"bb_lower_{period}"
    if upper_col not in df.columns or lower_col not in df.columns:
        return None
    price = df["close"].iloc[-1]
    upper = df[upper_col].iloc[-1]
    lower = df[lower_col].iloc[-1]
    if any(np.isnan(v) for v in [price, upper, lower]):
        return None

    if price > upper:
        return Signal(
            name=f"BB({period}) upper breakout",
            direction=Direction.LONG,
            strength=0.7,
            reason=f"Price {price:.2f} broke above BB upper {upper:.2f}",
        )
    if price < lower:
        return Signal(
            name=f"BB({period}) lower breakout",
            direction=Direction.SHORT,
            strength=0.7,
            reason=f"Price {price:.2f} broke below BB lower {lower:.2f}",
        )
    return None


def volume_spike(df: pd.DataFrame, multiplier: float = 2.0) -> Signal | None:
    if "volume_ratio" not in df.columns:
        return None
    ratio = df["volume_ratio"].iloc[-1]
    if np.isnan(ratio):
        return None
    if ratio > multiplier:
        direction = Direction.LONG if df["close_pct_change"].iloc[-1] > 0 else Direction.SHORT
        return Signal(
            name="Volume spike",
            direction=direction,
            strength=min(1.0, ratio / (multiplier * 2)),
            reason=f"Volume {ratio:.1f}x above 20-day average",
        )
    return None


def mfi_signal(df: pd.DataFrame, oversold: float = 20, overbought: float = 80) -> Signal | None:
    if "mfi" not in df.columns:
        return None
    val = df["mfi"].iloc[-1]
    if np.isnan(val):
        return None
    if val < oversold:
        return Signal(
            name="MFI oversold",
            direction=Direction.LONG,
            strength=min(1.0, (oversold - val) / oversold),
            reason=f"MFI = {val:.1f} < {oversold}",
        )
    if val > overbought:
        return Signal(
            name="MFI overbought",
            direction=Direction.SHORT,
            strength=min(1.0, (val - overbought) / (100 - overbought)),
            reason=f"MFI = {val:.1f} > {overbought}",
        )
    return None


def adx_trend_strength(df: pd.DataFrame, period: int = 14, threshold: float = 25) -> Signal | None:
    col = f"adx_{period}"
    if col not in df.columns:
        return None
    val = df[col].iloc[-1]
    if np.isnan(val):
        return None
    if val > threshold:
        pct_change = df["close_pct_change"].iloc[-1]
        direction = Direction.LONG if pct_change > 0 else Direction.SHORT
        return Signal(
            name=f"ADX({period}) strong trend",
            direction=direction,
            strength=min(1.0, val / 50),
            reason=f"ADX({period}) = {val:.1f} > {threshold} — strong trend detected",
        )
    return None


def stochastic_signal(
    df: pd.DataFrame, oversold: float = 20, overbought: float = 80
) -> Signal | None:
    if "stoch_k" not in df.columns or "stoch_d" not in df.columns:
        return None
    k, d = df["stoch_k"].iloc[-1], df["stoch_d"].iloc[-1]
    if np.isnan(k) or np.isnan(d):
        return None
    if k < oversold and d < oversold:
        return Signal(
            name="Stochastic oversold",
            direction=Direction.LONG,
            strength=min(1.0, (oversold - k) / oversold),
            reason=f"Stochastic K={k:.1f}, D={d:.1f} both below {oversold}",
        )
    if k > overbought and d > overbought:
        return Signal(
            name="Stochastic overbought",
            direction=Direction.SHORT,
            strength=min(1.0, (k - overbought) / (100 - overbought)),
            reason=f"Stochastic K={k:.1f}, D={d:.1f} both above {overbought}",
        )
    return None


# Registry of all signal generators with their parameter variants
SIGNAL_GENERATORS = {
    "rsi_oversold": {
        "fn": rsi_oversold,
        "params": [
            {"period": p, "threshold": t}
            for p in [7, 14, 21]
            for t in [20, 25, 30, 35]
        ],
    },
    "rsi_overbought": {
        "fn": rsi_overbought,
        "params": [
            {"period": p, "threshold": t}
            for p in [7, 14, 21]
            for t in [65, 70, 75, 80]
        ],
    },
    "macd_crossover_bull": {"fn": macd_crossover_bull, "params": [{}]},
    "macd_crossover_bear": {"fn": macd_crossover_bear, "params": [{}]},
    "sma_crossover": {
        "fn": sma_crossover,
        "params": [
            {"fast": f, "slow": s}
            for f in [7, 14, 21, 50]
            for s in [50, 100, 200]
            if f < s
        ],
    },
    "bollinger_squeeze": {
        "fn": bollinger_squeeze,
        "params": [
            {"period": p, "threshold": t}
            for p in [14, 20, 25]
            for t in [0.01, 0.02, 0.03]
        ],
    },
    "bollinger_breakout": {
        "fn": bollinger_breakout,
        "params": [{"period": p} for p in [14, 20, 25]],
    },
    "volume_spike": {
        "fn": volume_spike,
        "params": [{"multiplier": m} for m in [1.5, 2.0, 2.5, 3.0]],
    },
    "mfi_signal": {
        "fn": mfi_signal,
        "params": [
            {"oversold": o, "overbought": ob}
            for o in [15, 20, 25]
            for ob in [75, 80, 85]
        ],
    },
    "adx_trend_strength": {
        "fn": adx_trend_strength,
        "params": [
            {"period": p, "threshold": t}
            for p in [14, 20, 25]
            for t in [20, 25, 30]
        ],
    },
    "stochastic_signal": {
        "fn": stochastic_signal,
        "params": [
            {"oversold": o, "overbought": ob}
            for o in [15, 20, 25]
            for ob in [75, 80, 85]
        ],
    },
}
