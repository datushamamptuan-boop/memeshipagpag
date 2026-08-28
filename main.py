"""
Entry point. Designed to be run either:
  - locally, in a loop (python main.py --loop)
  - as a single pass triggered by GitHub Actions on a cron schedule
    (also triggerable on-demand the moment you tap a button on the dashboard)

Each run:
  1. Loads state.json (positions, history, pending confirmations)
  2. Applies any pending_actions.json decisions written by the dashboard
     (Confirm / Skip button presses)
  3. Checks exit conditions on open positions
  4. Circuit breaker check — daily loss cap / losing-streak cooldown
  5. Scans for new candidates and scores them
  6. If a candidate clears the entry threshold:
       - AUTO_TRADE_MODE=="auto"   -> opens the position immediately
       - AUTO_TRADE_MODE=="confirm" -> queues it in pending_confirmations
         and waits for a dashboard button press (or expires it)
  7. Writes state.json (+ clears processed pending_actions.json)
"""
import argparse
import json
import os
import time
import uuid

import config
from src import (
    data_sources, rug_check, social_signals, scoring, trading_engine,
    wallet_tracker, ai_narrative, circuit_breaker,
)

PENDING_ACTIONS_FILE = os.path.join(os.path.dirname(__file__), "data", "pending_actions.json")


def load_state() -> dict:
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "open_positions": [], "closed_trades": [], "candidates": [],
        "pending_confirmations": [], "last_run": None, "paused_reason": None,
        "mode": config.AUTO_TRADE_MODE,
    }


