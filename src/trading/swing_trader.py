"""Swing trading module for crypto — Claude Sonnet-powered multi-hour holds.

Pulls 1h OHLCV candles every 5 minutes, calculates technical indicators,
sends analysis to Claude Sonnet for trade selection, and manages positions
with TP/SL and an 8-hour max hold time.
"""

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import anthropic
from loguru import logger

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from config.settings import settings
from src.trading.alpaca_client import AlpacaClient


# ── Configuration ─────────────────────────────────────────────────────

SWING_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD"]
LOOP_INTERVAL_SEC = 300  # 5 minutes
MAX_HOLD_HOURS = 8
MIN_CONVICTION = 0.4  # minimum conviction to execute
SONNET_MODEL = "claude-sonnet-4-20250514"

SWING_SYSTEM_PROMPT = """You are an aggressive crypto swing trader. You receive hourly OHLCV data
and technical indicators for multiple crypto assets. Your job: pick the BEST 1-2 trades right now.

STRATEGY:
- Target 3-5% moves, willing to hold for hours (up to 8h max)
- You can go LONG (buy) if momentum is bullish
- You can go SHORT (sell) if momentum is bearish — but prefer longs in strong uptrends
- Be decisive — ALWAYS pick at least 1 trade. We want to be in the market.
- Size aggressively — this is paper trading, we want maximum exposure
- Higher conviction = bigger size

ANALYSIS FRAMEWORK:
- RSI < 30 = oversold bounce opportunity (buy)
- RSI > 70 = overbought reversal opportunity (sell) or momentum continuation
- Price above SMA20 = bullish bias, below = bearish bias
- Bollinger Band squeeze = breakout imminent
- Volume surge = confirms the move
- Higher highs + higher lows = uptrend, lower highs + lower lows = downtrend
- Multi-timeframe alignment (1h, 4h, 24h changes) = strongest setups

Reply with ONLY valid JSON — no markdown, no code fences, no explanation outside the array.
Return a JSON array of trade recommendations:
[{"symbol": "BTC/USD", "side": "buy", "conviction": 0.85, "target_pct": 0.04, "stop_pct": 0.025, "size_pct": 0.40, "reasoning": "Strong uptrend with RSI pulling back from 65, above SMA20, volume increasing"}]

Rules for the JSON:
- symbol: one of the symbols provided (e.g. "BTC/USD")
- side: "buy" or "sell"
- conviction: 0.0 to 1.0 (how confident you are)
- target_pct: 0.03 to 0.10 (take profit distance, e.g. 0.04 = 4%)
- stop_pct: 0.02 to 0.05 (stop loss distance, e.g. 0.025 = 2.5%)
- size_pct: 0.20 to 0.50 (fraction of equity to allocate)
- reasoning: brief explanation (under 30 words)

Return 1-2 trades. Always return at least 1."""

MANAGE_SYSTEM_PROMPT = """You are an aggressive crypto swing trader managing open positions.
You receive current position data and fresh technical indicators.

For each position, decide: HOLD, ADD, or EXIT.
- HOLD: keep position as-is, let it run toward target
- ADD: increase position size (only if conviction is very high and trend strengthening)
- EXIT: close position now (if momentum reversed, or close enough to target to take profit)

Be patient with winners — let them run. But cut losers quickly.
Max hold time is 8 hours — if a position has been open > 6 hours, bias toward EXIT.

Reply with ONLY valid JSON — no markdown, no code fences:
[{"symbol": "BTC/USD", "action": "hold", "reasoning": "Trend intact, 2% from target"}]

Actions: "hold", "add", "exit"
Provide a decision for EVERY open position."""


# ── Stats Tracking ────────────────────────────────────────────────────

