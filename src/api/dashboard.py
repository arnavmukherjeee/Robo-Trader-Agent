"""FastAPI dashboard — REST API for monitoring and controlling the trading system."""

import random
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    CryptoBarsRequest,
    StockSnapshotRequest,
    CryptoSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from src.api.dashboard_html import DASHBOARD_HTML
from src.backtest.backtester import Backtester
from src.strategies.engine import StrategyEngine

from config.settings import settings
from src.trading.alpaca_client import AlpacaClient
from src.trading.scalper import CryptoScalper
from src.trading.autopilot import Autopilot

scalper: CryptoScalper | None = None
scalper_thread: threading.Thread | None = None
alpaca: AlpacaClient | None = None
autopilot: Autopilot | None = None
autopilot_thread: threading.Thread | None = None

# ── Data clients & caches ───────────────────────────────────
_stock_data_client: StockHistoricalDataClient | None = None
_crypto_data_client: CryptoHistoricalDataClient | None = None
_backtest_cache: dict[str, list[dict]] = {}  # key = "symbol:days" -> results
_leaderboard_cache: list[dict] = []


def _is_crypto(symbol: str) -> bool:
    """Return True if symbol looks like a crypto pair (contains '/')."""
    return "/" in symbol


def _get_stock_client() -> StockHistoricalDataClient:
    global _stock_data_client
    if _stock_data_client is None:
        _stock_data_client = StockHistoricalDataClient(
            settings.alpaca_api_key, settings.alpaca_secret_key
        )
    return _stock_data_client


def _get_crypto_client() -> CryptoHistoricalDataClient:
    global _crypto_data_client
    if _crypto_data_client is None:
        _crypto_data_client = CryptoHistoricalDataClient(
            settings.alpaca_api_key, settings.alpaca_secret_key
        )
    return _crypto_data_client


_TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day": TimeFrame(1, TimeFrameUnit.Day),
}


def _fetch_bars(symbol: str, timeframe: TimeFrame, days: int) -> pd.DataFrame:
    """Fetch historical bars from Alpaca and return a DataFrame with standard columns."""
    start = datetime.now() - timedelta(days=days)
    if _is_crypto(symbol):
        client = _get_crypto_client()
        req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, start=start)
        barset = client.get_crypto_bars(req)
    else:
        client = _get_stock_client()
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, start=start)
        barset = client.get_stock_bars(req)

    bars = barset[symbol]
    rows = []
    for bar in bars:
        rows.append({
            "timestamp": bar.timestamp,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        })
    return pd.DataFrame(rows)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scalper, alpaca, autopilot, autopilot_thread
    logger.info("Starting Robo-Trader Agent v2 — Autopilot Mode...")
    alpaca = AlpacaClient()
    scalper = CryptoScalper()

    # Auto-start autopilot on launch
    autopilot = Autopilot()
    autopilot_thread = threading.Thread(target=autopilot.run, daemon=True)
    autopilot_thread.start()
    logger.info("Autopilot started automatically")

    yield
    if autopilot:
        autopilot.stop()
    if scalper:
        scalper.stop()
    logger.info("Robo-Trader Agent stopped")


app = FastAPI(
    title="Robo-Trader Agent — Crypto Scalper",
    description="Millisecond-level crypto scalping engine",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Status & Monitoring ─────────────────────────────────────

@app.get("/api/info")
async def api_info():
    return {
        "name": "Robo-Trader Agent — AI Strategy Platform",
        "status": "running",
        "mode": "platform",
        "time": datetime.now().isoformat(),
    }


@app.get("/status")
async def get_status():
    """Status works whether scalper is local or running via launchd."""
    positions = alpaca.get_positions() if alpaca else []
    # Parse last log line for stats
    stats = _parse_stats_from_logs()
    return {
        "running": len(positions) > 0 or stats.get("total_trades", 0) > 0 or _launchd_running(),
        "positions": {
            p["symbol"]: {
                "entry_price": p.get("avg_entry_price", 0),
                "notional": p.get("market_value", 0),
                "hold_time_ms": 0,
                "highest_pnl_pct": float(p.get("unrealized_plpc", 0)),
            }
            for p in positions
        },
        "stats": stats,
    }


def _launchd_running() -> bool:
    import subprocess
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=2)
        return "com.robotrader.scalper" in r.stdout
    except Exception:
        return False


