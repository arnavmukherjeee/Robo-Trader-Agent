"""Technical indicators used by trading strategies."""

import pandas as pd
import numpy as np
import ta


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a full suite of technical indicators on OHLCV data.

    Args:
        df: DataFrame with columns: open, high, low, close, volume

    Returns:
        DataFrame with all indicator columns added.
    """
    df = df.copy()

    # --- Trend Indicators ---
    for period in [7, 14, 21, 50, 100, 200]:
        df[f"sma_{period}"] = ta.trend.sma_indicator(df["close"], window=period)
        df[f"ema_{period}"] = ta.trend.ema_indicator(df["close"], window=period)

    df["macd"] = ta.trend.macd(df["close"])
    df["macd_signal"] = ta.trend.macd_signal(df["close"])
    df["macd_diff"] = ta.trend.macd_diff(df["close"])

    for period in [14, 20, 25]:
        df[f"adx_{period}"] = ta.trend.adx(df["high"], df["low"], df["close"], window=period)

    df["ichimoku_a"] = ta.trend.ichimoku_a(df["high"], df["low"])
    df["ichimoku_b"] = ta.trend.ichimoku_b(df["high"], df["low"])

    # --- Momentum Indicators ---
    for period in [7, 14, 21]:
        df[f"rsi_{period}"] = ta.momentum.rsi(df["close"], window=period)

    df["stoch_k"] = ta.momentum.stoch(df["high"], df["low"], df["close"])
    df["stoch_d"] = ta.momentum.stoch_signal(df["high"], df["low"], df["close"])

    for period in [10, 20]:
        df[f"williams_r_{period}"] = ta.momentum.williams_r(
            df["high"], df["low"], df["close"], lbp=period
        )
        df[f"roc_{period}"] = ta.momentum.roc(df["close"], window=period)

    df["awesome_osc"] = ta.momentum.awesome_oscillator(df["high"], df["low"])

    # --- Volatility Indicators ---
    for period in [14, 20, 25]:
        bb = ta.volatility.BollingerBands(df["close"], window=period)
        df[f"bb_upper_{period}"] = bb.bollinger_hband()
        df[f"bb_lower_{period}"] = bb.bollinger_lband()
        df[f"bb_mid_{period}"] = bb.bollinger_mavg()
        df[f"bb_width_{period}"] = bb.bollinger_wband()

    for period in [10, 14, 20]:
        df[f"atr_{period}"] = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=period
        )

    df["keltner_upper"] = ta.volatility.keltner_channel_hband(
        df["high"], df["low"], df["close"]
    )
    df["keltner_lower"] = ta.volatility.keltner_channel_lband(
        df["high"], df["low"], df["close"]
    )

    # --- Volume Indicators ---
    df["obv"] = ta.volume.on_balance_volume(df["close"], df["volume"])
    df["vwap"] = ta.volume.volume_weighted_average_price(
        df["high"], df["low"], df["close"], df["volume"]
    )
    df["mfi"] = ta.volume.money_flow_index(
        df["high"], df["low"], df["close"], df["volume"]
    )
    df["adi"] = ta.volume.acc_dist_index(df["high"], df["low"], df["close"], df["volume"])
    df["cmf"] = ta.volume.chaikin_money_flow(
        df["high"], df["low"], df["close"], df["volume"]
    )

    # --- Derived / Custom ---
    df["close_pct_change"] = df["close"].pct_change()
    df["volume_sma_20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma_20"]

    # Price relative to moving averages
    for period in [50, 200]:
        df[f"price_vs_sma_{period}"] = (df["close"] - df[f"sma_{period}"]) / df[f"sma_{period}"]

    return df
