"""Backtesting engine — tests strategies against historical data."""

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from loguru import logger

from src.strategies.engine import Strategy, StrategyEngine
from src.strategies.indicators import compute_all_indicators
from src.strategies.signals import Direction


@dataclass
class Trade:
    entry_date: datetime
    exit_date: datetime | None
    direction: Direction
    entry_price: float
    exit_price: float | None
    qty: float
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class BacktestResult:
    strategy: Strategy
    symbol: str
    trades: list[Trade]
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    total_trades: int
    start_date: datetime
    end_date: datetime

    def summary(self) -> str:
        return (
            f"Backtest: {self.strategy.name} on {self.symbol}\n"
            f"  Period: {self.start_date.date()} → {self.end_date.date()}\n"
            f"  Return: {self.total_return_pct:+.2f}%\n"
            f"  Sharpe: {self.sharpe_ratio:.2f}\n"
            f"  Max DD: {self.max_drawdown_pct:.2f}%\n"
            f"  Win Rate: {self.win_rate:.1f}% ({self.total_trades} trades)\n"
            f"  Profit Factor: {self.profit_factor:.2f}"
        )


class Backtester:
    """Run strategies against historical data to measure performance."""

    def __init__(
        self,
        initial_capital: float = 100_000,
        position_size_pct: float = 0.05,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.06,
    ):
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.engine = StrategyEngine()

    def run(
        self,
        strategy: Strategy,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
    ) -> BacktestResult:
        """Backtest a single strategy on historical OHLCV data."""
        df = compute_all_indicators(df)
        df = df.dropna(subset=["close"]).reset_index(drop=True)

        capital = self.initial_capital
        trades: list[Trade] = []
        equity_curve = [capital]
        position: Trade | None = None

        # Walk forward through bars
        lookback = min(50, len(df) // 3)  # adaptive lookback — use 50 or 1/3 of data
        for i in range(lookback, len(df)):
            window = df.iloc[: i + 1]
            current_price = df["close"].iloc[i]
            current_date = df["timestamp"].iloc[i] if "timestamp" in df.columns else i

            # Check exits first
            if position is not None:
                exit_price = None
                if position.direction == Direction.LONG:
                    pnl_pct = (current_price - position.entry_price) / position.entry_price
                    if pnl_pct <= -self.stop_loss_pct:
                        exit_price = current_price
                    elif pnl_pct >= self.take_profit_pct:
                        exit_price = current_price
                else:  # SHORT
                    pnl_pct = (position.entry_price - current_price) / position.entry_price
                    if pnl_pct <= -self.stop_loss_pct:
                        exit_price = current_price
                    elif pnl_pct >= self.take_profit_pct:
                        exit_price = current_price

                if exit_price is not None:
                    position.exit_date = current_date
                    position.exit_price = exit_price
                    if position.direction == Direction.LONG:
                        position.pnl = (exit_price - position.entry_price) * position.qty
                    else:
                        position.pnl = (position.entry_price - exit_price) * position.qty
                    position.pnl_pct = position.pnl / (position.entry_price * position.qty)
                    capital += position.pnl
                    trades.append(position)
                    position = None

            # Check entries (only if flat)
            if position is None:
                result = self.engine.evaluate(strategy, window)
                if result.direction != Direction.NEUTRAL and result.confidence > 0.4:
                    position_value = capital * self.position_size_pct
                    qty = position_value / current_price

                    position = Trade(
                        entry_date=current_date,
                        exit_date=None,
                        direction=result.direction,
                        entry_price=current_price,
                        exit_price=None,
                        qty=qty,
                    )

            equity_curve.append(capital + (
                _unrealized_pnl(position, current_price) if position else 0
            ))

        # Close any open position at end
        if position is not None:
            final_price = df["close"].iloc[-1]
            position.exit_date = df["timestamp"].iloc[-1] if "timestamp" in df.columns else len(df)
            position.exit_price = final_price
            if position.direction == Direction.LONG:
                position.pnl = (final_price - position.entry_price) * position.qty
            else:
                position.pnl = (position.entry_price - final_price) * position.qty
            position.pnl_pct = position.pnl / (position.entry_price * position.qty)
            capital += position.pnl
            trades.append(position)

        return self._compute_metrics(strategy, symbol, trades, equity_curve, df)

    def _compute_metrics(
        self,
        strategy: Strategy,
        symbol: str,
        trades: list[Trade],
        equity_curve: list[float],
        df: pd.DataFrame,
    ) -> BacktestResult:
        equity = np.array(equity_curve)
        returns = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([0.0])

        total_return = (equity[-1] - self.initial_capital) / self.initial_capital * 100
        sharpe = (
            float(np.mean(returns) / np.std(returns) * np.sqrt(252))
            if np.std(returns) > 0
            else 0.0
        )

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak * 100
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        # Win rate
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        win_rate = len(wins) / len(trades) * 100 if trades else 0.0
        avg_win = float(np.mean([t.pnl_pct for t in wins]) * 100) if wins else 0.0
        avg_loss = float(np.mean([t.pnl_pct for t in losses]) * 100) if losses else 0.0

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        start_date = df["timestamp"].iloc[0] if "timestamp" in df.columns else datetime.now()
        end_date = df["timestamp"].iloc[-1] if "timestamp" in df.columns else datetime.now()

        return BacktestResult(
            strategy=strategy,
            symbol=symbol,
            trades=trades,
            total_return_pct=total_return,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            profit_factor=profit_factor,
            total_trades=len(trades),
            start_date=start_date,
            end_date=end_date,
        )


def _unrealized_pnl(position: Trade | None, current_price: float) -> float:
    if position is None:
        return 0.0
    if position.direction == Direction.LONG:
        return (current_price - position.entry_price) * position.qty
    return (position.entry_price - current_price) * position.qty
