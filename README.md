# Memecoin Tracker

A Solana memecoin scanner/risk-manager that:

- Pulls new/trending pairs from **DexScreener** (free, keyless)
- Runs a **rug-risk check** via **RugCheck** (mint/freeze authority, LP lock %, top-holder concentration)
- Scores **social presence** (website/Twitter/Telegram; stronger with optional API keys)
- Optionally **shadows wallets you trust** to see what they're accumulating
- Combines all of that into one composite score, and applies **stop-loss / take-profit / trailing-stop** rules
- Runs entirely on **GitHub Actions** (scheduled scans) + **GitHub Pages** (dashboard) — no server needed
- Defaults to **paper trading (dry run)** — it will not touch real money unless you explicitly turn that on

## Read this before anything else

- **No bot can guarantee profit, "perfect" entries, or that it will "dominate the market."** Anything claiming that is lying to you, including hype around bots like this one. This tool manages risk with clear rules; it does not remove risk.
- Memecoins fail far more often than they succeed. RugCheck and social scoring catch *known* red flags — they cannot catch a determined scammer, and they cannot predict price.
- With **$5 of capital**, expect Solana network fees, DEX swap fees, and slippage to eat a real chunk of any trade. This is realistic on Solana (fees are usually cents, not dollars) but still matters at this size — you're not going to compound $5 into real money quickly no matter how good the logic is.
- **Live trading is optional and off by default.** Turning it on means a script holds your private key and submits real transactions. Only fund a wallet you are fully prepared to lose entirely, and never your main wallet.

## How it works

```
main.py
 ├─ src/data_sources.py     → pulls pairs & prices from DexScreener
 ├─ src/rug_check.py        → security/rug-risk report from RugCheck
 ├─ src/social_signals.py   → scores website/Twitter/Telegram presence
 ├─ src/wallet_tracker.py   → checks tracked wallets' recent token activity
 ├─ src/scoring.py          → combines everything into one 0-100 score
 ├─ src/trading_engine.py   → position sizing + stop-loss/take-profit/trailing-stop
 ├─ src/ai_narrative.py     → optional Claude-generated plain-English summary
 └─ data/state.json         → written every run; the dashboard reads this
dashboard/index.html         → GitHub Pages site that displays state.json
.github/workflows/scan.yml   → runs main.py on a schedule via GitHub Actions
```

Composite score weighting: **40% safety, 25% market (liquidity/volume), 20% social, 15% smart-wallet signal.** Safety is weighted highest on purpose — for a small bankroll, avoiding a rug matters more than catching every pump.

## Step-by-step setup

### 1. Get the code onto your machine
If you're reading this after downloading a zip, just extract it. Otherwise:
```bash
git clone <your-repo-url>
cd memecoin-tracker
```

### 2. Create a GitHub repo and push
```bash
git init
git add .
git commit -m "Initial commit: memecoin tracker"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```
Make the repo **private** if you plan to add any API keys as secrets later — private repos are safer for anything money-adjacent.

### 3. Enable GitHub Pages (for the dashboard)
- Go to your repo → **Settings → Pages**
- Under "Build and deployment", set Source to **Deploy from a branch**
- Branch: `main`, folder: `/ (root)` — or `/dashboard` if GitHub gives you that option (if only root is available, move `dashboard/index.html` to the repo root, or point Pages at `/docs` and rename the folder to `docs`)
- After a minute, GitHub gives you a URL like `https://<username>.github.io/<repo>/` — open it on **any device** to see the dashboard

### 4. Point the dashboard at your real state file
Open `dashboard/index.html` and change:
```js
const STATE_URL = "../data/state.json";
```
to the raw GitHub URL for your repo, e.g.:
```js
const STATE_URL = "https://raw.githubusercontent.com/<username>/<repo>/main/data/state.json";
```
Commit and push that change.

### 5. Enable the scheduled scanner
The workflow at `.github/workflows/scan.yml` already runs every 15 minutes automatically once it's on GitHub (edit the `cron` line to change frequency). You can also trigger it manually anytime: **Actions tab → Memecoin Scanner → Run workflow**.

