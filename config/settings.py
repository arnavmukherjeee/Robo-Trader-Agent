from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field

# Load .env first so shell-level empty vars don't override
load_dotenv(override=True)


class Settings(BaseSettings):
    # Alpaca
    alpaca_api_key: str = Field(default="")
    alpaca_secret_key: str = Field(default="")
    alpaca_base_url: str = Field(default="https://paper-api.alpaca.markets/v2")

    # Anthropic
    anthropic_api_key: str = Field(default="")

    # Risk
    max_position_size_pct: float = Field(default=0.20)
    max_portfolio_risk_pct: float = Field(default=0.20)
    max_open_positions: int = Field(default=10)
    stop_loss_pct: float = Field(default=0.002)

    # Trading
    trading_mode: str = Field(default="paper")
    equity_symbols: list[str] = Field(default=[])
    crypto_symbols: list[str] = Field(
        default=["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD"]
    )

    # Equity Day Trading
    equity_position_size_pct: float = Field(default=0.10)  # 10% per trade
    equity_max_positions: int = Field(default=5)
    equity_tp_pct: float = Field(default=0.02)  # 2% take profit
    equity_sl_pct: float = Field(default=0.01)  # 1% stop loss

    # Scalping
    scalp_take_profit_pct: float = Field(default=0.003)  # 0.3% take profit
    scalp_stop_loss_pct: float = Field(default=0.002)  # 0.2% stop loss
    scalp_cooldown_ms: int = Field(default=500)  # min ms between trades per symbol

    # System
    log_level: str = Field(default="INFO")
    strategy_refresh_minutes: int = Field(default=1)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
