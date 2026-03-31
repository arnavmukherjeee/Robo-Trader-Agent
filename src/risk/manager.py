"""Risk management module — position sizing, stop-losses, portfolio limits."""

from dataclasses import dataclass

from loguru import logger

from config.settings import settings
from src.strategies.signals import Direction
from src.llm.analyst import LLMTradeRecommendation


@dataclass
class RiskCheck:
    approved: bool
    adjusted_size_pct: float
    stop_loss_price: float
    take_profit_price: float
    rejection_reason: str | None = None


class RiskManager:
    """Enforces risk rules before any trade is executed."""

    def __init__(self):
        self.max_position_pct = settings.max_position_size_pct
        self.max_portfolio_risk = settings.max_portfolio_risk_pct
        self.max_positions = settings.max_open_positions
        self.default_stop_loss = settings.stop_loss_pct

    def check_trade(
        self,
        recommendation: LLMTradeRecommendation,
        current_price: float,
        account: dict,
        positions: list[dict],
    ) -> RiskCheck:
        """Run all risk checks on a proposed trade."""
        # 1. Max open positions
        if len(positions) >= self.max_positions:
            return RiskCheck(
                approved=False,
                adjusted_size_pct=0,
                stop_loss_price=0,
                take_profit_price=0,
                rejection_reason=f"Max positions ({self.max_positions}) reached",
            )

        # 2. Check if already holding this symbol
        existing = [p for p in positions if p["symbol"] == recommendation.symbol]
        if existing:
            existing_side = existing[0].get("side", "long")
            rec_side = "long" if recommendation.direction == Direction.LONG else "short"
            if existing_side == rec_side:
                return RiskCheck(
                    approved=False,
                    adjusted_size_pct=0,
                    stop_loss_price=0,
                    take_profit_price=0,
                    rejection_reason=f"Already have {existing_side} position in {recommendation.symbol}",
                )

        # 3. Cap position size
        size_pct = min(recommendation.position_size_pct, self.max_position_pct)

        # 4. Ensure enough cash
        equity = account.get("equity", 0)
        cash = account.get("cash", 0)
        required = equity * size_pct
        if required > cash:
            size_pct = cash / equity if equity > 0 else 0
            if size_pct < 0.005:  # less than 0.5% not worth it
                return RiskCheck(
                    approved=False,
                    adjusted_size_pct=0,
                    stop_loss_price=0,
                    take_profit_price=0,
                    rejection_reason="Insufficient cash for minimum position",
                )

        # 5. Portfolio concentration check — no more than 25% in correlated assets
        total_market_value = sum(abs(p.get("market_value", 0)) for p in positions)
        if total_market_value > equity * 0.8:
            size_pct = min(size_pct, 0.01)  # reduce to 1% if heavily invested
            logger.warning("Portfolio >80% invested, reducing position size to 1%")

        # 6. Confidence gate — require minimum confidence
        if recommendation.confidence < 0.5:
            return RiskCheck(
                approved=False,
                adjusted_size_pct=0,
                stop_loss_price=0,
                take_profit_price=0,
                rejection_reason=f"Confidence {recommendation.confidence:.2f} below minimum 0.50",
            )

        # 7. Calculate stop-loss and take-profit prices
        stop_pct = max(recommendation.stop_loss_pct, self.default_stop_loss)
        tp_pct = recommendation.take_profit_pct

        if recommendation.direction == Direction.LONG:
            stop_price = current_price * (1 - stop_pct)
            tp_price = current_price * (1 + tp_pct)
        else:
            stop_price = current_price * (1 + stop_pct)
            tp_price = current_price * (1 - tp_pct)

        logger.info(
            f"Risk check APPROVED: {recommendation.symbol} "
            f"size={size_pct:.2%} SL={stop_price:.2f} TP={tp_price:.2f}"
        )

        return RiskCheck(
            approved=True,
            adjusted_size_pct=size_pct,
            stop_loss_price=stop_price,
            take_profit_price=tp_price,
        )

    def check_portfolio_health(self, account: dict, positions: list[dict]) -> dict:
        """Overall portfolio health check."""
        equity = account.get("equity", 0)
        total_unrealized = sum(p.get("unrealized_pl", 0) for p in positions)
        total_exposure = sum(abs(p.get("market_value", 0)) for p in positions)

        drawdown_pct = abs(total_unrealized / equity * 100) if equity > 0 else 0
        exposure_pct = total_exposure / equity * 100 if equity > 0 else 0

        # Check for symbols that need stop-loss exits
        danger_positions = [
            p for p in positions if p.get("unrealized_plpc", 0) < -self.default_stop_loss
        ]

        status = "HEALTHY"
        if drawdown_pct > 5:
            status = "WARNING"
        if drawdown_pct > 10:
            status = "CRITICAL"

        return {
            "status": status,
            "equity": equity,
            "unrealized_pnl": total_unrealized,
            "drawdown_pct": drawdown_pct,
            "exposure_pct": exposure_pct,
            "num_positions": len(positions),
            "danger_positions": [p["symbol"] for p in danger_positions],
        }
