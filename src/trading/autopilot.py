"""Autopilot — fully autonomous trading engine.

Runs a continuous loop with zero human interaction:
  1. RESEARCH   (every 10s)   — backtest strategies across all symbols, pick top 5
  2. SIGNAL     (every 5s)    — evaluate top strategies on live data, execute trades
  3. MANAGE     (every 2s)    — monitor positions, enforce TP/SL/time exits
  4. REPORT     (continuous)  — maintain in-memory state for the dashboard
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from loguru import logger

from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config.settings import settings
from src.backtest.backtester import Backtester, BacktestResult
from src.strategies.engine import Strategy, StrategyEngine, StrategyResult
from src.strategies.signals import Direction
from src.trading.alpaca_client import AlpacaClient, AssetType, classify_asset


# ── Symbols ────────────────────────────────────────────────────────────────────

CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]
EQUITY_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META"]
ALL_SYMBOLS = CRYPTO_SYMBOLS + EQUITY_SYMBOLS

# ── Timing constants (seconds) ─────────────────────────────────────────────────

RESEARCH_INTERVAL = 10             # 10 seconds
SIGNAL_INTERVAL = 5                # 5 seconds
MANAGE_INTERVAL = 2                # 2 seconds

# ── Position management thresholds ─────────────────────────────────────────────

TAKE_PROFIT_PCT = 0.02           # +2 %
STOP_LOSS_PCT = 0.01             # -1 %
TIME_PROFIT_HOURS = 4.0          # close if >4h and profitable
FORCE_EXIT_HOURS = 6.0           # close regardless after 6h

# ── Sizing ─────────────────────────────────────────────────────────────────────

POSITION_SIZE_PCT = 0.15         # 15 % of equity per trade
MAX_POSITIONS = 5

# ── Research parameters ────────────────────────────────────────────────────────

STRATEGY_LIMIT = 200             # first N strategies to consider
STRATEGY_SAMPLE = 30             # sample this many for backtesting
BACKTEST_DAYS = 365              # 1 year of daily bars for backtesting
TOP_N_STRATEGIES = 5             # keep best N across all symbols


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class RankedStrategy:
    """A strategy paired with its backtest stats and target symbol."""

    strategy: Strategy
    symbol: str
    asset_type: AssetType
    sharpe: float
    total_return_pct: float
    win_rate: float
    total_trades: int
    max_drawdown_pct: float

    def label(self) -> str:
        return (
            f"{self.strategy.name} on {self.symbol} "
            f"(Sharpe {self.sharpe:.1f}, Return {self.total_return_pct:+.1f}%, "
            f"WR {self.win_rate:.0f}%)"
        )


@dataclass
class ManagedPosition:
    """An open position tracked by the autopilot."""

    symbol: str
    asset_type: AssetType
    side: str                       # "buy" or "sell"
    strategy_name: str
    entry_price: float
    notional: float
    entry_time: datetime
    order_id: str

    @property
    def age_hours(self) -> float:
        delta = datetime.now(timezone.utc) - self.entry_time
        return delta.total_seconds() / 3600


@dataclass
class TradeRecord:
    """Completed trade for statistics."""

    symbol: str
    strategy_name: str
    side: str
    pnl: float
    pnl_pct: float
    hold_hours: float
    exit_reason: str
    closed_at: datetime


@dataclass
class AutopilotStats:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades * 100 if self.total_trades else 0.0

    def record(self, pnl: float):
        self.total_trades += 1
        self.total_pnl += pnl
        if pnl > 0:
            self.wins += 1
            self.best_trade = max(self.best_trade, pnl)
        else:
            self.losses += 1
            self.worst_trade = min(self.worst_trade, pnl)


# ── Autopilot ──────────────────────────────────────────────────────────────────

class Autopilot:
    """Fully autonomous trading engine.  Call ``run()`` to block forever."""

    def __init__(self) -> None:
        self.alpaca = AlpacaClient()
        self.engine = StrategyEngine()
        self.backtester = Backtester(
            initial_capital=100_000,
            position_size_pct=POSITION_SIZE_PCT,
            stop_loss_pct=STOP_LOSS_PCT,
            take_profit_pct=TAKE_PROFIT_PCT,
        )

        # State
        self.top_strategies: list[RankedStrategy] = []
        self.positions: dict[str, ManagedPosition] = {}   # symbol -> position
        self.stats = AutopilotStats()
        self.trade_history: list[TradeRecord] = []

        # Dashboard state
        self._phase: str = "IDLE"
        self._active_signals: list[dict] = []
        self._research_log: deque[str] = deque(maxlen=50)
        self._last_research: datetime | None = None
        self._symbols_scanned: int = 0
        self._strategies_tested: int = 0

        # Timing
        self._last_research_ts: float = 0.0
        self._last_signal_ts: float = 0.0
        self._last_manage_ts: float = 0.0

        # Stop signal
        self._stop_event = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────

    def run(self) -> None:
        """Blocking main loop.  Runs until ``stop()`` is called."""
        logger.info("=" * 70)
        logger.info("  AUTOPILOT — Fully Autonomous Trading Engine")
        logger.info(f"  Symbols: {', '.join(ALL_SYMBOLS)}")
        logger.info(f"  Position size: {POSITION_SIZE_PCT:.0%} | Max positions: {MAX_POSITIONS}")
        logger.info(f"  TP: {TAKE_PROFIT_PCT:.1%} | SL: {STOP_LOSS_PCT:.1%}")
        logger.info(f"  Research every {RESEARCH_INTERVAL}s | Signals every {SIGNAL_INTERVAL}s | Manage every {MANAGE_INTERVAL}s")
        logger.info("=" * 70)

        account = self.alpaca.get_account()
        logger.info(
            f"Account: ${account['equity']:,.2f} equity | "
            f"${account['cash']:,.2f} cash | "
            f"${account['buying_power']:,.2f} buying power"
        )

        while not self._stop_event.is_set():
            try:
                now = time.monotonic()

                # Phase 1 — Research (every 30 min)
                if now - self._last_research_ts >= RESEARCH_INTERVAL:
                    self._phase_research()
                    self._last_research_ts = time.monotonic()

                # Phase 2 — Signal check (every 5 min)
                if (
                    self.top_strategies
                    and now - self._last_signal_ts >= SIGNAL_INTERVAL
                ):
                    self._phase_signal()
                    self._last_signal_ts = time.monotonic()

                # Phase 3 — Position management (every 1 min)
                if now - self._last_manage_ts >= MANAGE_INTERVAL:
                    self._phase_manage()
                    self._last_manage_ts = time.monotonic()

                # Idle between iterations
                self._phase = "IDLE"
                self._stop_event.wait(timeout=10)

            except Exception as exc:
                logger.exception(f"Main loop error: {exc}")
                self._stop_event.wait(timeout=30)

    def stop(self) -> None:
        """Gracefully stop: close all managed positions, then exit."""
        logger.info("Autopilot stopping — closing all managed positions...")
        self._stop_event.set()

        for symbol in list(self.positions.keys()):
            try:
                self.alpaca.close_position(
                    symbol.replace("/", "") if "/" in symbol else symbol
                )
                logger.info(f"Closed position: {symbol}")
            except Exception as exc:
                logger.warning(f"Failed to close {symbol} on shutdown: {exc}")

        self.positions.clear()
        logger.info(
            f"Autopilot stopped. "
            f"Trades: {self.stats.total_trades} | "
            f"PnL: ${self.stats.total_pnl:+,.2f} | "
            f"WR: {self.stats.win_rate:.0f}%"
        )

    def get_state(self) -> dict:
        """Return full state dict for the dashboard."""
        return {
            "phase": self._phase,
            "top_strategies": [
                {
                    "name": rs.strategy.name,
                    "symbol": rs.symbol,
                    "sharpe": rs.sharpe,
                    "return_pct": rs.total_return_pct,
                    "win_rate": rs.win_rate,
                    "trades": rs.total_trades,
                    "max_dd": rs.max_drawdown_pct,
                }
                for rs in self.top_strategies
            ],
            "active_signals": list(self._active_signals),
            "positions": {
                sym: {
                    "side": pos.side,
                    "strategy": pos.strategy_name,
                    "entry_price": pos.entry_price,
                    "notional": pos.notional,
                    "entry_time": pos.entry_time.isoformat(),
                    "age_hours": round(pos.age_hours, 2),
                }
                for sym, pos in self.positions.items()
            },
            "research_log": list(self._research_log),
            "stats": {
                "total_trades": self.stats.total_trades,
                "wins": self.stats.wins,
                "losses": self.stats.losses,
                "total_pnl": round(self.stats.total_pnl, 2),
                "best_trade": round(self.stats.best_trade, 2),
                "worst_trade": round(self.stats.worst_trade, 2),
                "win_rate": round(self.stats.win_rate, 1),
            },
            "last_research": (
                self._last_research.isoformat() if self._last_research else None
            ),
            "symbols_scanned": self._symbols_scanned,
            "strategies_tested": self._strategies_tested,
        }

    # ── Phase 1: Research ──────────────────────────────────────────────────

    def _phase_research(self) -> None:
        self._phase = "RESEARCHING"
        logger.info("--- RESEARCH PHASE START ---")

        all_strategies = self.engine.generate_strategies()
        # Deterministically limit, then random sample
        pool = all_strategies[:STRATEGY_LIMIT]
        sample = random.sample(pool, min(STRATEGY_SAMPLE, len(pool)))

        all_results: list[RankedStrategy] = []
        total_tested = 0

        for symbol in ALL_SYMBOLS:
            asset_type = classify_asset(symbol)
            self._research_log.append(f"[{datetime.now(timezone.utc):%H:%M:%S}] Scanning {symbol}...")
            try:
                df = self._fetch_daily_bars(symbol, asset_type, days=BACKTEST_DAYS)
            except Exception as exc:
                logger.warning(f"RESEARCH: Failed to fetch bars for {symbol}: {exc}")
                self._research_log.append(f"[{datetime.now(timezone.utc):%H:%M:%S}] ❌ {symbol}: fetch failed — {exc}")
                continue

            if df.empty or len(df) < 50:
                logger.warning(f"RESEARCH: Insufficient data for {symbol} ({len(df)} bars)")
                self._research_log.append(f"[{datetime.now(timezone.utc):%H:%M:%S}] ⚠️ {symbol}: only {len(df)} bars, need 50+")
                continue

            self._research_log.append(f"[{datetime.now(timezone.utc):%H:%M:%S}] 📊 {symbol}: {len(df)} bars loaded, testing {len(sample)} strategies...")
            found_for_symbol = 0
            for strategy in sample:
                if self._stop_event.is_set():
                    return
                try:
                    result: BacktestResult = self.backtester.run(strategy, df, symbol)
                    total_tested += 1

                    # Keep any strategy that traded and had positive return
                    if result.total_trades >= 2 and result.total_return_pct > -5:
                        all_results.append(
                            RankedStrategy(
                                strategy=strategy,
                                symbol=symbol,
                                asset_type=asset_type,
                                sharpe=result.sharpe_ratio,
                                total_return_pct=result.total_return_pct,
                                win_rate=result.win_rate,
                                total_trades=result.total_trades,
                                max_drawdown_pct=result.max_drawdown_pct,
                            )
                        )
                        found_for_symbol += 1
                except Exception as exc:
                    logger.debug(f"Backtest error {strategy.name}/{symbol}: {exc}")
            if found_for_symbol:
                self._research_log.append(f"[{datetime.now(timezone.utc):%H:%M:%S}] ✅ {symbol}: {found_for_symbol} viable strategies found")

        # Rank by Sharpe ratio and keep top N
        all_results.sort(key=lambda r: r.sharpe, reverse=True)
        self.top_strategies = all_results[:TOP_N_STRATEGIES]

        self._last_research = datetime.now(timezone.utc)
        self._symbols_scanned = len(ALL_SYMBOLS)
        self._strategies_tested = total_tested

        if self.top_strategies:
            best = self.top_strategies[0]
            msg = (
                f"RESEARCH: Tested {total_tested} strategies across "
                f"{len(ALL_SYMBOLS)} symbols. "
                f"Top strategy: {best.label()}"
            )
        else:
            msg = (
                f"RESEARCH: Tested {total_tested} strategies across "
                f"{len(ALL_SYMBOLS)} symbols. No viable strategies found."
            )

        logger.info(msg)
        self._research_log.append(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}")

        for i, rs in enumerate(self.top_strategies, 1):
            logger.info(f"  #{i}: {rs.label()}")

        logger.info("--- RESEARCH PHASE END ---")

    # ── Phase 2: Signal check ──────────────────────────────────────────────

    def _phase_signal(self) -> None:
        self._phase = "SCANNING"
        self._active_signals.clear()

        for ranked in self.top_strategies:
            if self._stop_event.is_set():
                return

            symbol = ranked.symbol
            asset_type = ranked.asset_type

            # Skip if we already hold this symbol
            if symbol in self.positions:
                continue

            # Skip if we are at max positions
            if len(self.positions) >= MAX_POSITIONS:
                break

            # For equities, check market hours
            if asset_type == AssetType.EQUITY and not self._is_market_open():
                continue

            try:
                df = self._fetch_intraday_bars(symbol, asset_type)
            except Exception as exc:
                logger.warning(f"SIGNAL: Failed to fetch intraday for {symbol}: {exc}")
                continue

            if df.empty or len(df) < 20:
                continue

            try:
                result: StrategyResult = self.engine.evaluate(ranked.strategy, df)
            except Exception as exc:
                logger.debug(f"SIGNAL: Evaluate error {symbol}: {exc}")
                continue

            if result.direction == Direction.NEUTRAL or result.confidence <= 0.5:
                continue

            side = "buy" if result.direction == Direction.LONG else "sell"
            sig_info = {
                "symbol": symbol,
                "strategy": ranked.strategy.name,
                "direction": side,
                "confidence": round(result.confidence, 3),
                "reasons": result.reasons,
                "time": datetime.now(timezone.utc).isoformat(),
            }
            self._active_signals.append(sig_info)

            log_msg = (
                f"SIGNAL: {ranked.strategy.name} fired {side.upper()} on {symbol} "
                f"(confidence {result.confidence:.2f})"
            )
            logger.info(log_msg)
            self._research_log.append(
                f"[{datetime.now(timezone.utc):%H:%M:%S}] {log_msg}"
            )

            # Execute
            self._execute_trade(symbol, asset_type, side, ranked.strategy.name)

    # ── Phase 3: Position management ───────────────────────────────────────

    def _phase_manage(self) -> None:
        self._phase = "MANAGING"

        if not self.positions:
            return

        # Fetch live positions from Alpaca to get current prices
        try:
            live_positions = {p["symbol"]: p for p in self.alpaca.get_positions()}
        except Exception as exc:
            logger.warning(f"MANAGE: Failed to fetch positions: {exc}")
            return

        for symbol in list(self.positions.keys()):
            managed = self.positions[symbol]
            # Alpaca stores crypto without the slash
            alpaca_symbol = symbol.replace("/", "") if "/" in symbol else symbol

            live = live_positions.get(alpaca_symbol)
            if live is None:
                # Position was closed externally
                logger.warning(f"MANAGE: {symbol} no longer in Alpaca positions, removing")
                self.positions.pop(symbol, None)
                continue

            current_price = live["current_price"]
            entry_price = managed.entry_price
            pnl_pct = (current_price - entry_price) / entry_price
            if managed.side == "sell":
                pnl_pct = -pnl_pct

            pnl_dollar = float(live["unrealized_pl"])
            age_h = managed.age_hours

            exit_reason: str | None = None

            if pnl_pct >= TAKE_PROFIT_PCT:
                exit_reason = f"TP {pnl_pct:+.2%}"
            elif pnl_pct <= -STOP_LOSS_PCT:
                exit_reason = f"SL {pnl_pct:+.2%}"
            elif age_h > TIME_PROFIT_HOURS and pnl_pct > 0:
                exit_reason = f"TIME-PROFIT {pnl_pct:+.2%} after {age_h:.1f}h"
            elif age_h > FORCE_EXIT_HOURS:
                exit_reason = f"FORCE-EXIT {pnl_pct:+.2%} after {age_h:.1f}h"

            if exit_reason is not None:
                self._close_position(symbol, pnl_dollar, pnl_pct, age_h, exit_reason)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _execute_trade(
        self, symbol: str, asset_type: AssetType, side: str, strategy_name: str
    ) -> None:
        """Place a market order and register the managed position."""
        try:
            account = self.alpaca.get_account()
            equity = account["equity"]
            notional = round(equity * POSITION_SIZE_PCT, 2)

            if notional < 1:
                logger.warning(f"TRADE: Notional too small (${notional}), skipping {symbol}")
                return

            order = self.alpaca.place_market_order(
                symbol=symbol, notional=notional, side=side
            )

            # Fetch the latest price as entry estimate
            entry_price = self.alpaca.get_latest_price(symbol, asset_type)

            self.positions[symbol] = ManagedPosition(
                symbol=symbol,
                asset_type=asset_type,
                side=side,
                strategy_name=strategy_name,
                entry_price=entry_price,
                notional=notional,
                entry_time=datetime.now(timezone.utc),
                order_id=order["order_id"],
            )

            log_msg = (
                f"TRADE: {side.upper()} ${notional:,.0f} of {symbol} "
                f"@ ~${entry_price:,.2f} | Strategy: {strategy_name}"
            )
            logger.info(log_msg)
            self._research_log.append(
                f"[{datetime.now(timezone.utc):%H:%M:%S}] {log_msg}"
            )
        except Exception as exc:
            logger.error(f"TRADE: Failed to execute {side} {symbol}: {exc}")

    def _close_position(
        self,
        symbol: str,
        pnl_dollar: float,
        pnl_pct: float,
        age_h: float,
        reason: str,
    ) -> None:
        """Close a managed position and record the trade."""
        managed = self.positions.pop(symbol, None)
        if managed is None:
            return

        alpaca_symbol = symbol.replace("/", "") if "/" in symbol else symbol
        try:
            self.alpaca.close_position(alpaca_symbol)
        except Exception as exc:
            logger.error(f"EXIT: Failed to close {symbol}: {exc}")
            self.positions[symbol] = managed  # put it back for retry
            return

        self.stats.record(pnl_dollar)
        self.trade_history.append(
            TradeRecord(
                symbol=symbol,
                strategy_name=managed.strategy_name,
                side=managed.side,
                pnl=pnl_dollar,
                pnl_pct=pnl_pct,
                hold_hours=age_h,
                exit_reason=reason,
                closed_at=datetime.now(timezone.utc),
            )
        )

        log_msg = (
            f"EXIT: Closed {symbol} ${pnl_dollar:+,.2f} ({pnl_pct:+.1%}) "
            f"after {age_h:.1f}hrs | {reason} | Strategy: {managed.strategy_name}"
        )
        logger.info(log_msg)
        self._research_log.append(
            f"[{datetime.now(timezone.utc):%H:%M:%S}] {log_msg}"
        )

    # ── Data fetching ──────────────────────────────────────────────────────

    def _fetch_daily_bars(
        self, symbol: str, asset_type: AssetType, days: int = 90
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for backtesting."""
        return self.alpaca.get_bars(
            symbol=symbol,
            asset_type=asset_type,
            timeframe=TimeFrame.Day,
            days_back=days,
        )

    def _fetch_intraday_bars(
        self, symbol: str, asset_type: AssetType
    ) -> pd.DataFrame:
        """Fetch 5 days of 15-min bars for signal evaluation."""
        tf = TimeFrame(amount=15, unit=TimeFrameUnit.Minute)
        return self.alpaca.get_bars(
            symbol=symbol,
            asset_type=asset_type,
            timeframe=tf,
            days_back=5,
        )

    def _is_market_open(self) -> bool:
        """Check if the US equity market is currently open."""
        try:
            clock = self.alpaca.trading_client.get_clock()
            return clock.is_open
        except Exception as exc:
            logger.debug(f"Market clock check failed: {exc}")
            return False
