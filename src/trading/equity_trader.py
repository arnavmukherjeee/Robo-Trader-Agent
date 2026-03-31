"""Equity day trading engine — scans top S&P 500 stocks every 15 minutes.

Pulls 15-min bars, computes technical indicators, pre-filters the top movers,
sends them to Sonnet for deep analysis, and executes the highest-conviction
long trades via the existing AlpacaClient.
"""

import json
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic
import numpy as np
import pandas as pd
from loguru import logger

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config.settings import settings
from src.trading.alpaca_client import AlpacaClient, AssetType

# ── Eastern timezone for market hours ────────────────────────────────────────
ET = ZoneInfo("America/New_York")

# ── Top ~100 most-liquid S&P 500 symbols ─────────────────────────────────────
SP500_UNIVERSE: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "UNH", "JNJ",
    "V", "XOM", "JPM", "PG", "MA", "HD", "AVGO", "CVX", "LLY", "MRK",
    "ABBV", "PEP", "KO", "COST", "ADBE", "WMT", "MCD", "CSCO", "CRM", "TMO",
    "ACN", "ABT", "BAC", "NFLX", "DHR", "LIN", "AMD", "PFE", "CMCSA", "TXN",
    "NKE", "WFC", "PM", "ORCL", "INTC", "UNP", "UPS", "QCOM", "RTX", "NEE",
    "LOW", "HON", "INTU", "AMGN", "SPGI", "IBM", "GE", "AMAT", "DE", "BA",
    "CAT", "GS", "ISRG", "BLK", "MDLZ", "GILD", "ADP", "SYK", "BKNG", "ADI",
    "VRTX", "REGN", "MMC", "TMUS", "LRCX", "PANW", "SCHW", "PGR", "NOW", "MU",
    "CB", "C", "SO", "DUK", "ZTS", "CL", "SNPS", "CDNS", "BSX", "KLAC",
    "FI", "CME", "SHW", "ICE", "MCK", "PH", "EQIX", "MSI", "APH", "MELI",
]

# ── Sonnet system prompt for equity analysis ─────────────────────────────────
EQUITY_SYSTEM_PROMPT = (
    "You are an elite equities day trader. You receive technical analysis on the "
    "top momentum stocks. Pick only the highest-conviction setups. Look for: "
    "breakouts above resistance with volume, oversold bounces with RSI < 30, "
    "trend continuations on pullbacks to the 20-SMA. Avoid: extended stocks far "
    "above VWAP, low volume moves, stocks near resistance with fading momentum. "
    "Return JSON array of trades.\n\n"
    "Each trade object must have:\n"
    '  {"symbol":"AAPL","confidence":0.85,"direction":"long",'
    '"size_pct":0.10,"reason":"20 words max explaining the edge"}\n\n'
    "confidence: 0.0-1.0\n"
    "size_pct: fraction of portfolio (0.05 to 0.10)\n"
    "direction: always \"long\"\n"
    "Reply with ONLY a valid JSON array, no markdown."
)