@dataclass
class SwingStats:
    """Track swing trading performance."""

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_notional: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    start_time: float = field(default_factory=time.time)

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def runtime_hours(self) -> float:
        return (time.time() - self.start_time) / 3600

    def record_trade(self, pnl: float, notional: float) -> None:
        self.total_trades += 1
        self.total_pnl += pnl
        self.total_notional += notional
        if pnl >= 0:
            self.wins += 1
            self.largest_win = max(self.largest_win, pnl)
        else:
            self.losses += 1
            self.largest_loss = min(self.largest_loss, pnl)

    def summary(self) -> str:
        return (
            f"SwingStats | Trades: {self.total_trades} | "
            f"W/L: {self.wins}/{self.losses} ({self.win_rate:.0%}) | "
            f"PnL: ${self.total_pnl:,.2f} | Avg: ${self.avg_pnl:,.2f} | "
            f"Best: ${self.largest_win:,.2f} | Worst: ${self.largest_loss:,.2f} | "
            f"Runtime: {self.runtime_hours:.1f}h"
        )


# ── Position Tracking ─────────────────────────────────────────────────

@dataclass
class SwingPosition:
    """Track an open swing trade."""

    symbol: str
    side: str
    entry_price: float
    notional: float
    target_pct: float
    stop_pct: float
    conviction: float
    reasoning: str
    entry_time: float = field(default_factory=time.time)

    @property
    def hold_hours(self) -> float:
        return (time.time() - self.entry_time) / 3600

    @property
    def target_price(self) -> float:
        if self.side == "buy":
            return self.entry_price * (1 + self.target_pct)
        return self.entry_price * (1 - self.target_pct)

    @property
    def stop_price(self) -> float:
        if self.side == "buy":
            return self.entry_price * (1 - self.stop_pct)
        return self.entry_price * (1 + self.stop_pct)

    def alpaca_symbol(self) -> str:
        """Convert BTC/USD -> BTCUSD for Alpaca positions API."""
        return self.symbol.replace("/", "")


# ── Technical Indicators (manual calculations) ────────────────────────

def calc_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI manually."""
    if len(closes) < period + 1:
        return 50.0  # neutral default

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    # Use last `period` changes
    recent_gains = gains[-(period):]
    recent_losses = losses[-(period):]

    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_sma(values: list[float], period: int = 20) -> float:
    """Simple moving average of last N values."""
    if len(values) < period:
        return sum(values) / len(values) if values else 0.0
    return sum(values[-period:]) / period


def calc_bollinger_bands(closes: list[float], period: int = 20, num_std: float = 2.0) -> dict:
    """Calculate Bollinger Bands."""
    if len(closes) < period:
        mid = sum(closes) / len(closes) if closes else 0
        return {"upper": mid, "middle": mid, "lower": mid, "position": 0.5}

    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = math.sqrt(variance)

    upper = mid + num_std * std
    lower = mid - num_std * std

    current = closes[-1]
    band_width = upper - lower
    position = (current - lower) / band_width if band_width > 0 else 0.5

    return {"upper": upper, "middle": mid, "lower": lower, "position": position}


def calc_trend(highs: list[float], lows: list[float]) -> str:
    """Determine simple trend direction from recent highs/lows."""
    if len(highs) < 4 or len(lows) < 4:
        return "neutral"

    recent_highs = highs[-4:]
    recent_lows = lows[-4:]

    higher_highs = all(recent_highs[i] >= recent_highs[i - 1] for i in range(1, len(recent_highs)))
    higher_lows = all(recent_lows[i] >= recent_lows[i - 1] for i in range(1, len(recent_lows)))
    lower_highs = all(recent_highs[i] <= recent_highs[i - 1] for i in range(1, len(recent_highs)))
    lower_lows = all(recent_lows[i] <= recent_lows[i - 1] for i in range(1, len(recent_lows)))

    if higher_highs and higher_lows:
        return "uptrend"
    elif lower_highs and lower_lows:
        return "downtrend"
    return "neutral"


def analyze_symbol(bars_df) -> dict:
    """Calculate all indicators for a single symbol's bar data."""
    closes = bars_df["close"].tolist()
    highs = bars_df["high"].tolist()
    lows = bars_df["low"].tolist()
    volumes = bars_df["volume"].tolist()

    if len(closes) < 2:
        return {"error": "insufficient data"}

    current_price = closes[-1]
    rsi = calc_rsi(closes, 14)
    sma20 = calc_sma(closes, 20)
    bb = calc_bollinger_bands(closes, 20)

    # Price changes over different periods
    change_1h = (closes[-1] / closes[-2] - 1) if len(closes) >= 2 else 0
    change_4h = (closes[-1] / closes[-5] - 1) if len(closes) >= 5 else 0
    change_24h = (closes[-1] / closes[0] - 1) if len(closes) >= 24 else (closes[-1] / closes[0] - 1)

    # Volume analysis
    avg_volume = sum(volumes) / len(volumes) if volumes else 0
    current_volume = volumes[-1] if volumes else 0
    volume_above_avg = current_volume > avg_volume

    # Trend
    trend = calc_trend(highs, lows)

    return {
        "current_price": round(current_price, 4),
        "rsi_14": round(rsi, 2),
        "sma_20": round(sma20, 4),
        "price_vs_sma20": round((current_price / sma20 - 1) * 100, 3) if sma20 > 0 else 0,
        "bollinger": {
            "upper": round(bb["upper"], 4),
            "middle": round(bb["middle"], 4),
            "lower": round(bb["lower"], 4),
            "position": round(bb["position"], 3),
        },
        "change_1h_pct": round(change_1h * 100, 3),
        "change_4h_pct": round(change_4h * 100, 3),
        "change_24h_pct": round(change_24h * 100, 3),
        "current_volume": round(current_volume, 2),
        "avg_volume": round(avg_volume, 2),
        "volume_above_avg": volume_above_avg,
        "trend": trend,
        "high_24h": round(max(highs), 4),
        "low_24h": round(min(lows), 4),
    }


