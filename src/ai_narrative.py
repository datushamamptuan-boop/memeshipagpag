"""
Optional: turns the structured score breakdown into a short, plain-English
narrative using the Claude API. This is the "AI overlooking the process"
piece — it explains and summarizes the same numbers you can already see,
it does not gain any extra market-predicting power from being an LLM.

Skipped automatically if ANTHROPIC_API_KEY is not set (the bot works fine
without it — this is a readability nicety, not the decision-maker).
"""
import config


def summarize(token_symbol: str, scored: dict) -> str:
    if not config.ANTHROPIC_API_KEY:
        return ""

    try:
        import anthropic
    except ImportError:
        return ""

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = (
        f"Token: {token_symbol}\n"
        f"Composite score: {scored['composite_score']}/100\n"
        f"Safety score: {scored['safety_score']}/100\n"
        f"Market score: {scored['market_score']}/100\n"
        f"Social score: {scored['social_score']}/100\n"
        f"Smart-wallet score: {scored['wallet_score']}/100\n"
        f"Signals:\n- " + "\n- ".join(scored["reasons"]) + "\n\n"
        "In 2-3 plain sentences, summarize the risk/opportunity picture for "
        "a retail trader with a very small ($5) bankroll. Be balanced and "
        "explicit about uncertainty — do not claim any prediction is "
        "reliable, and do not tell them to buy or not buy."
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    except Exception as e:
        print(f"[ai_narrative] Claude API call failed: {e}")
        return ""
