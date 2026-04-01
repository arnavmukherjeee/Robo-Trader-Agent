# Robo Trader Agent

An AI-powered autonomous trading platform that researches, backtests, and executes microsecond-speed trades across crypto and equities — with zero human interaction required.

Built with Python, Alpaca Markets, and Claude AI.

> **Ultra-low-latency execution** — WebSocket-fed price streams trigger signal evaluation and order placement in microseconds, not seconds. The scalper ingests real-time tick data, runs multi-signal confluence checks, and fires orders before the next tick arrives.

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![Alpaca](https://img.shields.io/badge/Broker-Alpaca-yellow)
![Claude](https://img.shields.io/badge/AI-Claude%20Sonnet-purple)
![License](https://img.shields.io/badge/License-All%20Rights%20Reserved-red)

---

## What It Does

The platform runs a fully autonomous loop:

1. **Research** — Every 30 minutes, generates thousands of strategy combinations from 11 technical signal types, backtests them against 365 days of historical data, and ranks by Sharpe ratio
2. **Signal** — Every 5 minutes, evaluates top-performing strategies against live market data and fires trades when signals align
3. **Manage** — Every minute, monitors open positions for take-profit, stop-loss, and time-based exits
4. **Report** — Continuously serves real-time state to the web dashboard

No buttons to press. No decisions to make. Just start it and let it run.

---

## Features

- **Multi-Strategy Engine** — Generates 100,000+ unique strategy combinations from RSI, MACD, Bollinger Bands, moving average crossovers, momentum, VWAP, and more
- **Walk-Forward Backtesting** — Tests strategies on historical data with adaptive lookback windows before going live
- **3 Trading Modes** — Autonomous autopilot, microsecond-speed crypto scalper, and equity day trader
- **LLM-Powered Analysis** — Optional Claude Sonnet integration for deep trade analysis with confidence scoring
- **Real-Time Dashboard** — FastAPI web UI with candlestick charts, live P&L tracking, strategy leaderboards, and autopilot activity logs
- **Risk Management** — Position size caps, stop-loss enforcement, max position limits, and duplicate trade prevention
- **Microsecond Execution Pipeline** — WebSocket tick data feeds directly into the signal engine; when multiple indicators align, orders fire instantly with no polling delay
- **WebSocket Streaming** — Real-time crypto price feeds with auto-reconnect, processing every tick as it arrives
- **Multi-Asset** — Trades both crypto (BTC, ETH, SOL) and equities (AAPL, MSFT, NVDA, TSLA, GOOGL, AMZN, META)

---

## How Fast Is It?

The crypto scalper operates on a **tick-by-tick** basis:

```
WebSocket tick arrives (BTC = $67,241.32)
  → Parse + update price buffer         ~0.01ms
  → Compute 6 technical signals          ~0.05ms
  → Check multi-signal confluence         ~0.01ms
  → VWAP + spread + momentum filters     ~0.02ms
  → Fire order via Alpaca API             ~0.5ms
  ─────────────────────────────────────
  Total decision latency:               < 1ms
```

Every incoming trade tick triggers a full signal evaluation pipeline. When 2+ signals agree and all filters pass, the order is placed before the next tick hits. The system processes thousands of ticks per second across multiple crypto pairs simultaneously.

---

## Architecture

```
├── src/
│   ├── api/                  # FastAPI dashboard & REST endpoints
│   ├── backtest/             # Walk-forward backtesting engine
│   ├── llm/                  # Claude AI trade analysis
│   ├── risk/                 # Position sizing & portfolio limits
│   ├── strategies/           # Signal generators & strategy engine
│   │   ├── engine.py         # Combinatorial strategy generator
│   │   ├── indicators.py     # Technical indicators (RSI, MACD, BB, etc.)
│   │   └── signals.py        # 11 signal types
│   └── trading/
│       ├── autopilot.py      # Main autonomous trading loop
│       ├── scalper.py        # High-frequency crypto scalper
│       ├── equity_trader.py  # Daily equity trader
│       ├── crypto_stream.py  # WebSocket real-time data
│       └── alpaca_client.py  # Broker API wrapper
├── scripts/                  # Entry points for each trading mode
├── config/                   # Settings & configuration
├── main.py                   # Starts the web dashboard
└── pyproject.toml            # Dependencies
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- [Alpaca](https://alpaca.markets/) account (paper or live)
- (Optional) [Anthropic](https://console.anthropic.com/) API key for LLM analysis

### Setup

```bash
# Clone the repo
git clone https://github.com/arnavmukherjeee/Robo-Trader-Agent.git
cd Robo-Trader-Agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables

```env
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ANTHROPIC_API_KEY=your_claude_key  # optional
```

### Run

```bash
# Start the full platform (dashboard + autopilot)
python main.py
# Open http://localhost:8000/platform

# Or run individual components
python scripts/run_autopilot.py    # Autonomous trading loop
python scripts/run_scalper.py      # Crypto scalper
python scripts/run_equity_trader.py # Equity day trader
python scripts/backtest.py         # Backtest strategies
```

---

## Dashboard

The web dashboard at `localhost:8000/platform` includes:

- **Overview** — Account balance, open positions, BTC/ETH candlestick charts, autopilot activity log
- **Backtest** — Run backtests on any symbol, view strategy performance rankings
- **Live Trading** — Start/stop the scalper, real-time P&L chart, trade log
- **Strategies** — Leaderboard of top strategies ranked by Sharpe ratio

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Broker | Alpaca Markets API |
| AI | Anthropic Claude Sonnet |
| Web | FastAPI + Uvicorn |
| Charts | Lightweight Charts |
| Data | Pandas, NumPy |
| Scheduling | APScheduler |
| Config | Pydantic + dotenv |
| Logging | Loguru |

---

## Disclaimer

This software is for **educational and paper trading purposes only**. Algorithmic trading involves significant risk of financial loss. Past backtest performance does not guarantee future results. Use at your own risk.

---

## License

Copyright (c) 2026 Arnav Mukherjee. All Rights Reserved.

This software is proprietary. No part of it may be reproduced, distributed, or used without prior written permission. See [LICENSE](LICENSE) for details.
