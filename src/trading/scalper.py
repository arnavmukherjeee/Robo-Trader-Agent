"""BEAST MODE crypto scalper — maximum aggression, maximum speed.

Full send configuration:
- 40% position size per symbol (can have multiple positions)
- 5 symbols: BTC, ETH, SOL, DOGE, AVAX
- 1 second cooldown between trades
- Low thresholds — trade on any signal
- TP: 1.0% | SL: 0.5% (2:1 R:R)
- LLM confirms but with aggressive bias
- No VWAP filter — just send it
"""

import time
from dataclasses import dataclass, field
from collections import defaultdict

from loguru import logger

from config.settings import settings
from src.trading.alpaca_client import AlpacaClient, AssetType
from src.trading.crypto_stream import CryptoStream, TickData, ScalpContext
from src.strategies.scalp_signals import (
    SCALP_SIGNALS,
    ScalpSignal,
    ScalpDirection,
)
from src.llm.scalp_analyst import ScalpAnalyst


@dataclass
class ScalpPosition:
    symbol: str
    direction: ScalpDirection
    entry_price: float
    qty: float
    notional: float
    entry_time_ms: float
    stop_loss: float
    take_profit: float
    signals_used: list[str]
    max_price: float = 0.0
    min_price: float = float("inf")
    highest_pnl_pct: float = 0.0


@dataclass
class ScalpStats:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    biggest_win: float = 0.0
    biggest_loss: float = 0.0
    avg_hold_time_ms: float = 0.0
    _hold_times: list = field(default_factory=list)
    trades_rejected: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades * 100 if self.total_trades > 0 else 0.0

    def record_trade(self, pnl: float, hold_time_ms: float):
        self.total_trades += 1
        self.total_pnl += pnl
        self._hold_times.append(hold_time_ms)
        self.avg_hold_time_ms = sum(self._hold_times) / len(self._hold_times)
        if pnl > 0:
            self.wins += 1
            self.biggest_win = max(self.biggest_win, pnl)
        else:
            self.losses += 1
            self.biggest_loss = min(self.biggest_loss, pnl)

    def summary(self) -> str:
        return (
            f"Trades: {self.total_trades} | "
            f"W/L: {self.wins}/{self.losses} ({self.win_rate:.0f}%) | "
            f"PnL: ${self.total_pnl:+,.2f} | "
            f"Avg Hold: {self.avg_hold_time_ms / 1000:.1f}s | "
            f"Best: ${self.biggest_win:+,.2f} Worst: ${self.biggest_loss:+,.2f} | "
            f"Rejected: {self.trades_rejected}"
        )