It will commit an updated `data/state.json` back to your repo after every run — that's what powers the dashboard.

### 6. Choose Confirm or Auto mode
Set `AUTO_TRADE_MODE` in the workflow file (or as a repo variable) to:

- **`confirm`** (default) — when a candidate clears the entry threshold, it shows up on your dashboard as a card with the AI's plain-English reasoning and **Confirm / Skip** buttons. Nothing executes until you tap one. Do this from the settings gear on the dashboard: paste in a GitHub personal access token (fine-grained, scoped to just this repo, with **Contents: read & write** and **Actions: read & write** permissions — never use a token with broader access, and never paste it anywhere else). It's stored only in your browser's local storage.
- **`auto`** — trades execute the instant a signal clears the threshold, no tap required. This still respects two hard circuit breakers that are **always on regardless of mode**:
  - `MAX_DAILY_LOSS_PCT` (default 30%) — if today's realized losses hit this, trading pauses until the next UTC day
  - `MAX_CONSECUTIVE_LOSSES` (default 3) + `CONSECUTIVE_LOSS_COOLDOWN_MINUTES` (default 120) — after this many losses in a row, it pauses for a cooldown instead of continuing to trade through a bad streak

  These aren't there to slow you down for no reason — they're what stops one bad run from taking the whole bankroll while you're not watching. You can loosen them in `.env`/the workflow file, but I'd think carefully before removing them entirely.

### 7. Add stronger signals via secrets (optional)
Go to **Settings → Secrets and variables → Actions → New repository secret** and add any of:
| Secret | Purpose |
|---|---|
| `HELIUS_API_KEY` | Faster/more reliable Solana RPC for wallet tracking (free tier at helius.dev) |
| `TWITTER_BEARER_TOKEN` | Real follower counts instead of just "has a link" |
| `TELEGRAM_BOT_TOKEN` | (Optional, unused by default — dashboard confirm doesn't need this) |
| `ANTHROPIC_API_KEY` | Plain-English narrative summaries of each candidate, shown on confirm cards |
| `WATCHED_WALLETS` | Comma-separated Solana wallet addresses to shadow |

None of these are required — the bot works with sensible fallbacks without them.

### 8. Run locally too, if you want (optional)
```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env if you want to change any thresholds
python main.py            # single scan
python main.py --loop --interval 300   # keep running every 5 minutes
```

### 9. Live trading (only if you're sure)
This is **off by default** and stays off unless you explicitly opt in. If you do:
1. Create a **new, dedicated** Solana wallet — do not reuse an existing one.
2. Fund it with only the amount you're fully prepared to lose.
3. `pip install solders solana`
4. Set `LIVE_TRADING=true` and `SOLANA_PRIVATE_KEY=<your base58 key>` — locally in `.env`, **not** as a GitHub Actions secret (avoid putting a live private key in CI at all if you can help it; run live trading from your own machine instead).
5. Watch it closely, especially at first. Nothing here removes the need for judgment.

## Tuning the risk rules
All in `.env` / `config.py`:
- `STOP_LOSS_PCT` — how much a position can drop before auto-exit (default 25%)
- `TAKE_PROFIT_PCT` — target gain to lock in (default 60%)
- `TRAILING_STOP_PCT` — once in profit, how far it can pull back from its peak before exiting (default 20%)
- `ENTRY_SCORE_THRESHOLD` — minimum composite score (0-100) required to enter (default 70, conservative)
- `MIN_LIQUIDITY_USD` / `MAX_TOP_HOLDER_PCT` — hard filters, tokens failing these are skipped regardless of score

Raise `ENTRY_SCORE_THRESHOLD` for fewer, higher-conviction trades. Lower it and you'll trade more often but with weaker signal — that's a real trade-off, not a free upgrade.

## Limitations, honestly
- DexScreener/RugCheck data can lag or be wrong; always treat flags as "known so far," not certainty.
- The public Solana RPC used for wallet tracking is rate-limited; get a free Helius key if you rely on this feature.
- Twitter/Telegram scoring is weak without API keys — presence of a link isn't proof of a real community.
- This is heuristic risk management, not alpha generation. It won't find winners no other tool can see.