# ── Swing Trader ──────────────────────────────────────────────────────

class SwingTrader:
    """Aggressive crypto swing trader powered by Claude Sonnet."""

    def __init__(self):
        self.alpaca = AlpacaClient()
        self.crypto_data = CryptoHistoricalDataClient()
        self.llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.positions: dict[str, SwingPosition] = {}  # symbol -> SwingPosition
        self.stats = SwingStats()
        self._running = False
        logger.info("SwingTrader initialized | symbols={} | interval={}s", SWING_SYMBOLS, LOOP_INTERVAL_SEC)

    # ── Data Fetching ─────────────────────────────────────────

    def fetch_candles(self, symbol: str) -> dict | None:
        """Fetch 24 hourly candles for a symbol and return indicator analysis."""
        try:
            start = datetime.now(timezone.utc) - timedelta(hours=25)
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Hour,
                start=start,
                limit=24,
            )
            bars = self.crypto_data.get_crypto_bars(request)
            df = bars.df.reset_index()

            if "symbol" in df.columns:
                df = df[df["symbol"] == symbol].copy()

            df = df.rename(columns={
                "open": "open", "high": "high", "low": "low",
                "close": "close", "volume": "volume",
            })
            df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

            if len(df) < 5:
                logger.warning("Insufficient bars for {}: only {} rows", symbol, len(df))
                return None

            indicators = analyze_symbol(df)
            indicators["symbol"] = symbol
            return indicators

        except Exception as e:
            logger.error("Failed to fetch candles for {}: {}", symbol, e)
            return None

    def fetch_all_candles(self) -> list[dict]:
        """Fetch and analyze candles for all symbols."""
        results = []
        for symbol in SWING_SYMBOLS:
            data = self.fetch_candles(symbol)
            if data and "error" not in data:
                results.append(data)
        return results

    # ── LLM Calls ─────────────────────────────────────────────

    def _parse_llm_json(self, text: str) -> list[dict]:
        """Parse JSON from LLM response, handling code fences."""
        text = text.strip()
        if "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)

    def ask_sonnet_for_trades(self, market_data: list[dict]) -> list[dict]:
        """Send market data to Claude Sonnet and get trade recommendations."""
        try:
            account = self.alpaca.get_account()
            equity = account["equity"]

            # Build context about current positions
            pos_text = "No open swing positions."
            if self.positions:
                pos_lines = []
                for sym, pos in self.positions.items():
                    pos_lines.append(
                        f"  {sym}: {pos.side} | entry=${pos.entry_price:,.2f} | "
                        f"TP=${pos.target_price:,.2f} | SL=${pos.stop_price:,.2f} | "
                        f"held {pos.hold_hours:.1f}h | conviction={pos.conviction:.2f}"
                    )
                pos_text = "Current positions:\n" + "\n".join(pos_lines)

            prompt = (
                f"ACCOUNT: equity=${equity:,.2f}\n"
                f"{pos_text}\n\n"
                f"MARKET DATA (1h candles, last 24 bars):\n"
                f"{json.dumps(market_data, indent=2)}\n\n"
                f"Pick the best 1-2 NEW trades (avoid symbols we already hold). "
                f"Be aggressive — we're paper trading."
            )

            resp = self.llm.messages.create(
                model=SONNET_MODEL,
                max_tokens=600,
                system=SWING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            trades = self._parse_llm_json(text)

            logger.info("Sonnet recommended {} trade(s)", len(trades))
            for t in trades:
                logger.info(
                    "  -> {} {} | conviction={} | TP={}% SL={}% | size={}% | {}",
                    t.get("side", "?").upper(),
                    t.get("symbol", "?"),
                    t.get("conviction", 0),
                    round(t.get("target_pct", 0) * 100, 1),
                    round(t.get("stop_pct", 0) * 100, 1),
                    round(t.get("size_pct", 0) * 100, 0),
                    t.get("reasoning", ""),
                )
            return trades

        except Exception as e:
            logger.error("Sonnet trade analysis failed: {}", e)
            return []

    def ask_sonnet_to_manage(self, market_data: list[dict]) -> list[dict]:
        """Ask Sonnet to manage existing positions."""
        if not self.positions:
            return []

        try:
            pos_details = []
            for sym, pos in self.positions.items():
                # Find current data for this symbol
                sym_data = next((d for d in market_data if d["symbol"] == sym), None)
                current_price = sym_data["current_price"] if sym_data else pos.entry_price

                if pos.side == "buy":
                    pnl_pct = (current_price / pos.entry_price - 1) * 100
                else:
                    pnl_pct = (pos.entry_price / current_price - 1) * 100

                pos_details.append({
                    "symbol": sym,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "current_price": current_price,
                    "pnl_pct": round(pnl_pct, 3),
                    "target_pct": pos.target_pct * 100,
                    "stop_pct": pos.stop_pct * 100,
                    "hold_hours": round(pos.hold_hours, 2),
                    "conviction": pos.conviction,
                })

            prompt = (
                f"OPEN POSITIONS:\n{json.dumps(pos_details, indent=2)}\n\n"
                f"FRESH MARKET DATA:\n{json.dumps(market_data, indent=2)}\n\n"
                f"For each position: HOLD, ADD, or EXIT?"
            )

            resp = self.llm.messages.create(
                model=SONNET_MODEL,
                max_tokens=400,
                system=MANAGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            decisions = self._parse_llm_json(text)

            for d in decisions:
                logger.info(
                    "  Position {} -> {} | {}",
                    d.get("symbol", "?"),
                    d.get("action", "?").upper(),
                    d.get("reasoning", ""),
                )
            return decisions

        except Exception as e:
            logger.error("Sonnet position management failed: {}", e)
            return []

    # ── Trade Execution ───────────────────────────────────────

    def execute_trade(self, trade: dict) -> bool:
        """Execute a single trade recommendation."""
        symbol = trade.get("symbol", "")
        side = trade.get("side", "buy")
        conviction = trade.get("conviction", 0)
        target_pct = trade.get("target_pct", 0.04)
        stop_pct = trade.get("stop_pct", 0.025)
        size_pct = trade.get("size_pct", 0.30)
        reasoning = trade.get("reasoning", "")

        # Validate
        if symbol not in SWING_SYMBOLS:
            logger.warning("Invalid symbol from LLM: {}", symbol)
            return False

        if conviction < MIN_CONVICTION:
            logger.info("Skipping {} — conviction {:.2f} below threshold {}", symbol, conviction, MIN_CONVICTION)
            return False

        if symbol in self.positions:
            logger.info("Already in position for {} — skipping", symbol)
            return False

        try:
            account = self.alpaca.get_account()
            equity = account["equity"]
            notional = equity * min(size_pct, 0.50)  # cap at 50%

            if notional < 1.0:
                logger.warning("Notional too small for {}: ${:.2f}", symbol, notional)
                return False

            # Get current price for tracking
            current_price = self.alpaca.get_latest_price(symbol, "crypto")

            # Place the order
            order = self.alpaca.place_market_order(
                symbol=symbol,
                notional=notional,
                side=side,
            )

            # Track the position
            self.positions[symbol] = SwingPosition(
                symbol=symbol,
                side=side,
                entry_price=current_price,
                notional=notional,
                target_pct=target_pct,
                stop_pct=stop_pct,
                conviction=conviction,
                reasoning=reasoning,
            )

            logger.info(
                "OPENED {} {} | ${:,.2f} notional @ ${:,.2f} | "
                "TP=${:,.2f} SL=${:,.2f} | conviction={:.2f} | order={}",
                side.upper(), symbol, notional, current_price,
                self.positions[symbol].target_price,
                self.positions[symbol].stop_price,
                conviction, order.get("order_id", "?"),
            )
            return True

        except Exception as e:
            logger.error("Failed to execute trade for {}: {}", symbol, e)
            return False

    def close_swing_position(self, symbol: str, reason: str) -> bool:
        """Close a swing position and record stats."""
        if symbol not in self.positions:
            logger.warning("No tracked position for {} to close", symbol)
            return False

        pos = self.positions[symbol]
        alpaca_symbol = pos.alpaca_symbol()

        try:
            # Get current price for P&L calculation
            current_price = self.alpaca.get_latest_price(symbol, "crypto")

            if pos.side == "buy":
                pnl_pct = (current_price / pos.entry_price - 1)
            else:
                pnl_pct = (pos.entry_price / current_price - 1)

            pnl_dollar = pos.notional * pnl_pct

            # Close on Alpaca
            self.alpaca.close_position(alpaca_symbol)

            # Record stats
            self.stats.record_trade(pnl_dollar, pos.notional)

            logger.info(
                "CLOSED {} {} | entry=${:,.2f} exit=${:,.2f} | "
                "PnL=${:,.2f} ({:+.2%}) | held {:.1f}h | reason: {}",
                pos.side.upper(), symbol, pos.entry_price, current_price,
                pnl_dollar, pnl_pct, pos.hold_hours, reason,
            )

            del self.positions[symbol]
            return True

        except Exception as e:
            logger.error("Failed to close position {}: {}", symbol, e)
            # Remove from tracking anyway to avoid stuck positions
            del self.positions[symbol]
            return False

    # ── Position Management ───────────────────────────────────

    def check_hard_limits(self, market_data: list[dict]) -> None:
        """Check TP, SL, and max hold time — exit immediately if hit."""
        symbols_to_close = []

        for symbol, pos in self.positions.items():
            sym_data = next((d for d in market_data if d["symbol"] == symbol), None)
            if not sym_data:
                continue

            current_price = sym_data["current_price"]

            if pos.side == "buy":
                pnl_pct = current_price / pos.entry_price - 1
            else:
                pnl_pct = pos.entry_price / current_price - 1

            # Take profit hit
            if pnl_pct >= pos.target_pct:
                symbols_to_close.append((symbol, f"TP hit ({pnl_pct:+.2%})"))
                continue

            # Stop loss hit
            if pnl_pct <= -pos.stop_pct:
                symbols_to_close.append((symbol, f"SL hit ({pnl_pct:+.2%})"))
                continue

            # Max hold time
            if pos.hold_hours >= MAX_HOLD_HOURS:
                symbols_to_close.append((symbol, f"Max hold time ({pos.hold_hours:.1f}h)"))
                continue

        for symbol, reason in symbols_to_close:
            self.close_swing_position(symbol, reason)

    def manage_positions(self, market_data: list[dict]) -> None:
        """Use Sonnet to decide on existing positions after hard limits checked."""
        if not self.positions:
            return

        decisions = self.ask_sonnet_to_manage(market_data)

        for decision in decisions:
            symbol = decision.get("symbol", "")
            action = decision.get("action", "hold").lower()
            reasoning = decision.get("reasoning", "")

            if symbol not in self.positions:
                continue

            if action == "exit":
                self.close_swing_position(symbol, f"Sonnet exit: {reasoning}")
            elif action == "add":
                # Add to position — place another order
                pos = self.positions[symbol]
                try:
                    account = self.alpaca.get_account()
                    add_notional = account["equity"] * 0.15  # add 15% equity
                    self.alpaca.place_market_order(
                        symbol=symbol,
                        notional=add_notional,
                        side=pos.side,
                    )
                    pos.notional += add_notional
                    logger.info("ADDED to {} | +${:,.2f} | total ${:,.2f}", symbol, add_notional, pos.notional)
                except Exception as e:
                    logger.error("Failed to add to {}: {}", symbol, e)
            # else: hold — do nothing

    # ── Main Loop ─────────────────────────────────────────────

    async def run(self) -> None:
        """Main swing trading loop — runs every 5 minutes."""
        self._running = True
        logger.info("SwingTrader starting main loop")
        logger.info("Symbols: {} | Interval: {}s | Max hold: {}h", SWING_SYMBOLS, LOOP_INTERVAL_SEC, MAX_HOLD_HOURS)

        cycle = 0
        while self._running:
            cycle += 1
            try:
                logger.info("--- Swing cycle #{} ---", cycle)

                # 1. Fetch market data
                market_data = self.fetch_all_candles()
                if not market_data:
                    logger.warning("No market data available, skipping cycle")
                    await asyncio.sleep(LOOP_INTERVAL_SEC)
                    continue

                logger.info("Fetched data for {} symbols", len(market_data))

                # 2. Check hard limits on existing positions (TP/SL/max hold)
                self.check_hard_limits(market_data)

                # 3. Manage existing positions with Sonnet
                self.manage_positions(market_data)

                # 4. Look for new trades (if we have capacity)
                open_count = len(self.positions)
                if open_count < 3:  # max 3 concurrent swing positions
                    trades = self.ask_sonnet_for_trades(market_data)
                    executed = 0
                    for trade in trades:
                        if self.execute_trade(trade):
                            executed += 1
                    if executed:
                        logger.info("Executed {} new trade(s)", executed)
                else:
                    logger.info("At max positions ({}/3), skipping new trade scan", open_count)

                # 5. Log stats
                logger.info(self.stats.summary())
                logger.info(
                    "Open positions: {} | {}",
                    len(self.positions),
                    ", ".join(f"{s}({p.side})" for s, p in self.positions.items()) or "none",
                )

            except Exception as e:
                logger.exception("Swing cycle #{} failed: {}", cycle, e)

            # Wait for next cycle
            if self._running:
                await asyncio.sleep(LOOP_INTERVAL_SEC)

        logger.info("SwingTrader loop stopped")

    def stop(self) -> None:
        """Signal the trader to stop gracefully."""
        logger.info("SwingTrader stop requested")
        self._running = False

    def close_all(self) -> None:
        """Close all tracked swing positions."""
        logger.info("Closing all {} swing positions", len(self.positions))
        for symbol in list(self.positions.keys()):
            self.close_swing_position(symbol, "Shutdown — closing all")
        logger.info("Final stats: {}", self.stats.summary())
