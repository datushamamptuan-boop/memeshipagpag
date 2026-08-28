"""
Hard stops that apply in BOTH confirm and auto mode. These exist because
"the AI decided to keep trading" is exactly the failure mode that already
cost money once — a bad streak needs something outside the decision loop
to actually stop it, not another layer of judgment that can also be wrong.
"""
import time
import config


def check_can_trade(state: dict) -> dict:
    """Returns {"can_trade": bool, "reason": str|None}."""
    now = time.time()
    today_start = now - (now % 86400)

    todays_trades = [t for t in state.get("closed_trades", []) if t.get("closed_at", 0) >= today_start]
    todays_pnl_usd = sum(t.get("pnl_usd", 0) for t in todays_trades)
    daily_loss_limit_usd = -config.TOTAL_CAPITAL_USD * (config.MAX_DAILY_LOSS_PCT / 100)

    if todays_pnl_usd <= daily_loss_limit_usd:
        return {
            "can_trade": False,
            "reason": (
                f"Daily loss cap hit (${todays_pnl_usd:.2f} today, limit "
                f"${daily_loss_limit_usd:.2f}). Paused until tomorrow (UTC)."
            ),
        }

    # Consecutive losses, most recent first
    recent = sorted(state.get("closed_trades", []), key=lambda t: t.get("closed_at", 0), reverse=True)
    streak = 0
    for t in recent:
        if t.get("pnl_usd", 0) < 0:
            streak += 1
        else:
            break

    if streak >= config.MAX_CONSECUTIVE_LOSSES:
        last_loss_time = recent[0].get("closed_at", 0)
        cooldown_ends = last_loss_time + config.CONSECUTIVE_LOSS_COOLDOWN_MINUTES * 60
        if now < cooldown_ends:
            minutes_left = round((cooldown_ends - now) / 60, 1)
            return {
                "can_trade": False,
                "reason": (
                    f"{streak} losses in a row — cooling down for {minutes_left} "
                    f"more minutes before the bot will trade again."
                ),
            }

    return {"can_trade": True, "reason": None}