def save_state(state: dict):
    os.makedirs(os.path.dirname(config.STATE_FILE), exist_ok=True)
    state["last_run"] = time.time()
    state["dry_run"] = config.DRY_RUN
    state["mode"] = config.AUTO_TRADE_MODE
    state["total_capital_usd"] = config.TOTAL_CAPITAL_USD
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_pending_actions() -> list:
    """Actions written by the dashboard (Confirm/Skip button clicks)."""
    if not os.path.exists(PENDING_ACTIONS_FILE):
        return []
    try:
        with open(PENDING_ACTIONS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def clear_pending_actions():
    os.makedirs(os.path.dirname(PENDING_ACTIONS_FILE), exist_ok=True)
    with open(PENDING_ACTIONS_FILE, "w") as f:
        json.dump([], f)


def apply_dashboard_decisions(state: dict):
    """Resolve any Confirm/Skip clicks the dashboard has queued up."""
    actions = load_pending_actions()
    if not actions:
        return
    pending_by_id = {p["request_id"]: p for p in state.get("pending_confirmations", [])}

    for action in actions:
        req_id = action.get("request_id")
        decision = action.get("action")  # "confirm" or "skip"
        candidate = pending_by_id.pop(req_id, None)
        if not candidate:
            continue  # already expired / processed / stale click

        if decision == "confirm":
            _open_position_from_candidate(state, candidate, candidate["proposed_size_usd"])
            print(f"[CONFIRMED] {candidate['symbol']} opened via dashboard confirm.")
        else:
            print(f"[SKIPPED] {candidate['symbol']} skipped via dashboard.")

    state["pending_confirmations"] = list(pending_by_id.values())
    clear_pending_actions()


def expire_stale_confirmations(state: dict):
    now = time.time()
    timeout_s = config.CONFIRMATION_TIMEOUT_MINUTES * 60
    still_pending = []
    for p in state.get("pending_confirmations", []):
        if now - p["proposed_at"] > timeout_s:
            print(f"[EXPIRED] {p['symbol']} confirmation window closed with no response.")
        else:
            still_pending.append(p)
    state["pending_confirmations"] = still_pending


def manage_open_positions(state: dict):
    still_open = []
    for pos in state["open_positions"]:
        pair = data_sources.get_pair_details(pos["pair_address"])
        if not pair:
            still_open.append(pos)  # couldn't fetch price this round, leave it
            continue
        current_price = data_sources.extract_price_usd(pair)
        exit_decision = trading_engine.evaluate_exit(pos, current_price)
        if exit_decision:
            pos["exit_price"] = current_price
            pos["closed_at"] = time.time()
            pos["exit_reason"] = exit_decision["reason"]
            pos["pnl_pct"] = round(exit_decision["pct_change"], 2)
            pos["pnl_usd"] = round(pos["entry_usd"] * exit_decision["pct_change"] / 100, 4)
            pos["status"] = "closed"
            state["closed_trades"].append(pos)
            print(f"[EXIT] {pos['token_symbol']} closed: {exit_decision['reason']} "
                  f"({pos['pnl_pct']}%)")
            if not config.DRY_RUN:
                # TODO: call trading_engine.execute_swap_live(...) to sell here
                pass
        else:
            still_open.append(pos)
    state["open_positions"] = still_open


def _open_position_from_candidate(state: dict, candidate: dict, size_usd: float):
    pair = data_sources.get_pair_details(candidate["pair_address"])
    if not pair:
        print(f"[skip] Could not refetch pair for {candidate['symbol']}, aborting entry.")
        return
    price_now = data_sources.extract_price_usd(pair)
    position = trading_engine.open_position(pair, candidate, price_now)
    position["entry_usd"] = size_usd
    state["open_positions"].append(position)
    print(f"[ENTRY] Opened {candidate['symbol']} for ${size_usd} "
          f"(score {candidate['composite_score']}) — DRY_RUN={config.DRY_RUN}")
    if not config.DRY_RUN:
        # TODO: call trading_engine.execute_swap_live(...) to actually buy here
        pass


def scan_and_decide(state: dict, breaker_status: dict):
    if len(state["open_positions"]) >= config.MAX_OPEN_POSITIONS:
        print("[scan] Max open positions reached, skipping scan.")
        return
    if state.get("pending_confirmations"):
        print("[scan] Already have a trade awaiting confirmation, skipping new scan.")
        return

    print("[scan] Fetching candidate pairs...")
    pairs = data_sources.search_new_pairs()
    signal_map = wallet_tracker.build_watchlist_signal_map() if config.WATCHED_WALLETS else {}

    candidates = []
    best = None

    for pair in pairs:
        mint = (pair.get("baseToken") or {}).get("address")
        symbol = (pair.get("baseToken") or {}).get("symbol", "?")
        if not mint:
            continue

        liquidity = data_sources.extract_liquidity_usd(pair)
        if liquidity < config.MIN_LIQUIDITY_USD:
            continue

        rug_result = rug_check.check_token(mint)
        social_result = social_signals.score_socials(data_sources.extract_socials(pair))
        wallets_holding = wallet_tracker.wallets_in_token(mint, signal_map)
        scored = scoring.score_token(pair, rug_result, social_result, wallets_holding)
        narrative = ai_narrative.summarize(symbol, scored)

        candidate = {
            "symbol": symbol,
            "mint": mint,
            "pair_address": pair.get("pairAddress"),
            "price_usd": data_sources.extract_price_usd(pair),
            "liquidity_usd": liquidity,
            **scored,
            "narrative": narrative,
        }
        candidates.append(candidate)

        if scoring.should_enter(scored) and (best is None or scored["composite_score"] > best["composite_score"]):
            best = candidate

    candidates.sort(key=lambda c: c["composite_score"], reverse=True)
    state["candidates"] = candidates[:15]  # keep dashboard light

    if not best:
        print("[scan] No candidate cleared the entry threshold this round.")
        return

    if not breaker_status["can_trade"]:
        print(f"[paused] {breaker_status['reason']}")
        state["paused_reason"] = breaker_status["reason"]
        return
    state["paused_reason"] = None

    size_usd = trading_engine.position_size_usd(state["open_positions"])
    if size_usd <= 0:
        print("[scan] No capital available for a new position.")
        return

    if config.AUTO_TRADE_MODE == "auto":
        _open_position_from_candidate(state, best, size_usd)
    else:
        best["proposed_size_usd"] = size_usd
        best["proposed_at"] = time.time()
        best["request_id"] = uuid.uuid4().hex[:12]
        state.setdefault("pending_confirmations", []).append(best)
        print(f"[PENDING] {best['symbol']} (score {best['composite_score']}) queued for "
              f"dashboard confirmation — open the Pages site to Confirm or Skip.")


def run_once():
    state = load_state()
    apply_dashboard_decisions(state)
    expire_stale_confirmations(state)
    manage_open_positions(state)
    breaker_status = circuit_breaker.check_can_trade(state)
    scan_and_decide(state, breaker_status)
    save_state(state)
    print(f"[done] Mode={config.AUTO_TRADE_MODE} · Open: {len(state['open_positions'])} · "
          f"Pending confirm: {len(state.get('pending_confirmations', []))} · "
          f"Closed: {len(state['closed_trades'])} · Candidates: {len(state['candidates'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run continuously instead of once")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between loop iterations")
    args = parser.parse_args()

    if args.loop:
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[error] {e}")
            time.sleep(args.interval)
    else:
        run_once()
