"""
Central configuration for the memecoin tracker.
Everything is driven by environment variables so the same code works
locally, in GitHub Actions, or on any host — you never hard-code secrets.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # no-op in CI where real env vars/secrets are injected


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Safety switches. DRY_RUN=True means the bot only simulates trades and
# writes them to data/state.json. Nothing ever touches real funds unless
# you explicitly flip LIVE_TRADING to true AND provide a private key.
# ---------------------------------------------------------------------------
DRY_RUN = not _bool("LIVE_TRADING", "false")

# Chain / data sources
CHAIN = "solana"  # Axiom trades primarily on Solana
DEXSCREENER_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
DEXSCREENER_PAIRS_URL = "https://api.dexscreener.com/latest/dex/pairs/solana"
RUGCHECK_REPORT_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL = "https://quote-api.jup.ag/v6/swap"

# Optional API keys (leave blank to skip that data source gracefully)
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
SOLANA_RPC_URL = os.getenv(
    "SOLANA_RPC_URL",
    f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}" if HELIUS_API_KEY
    else "https://api.mainnet-beta.solana.com",
)
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # optional narrative summaries

# Wallets you want to shadow / copy-signal from (comma separated addresses)
WATCHED_WALLETS = [w.strip() for w in os.getenv("WATCHED_WALLETS", "").split(",") if w.strip()]

# Capital & risk management — tuned for a small ~$5 bankroll.
TOTAL_CAPITAL_USD = _float("TOTAL_CAPITAL_USD", 5.0)
MAX_RISK_PER_TRADE_PCT = _float("MAX_RISK_PER_TRADE_PCT", 20.0)      # % of capital risked per trade
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", 25.0)                          # exit if price drops this %
TAKE_PROFIT_PCT = _float("TAKE_PROFIT_PCT", 60.0)                      # exit if price rises this %
TRAILING_STOP_PCT = _float("TRAILING_STOP_PCT", 20.0)                  # trail from local high once in profit
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "1"))         # $5 capital = don't split it further

# Filters — tokens that don't clear these are ignored outright
MIN_LIQUIDITY_USD = _float("MIN_LIQUIDITY_USD", 3000.0)
MIN_PAIR_AGE_MINUTES = _float("MIN_PAIR_AGE_MINUTES", 10.0)   # skip brand-new pairs (highest snipe/rug risk)
MAX_TOP_HOLDER_PCT = _float("MAX_TOP_HOLDER_PCT", 20.0)       # reject if one wallet holds more than this

# Composite score threshold to open a position (0-100 scale, see src/scoring.py)
ENTRY_SCORE_THRESHOLD = _float("ENTRY_SCORE_THRESHOLD", 70.0)

# Live trading (Jupiter swap) — only used if LIVE_TRADING=true
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")  # base58 secret key, NEVER commit this
SLIPPAGE_BPS = int(os.getenv("SLIPPAGE_BPS", "300"))  # 3% default, memecoins are volatile

# ---------------------------------------------------------------------------
# Trade authorization mode
#   "confirm" (default): bot proposes a trade + AI reasoning via Telegram,
#                         a human taps Confirm/Skip before anything executes.
#   "auto": bot executes the moment a signal clears threshold, no tap needed.
# "auto" still respects the circuit breakers below — those are not optional,
# they're what stops one bad streak from wiping the whole bankroll unattended.
# ---------------------------------------------------------------------------
AUTO_TRADE_MODE = os.getenv("AUTO_TRADE_MODE", "confirm").strip().lower()
if AUTO_TRADE_MODE not in ("confirm", "auto"):
    AUTO_TRADE_MODE = "confirm"

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # where confirmation requests are sent
CONFIRMATION_TIMEOUT_MINUTES = _float("CONFIRMATION_TIMEOUT_MINUTES", 10.0)

# Circuit breakers — always enforced, in both confirm and auto mode.
MAX_DAILY_LOSS_PCT = _float("MAX_DAILY_LOSS_PCT", 30.0)          # % of capital lost today -> pause till tomorrow
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
CONSECUTIVE_LOSS_COOLDOWN_MINUTES = _float("CONSECUTIVE_LOSS_COOLDOWN_MINUTES", 120.0)

STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "state.json")