# ── Technical indicator helpers ──────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI for a price series."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """Compute intraday VWAP from OHLCV bars."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute a full set of indicators from 15-min OHLCV bars.

    Returns a dict with latest values for RSI, SMAs, VWAP, volume metrics,
    and day-move percentage.
    """
    if len(df) < 50:
        return {}

    close = df["close"]
    volume = df["volume"]

    rsi_series = compute_rsi(close, 14)
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()
    vwap = compute_vwap(df)
    avg_volume = volume.rolling(20).mean()

    latest = close.iloc[-1]
    prev_close = close.iloc[-26] if len(close) > 26 else close.iloc[0]  # ~1 day back
    day_move_pct = (latest - prev_close) / prev_close * 100

    vol_ratio = volume.iloc[-1] / avg_volume.iloc[-1] if avg_volume.iloc[-1] > 0 else 0

    return {
        "price": float(latest),
        "rsi": float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0,
        "sma_20": float(sma_20.iloc[-1]) if not pd.isna(sma_20.iloc[-1]) else float(latest),
        "sma_50": float(sma_50.iloc[-1]) if not pd.isna(sma_50.iloc[-1]) else float(latest),
        "vwap": float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else float(latest),
        "volume": float(volume.iloc[-1]),
        "avg_volume": float(avg_volume.iloc[-1]) if not pd.isna(avg_volume.iloc[-1]) else 0,
        "vol_ratio": float(vol_ratio),
        "day_move_pct": float(day_move_pct),
        "above_sma20": bool(latest > sma_20.iloc[-1]) if not pd.isna(sma_20.iloc[-1]) else False,
        "above_sma50": bool(latest > sma_50.iloc[-1]) if not pd.isna(sma_50.iloc[-1]) else False,
        "above_vwap": bool(latest > vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else False,
    }


def build_chart_summary(df: pd.DataFrame, indicators: dict) -> str:
    """Build a text summary of recent bars + indicators for the LLM."""
    recent = df.tail(10)
    lines = ["Recent 15-min bars (oldest -> newest):"]
    for _, row in recent.iterrows():
        ts = row["timestamp"]
        ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[-8:-3]
        lines.append(
            f"  {ts_str} | O:{row['open']:.2f} H:{row['high']:.2f} "
            f"L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volume']:,.0f}"
        )

    lines.append("")
    lines.append(f"RSI(14): {indicators['rsi']:.1f}")
    lines.append(f"20-SMA: ${indicators['sma_20']:.2f}  (price {'above' if indicators['above_sma20'] else 'below'})")
    lines.append(f"50-SMA: ${indicators['sma_50']:.2f}  (price {'above' if indicators['above_sma50'] else 'below'})")
    lines.append(f"VWAP: ${indicators['vwap']:.2f}  (price {'above' if indicators['above_vwap'] else 'below'})")
    lines.append(f"Volume ratio vs 20-bar avg: {indicators['vol_ratio']:.2f}x")
    lines.append(f"Today's move: {indicators['day_move_pct']:+.2f}%")

    return "\n".join(lines)


# ── Main equity trading engine ───────────────────────────────────────────────

class EquityTrader:
    """Scans top S&P 500 stocks every 15 minutes and trades via Sonnet analysis."""

    def __init__(self):
        self.client = AlpacaClient()
        self.anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = "claude-sonnet-4-20250514"
        self._running = False
        self._stop_event = threading.Event()

        # Config from settings
        self.position_size_pct = settings.equity_position_size_pct
        self.max_positions = settings.equity_max_positions
        self.tp_pct = settings.equity_tp_pct
        self.sl_pct = settings.equity_sl_pct

        # Track open equity positions managed by this module
        self._managed_positions: dict[str, dict] = {}  # symbol -> {entry_price, qty, order_id}

        logger.info(
            f"EquityTrader initialized | universe={len(SP500_UNIVERSE)} symbols | "
            f"max_positions={self.max_positions} | tp={self.tp_pct:.1%} sl={self.sl_pct:.1%}"
        )

    # ── Market hours ─────────────────────────────────────────────────────────

    @staticmethod
    def _now_et() -> datetime:
        return datetime.now(ET)

    def _is_market_open(self) -> bool:
        """Check if we are within regular market hours (9:30am - 4:00pm ET, weekdays)."""
        now = self._now_et()
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close

    def _can_enter_new_trade(self) -> bool:
        """Allow entries only 9:30am - 3:30pm ET (no new entries in last 30min)."""
        now = self._now_et()
        if now.weekday() >= 5:
            return False
        entry_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        entry_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return entry_open <= now <= entry_close

    # ── Data fetching ────────────────────────────────────────────────────────

    def _fetch_bars(self, symbol: str) -> pd.DataFrame | None:
        """Fetch last 5 days of 15-min bars for a symbol."""
        try:
            df = self.client.get_bars(
                symbol=symbol,
                asset_type=AssetType.EQUITY,
                timeframe=TimeFrame.Minute,  # Will use 15-min via direct request below
                days_back=5,
            )
            return df if len(df) >= 50 else None
        except Exception:
            return None

    def _fetch_bars_15min(self, symbol: str) -> pd.DataFrame | None:
        """Fetch last 5 days of 15-min bars directly from Alpaca data API."""
        try:
            start = datetime.now() - timedelta(days=7)  # 7 calendar days for 5 trading days
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame(15, "Min"),
                start=start,
            )
            bars = self.client.stock_data.get_stock_bars(request)
            df = bars.df.reset_index()
            if "symbol" in df.columns:
                df = df[df["symbol"] == symbol].copy()
            df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
            return df if len(df) >= 50 else None
        except Exception as e:
            logger.debug(f"Failed to fetch bars for {symbol}: {e}")
            return None

    # ── Scanning & filtering ─────────────────────────────────────────────────

    def _scan_universe(self) -> list[tuple[str, pd.DataFrame, dict]]:
        """Scan all symbols and return list of (symbol, df, indicators) sorted by momentum."""
        results = []

        for symbol in SP500_UNIVERSE:
            if self._stop_event.is_set():
                break

            df = self._fetch_bars_15min(symbol)
            if df is None:
                continue

            indicators = compute_indicators(df)
            if not indicators:
                continue

            results.append((symbol, df, indicators))

        logger.info(f"Scanned {len(results)}/{len(SP500_UNIVERSE)} symbols successfully")
        return results

    def _filter_top_movers(
        self, scanned: list[tuple[str, pd.DataFrame, dict]], top_n: int = 10
    ) -> list[tuple[str, pd.DataFrame, dict]]:
        """Pre-filter to find the top N movers by momentum score.

        Scoring: combination of |day_move_pct|, volume ratio, and RSI extremes.
        """
        scored = []
        for symbol, df, ind in scanned:
            # Skip symbols we already have a position in
            if symbol in self._managed_positions:
                continue

            momentum_score = abs(ind["day_move_pct"]) * 2.0
            volume_score = min(ind["vol_ratio"], 5.0)  # cap at 5x
            rsi_extreme_score = max(0, 30 - ind["rsi"]) * 0.1 + max(0, ind["rsi"] - 70) * 0.05

            total_score = momentum_score + volume_score + rsi_extreme_score
            scored.append((total_score, symbol, df, ind))

        scored.sort(reverse=True, key=lambda x: x[0])
        top = scored[:top_n]

        if top:
            names = [s[1] for s in top]
            logger.info(f"Top {len(top)} movers: {', '.join(names)}")

        return [(s[1], s[2], s[3]) for s in top]

    # ── LLM analysis ─────────────────────────────────────────────────────────

    def _analyze_with_sonnet(
        self, candidates: list[tuple[str, pd.DataFrame, dict]]
    ) -> list[dict]:
        """Send top movers to Sonnet for deep analysis. Returns list of trade recommendations."""
        if not candidates:
            return []

        # Build the prompt with all candidates
        sections = []
        for symbol, df, indicators in candidates:
            chart = build_chart_summary(df, indicators)
            sections.append(f"=== {symbol} ===\n{chart}")

        account = self.client.get_account()
        portfolio_value = account["portfolio_value"]
        open_count = len(self._managed_positions)

        prompt = (
            f"Portfolio: ${portfolio_value:,.0f} | Open positions: {open_count}/{self.max_positions}\n"
            f"Max new positions this cycle: {self.max_positions - open_count}\n"
            f"Position size: {self.position_size_pct:.0%} of portfolio (${portfolio_value * self.position_size_pct:,.0f})\n"
            f"Take profit: {self.tp_pct:.1%} | Stop loss: {self.sl_pct:.1%}\n\n"
            f"Analyze these {len(candidates)} stocks and pick the best 3-5 trades "
            f"(only if high conviction). Return empty array [] if nothing is compelling.\n\n"
            + "\n\n".join(sections)
        )

        try:
            resp = self.anthropic.messages.create(
                model=self.model,
                max_tokens=1000,
                system=EQUITY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()

            # Strip markdown code fences if present
            if "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
                if text.startswith("json"):
                    text = text[4:].strip()

            trades = json.loads(text)
            if not isinstance(trades, list):
                logger.warning("Sonnet returned non-array response, skipping")
                return []

            logger.info(f"Sonnet recommended {len(trades)} trades")
            for t in trades:
                logger.info(
                    f"  -> {t.get('symbol')} | confidence={t.get('confidence', 0):.0%} | "
                    f"{t.get('reason', 'no reason')}"
                )
            return trades

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Sonnet response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Sonnet analysis failed: {e}")
            return []

    # ── Order execution ──────────────────────────────────────────────────────

    def _execute_trades(self, trades: list[dict]) -> None:
        """Execute the recommended trades, respecting position limits and confidence threshold."""
        account = self.client.get_account()
        portfolio_value = account["portfolio_value"]
        open_count = len(self._managed_positions)

        for trade in trades:
            if self._stop_event.is_set():
                break

            symbol = trade.get("symbol", "")
            confidence = float(trade.get("confidence", 0))
            direction = trade.get("direction", "long")
            reason = trade.get("reason", "")

            # Validations
            if direction != "long":
                logger.info(f"Skipping {symbol}: direction={direction} (long only)")
                continue

            if confidence < 0.75:
                logger.info(f"Skipping {symbol}: confidence={confidence:.0%} < 75% threshold")
                continue

            if symbol in self._managed_positions:
                logger.info(f"Skipping {symbol}: already have open position")
                continue

            if open_count >= self.max_positions:
                logger.info(f"Max positions reached ({self.max_positions}), stopping execution")
                break

            # Calculate position size
            size_pct = min(float(trade.get("size_pct", self.position_size_pct)), self.position_size_pct)
            notional = portfolio_value * size_pct

            try:
                # Get current price for qty calculation and TP/SL tracking
                price = self.client.get_latest_price(symbol, AssetType.EQUITY)

                order = self.client.place_market_order(
                    symbol=symbol,
                    notional=round(notional, 2),
                    side="buy",
                )

                qty = float(order.get("qty", 0)) if order.get("qty") else notional / price
                self._managed_positions[symbol] = {
                    "entry_price": price,
                    "qty": qty,
                    "order_id": order["order_id"],
                    "tp_price": price * (1 + self.tp_pct),
                    "sl_price": price * (1 - self.sl_pct),
                    "entered_at": datetime.now(ET).isoformat(),
                    "reason": reason,
                }
                open_count += 1

                logger.info(
                    f"ENTERED {symbol} | ${notional:,.0f} @ ${price:.2f} | "
                    f"TP=${price * (1 + self.tp_pct):.2f} SL=${price * (1 - self.sl_pct):.2f} | "
                    f"confidence={confidence:.0%} | {reason}"
                )

            except Exception as e:
                logger.error(f"Failed to enter {symbol}: {e}")

    # ── Position management ──────────────────────────────────────────────────

    def _manage_positions(self) -> None:
        """Check TP/SL on all managed positions and exit if hit."""
        if not self._managed_positions:
            return

        symbols_to_close = []
        for symbol, pos in self._managed_positions.items():
            try:
                price = self.client.get_latest_price(symbol, AssetType.EQUITY)
                entry = pos["entry_price"]
                pnl_pct = (price - entry) / entry * 100

                if price >= pos["tp_price"]:
                    logger.info(
                        f"TP HIT {symbol} | entry=${entry:.2f} exit=${price:.2f} | "
                        f"PnL={pnl_pct:+.2f}%"
                    )
                    symbols_to_close.append(symbol)
                elif price <= pos["sl_price"]:
                    logger.info(
                        f"SL HIT {symbol} | entry=${entry:.2f} exit=${price:.2f} | "
                        f"PnL={pnl_pct:+.2f}%"
                    )
                    symbols_to_close.append(symbol)
                else:
                    logger.debug(
                        f"  {symbol}: ${price:.2f} (PnL={pnl_pct:+.2f}%) | "
                        f"TP=${pos['tp_price']:.2f} SL=${pos['sl_price']:.2f}"
                    )

            except Exception as e:
                logger.warning(f"Failed to check price for {symbol}: {e}")

        for symbol in symbols_to_close:
            try:
                self.client.close_position(symbol)
                del self._managed_positions[symbol]
                logger.info(f"Position closed: {symbol}")
            except Exception as e:
                logger.error(f"Failed to close position {symbol}: {e}")

    # ── End-of-day cleanup ───────────────────────────────────────────────────

    def _close_all_managed(self) -> None:
        """Close all positions managed by this module (end-of-day or shutdown)."""
        if not self._managed_positions:
            return

        logger.info(f"Closing all {len(self._managed_positions)} managed positions")
        for symbol in list(self._managed_positions.keys()):
            try:
                price = self.client.get_latest_price(symbol, AssetType.EQUITY)
                entry = self._managed_positions[symbol]["entry_price"]
                pnl_pct = (price - entry) / entry * 100
                self.client.close_position(symbol)
                logger.info(f"Closed {symbol} | PnL={pnl_pct:+.2f}%")
            except Exception as e:
                logger.error(f"Failed to close {symbol}: {e}")

        self._managed_positions.clear()

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run_cycle(self) -> None:
        """Execute one full scan-analyze-trade cycle."""
        now = self._now_et()
        logger.info(f"=== Equity scan cycle @ {now.strftime('%Y-%m-%d %H:%M ET')} ===")

        # Always manage existing positions (TP/SL checks)
        self._manage_positions()

        # Check if market is past 3:50pm ET -> close all for the day
        if now.hour == 15 and now.minute >= 50:
            logger.info("Approaching market close, closing all managed positions")
            self._close_all_managed()
            return

        # Only scan and enter new trades during allowed hours
        if not self._can_enter_new_trade():
            logger.info("Outside entry window (9:30am-3:30pm ET), skipping scan")
            return

        # 1. Scan universe
        scanned = self._scan_universe()

        # 2. Filter top movers
        top_movers = self._filter_top_movers(scanned, top_n=10)
        if not top_movers:
            logger.info("No compelling movers found this cycle")
            return

        # 3. Analyze with Sonnet
        trades = self._analyze_with_sonnet(top_movers)

        # 4. Execute trades
        if trades:
            self._execute_trades(trades)
        else:
            logger.info("Sonnet found no high-conviction setups")

    def run(self) -> None:
        """Main loop: run a cycle every 15 minutes during market hours."""
        self._running = True
        logger.info("EquityTrader started — scanning every 15 minutes during market hours")

        while self._running and not self._stop_event.is_set():
            try:
                if self._is_market_open():
                    self._run_cycle()
                else:
                    now = self._now_et()
                    logger.debug(
                        f"Market closed ({now.strftime('%A %H:%M ET')}), waiting..."
                    )
                    # Clear any stale managed positions from yesterday
                    if self._managed_positions:
                        logger.warning("Found stale managed positions outside market hours, clearing")
                        self._managed_positions.clear()

            except Exception as e:
                logger.exception(f"Error in equity trading cycle: {e}")

            # Sleep 15 minutes, but check stop event every 5 seconds for fast shutdown
            for _ in range(180):  # 180 * 5s = 900s = 15min
                if self._stop_event.is_set():
                    break
                time.sleep(5)

        # Clean shutdown
        self._close_all_managed()
        logger.info("EquityTrader stopped")

    def stop(self) -> None:
        """Signal the trader to stop gracefully."""
        logger.info("EquityTrader shutdown requested")
        self._running = False
        self._stop_event.set()
