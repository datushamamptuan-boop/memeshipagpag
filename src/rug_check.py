"""
Security / rug-risk analysis for a token mint, using RugCheck's public
report API (the same underlying idea Axiom's "safety" badge uses).

Nothing here can prove a token is safe — it can only surface known red
flags. Absence of red flags is not a guarantee.
"""
import requests
import config

TIMEOUT = 10


def check_token(mint_address: str) -> dict:
    """
    Returns a dict:
      {
        "ok": bool,                 # could we fetch a report at all
        "risk_score": 0-100,        # 100 = safest, our own normalization
        "flags": [str, ...],        # human-readable red flags found
        "mint_authority_active": bool,
        "freeze_authority_active": bool,
        "top_holder_pct": float,
        "lp_locked_pct": float,
      }
    """
    url = config.RUGCHECK_REPORT_URL.format(mint=mint_address)
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return _unknown_result(f"rugcheck returned HTTP {r.status_code}")
        report = r.json()
    except requests.RequestException as e:
        return _unknown_result(f"rugcheck request failed: {e}")

    flags = []
    mint_active = bool(report.get("mintAuthority"))
    freeze_active = bool(report.get("freezeAuthority"))
    if mint_active:
        flags.append("Mint authority NOT renounced (supply can be inflated)")
    if freeze_active:
        flags.append("Freeze authority active (dev can freeze your tokens)")

    holders = report.get("topHolders", []) or []
    top_holder_pct = max((h.get("pct", 0) for h in holders), default=0.0)
    if top_holder_pct > config.MAX_TOP_HOLDER_PCT:
        flags.append(f"Top holder owns {top_holder_pct:.1f}% of supply")

    markets = report.get("markets", []) or []
    lp_locked_pct = 0.0
    if markets:
        locked_vals = [m.get("lp", {}).get("lpLockedPct", 0) for m in markets]
        lp_locked_pct = max(locked_vals) if locked_vals else 0.0
    if lp_locked_pct < 50:
        flags.append(f"Only {lp_locked_pct:.1f}% of LP is locked/burned")

    rc_score = report.get("score")  # RugCheck's own 0(safe)-∞(risky)-ish score if present

    # Normalize into our own 0-100 "safety score" (100 = safest)
    penalty = 0
    penalty += 35 if mint_active else 0
    penalty += 35 if freeze_active else 0
    penalty += min(20, top_holder_pct)      # up to -20
    penalty += max(0, (50 - lp_locked_pct) / 50 * 20)  # up to -20
    safety_score = max(0, 100 - penalty)

    return {
        "ok": True,
        "risk_score": round(safety_score, 1),
        "flags": flags,
        "mint_authority_active": mint_active,
        "freeze_authority_active": freeze_active,
        "top_holder_pct": round(top_holder_pct, 2),
        "lp_locked_pct": round(lp_locked_pct, 2),
        "raw_rugcheck_score": rc_score,
    }


def _unknown_result(reason: str) -> dict:
    return {
        "ok": False,
        "risk_score": 0,  # treat unknown as unsafe by default — fail closed
        "flags": [f"Could not verify security ({reason}) — treated as high risk"],
        "mint_authority_active": None,
        "freeze_authority_active": None,
        "top_holder_pct": None,
        "lp_locked_pct": None,
        "raw_rugcheck_score": None,
    }