def _parse_stats_from_logs() -> dict:
    """Parse trade stats from the most recent scalper log file."""
    import re
    log_dir = Path("logs")
    log_files = sorted(log_dir.glob("scalper_*.log"), key=lambda p: p.name, reverse=True)
    if not log_files:
        return {"total_trades": 0, "win_rate": 0, "total_pnl": 0, "avg_hold_ms": 0, "rejected": 0}
    try:
        with open(log_files[0], "r") as f:
            lines = f.readlines()
        # Find the last EXIT line which has cumulative stats
        for line in reversed(lines):
            if "EXIT" in line and "Trades:" in line:
                m_trades = re.search(r"Trades:\s*(\d+)", line)
                m_wl = re.search(r"W/L:\s*(\d+)/(\d+)", line)
                m_pnl = re.search(r"PnL:\s*\$([+-]?[\d,.]+)", line)
                m_hold = re.search(r"Avg Hold:\s*([\d.]+)s", line)
                m_best = re.search(r"Best:\s*\$\+?([\d,.]+)", line)
                m_worst = re.search(r"Worst:\s*\$-?([\d,.]+)", line)
                m_rej = re.search(r"Rejected:\s*(\d+)", line)
                total = int(m_trades.group(1)) if m_trades else 0
                wins = int(m_wl.group(1)) if m_wl else 0
                losses = int(m_wl.group(2)) if m_wl else 0
                pnl_str = m_pnl.group(1).replace(",", "") if m_pnl else "0"
                return {
                    "total_trades": total,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": (wins / total) if total > 0 else 0,
                    "total_pnl": float(pnl_str),
                    "biggest_win": float(m_best.group(1).replace(",", "")) if m_best else 0,
                    "biggest_loss": -float(m_worst.group(1).replace(",", "")) if m_worst else 0,
                    "avg_hold_time_ms": float(m_hold.group(1)) * 1000 if m_hold else 0,
                    "rejected": int(m_rej.group(1)) if m_rej else 0,
                }
        # Count rejections from log even if no exits yet
        rej_count = sum(1 for l in lines if "REJECTED" in l)
        entry_count = sum(1 for l in lines if "ENTRY" in l)
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
                "biggest_win": 0, "biggest_loss": 0, "avg_hold_time_ms": 0,
                "rejected": rej_count, "active_trades": entry_count}
    except Exception:
        return {"total_trades": 0, "win_rate": 0, "total_pnl": 0, "avg_hold_ms": 0, "rejected": 0}


@app.get("/api/autopilot/state")
async def get_autopilot_state():
    """Return full autopilot state for the dashboard."""
    if autopilot is None:
        return {"phase": "NOT_STARTED", "top_strategies": [], "positions": [], "research_log": [], "stats": {}}
    return autopilot.get_state()


@app.get("/account")
async def get_account():
    if alpaca is None:
        raise HTTPException(503, "Not initialized")
    return alpaca.get_account()


@app.get("/positions")
async def get_positions():
    if alpaca is None:
        raise HTTPException(503, "Not initialized")
    return alpaca.get_positions()


@app.get("/orders")
async def get_orders(status: str = "open"):
    if alpaca is None:
        raise HTTPException(503, "Not initialized")
    return alpaca.get_orders(status)


@app.get("/stats")
async def get_stats():
    """Parse stats from live logs — works with launchd scalper."""
    return _parse_stats_from_logs()


# ── Scalper Controls ─────────────────────────────────────────

@app.post("/scalper/start")
async def start_scalper():
    """Start the scalper in a background thread."""
    global scalper_thread
    if scalper is None:
        raise HTTPException(503, "Scalper not initialized")
    if scalper_thread and scalper_thread.is_alive():
        return {"status": "already_running"}

    scalper_thread = threading.Thread(target=scalper.run, daemon=True)
    scalper_thread.start()
    return {"status": "scalper_started", "symbols": scalper.symbols}


@app.post("/scalper/stop")
async def stop_scalper():
    """Stop the scalper and close all positions."""
    if scalper is None:
        raise HTTPException(503, "Scalper not initialized")
    scalper.stop()
    return {"status": "scalper_stopped", "final_stats": scalper.stats.summary()}


@app.post("/close-all")
async def close_all_positions():
    if alpaca is None:
        raise HTTPException(503, "Not initialized")
    try:
        return alpaca.close_all_positions()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/close-position/{symbol}")
async def close_position(symbol: str):
    if alpaca is None:
        raise HTTPException(503, "Not initialized")
    try:
        return alpaca.close_position(symbol)
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Backtest & Market Data ──────────────────────────────────

