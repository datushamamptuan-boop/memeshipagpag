"""
Combines liquidity/volume, rug-check safety, social score, and smart-wallet
signal into one 0-100 composite score, plus a plain-English breakdown.

Weights are deliberately conservative: safety and liquidity dominate,
because for a $5 bankroll a single rug or an illiquid exit wipes you out
regardless of how exciting the token narrative is.

WEIGHTS = safety 40, liquidity/volume 25, social 20, smart-wallet 15
"""
import config


def score_token(pair: dict, rug_result: dict, social_result: dict, wallets_holding: list):
    from src.data_sources import extract_liquidity_usd, extract_volume_24h

    liquidity = extract_liquidity_usd(pair)
    volume_24h = extract_volume_24h(pair)

    # --- liquidity/volume sub-score (0-100) ---
    liq_score = min(100, (liquidity / max(config.MIN_LIQUIDITY_USD, 1)) * 40)
    vol_score = min(100, (volume_24h / max(liquidity, 1)) * 50)  # healthy turnover vs liquidity
    market_score = min(100, liq_score * 0.6 + vol_score * 0.4)

    # --- smart wallet sub-score ---
    wallet_score = min(100, len(wallets_holding) * 50)  # 2+ tracked wallets = max signal

    composite = (
        rug_result["risk_score"] * 0.40
        + market_score * 0.25
        + social_result["score"] * 0.20
        + wallet_score * 0.15
    )

    reasons = []
    reasons.extend(f"[Security] {f}" for f in rug_result["flags"])
    reasons.extend(f"[Social] {n}" for n in social_result["notes"])
    if wallets_holding:
        reasons.append(f"[Smart money] Held by tracked wallet(s): {', '.join(wallets_holding)}")
    else:
        reasons.append("[Smart money] No tracked wallets currently in this token")
    reasons.append(f"[Market] Liquidity ${liquidity:,.0f}, 24h volume ${volume_24h:,.0f}")

    return {
        "composite_score": round(composite, 1),
        "safety_score": rug_result["risk_score"],
        "market_score": round(market_score, 1),
        "social_score": social_result["score"],
        "wallet_score": wallet_score,
        "reasons": reasons,
        "meets_liquidity_floor": liquidity >= config.MIN_LIQUIDITY_USD,
        "meets_holder_floor": (
            rug_result.get("top_holder_pct") is not None
            and rug_result["top_holder_pct"] <= config.MAX_TOP_HOLDER_PCT
        ),
    }


def should_enter(scored: dict) -> bool:
    return (
        scored["composite_score"] >= config.ENTRY_SCORE_THRESHOLD
        and scored["meets_liquidity_floor"]
        and scored["meets_holder_floor"]
    )
