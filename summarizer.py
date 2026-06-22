"""
summarizer.py — AI summary using OpenAI-compatible providers.

Supports: Groq (free), DeepSeek, OpenAI
Uses the openai package with different base URLs.

One-time setup: paste your API key in API_KEY below.
"""

import logging
import time

logger = logging.getLogger(__name__)

# ── One-time setup: paste your API key here ──
API_KEY = "gsk_1IcVVVVVVVVVVVjMvw5kS2OaNeFNwULxKWzwCj"
AI_PROVIDER = "groq"

PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}


def _call_ai(prompt: str, api_key: str, provider: str, max_tokens: int = 2000) -> str:
    """Call an OpenAI-compatible AI API."""
    from openai import OpenAI

    config = PROVIDERS.get(provider, PROVIDERS["groq"])
    client = OpenAI(api_key=api_key, base_url=config["base_url"])

    for attempt in range(1, 3):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=[
                    {"role": "system", "content": "You are a web content analyst. Write clear, factual summaries."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("AI attempt %d failed: %s", attempt, str(e)[:120])
            if attempt < 2:
                time.sleep(10)

    raise Exception(f"AI summary failed after 2 attempts via {provider}")


def _build_prompt(data: dict) -> str:
    """Build a rich prompt from scraped page data."""
    parts = []
    parts.append(f"TITLE: {data.get('title', 'N/A')}")
    if data.get("description"):
        parts.append(f"DESCRIPTION: {data['description']}")
    parts.append(
        f"TOTAL: {len(data.get('headings', []))} headings, "
        f"{len(data.get('paragraphs', []))} paragraphs, "
        f"{len(data.get('links', []))} links, "
        f"{len(data.get('images', []))} images"
    )

    if data.get("headings"):
        parts.append("\nHEADINGS:")
        for h in data["headings"][:15]:
            parts.append(f"  {'#' * h.get('level', 2)} {h['text']}")

    if data.get("paragraphs"):
        parts.append("\nKEY CONTENT (first 20 paragraphs):")
        for p in data["paragraphs"][:20]:
            parts.append(f"  - {p[:300]}")

    if data.get("lists"):
        parts.append("\nKEY LISTS:")
        for lst in data["lists"][:5]:
            parts.append(f"  [{lst.get('type')}]:")
            for item in lst["items"][:8]:
                parts.append(f"    - {item[:200]}")

    if data.get("links"):
        parts.append("\nTOP LINKS:")
        for l in data["links"][:10]:
            badge = "[EXT]" if l.get("is_external") else "[INT]"
            parts.append(f"  {badge} {l['text']} -> {l['url']}")

    if data.get("tables"):
        parts.append("\nTABLES:")
        for idx, table in enumerate(data["tables"][:3], 1):
            parts.append(f"  Table {idx}:")
            for row in table[:5]:
                parts.append(f"    | {'  |  '.join(row[:5])} |")

    prompt = (
        "You are a web content analyst. Summarize the following scraped page content.\n\n"
        + "\n".join(parts)
        + "\n\nProvide a comprehensive summary with these sections:\n"
        "1. OVERVIEW - What is this page about? (2-3 sentences)\n"
        "2. KEY POINTS - Main takeaways in bullet points (5-10 points)\n"
        "3. IMPORTANT LINKS - Top 5 most useful links with brief descriptions\n"
        "4. DATA HIGHLIGHTS - Any notable data, statistics, or tables found\n"
        "5. CONTENT TYPE - What kind of page is this? (blog, docs, landing page, wiki, etc.)\n\n"
        "Be specific. Use facts from the content. Do NOT make up information."
    )
    return prompt


def generate_summary(data: dict, api_key: str = "", provider: str = "") -> str:
    """
    Generate an AI summary of scraped page data.

    Uses the hardcoded API_KEY/AI_PROVIDER if no arguments given.
    Falls back gracefully if no key is configured.
    """
    key = api_key or API_KEY
    prov = provider or AI_PROVIDER

    if not key or key == "paste-your-groq-key-here":
        # No API key configured — return a built-in summary
        logger.info("No API key configured. Returning built-in summary.")
        return _built_in_summary(data)

    prompt = _build_prompt(data)
    logger.info("Generating AI summary via %s...", prov)
    summary = _call_ai(prompt, key, prov)
    logger.info("Summary generated (%d chars)", len(summary))
    return summary


def _built_in_summary(data: dict) -> str:
    """Generate a basic summary without any API key."""
    parts = []
    parts.append(f"TITLE: {data.get('title', 'N/A')}")
    if data.get("description"):
        parts.append(f"DESCRIPTION: {data['description']}\n")

    parts.append("KEY POINTS:")
    for h in data.get("headings", [])[:10]:
        parts.append(f"  - {h['text']}")

    for p in data.get("paragraphs", [])[:3]:
        first_sent = p.split(".")[0].strip()
        if len(first_sent) > 15:
            parts.append(f"  - {first_sent}.")

    parts.append(f"\nContent: {len(data.get('paragraphs', []))} paragraphs, "
                 f"{len(data.get('links', []))} links, "
                 f"{len(data.get('images', []))} images")

    return "\n".join(parts)