# USD per 1M tokens (input, output), standard tier, checked 2026-10-26; unlisted ids report n/a.
# https://platform.claude.com/docs/en/about-claude/pricing (Haiku price is for prompts up to 100k tokens)
# https://developers.openai.com/api/docs/pricing (short-context tier)
# https://docs.mistral.ai/inference/pricing (-latest aliases can move to a new model and price)
PRICE_PER_MILLION: dict[str, tuple[float, float]] = {
    "anthropic:claude-opus-5-5": (4.00, 20.00),
    "anthropic:claude-sonnet-5-5": (2.00, 10.00),
    "anthropic:claude-haiku-5-5": (0.10, 0.50),
    "openai:gpt-6-astra": (10.00, 50.00),
    "openai:gpt-6.1-sol": (2.00, 10.00),
    "openai:gpt-6-luna": (0.10, 0.50),
    "mistralai:mistral-medium-latest": (1.50, 7.50),
    "mistralai:mistral-small-latest": (0.15, 0.60),
}


def cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = PRICE_PER_MILLION.get(model_id)
    if prices is None:
        return None
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000
