"""
Pulls raw market data for Solana memecoin pairs from DexScreener's free,
keyless public API. This is the same data Axiom itself is largely built on
top of (pair creation time, liquidity, volume, price change, socials).
"""
import time
import requests
import config

TIMEOUT = 10


def _get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[data_sources] request failed: {url} -> {e}")
        return None


def search_new_pairs(query: str = "solana"):
    """
    Returns a list of recently created Solana pairs matching a broad query.
    DexScreener's /search endpoint is the closest free equivalent to
    Axiom's "new pairs" / "trending" feed.
    """
    data = _get(config.DEXSCREENER_SEARCH_URL, params={"q": query})
    if not data or "pairs" not in data:
        return []

    pairs = [p for p in data["pairs"] if p.get("chainId") == config.CHAIN]
    now_ms = time.time() * 1000
    fresh = []
    for p in pairs:
        created_at = p.get("pairCreatedAt")
        if not created_at:
            continue
        age_minutes = (now_ms - created_at) / 60000
        if age_minutes >= config.MIN_PAIR_AGE_MINUTES:
            p["_age_minutes"] = age_minutes
            fresh.append(p)
    return fresh


def get_pair_details(pair_address: str):
    """Fetch full detail for one known pair address."""
    data = _get(f"{config.DEXSCREENER_PAIRS_URL}/{pair_address}")
    if not data or not data.get("pairs"):
        return None
    return data["pairs"][0]


def extract_socials(pair: dict) -> dict:
    """
    DexScreener surfaces whatever socials the token team has submitted
    (website, twitter, telegram) inside pair['info'].
    """
    info = pair.get("info", {}) or {}
    socials = {"website": None, "twitter": None, "telegram": None}
    for site in info.get("websites", []) or []:
        socials["website"] = site.get("url")
    for s in info.get("socials", []) or []:
        stype = (s.get("type") or "").lower()
        if stype in socials:
            socials[stype] = s.get("url")
    return socials


def extract_liquidity_usd(pair: dict) -> float:
    return float((pair.get("liquidity") or {}).get("usd") or 0)


def extract_volume_24h(pair: dict) -> float:
    return float((pair.get("volume") or {}).get("h24") or 0)


def extract_price_usd(pair: dict) -> float:
    try:
        return float(pair.get("priceUsd") or 0)
    except (TypeError, ValueError):
        return 0.0