class CryptoScalper:
    """BEAST MODE — trades fast, trades big, trades often."""

    def __init__(self):
        self.alpaca = AlpacaClient()
        self.positions: dict[str, ScalpPosition] = {}
        self.last_trade_ms: dict[str, float] = defaultdict(float)
        self.stats = ScalpStats()

        # ALL liquid crypto pairs
        self.symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD"]
        self._running = False

        # SNIPER MODE — fewer trades, bigger wins, Sonnet picks only the best
        self.tp_pct = 0.03       # 3% take profit — big wins
        self.sl_pct = 0.004      # 0.4% stop loss — cut fast
        self.cooldown_ms = 5_000  # 5 second cooldown — no rushing
        self.position_size_pct = 0.25  # 25% per trade — big when confident
        self.min_signals = 1     # signal triggers LLM, LLM decides
        self.max_spread_pct = 0.0015  # 0.15% max spread — need clean entry
        self.min_momentum = 0.0003    # 0.03% min momentum
        self.min_tick_velocity = 0.5  # decent liquidity
        self.min_ticks = 15      # need good price history for LLM

        # Cache account
        self._cached_equity = 0.0
        self._cached_cash = 0.0
        self._last_account_refresh = 0.0

        # No LLM — pure technical filters, zero API cost
        self.stream = CryptoStream(on_tick_callback=self._on_tick)

        logger.info(
            f"🔥 BEAST MODE SCALPER | TP: {self.tp_pct:.2%} | SL: {self.sl_pct:.2%} | "
            f"Size: {self.position_size_pct:.0%} | Cooldown: {self.cooldown_ms/1000:.0f}s | "
            f"Max Spread: {self.max_spread_pct:.2%} | Min Momentum: {self.min_momentum:.2%} | "
            f"Symbols: {', '.join(self.symbols)}"
        )

    def _refresh_account(self):
        now = time.time()
        if now - self._last_account_refresh < 2:
            return
        try:
            account = self.alpaca.get_account()
            self._cached_equity = account["equity"]
            self._cached_cash = account["cash"]
            self._last_account_refresh = now
        except Exception:
            pass

    async def _on_tick(self, tick: TickData, ctx: ScalpContext):
        symbol = tick.symbol
        now_ms = time.time() * 1000

        # 1. Manage existing positions
        if symbol in self.positions:
            self._check_exit(symbol, tick.price, now_ms)
            # Don't return — can still enter other symbols

        # 2. Already in this symbol? skip (one position per symbol at a time)
        if symbol in self.positions:
            return

        # 3. Cooldown
        if now_ms - self.last_trade_ms[symbol] < self.cooldown_ms:
            return

        # 3. Need some data
        if len(ctx.ticks) < self.min_ticks:
            return

        # 4. Light pre-filters
        if ctx.last_price > 0 and ctx.spread > 0:
            spread_pct = ctx.spread / ctx.last_price
            if spread_pct > self.max_spread_pct:
                return

        if ctx.tick_velocity < self.min_tick_velocity:
            return

        if abs(ctx.price_momentum) < self.min_momentum:
            return

        # 5. Evaluate signals — any signal is enough
        signals = self._evaluate_signals(ctx)
        if not signals:
            return

        # 6. Any long signal = go (no consensus needed in beast mode)
        longs = [s for s in signals if s.direction == ScalpDirection.LONG]
        shorts = [s for s in signals if s.direction == ScalpDirection.SHORT]

        if longs:
            # Pure technical — need 2+ signals agreeing for quality filter
            if len(longs) >= 2:
                avg_strength = sum(s.strength for s in longs) / len(longs)
                if avg_strength > 0.5:
                    # VWAP confirmation: only buy at or below VWAP
                    if ctx.vwap_1m > 0 and ctx.last_price > ctx.vwap_1m * 1.001:
                        self.stats.trades_rejected += 1
                        return
                    await self._enter(symbol, tick.price, "buy", longs, now_ms, 1.0)
                else:
                    self.stats.trades_rejected += 1
            else:
                self.stats.trades_rejected += 1

    def _evaluate_signals(self, ctx: ScalpContext) -> list[ScalpSignal]:
        signals = []
        for signal_fn in SCALP_SIGNALS:
            try:
                sig = signal_fn(ctx)
                if sig is not None:
                    signals.append(sig)
            except Exception:
                pass
        return signals

    async def _enter(self, symbol: str, price: float, side: str, signals: list[ScalpSignal], now_ms: float, size_mult: float = 1.0):
        # Force fresh account data before big trades
        self._last_account_refresh = 0
        self._refresh_account()

        notional = round(self._cached_equity * self.position_size_pct * size_mult, 2)
        # Use all available cash
        max_notional = self._cached_cash * 0.98
        if notional > max_notional:
            notional = round(max_notional, 2)
        if notional < 50:
            return

        if side == "buy":
            tp = price * (1 + self.tp_pct)
            sl = price * (1 - self.sl_pct)
        else:
            tp = price * (1 - self.tp_pct)
            sl = price * (1 + self.sl_pct)

        try:
            order = self.alpaca.place_market_order(symbol=symbol, notional=notional, side=side)

            self.positions[symbol] = ScalpPosition(
                symbol=symbol,
                direction=ScalpDirection.LONG if side == "buy" else ScalpDirection.SHORT,
                entry_price=price,
                qty=0,
                notional=notional,
                entry_time_ms=now_ms,
                stop_loss=sl,
                take_profit=tp,
                signals_used=[s.name for s in signals],
                max_price=price,
                min_price=price,
            )
            self.last_trade_ms[symbol] = now_ms
            self._cached_cash -= notional

            spread_pct = (self.stream.get_context(symbol).spread / price * 100) if price > 0 else 0
            reasons = " + ".join(s.name for s in signals)
            logger.info(
                f"🔥 ENTRY: ${notional:,.0f} {side.upper()} {symbol} @ ${price:,.2f} | "
                f"TP=${tp:,.2f} SL=${sl:,.2f} | spread={spread_pct:.3f}% | "
                f"momentum={self.stream.get_context(symbol).price_momentum:+.4%} | {reasons}"
            )
        except Exception as e:
            logger.error(f"Entry failed {symbol}: {e}")

    def _check_exit(self, symbol: str, price: float, now_ms: float):
        pos = self.positions[symbol]
        pos.max_price = max(pos.max_price, price)

        if pos.direction == ScalpDirection.LONG:
            pnl_pct = (price - pos.entry_price) / pos.entry_price
        else:
            pnl_pct = (pos.entry_price - price) / pos.entry_price

        pos.highest_pnl_pct = max(pos.highest_pnl_pct, pnl_pct)

        should_exit = False
        reason = ""

        # 1. HARD STOP — cut losers FAST at 0.3% (small loss)
        if pnl_pct <= -self.sl_pct:
            should_exit = True
            reason = f"💀 CUT {pnl_pct:+.3%}"

        # 2. Take profit — 2.5% (big win)
        elif pnl_pct >= self.tp_pct:
            should_exit = True
            reason = f"🎯 TP {pnl_pct:+.3%}"

        # 3. Trailing stop — once we're up 0.5%, protect with trailing
        #    Keep at least 60% of peak profit, never let a winner turn into a loser
        elif pos.highest_pnl_pct > 0.005:
            min_keep = pos.highest_pnl_pct * 0.6
            if pnl_pct < min_keep:
                should_exit = True
                reason = f"🔒 TRAIL {pnl_pct:+.3%} (peak {pos.highest_pnl_pct:+.3%})"

        # 4. Break-even protection — after 1min in profit, lock it in if it's fading
        elif pos.highest_pnl_pct > 0.002 and pnl_pct < 0.0005 and now_ms - pos.entry_time_ms > 60_000:
            should_exit = True
            reason = f"🛡️ PROTECT {pnl_pct:+.3%} (was {pos.highest_pnl_pct:+.3%})"

        # 5. Max hold 15 minutes — exit only if not deeply in profit
        elif now_ms - pos.entry_time_ms > 900_000:
            should_exit = True
            reason = f"MAX-TIME {pnl_pct:+.3%}"

        if should_exit:
            self._exit(symbol, price, now_ms, reason)

    def _exit(self, symbol: str, price: float, now_ms: float, reason: str):
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return

        try:
            self.alpaca.close_position(symbol.replace("/", ""))
            hold_ms = now_ms - pos.entry_time_ms

            if pos.direction == ScalpDirection.LONG:
                pnl = (price - pos.entry_price) / pos.entry_price * pos.notional
            else:
                pnl = (pos.entry_price - price) / pos.entry_price * pos.notional

            self.stats.record_trade(pnl, hold_ms)
            self._cached_cash += pos.notional + pnl

            icon = "✅" if pnl > 0 else "❌"
            logger.info(
                f"{icon} EXIT {symbol} | ${pnl:+,.2f} | {hold_ms/1000:.1f}s | {reason} || "
                f"{self.stats.summary()}"
            )
        except Exception as e:
            if "position not found" in str(e):
                # Position already closed externally — just record it
                logger.warning(f"Position {symbol} already closed externally, clearing")
            else:
                logger.error(f"Exit failed {symbol}: {e}")
                self.positions[symbol] = pos  # only retry on real errors

    def run(self):
        self._running = True
        logger.info("=" * 70)
        logger.info("  🔥🔥🔥 BEAST MODE CRYPTO SCALPER 🔥🔥🔥")
        logger.info(f"  TP: {self.tp_pct:.2%} | SL: {self.sl_pct:.2%} | Size: {self.position_size_pct:.0%}")
        logger.info(f"  Max Spread: {self.max_spread_pct:.2%} | Min Momentum: {self.min_momentum:.2%}")
        logger.info(f"  Cooldown: {self.cooldown_ms/1000:.0f}s | Min Signals: {self.min_signals}")
        logger.info(f"  Symbols: {', '.join(self.symbols)}")
        logger.info("  RISK: HIGH | MODE: DIVERSIFIED BEAST (20% x 5 symbols)")
        logger.info("=" * 70)

        account = self.alpaca.get_account()
        self._cached_equity = account["equity"]
        self._cached_cash = account["cash"]
        self._last_account_refresh = time.time()
        logger.info(f"Account: ${account['equity']:,.2f} equity | ${account['cash']:,.2f} cash")

        self.stream.start(self.symbols)

    def stop(self):
        self._running = False
        for symbol in list(self.positions.keys()):
            try:
                self.alpaca.close_position(symbol.replace("/", ""))
            except Exception:
                pass
        self.stream.stop()
        logger.info(f"Stopped. {self.stats.summary()}")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "positions": {
                sym: {
                    "entry_price": pos.entry_price,
                    "notional": pos.notional,
                    "hold_time_ms": time.time() * 1000 - pos.entry_time_ms,
                    "highest_pnl_pct": pos.highest_pnl_pct,
                }
                for sym, pos in self.positions.items()
            },
            "stats": {
                "total_trades": self.stats.total_trades,
                "win_rate": self.stats.win_rate,
                "total_pnl": self.stats.total_pnl,
                "avg_hold_ms": self.stats.avg_hold_time_ms,
                "rejected": self.stats.trades_rejected,
            },
        }
