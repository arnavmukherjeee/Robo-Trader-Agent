"""LLM analyst for trade confirmation — Sonnet-powered deep analysis.

Feeds Claude rich market context and asks for careful, high-conviction decisions.
Prioritizes ACCURACY over speed. Only trades when Claude sees a real edge.
"""

import json
import time
import anthropic
from loguru import logger
from config.settings import settings
from src.trading.crypto_stream import ScalpContext
from src.strategies.scalp_signals import ScalpSignal


SYSTEM_PROMPT = """You are an elite crypto trader managing a $100k paper portfolio. Your job is to
analyze real-time market data and decide whether to enter a trade. You are running overnight
and need to be HIGHLY SELECTIVE — only take trades with a genuine edge.

ANALYSIS FRAMEWORK:
1. TREND: Is price trending up, down, or ranging? Look at the price history.
2. MOMENTUM: Is momentum accelerating or decelerating? Is it fresh or exhausted?
3. SUPPORT/RESISTANCE: Is price near a recent high (resistance) or low (support)?
4. SPREAD: Tight spread = liquid market = good. Wide spread = avoid.
5. VOLUME: High tick velocity = active market. Low = thin, dangerous.
6. VWAP: Price below VWAP = potential long. Above VWAP = potential short/wait.
7. RISK: What's the downside? Is there a clear level to cut the trade?

DECISION RULES:
- ONLY approve if you see a clear directional edge with a favorable entry point
- BUY near support/dips, NOT at resistance/peaks
- Require momentum IN the direction of the trade
- Reject if price just spiked (chasing) — wait for a pullback
- Reject if spread is eating >30% of the expected move
- Reject in choppy/sideways markets with no clear direction
- Size UP (1.3-1.5x) only on your highest conviction setups
- Size DOWN (0.5-0.7x) on decent but not amazing setups

You are ALLOWED to say no. In fact, saying no to bad trades is how you make money.
Aim for 70%+ win rate, not trade volume.

Reply with ONLY valid JSON, no markdown:
{"go":true,"confidence":0.85,"size_mult":1.0,"direction":"long","reason":"20 words max explaining the edge"}

confidence: 0.0-1.0 (only trade if > 0.7)
size_mult: 0.5-1.5
direction: "long" or "short"
"""


class ScalpAnalyst:
    """Sonnet-powered deep analyst for high-conviction trades."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = "claude-sonnet-4-20250514"
        self._enabled = bool(settings.anthropic_api_key)
        if self._enabled:
            logger.info("Scalp LLM analyst enabled (Sonnet — Deep Analysis)")
        else:
            logger.warning("Scalp LLM analyst disabled — no API key")

    def _build_price_history(self, ctx: ScalpContext) -> str:
        """Build a mini price chart from recent ticks for Claude to analyze."""
        ticks = list(ctx.ticks)
        if len(ticks) < 5:
            return "Insufficient data"

        # Sample ~20 price points across the tick history
        step = max(1, len(ticks) // 20)
        sampled = ticks[::step][-20:]

        prices = [t.price for t in sampled]
        high = max(prices)
        low = min(prices)
        rng = high - low if high != low else 1

        # Build text chart and stats
        lines = []
        for i, t in enumerate(sampled):
            bar_len = int((t.price - low) / rng * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            age_s = (time.time() * 1000 - t.timestamp) / 1000
            lines.append(f"  {age_s:5.0f}s ago │{bar}│ ${t.price:,.2f}")

        # Calculate trend stats
        first_price = prices[0]
        last_price = prices[-1]
        trend_pct = (last_price - first_price) / first_price * 100

        # Find local highs and lows (support/resistance)
        recent_high = max(prices[-5:])
        recent_low = min(prices[-5:])
        overall_high = high
        overall_low = low

        # Momentum analysis: split into halves
        mid_idx = len(prices) // 2
        first_half_chg = (prices[mid_idx] - prices[0]) / prices[0] * 100 if prices[0] > 0 else 0
        second_half_chg = (prices[-1] - prices[mid_idx]) / prices[mid_idx] * 100 if prices[mid_idx] > 0 else 0

        header = (
            f"PRICE HISTORY ({len(ticks)} ticks, ~{(time.time()*1000 - ticks[0].timestamp)/1000:.0f}s window)\n"
            f"  Overall trend: {trend_pct:+.3f}%\n"
            f"  First half: {first_half_chg:+.3f}% | Second half: {second_half_chg:+.3f}%\n"
            f"  Range: ${overall_low:,.2f} — ${overall_high:,.2f}\n"
            f"  Recent support: ${recent_low:,.2f} | Recent resistance: ${recent_high:,.2f}\n"
            f"  Current: ${last_price:,.2f} ({'near high' if last_price > recent_high * 0.999 else 'near low' if last_price < recent_low * 1.001 else 'mid-range'})\n"
        )

        return header + "\n".join(lines)

    def confirm_entry(
        self,
        symbol: str,
        ctx: ScalpContext,
        signals: list[ScalpSignal],
    ) -> tuple[bool, float]:
        """Ask Sonnet to deeply analyze and confirm/reject a trade. Returns (go, size_multiplier)."""
        if not self._enabled:
            return True, 1.0

        signal_text = "\n".join(
            f"  - {s.name} ({s.direction.value}, strength={s.strength:.2f}): {s.reason}"
            for s in signals
        )

        # Rich context
        vwap_dev = ((ctx.last_price - ctx.vwap_1m) / ctx.vwap_1m * 100) if ctx.vwap_1m > 0 else 0
        spread_pct = (ctx.spread / ctx.last_price * 100) if ctx.last_price > 0 else 0
        price_history = self._build_price_history(ctx)

        prompt = (
            f"═══ TRADE ANALYSIS REQUEST: {symbol} ═══\n\n"
            f"CURRENT STATE:\n"
            f"  Price: ${ctx.last_price:,.2f}\n"
            f"  VWAP (1m): ${ctx.vwap_1m:,.2f} (price is {vwap_dev:+.4f}% from VWAP)\n"
            f"  Spread: ${ctx.spread:.4f} ({spread_pct:.4f}%)\n"
            f"  Momentum (20-tick): {ctx.price_momentum:+.5%}\n"
            f"  Tick velocity: {ctx.tick_velocity:.1f} ticks/sec\n"
            f"  Volume (1m): {ctx.volume_1m:.6f}\n\n"
            f"{price_history}\n\n"
            f"SIGNALS FIRING:\n{signal_text}\n\n"
            f"QUESTION: Should we BUY {symbol} here? Analyze the trend, entry quality, "
            f"and risk/reward. Only approve if you see a genuine edge."
        )

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
                if text.startswith("json"):
                    text = text[4:].strip()

            result = json.loads(text)
            go = bool(result.get("go", False))
            confidence = float(result.get("confidence", 0.0))
            size_mult = float(result.get("size_mult", 1.0))
            size_mult = max(0.5, min(1.5, size_mult))
            reason = result.get("reason", "no reason")

            # Only trade if confidence is above threshold
            if go and confidence < 0.7:
                logger.info(f"⚠️ LOW CONFIDENCE {symbol}: {confidence:.0%} — {reason} (need 70%+)")
                return False, 1.0

            if not go:
                logger.info(f"🚫 REJECTED {symbol} ({confidence:.0%}): {reason}")
            else:
                logger.info(f"✅ APPROVED {symbol} ({confidence:.0%}, {size_mult}x): {reason}")

            return go, size_mult

        except Exception as e:
            logger.warning(f"LLM analysis failed, REJECTING: {e}")
            return False, 1.0  # fail-closed
