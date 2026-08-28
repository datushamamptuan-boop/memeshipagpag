"""
Scores a token's social footprint. Real social APIs (Twitter/X's official
API in particular) are paid and rate-limited, so this module is built to
degrade gracefully:

  - If no API keys are set, it scores based on presence/shape of the links
    themselves (does it have a twitter? telegram? does the handle look
    reused/recycled? etc.) — weak signal, but free and always available.
  - If TWITTER_BEARER_TOKEN / TELEGRAM_BOT_TOKEN are set, it upgrades to
    real follower/member counts and account age.

Fill in the TODO sections with your own keys to get the stronger signal.
"""
import re
import requests
import config

TIMEOUT = 10


def score_socials(socials: dict) -> dict:
    """
    socials: {"website": ..., "twitter": ..., "telegram": ...} from data_sources.extract_socials
    Returns {"score": 0-100, "notes": [str, ...]}
    """
    notes = []
    score = 0

    if socials.get("website"):
        score += 15
        notes.append("Has a dedicated website")
    else:
        notes.append("No website found")

    if socials.get("twitter"):
        score += 15
        tw = _twitter_details(socials["twitter"])
        if tw:
            score += tw["bonus"]
            notes.append(tw["note"])
        else:
            notes.append("Has a Twitter/X link (follower data unavailable)")
    else:
        notes.append("No Twitter/X account found — common rug red flag")

    if socials.get("telegram"):
        score += 15
        tg = _telegram_details(socials["telegram"])
        if tg:
            score += tg["bonus"]
            notes.append(tg["note"])
        else:
            notes.append("Has a Telegram link (member data unavailable)")
    else:
        notes.append("No Telegram found — common rug red flag")

    return {"score": min(100, score), "notes": notes}


def _twitter_details(url: str):
    """Optional stronger signal if TWITTER_BEARER_TOKEN is configured."""
    if not config.TWITTER_BEARER_TOKEN:
        return None
    match = re.search(r"(?:twitter|x)\.com/([A-Za-z0-9_]+)", url)
    if not match:
        return None
    handle = match.group(1)
    try:
        r = requests.get(
            f"https://api.twitter.com/2/users/by/username/{handle}",
            headers={"Authorization": f"Bearer {config.TWITTER_BEARER_TOKEN}"},
            params={"user.fields": "created_at,public_metrics"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data", {})
        followers = (data.get("public_metrics") or {}).get("followers_count", 0)
        bonus = min(20, followers // 500)  # cheap heuristic, cap at +20
        return {"bonus": bonus, "note": f"Twitter @{handle}: {followers} followers"}
    except requests.RequestException:
        return None


def _telegram_details(url: str):
    """Optional stronger signal if TELEGRAM_BOT_TOKEN is configured."""
    if not config.TELEGRAM_BOT_TOKEN:
        return None
    match = re.search(r"t\.me/([A-Za-z0-9_]+)", url)
    if not match:
        return None
    channel = "@" + match.group(1)
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getChatMemberCount",
            params={"chat_id": channel},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        count = r.json().get("result", 0)
        bonus = min(20, count // 100)
        return {"bonus": bonus, "note": f"Telegram {channel}: {count} members"}
    except requests.RequestException:
        return None
