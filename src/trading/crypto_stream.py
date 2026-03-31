"""Real-time crypto data stream via Alpaca WebSocket.

Streams live quotes and trades for sub-second scalping decisions.
"""

import asyncio
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

import certifi
from loguru import logger

from alpaca.data.live import CryptoDataStream
from config.settings import settings

# Fix macOS SSL certificate issue
os.environ.setdefault("SSL_CERT_FILE", certifi.where())


@dataclass
class TickData:
    """Single price tick."""
    symbol: str
    price: float
    size: float
    timestamp: float  # epoch ms
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0


@dataclass
class ScalpContext:
    """Real-time context for a single symbol, updated on every tick."""
    symbol: str
    ticks: deque = field(default_factory=lambda: deque(maxlen=500))
    last_price: float = 0.0
    last_bid: float = 0.0
    last_ask: float = 0.0
    spread: float = 0.0
    vwap_1m: float = 0.0
    volume_1m: float = 0.0
    price_momentum: float = 0.0  # price change over last N ticks
    tick_velocity: float = 0.0  # ticks per second
    last_update_ms: float = 0.0

    def update_from_tick(self, tick: TickData):
        self.ticks.append(tick)
        self.last_price = tick.price
        self.last_bid = tick.bid
        self.last_ask = tick.ask
        self.spread = tick.spread
        self.last_update_ms = tick.timestamp
        self._recalculate()

    def _recalculate(self):
        now = time.time() * 1000
        one_min_ago = now - 60_000

        # Filter ticks in last minute
        recent = [t for t in self.ticks if t.timestamp > one_min_ago]
        if len(recent) < 2:
            return

        # VWAP over 1 minute
        total_value = sum(t.price * t.size for t in recent if t.size > 0)
        total_volume = sum(t.size for t in recent if t.size > 0)
        self.vwap_1m = total_value / total_volume if total_volume > 0 else self.last_price
        self.volume_1m = total_volume

        # Price momentum: % change over last 20 ticks
        lookback = min(20, len(recent))
        if lookback >= 2:
            old_price = recent[-lookback].price
            self.price_momentum = (self.last_price - old_price) / old_price if old_price > 0 else 0

        # Tick velocity: ticks per second in last 5 seconds
        five_sec_ago = now - 5_000
        recent_5s = [t for t in recent if t.timestamp > five_sec_ago]
        self.tick_velocity = len(recent_5s) / 5.0


class CryptoStream:
    """Manages websocket connection and streams live crypto data."""

    def __init__(self, on_tick_callback=None):
        self.stream = CryptoDataStream(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        self.contexts: dict[str, ScalpContext] = {}
        self.on_tick = on_tick_callback
        self._running = False

    def get_context(self, symbol: str) -> ScalpContext | None:
        return self.contexts.get(symbol)

    async def _handle_trade(self, trade):
        """Handle incoming trade data."""
        symbol = trade.symbol
        tick = TickData(
            symbol=symbol,
            price=float(trade.price),
            size=float(trade.size),
            timestamp=time.time() * 1000,
        )

        if symbol not in self.contexts:
            self.contexts[symbol] = ScalpContext(symbol=symbol)
        self.contexts[symbol].update_from_tick(tick)

        if self.on_tick:
            await self.on_tick(tick, self.contexts[symbol])

    async def _handle_quote(self, quote):
        """Handle incoming quote (bid/ask) data."""
        symbol = quote.symbol
        bid = float(quote.bid_price)
        ask = float(quote.ask_price)
        spread = ask - bid
        mid = (bid + ask) / 2

        tick = TickData(
            symbol=symbol,
            price=mid,
            size=0,
            timestamp=time.time() * 1000,
            bid=bid,
            ask=ask,
            spread=spread,
        )

        if symbol not in self.contexts:
            self.contexts[symbol] = ScalpContext(symbol=symbol)
        ctx = self.contexts[symbol]
        ctx.last_bid = bid
        ctx.last_ask = ask
        ctx.spread = spread
        ctx.update_from_tick(tick)

        if self.on_tick:
            await self.on_tick(tick, ctx)

    def start(self, symbols: list[str]):
        """Start streaming with auto-reconnect on disconnect."""
        self._running = True
        self._symbols = symbols
        logger.info(f"Starting crypto stream for: {symbols}")

        while self._running:
            try:
                # Fresh stream on each reconnect
                self.stream = CryptoDataStream(
                    api_key=settings.alpaca_api_key,
                    secret_key=settings.alpaca_secret_key,
                )
                self.stream.subscribe_trades(self._handle_trade, *symbols)
                self.stream.subscribe_quotes(self._handle_quote, *symbols)
                self.stream.run()
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"WebSocket disconnected: {e}. Reconnecting in 5s...")
                time.sleep(5)

    def stop(self):
        self._running = False
        self.stream.stop()
        logger.info("Crypto stream stopped")