@app.get("/api/backtest/run")
async def run_backtest(
    symbol: str = Query(default="BTC/USD"),
    days: int = Query(default=30, ge=7, le=365),
    top_n: int = Query(default=20, ge=1, le=100),
):
    """Run backtest: fetch bars, generate strategies, test top_n, return results."""
    cache_key = f"{symbol}:{days}:{top_n}"
    if cache_key in _backtest_cache:
        return _backtest_cache[cache_key]

    try:
        # 1. Fetch daily bars
        df = _fetch_bars(symbol, TimeFrame(1, TimeFrameUnit.Day), days)
        if df.empty or len(df) < 30:
            return []

        # 2. Generate strategies (limit to first 100, then sample top_n)
        engine = StrategyEngine()
        all_strategies = engine.generate_strategies()
        pool = all_strategies[:100]
        if len(pool) > top_n:
            pool = random.sample(pool, top_n)

        # 3. Backtest each strategy
        backtester = Backtester()
        results: list[dict] = []
        for strat in pool:
            try:
                bt_result = backtester.run(strat, df.copy(), symbol=symbol)
                results.append({
                    "strategy_name": strat.name,
                    "signals_used": [sc["generator"] for sc in strat.signals_config],
                    "total_return_pct": round(bt_result.total_return_pct, 2),
                    "sharpe_ratio": round(bt_result.sharpe_ratio, 2),
                    "max_drawdown_pct": round(bt_result.max_drawdown_pct, 2),
                    "win_rate": round(bt_result.win_rate, 1),
                    "profit_factor": round(bt_result.profit_factor, 2)
                    if bt_result.profit_factor != float("inf")
                    else 999.99,
                    "total_trades": bt_result.total_trades,
                    "avg_win_pct": round(bt_result.avg_win_pct, 2),
                    "avg_loss_pct": round(bt_result.avg_loss_pct, 2),
                })
            except Exception as e:
                logger.warning(f"Backtest failed for {strat.name}: {e}")
                continue

        # Sort by total_return_pct descending
        results.sort(key=lambda r: r["total_return_pct"], reverse=True)

        # Cache and update leaderboard
        _backtest_cache[cache_key] = results
        _update_leaderboard(results)

        return results
    except Exception as e:
        logger.error(f"Backtest endpoint error: {e}")
        return []


def _update_leaderboard(new_results: list[dict]):
    """Merge new backtest results into the global leaderboard (top 50 by Sharpe)."""
    global _leaderboard_cache
    existing_names = {r["strategy_name"] for r in _leaderboard_cache}
    for r in new_results:
        if r["strategy_name"] not in existing_names:
            _leaderboard_cache.append(r)
            existing_names.add(r["strategy_name"])
    _leaderboard_cache.sort(key=lambda r: r["sharpe_ratio"], reverse=True)
    _leaderboard_cache = _leaderboard_cache[:50]


