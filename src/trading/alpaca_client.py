"""Alpaca trading client for equities and crypto."""

from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
from loguru import logger

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    CryptoBarsRequest,
    StockLatestQuoteRequest,
    CryptoLatestQuoteRequest,
)
from alpaca.data.timeframe import TimeFrame

from config.settings import settings


class AssetType(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"


class AlpacaClient:
    """Unified client for Alpaca equity and crypto trading."""

    def __init__(self):
        self.trading_client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,
        )
        self.stock_data = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        self.crypto_data = CryptoHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        logger.info("Alpaca client initialized (paper trading mode)")

    # ── Account ──────────────────────────────────────────────

    def get_account(self) -> dict:
        account = self.trading_client.get_account()
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "day_trade_count": account.daytrade_count,
        }

    def get_positions(self) -> list[dict]:
        positions = self.trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side,
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "current_price": float(p.current_price),
                "avg_entry_price": float(p.avg_entry_price),
                "asset_class": p.asset_class,
            }
            for p in positions
        ]

    # ── Market Data ──────────────────────────────────────────

    def get_bars(
        self,
        symbol: str,
        asset_type: AssetType,
        timeframe: TimeFrame = TimeFrame.Hour,
        days_back: int = 30,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars as a DataFrame."""
        start = datetime.now() - timedelta(days=days_back)

        if asset_type == AssetType.EQUITY:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=start,
            )
            bars = self.stock_data.get_stock_bars(request)
        else:
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=start,
            )
            bars = self.crypto_data.get_crypto_bars(request)

        df = bars.df.reset_index()
        if "symbol" in df.columns:
            df = df[df["symbol"] == symbol].copy()

        df = df.rename(
            columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
        )
        return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    def get_latest_price(self, symbol: str, asset_type: AssetType) -> float:
        """Get the latest price for a symbol."""
        if asset_type == AssetType.EQUITY:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.stock_data.get_stock_latest_quote(request)
            return float(quote[symbol].ask_price)
        else:
            request = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.crypto_data.get_crypto_latest_quote(request)
            return float(quote[symbol].ask_price)

    # ── Order Execution ──────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        qty: float | None = None,
        notional: float | None = None,
        side: str = "buy",
    ) -> dict:
        """Place a market order by qty or dollar amount (notional)."""
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        is_crypto = "/" in symbol

        # Crypto uses GTC; equity fractional/notional requires DAY
        if is_crypto:
            tif = TimeInForce.GTC
        else:
            tif = TimeInForce.DAY if notional is not None else TimeInForce.GTC

        params = {
            "symbol": symbol,
            "side": order_side,
            "time_in_force": tif,
        }

        if is_crypto and notional is not None:
            # Crypto doesn't support notional — convert to qty
            from src.trading.alpaca_client import classify_asset
            price = self.get_latest_price(symbol, AssetType.CRYPTO)
            params["qty"] = round(notional / price, 6)
        elif qty is not None:
            params["qty"] = qty
        elif notional is not None:
            params["notional"] = notional
        else:
            raise ValueError("Must specify either qty or notional")

        order_request = MarketOrderRequest(**params)
        order = self.trading_client.submit_order(order_request)

        logger.info(f"Market order placed: {side} {symbol} | order_id={order.id}")
        return {
            "order_id": str(order.id),
            "symbol": order.symbol,
            "side": str(order.side),
            "qty": str(order.qty),
            "status": str(order.status),
            "type": str(order.type),
        }

    def place_limit_order(
        self,
        symbol: str,
        qty: float,
        limit_price: float,
        side: str = "buy",
    ) -> dict:
        """Place a limit order."""
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        order_request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.GTC,
            limit_price=limit_price,
        )
        order = self.trading_client.submit_order(order_request)

        logger.info(
            f"Limit order placed: {side} {qty} {symbol} @ {limit_price} | order_id={order.id}"
        )
        return {
            "order_id": str(order.id),
            "symbol": order.symbol,
            "side": str(order.side),
            "qty": str(order.qty),
            "limit_price": str(order.limit_price),
            "status": str(order.status),
        }

    def get_orders(self, status: str = "open") -> list[dict]:
        """Get orders by status."""
        query_status = QueryOrderStatus.OPEN if status == "open" else QueryOrderStatus.CLOSED
        request = GetOrdersRequest(status=query_status, limit=100)
        orders = self.trading_client.get_orders(request)
        return [
            {
                "order_id": str(o.id),
                "symbol": o.symbol,
                "side": str(o.side),
                "qty": str(o.qty),
                "status": str(o.status),
                "type": str(o.type),
                "created_at": str(o.created_at),
            }
            for o in orders
        ]

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order."""
        self.trading_client.cancel_order_by_id(order_id)
        logger.info(f"Order cancelled: {order_id}")

    def close_position(self, symbol: str) -> dict:
        """Close an entire position for a symbol."""
        order = self.trading_client.close_position(symbol)
        logger.info(f"Position closed: {symbol}")
        return {"symbol": symbol, "status": "closed", "order_id": str(order.id)}

    def close_all_positions(self) -> list[dict]:
        """Close all open positions."""
        results = self.trading_client.close_all_positions()
        logger.info(f"All positions closed: {len(results)} orders")
        return [{"symbol": str(r)} for r in results]


def classify_asset(symbol: str) -> AssetType:
    """Determine if a symbol is equity or crypto."""
    if "/" in symbol:
        return AssetType.CRYPTO
    return AssetType.EQUITY
