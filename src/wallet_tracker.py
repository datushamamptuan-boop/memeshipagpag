"""
Tracks specific Solana wallets (config.WATCHED_WALLETS) to see what they're
buying, so a token that several historically-profitable wallets are
accumulating gets a boost in the composite score.

Uses the public Solana RPC (getSignaturesForAddress / getTransaction) via
config.SOLANA_RPC_URL. Works with the free public RPC but is rate-limited;
for reliable use, get a free Helius API key and set HELIUS_API_KEY.
"""
import time
import requests
import config

TIMEOUT = 15


def _rpc(method: str, params: list):
    try:
        r = requests.post(
            config.SOLANA_RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("result")
    except requests.RequestException as e:
        print(f"[wallet_tracker] RPC call failed: {e}")
        return None


def get_recent_token_mints_touched(wallet: str, limit: int = 20):
    """
    Returns a set of token mint addresses this wallet has interacted with
    recently, based on its latest transaction signatures. This is a light
    heuristic (not a full parsed trade history) to keep RPC usage cheap.
    """
    sigs = _rpc("getSignaturesForAddress", [wallet, {"limit": limit}])
    if not sigs:
        return set()

    mints = set()
    for sig_info in sigs:
        sig = sig_info.get("signature")
        if not sig:
            continue
        tx = _rpc("getTransaction", [sig, {"maxSupportedTransactionVersion": 0}])
        if not tx:
            continue
        meta = tx.get("meta", {}) or {}
        for balances_key in ("postTokenBalances", "preTokenBalances"):
            for bal in meta.get(balances_key, []) or []:
                mint = bal.get("mint")
                if mint:
                    mints.add(mint)
        time.sleep(0.1)  # be gentle with public RPC rate limits
    return mints


def build_watchlist_signal_map():
    """
    Pre-fetches recent activity for every configured watched wallet.
    Returns {mint_address: [wallet, wallet, ...]} so scoring.py can quickly
    check "is any smart wallet already in this token?".
    """
    signal_map = {}
    for wallet in config.WATCHED_WALLETS:
        for mint in get_recent_token_mints_touched(wallet):
            signal_map.setdefault(mint, []).append(wallet)
    return signal_map


def wallets_in_token(mint_address: str, signal_map: dict):
    return signal_map.get(mint_address, [])
