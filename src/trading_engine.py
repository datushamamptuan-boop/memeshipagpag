"""
Manages position sizing and entry/exit rules. Defaults to DRY_RUN (paper
trading) — it writes what it *would* have done to data/state.json without
touching real funds. Live execution via Jupiter is implemented but gated
hard behind config.DRY_RUN / LIVE_TRADING and requires you to supply your
own private key. There is no "auto-become-profitable" switch — these are
plain stop-loss/take-profit/trailing-stop rules, same as any basic bot.
"""
import time
import config


def position_size_usd(open_positions: list) -> float:
    """
    How much (in USD) to put into a new trade. With MAX_OPEN_POSITIONS=1
    and a $5 bankroll, this simply risks MAX_RISK_PER_TRADE_PCT of what's
    left, so one bad trade never wipes the whole bankroll if you raise
    MAX_OPEN_POSITIONS later.
    """
    available = config.TOTAL_CAPITAL_USD - sum(p["entry_usd"] for p in open_positions)
    size = available * (config.MAX_RISK_PER_TRADE_PCT / 100)
    return max(0.0, round(min(size, available), 4))


def open_position(pair: dict, scored: dict, price_usd: float) -> dict:
    from src.data_sources import extract_price_usd

    size_usd = 0  # filled in by caller after checking open_positions
    return {
        "pair_address": pair.get("pairAddress"),
        "token_symbol": (pair.get("baseToken") or {}).get("symbol", "?"),
        "mint_address": (pair.get("baseToken") or {}).get("address"),
        "entry_price": price_usd,
        "entry_usd": size_usd,
        "high_water_price": price_usd,
        "opened_at": time.time(),
        "composite_score_at_entry": scored["composite_score"],
        "status": "open",
    }


def evaluate_exit(position: dict, current_price: float) -> dict | None:
    """
    Returns an exit decision dict if the position should be closed, else None.
    Checks, in order: stop-loss, trailing-stop (once in profit), take-profit.
    """
    entry = position["entry_price"]
    if entry <= 0:
        return None

    pct_change = (current_price - entry) / entry * 100

    if pct_change <= -config.STOP_LOSS_PCT:
        return {"reason": "stop_loss", "pct_change": pct_change}

    if current_price > position.get("high_water_price", entry):
        position["high_water_price"] = current_price

    high = position.get("high_water_price", entry)
    drawdown_from_high = (current_price - high) / high * 100
    is_in_profit = current_price > entry
    if is_in_profit and drawdown_from_high <= -config.TRAILING_STOP_PCT:
        return {"reason": "trailing_stop", "pct_change": pct_change}

    if pct_change >= config.TAKE_PROFIT_PCT:
        return {"reason": "take_profit", "pct_change": pct_change}

    return None


def execute_swap_live(input_mint: str, output_mint: str, amount_lamports: int):
    """
    LIVE TRADING — only runs if config.DRY_RUN is False and a private key
    is configured. Uses Jupiter's aggregator to route the swap.

    SECURITY WARNING: this signs and submits a real on-chain transaction
    with real funds. Test thoroughly in DRY_RUN first. Never commit your
    private key to git — use an environment secret. Prefer running live
    trading locally rather than in CI/GitHub Actions, since anything with
    access to your repo's secrets could theoretically reach a compromised
    workflow step.
    """
    if config.DRY_RUN:
        raise RuntimeError("execute_swap_live called while DRY_RUN is True — refusing to trade.")
    if not config.SOLANA_PRIVATE_KEY:
        raise RuntimeError("LIVE_TRADING is on but SOLANA_PRIVATE_KEY is not set.")

    try:
        import requests
        import base64
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
        from solana.rpc.api import Client
    except ImportError as e:
        raise RuntimeError(
            "Live trading needs extra packages. Run: "
            "pip install solders solana"
        ) from e

    keypair = Keypair.from_base58_string(config.SOLANA_PRIVATE_KEY)
    client = Client(config.SOLANA_RPC_URL)

    quote = requests.get(
        config.JUPITER_QUOTE_URL,
        params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount_lamports,
            "slippageBps": config.SLIPPAGE_BPS,
        },
        timeout=15,
    ).json()

    swap_resp = requests.post(
        config.JUPITER_SWAP_URL,
        json={
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True,
        },
        timeout=15,
    ).json()

    swap_tx_b64 = swap_resp["swapTransaction"]
    raw_tx = VersionedTransaction.from_bytes(base64.b64decode(swap_tx_b64))
    signed_tx = VersionedTransaction(raw_tx.message, [keypair])
    result = client.send_raw_transaction(bytes(signed_tx))
    return {"signature": str(result.value)}