@app.get("/api/market/prices")
async def get_market_prices(
    symbols: str = Query(default="BTC/USD,ETH/USD"),
):
    """Return latest price, daily change %, and volume for each symbol."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    results: list[dict] = []

    crypto_syms = [s for s in symbol_list if _is_crypto(s)]
    stock_syms = [s for s in symbol_list if not _is_crypto(s)]

    # Crypto snapshots
    if crypto_syms:
        try:
            client = _get_crypto_client()
            req = CryptoSnapshotRequest(symbol_or_symbols=crypto_syms)
            snapshots = client.get_crypto_snapshot(req)
            for sym in crypto_syms:
                snap = snapshots.get(sym)
                if snap:
                    bar = snap.daily_bar
                    price = float(snap.latest_trade.price) if snap.latest_trade else float(bar.close)
                    change_pct = ((float(bar.close) - float(bar.open)) / float(bar.open) * 100) if bar else 0
                    results.append({
                        "symbol": sym,
                        "price": round(price, 4),
                        "change_pct": round(change_pct, 2),
                        "volume": float(bar.volume) if bar else 0,
                    })
        except Exception as e:
            logger.error(f"Crypto snapshot error: {e}")
            for sym in crypto_syms:
                results.append({"symbol": sym, "price": 0, "change_pct": 0, "volume": 0})

    # Stock snapshots
    if stock_syms:
        try:
            client = _get_stock_client()
            req = StockSnapshotRequest(symbol_or_symbols=stock_syms)
            snapshots = client.get_stock_snapshot(req)
            for sym in stock_syms:
                snap = snapshots.get(sym)
                if snap:
                    bar = snap.daily_bar
                    price = float(snap.latest_trade.price) if snap.latest_trade else float(bar.close)
                    change_pct = ((float(bar.close) - float(bar.open)) / float(bar.open) * 100) if bar else 0
                    results.append({
                        "symbol": sym,
                        "price": round(price, 4),
                        "change_pct": round(change_pct, 2),
                        "volume": float(bar.volume) if bar else 0,
                    })
        except Exception as e:
            logger.error(f"Stock snapshot error: {e}")
            for sym in stock_syms:
                results.append({"symbol": sym, "price": 0, "change_pct": 0, "volume": 0})

    # Convert list to dict keyed by symbol for easy frontend access
    return {r["symbol"]: r for r in results}


@app.get("/api/market/candles")
async def get_market_candles(
    symbol: str = Query(default="BTC/USD"),
    timeframe: str = Query(default="1Hour"),
    days: int = Query(default=7, ge=1, le=90),
):
    """Return OHLCV candles for charting."""
    tf = _TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        raise HTTPException(400, f"Invalid timeframe '{timeframe}'. Use: {list(_TIMEFRAME_MAP.keys())}")

    try:
        df = _fetch_bars(symbol, tf, days)
        if df.empty:
            return []
        candles = []
        for _, row in df.iterrows():
            candles.append({
                "t": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
                "o": round(row["open"], 4),
                "h": round(row["high"], 4),
                "l": round(row["low"], 4),
                "c": round(row["close"], 4),
                "v": round(row["volume"], 2),
            })
        return candles
    except Exception as e:
        logger.error(f"Candles endpoint error: {e}")
        return []


@app.get("/api/strategies/leaderboard")
async def strategy_leaderboard():
    """Return top 50 strategies by Sharpe ratio from cached backtest results."""
    return _leaderboard_cache


@app.get("/trades/closed")
async def get_closed_trades():
    """Return closed round-trip trades with per-trade P&L."""
    if alpaca is None:
        raise HTTPException(503, "Not initialized")
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=200)
        orders = alpaca.trading_client.get_orders(req)
        # Pair buys and sells by symbol chronologically
        fills = []
        for o in orders:
            if o.filled_avg_price and o.filled_qty:
                fills.append({
                    "symbol": o.symbol,
                    "side": str(o.side),
                    "qty": float(o.filled_qty),
                    "price": float(o.filled_avg_price),
                    "filled_at": o.filled_at.isoformat() if o.filled_at else "",
                    "notional": float(o.filled_qty) * float(o.filled_avg_price),
                })
        # Match buy→sell pairs (oldest first)
        fills.sort(key=lambda x: x["filled_at"])
        open_buys: dict[str, list] = {}
        trades = []
        for f in fills:
            sym = f["symbol"]
            if "buy" in f["side"].lower():
                open_buys.setdefault(sym, []).append(f)
            elif "sell" in f["side"].lower() and open_buys.get(sym):
                buy = open_buys[sym].pop(0)
                pnl = (f["price"] - buy["price"]) * f["qty"]
                pnl_pct = (f["price"] - buy["price"]) / buy["price"] * 100
                trades.append({
                    "symbol": sym,
                    "entry_price": buy["price"],
                    "exit_price": f["price"],
                    "qty": f["qty"],
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 3),
                    "entry_time": buy["filled_at"],
                    "exit_time": f["filled_at"],
                    "notional": round(buy["notional"], 2),
                })
        # Most recent first
        trades.reverse()
        running_pnl = 0
        for t in reversed(trades):
            running_pnl += t["pnl"]
            t["cumulative_pnl"] = round(running_pnl, 2)
        return trades
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Logs & Dashboard ─────────────────────────────────────────

@app.get("/logs/recent")
async def get_recent_logs():
    """Return the last 50 lines of the most recent scalper log file."""
    log_dir = Path("logs")
    log_files = sorted(log_dir.glob("scalper_*.log"), key=lambda p: p.name, reverse=True)
    if not log_files:
        # Fallback to scalper.log
        fallback = log_dir / "scalper.log"
        if fallback.exists():
            log_files = [fallback]
        else:
            return {"lines": ["No log files found."]}
    try:
        with open(log_files[0], "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        lines = [line.rstrip("\n") for line in all_lines[-50:]]
        return {"lines": lines}
    except Exception as e:
        return {"lines": [f"Error reading logs: {e}"]}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the old single-page trading dashboard."""
    return DASHBOARD_HTML


@app.get("/platform", response_class=HTMLResponse)
async def platform():
    """Serve the full AI strategy platform dashboard."""
    from src.api.platform_html import PLATFORM_HTML
    return PLATFORM_HTML


@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    """Redirect root to platform."""
    from src.api.platform_html import PLATFORM_HTML
    return PLATFORM_HTML
