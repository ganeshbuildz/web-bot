"""
researcher.py — Advanced Topic Research Agent.

Takes ANY topic, automatically:
  1. Generates multiple search queries for broad coverage
  2. Searches DuckDuckGo across queries
  3. Scrapes and scores each page for relevance
  4. Aggregates content with sub-topic categorization
  5. Generates a detailed AI-powered research report with citations

Usage:
    from researcher import research_topic
    result = research_topic("artificial intelligence", max_pages=8)
"""

import re
import time
import logging
from urllib.parse import urlparse
from ddgs import DDGS
from bot import scrape_url

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────

# Hardcode your API key here (one-time setup) — or pass --api-key in CLI
API_KEY = "paste-your-groq-key-here"
AI_PROVIDER = "groq"

# Provider configs
PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}

_SKIP_DOMAINS = [
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com",
    "reddit.com", "google.com", "amazon.com", "ebay.com",
]
_SKIP_EXTS = [".pdf", ".jpg", ".png", ".gif", ".mp4", ".zip", ".docx", ".xlsx"]

# Relevance scoring keywords (generic boosters)
_BOOST_WORDS = [
    "introduction", "overview", "guide", "explained", "what is",
    "definition", "history", "future", "applications", "benefits",
    "challenges", "impact", "analysis", "review", "latest", "recent",
    "research", "study", "report", "statistics", "trends",
]


# ── URL Filtering ──────────────────────────────────────


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if any(s in parsed.netloc for s in _SKIP_DOMAINS):
            return False
        if any(parsed.path.lower().endswith(e) for e in _SKIP_EXTS):
            return False
        return bool(parsed.scheme) and bool(parsed.netloc)
    except Exception:
        return False


def _deduplicate_urls(urls: list) -> list:
    seen_domains = set()
    unique = []
    for url in urls:
        try:
            domain = urlparse(url).netloc.replace("www.", "")
            if domain not in seen_domains:
                seen_domains.add(domain)
                unique.append(url)
        except Exception:
            unique.append(url)
    return unique


def _score_url_relevance(url: str, title: str = "", snippet: str = "") -> float:
    """Score a URL's potential relevance (0-10). Higher = more likely useful."""
    score = 5.0  # base score

    text = (url + " " + title + " " + snippet).lower()

    # Boost for common informational keywords
    for word in _BOOST_WORDS:
        if word in text:
            score += 0.5

    # Penalize very short snippets (likely low-content pages)
    if snippet and len(snippet) < 50:
        score -= 2.0

    # Bonus for Wikipedia, educational, or known-good domains
    good_domains = ["wikipedia.org", "britannica.com", "nature.com", "arxiv.org",
                    "scholar.google.com", "medium.com", "techcrunch.com", "wired.com"]
    for gd in good_domains:
        if gd in url:
            score += 2.0
            break

    # Penalize news-only pages (often thin content)
    news_words = ["breaking", "just in", "live updates"]
    for nw in news_words:
        if nw in text:
            score -= 1.0

    return min(score, 10.0)


# ── Multi-Query Search ─────────────────────────────────


def _generate_search_queries(topic: str) -> list:
    """Generate multiple search queries for broader coverage."""
    queries = [
        topic,                           # Main topic
        f"{topic} overview guide",       # Overview
        f"{topic} latest research 2025 2026",  # Recent
        f"what is {topic} explained",    # Explanation
    ]
    # Add specific aspect queries
    aspects = [
        "applications", "benefits", "challenges",
        "future trends", "how it works", "history",
    ]
    for aspect in aspects[:3]:
        queries.append(f"{topic} {aspect}")

    return queries


def _search_all_queries(queries: list, max_results_per_query: int = 8) -> list:
    """Search across multiple queries and merge + deduplicate results."""
    all_results = {}  # url -> {url, title, snippet, score}

    try:
        ddgs = DDGS()
    except Exception as e:
        logger.error("Failed to init search: %s", e)
        return []

    for query in queries:
        logger.info("  Searching: \"%s\"", query)
        try:
            results = list(ddgs.text(query, max_results=max_results_per_query))
            for r in results:
                url = r.get("href", "")
                if _is_valid_url(url):
                    if url not in all_results:
                        all_results[url] = {
                            "url": url,
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                        }
        except Exception as e:
            logger.warning("  Search query failed: %s", str(e)[:80])
            continue

    # Score and sort
    scored = []
    for url, info in all_results.items():
        score = _score_url_relevance(url, info["title"], info["snippet"])
        scored.append((url, info, score))

    scored.sort(key=lambda x: x[2], reverse=True)

    logger.info(
        "Search complete: %d unique results across %d queries",
        len(scored), len(queries),
    )
    return scored


# ── Content Quality Scoring ────────────────────────────


def _score_page_content(data: dict, topic: str) -> float:
    """Score how rich/relevant a scraped page is (0-100)."""
    score = 0.0
    topic_lower = topic.lower()

    # Paragraph count and length
    paras = data.get("paragraphs", [])
    score += min(len(paras) * 3, 30)

    # How many paragraphs mention the topic
    topic_mentions = sum(1 for p in paras if topic_lower in p.lower())
    score += min(topic_mentions * 2, 20)

    # Heading depth
    headings = data.get("headings", [])
    score += min(len(headings) * 2, 15)

    # Has tables (data-rich)
    if data.get("tables"):
        score += 10

    # Has lists (structured info)
    if data.get("lists"):
        score += min(len(data["lists"]) * 3, 10)

    # Long paragraphs (in-depth content)
    long_paras = sum(1 for p in paras if len(p) > 200)
    score += min(long_paras * 2, 15)

    return min(score, 100)


# ── Page Scraping with Progress ────────────────────────


def _scrape_pages(scored_results: list, max_pages: int, topic: str,
                  progress_callback=None) -> list:
    """Scrape top pages with quality scoring and progress feedback."""
    pages = []
    total_to_try = min(len(scored_results), max_pages * 2)  # try 2x to account for failures

    for i, (url, info, search_score) in enumerate(scored_results[:total_to_try]):
        if len(pages) >= max_pages:
            break

        if progress_callback:
            progress_callback(i + 1, total_to_try, url, info.get("title", ""))

        logger.info("[%d/%d] Scraping: %s", i + 1, total_to_try, url[:80])
        data = scrape_url(url)

        if "error" in data:
            logger.warning("  Skipped: %s", data.get("error", "")[:80])
            continue

        # Score content quality
        content_score = _score_page_content(data, topic)
        data["_search_score"] = search_score
        data["_content_score"] = content_score
        data["_combined_score"] = (search_score + content_score) / 2

        logger.info(
            "  OK: %d paras, %d headings [content_score=%.0f]",
            len(data.get("paragraphs", [])),
            len(data.get("headings", [])),
            content_score,
        )

        pages.append(data)

    return pages


# ── Smart Aggregation ──────────────────────────────────


def _categorize_headings(headings: list, topic: str) -> dict:
    """Group headings into sub-topics for organized report."""
    topic_words = set(topic.lower().split())

    categories = {
        "definition": [],
        "history_background": [],
        "applications": [],
        "benefits_advantages": [],
        "challenges_limitations": [],
        "future_trends": [],
        "technical_details": [],
        "other": [],
    }

    def _match_category(text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["what is", "definition", "introduction", "overview"]):
            return "definition"
        if any(w in t for w in ["history", "origin", "background", "evolution", "timeline"]):
            return "history_background"
        if any(w in t for w in ["application", "use case", "example", "industry", "implementation"]):
            return "applications"
        if any(w in t for w in ["benefit", "advantage", "pro", "strength", "positive"]):
            return "benefits_advantages"
        if any(w in t for w in ["challenge", "limitation", "risk", "concern", "problem", "issue", "disadvantage"]):
            return "challenges_limitations"
        if any(w in t for w in ["future", "trend", "prediction", "outlook", "2025", "2026", "next"]):
            return "future_trends"
        if any(w in t for w in ["how", "technical", "architecture", "algorithm", "method", "process", "mechanism"]):
            return "technical_details"
        return "other"

    for h in headings:
        cat = _match_category(h.get("text", ""))
        categories[cat].append(h)

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}


def _extract_key_facts(paragraphs: list) -> list:
    """Extract sentences that look like facts, stats, or key data points."""
    facts = []
    fact_patterns = [
        r'\d+\.?\d*%.*',            # percentages
        r'\$[\d,.]+.*',            # dollar amounts
        r'\d+\s+(million|billion|trillion).*',  # large numbers
        r'(according to|research shows|studies|report|found that|estimated).*',
        r'(in \d{4}|since \d{4}|by \d{4}).*',  # year references
    ]

    seen = set()
    for p in paragraphs:
        for sentence in p["text"].split(". "):
            sentence = sentence.strip()
            if len(sentence) < 30 or len(sentence) > 300:
                continue
            if any(re.search(pat, sentence, re.IGNORECASE) for pat in fact_patterns):
                if sentence not in seen:
                    seen.add(sentence)
                    facts.append({"fact": sentence, "source": p.get("source", "")})

    return facts[:20]


def _aggregate(pages: list, topic: str) -> dict:
    """Combine data from multiple pages with categorization."""
    all_headings = []
    all_paragraphs = []
    all_links = []
    all_images = []
    all_tables = []
    all_lists = []
    seen_paragraphs = set()
    page_scores = []

    for page in pages:
        source_url = page.get("url", "")
        page_title = page.get("title", "")

        # Track page quality
        page_scores.append({
            "url": source_url,
            "title": page_title[:80],
            "paragraphs": len(page.get("paragraphs", [])),
            "headings": len(page.get("headings", [])),
            "content_score": page.get("_content_score", 0),
        })

        for h in page.get("headings", []):
            all_headings.append({**h, "source": source_url, "page_title": page_title})

        for p in page.get("paragraphs", []):
            if p not in seen_paragraphs and len(p) > 30:
                seen_paragraphs.add(p)
                all_paragraphs.append({"text": p, "source": source_url})

        for l in page.get("links", []):
            all_links.append({**l, "source": source_url})

        for img in page.get("images", []):
            all_images.append({**img, "source": source_url})

        for t in page.get("tables", []):
            all_tables.append({"rows": t, "source": source_url})

        for lst in page.get("lists", []):
            all_lists.append({**lst, "source": source_url})

    # Categorize headings into sub-topics
    categorized = _categorize_headings(all_headings, topic)

    # Extract key facts and statistics
    key_facts = _extract_key_facts(all_paragraphs)

    return {
        "topic": topic,
        "total_pages": len(pages),
        "page_scores": page_scores,
        "all_headings": all_headings,
        "categorized_headings": categorized,
        "all_paragraphs": all_paragraphs,
        "all_links": all_links,
        "all_images": all_images,
        "all_tables": all_tables,
        "all_lists": all_lists,
        "key_facts": key_facts,
    }


# ── AI Report Generation ───────────────────────────────


def _call_ai(prompt: str, api_key: str, provider: str, max_tokens: int = 4000) -> str:
    """Call an OpenAI-compatible AI API with retry logic."""
    from openai import OpenAI

    config = PROVIDERS.get(provider, PROVIDERS["groq"])
    client = OpenAI(api_key=api_key, base_url=config["base_url"])

    for attempt in range(1, 3):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=[
                    {"role": "system", "content": "You are an expert research analyst. Write detailed, factual, well-structured reports with citations."},
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

    raise Exception("AI generation failed after 2 attempts")


def _build_research_prompt(aggregate: dict, topic: str) -> str:
    """Build a rich prompt for detailed AI research report."""
    paragraphs = aggregate.get("all_paragraphs", [])
    headings = aggregate.get("all_headings", [])
    categorized = aggregate.get("categorized_headings", {})
    key_facts = aggregate.get("key_facts", [])
    tables = aggregate.get("all_tables", [])
    links = aggregate.get("all_links", [])
    page_scores = aggregate.get("page_scores", [])

    # Build source list for citations
    sources = []
    for ps in page_scores:
        sources.append(f"  [{ps['url']}] - {ps['title']}")

    parts = []
    parts.append(f"RESEARCH TOPIC: {topic}")
    parts.append(f"TOTAL SOURCES SCRAPED: {aggregate.get('total_pages', 0)}")
    parts.append("")

    # Sources
    parts.append("SOURCES:")
    for s in sources:
        parts.append(s)

    # Categorized structure
    parts.append("\nCONTENT STRUCTURE (by category):")
    cat_names = {
        "definition": "Definition & Overview",
        "history_background": "History & Background",
        "applications": "Applications & Use Cases",
        "benefits_advantages": "Benefits & Advantages",
        "challenges_limitations": "Challenges & Limitations",
        "future_trends": "Future Trends & Outlook",
        "technical_details": "Technical Details",
        "other": "Other Sections",
    }
    for cat_key, cat_headings in categorized.items():
        name = cat_names.get(cat_key, cat_key)
        parts.append(f"\n  >> {name}:")
        for h in cat_headings[:5]:
            parts.append(f"     - {h['text']}")

    # Key facts
    if key_facts:
        parts.append("\nKEY FACTS & STATISTICS FOUND:")
        for kf in key_facts[:10]:
            parts.append(f"  - {kf['fact']}")

    # Best content paragraphs (longest, most relevant)
    parts.append("\nDETAILED CONTENT FROM SOURCES:")
    # Sort by length (longer = more detailed)
    sorted_paras = sorted(paragraphs, key=lambda p: len(p["text"]), reverse=True)
    for p in sorted_paras[:20]:
        parts.append(f"  [Source: {p['source'][:50]}]")
        parts.append(f"  {p['text'][:500]}")
        parts.append("")

    # Tables with data
    if tables:
        parts.append("\nDATA TABLES FOUND:")
        for i, t in enumerate(tables[:3], 1):
            parts.append(f"  Table {i} (from {t.get('source', '')[:40]}):")
            for row in t.get("rows", [])[:6]:
                parts.append(f"    | {'  |  '.join(row[:5])} |")

    # External links
    ext_links = [l for l in links if l.get("is_external")][:10]
    if ext_links:
        parts.append("\nIMPORTANT EXTERNAL LINKS:")
        for l in ext_links:
            parts.append(f"  - {l['text']}: {l['url']}")

    # The actual prompt for the AI
    prompt = (
        "Based on ALL the research data below, write a comprehensive, detailed research report.\n\n"
        + "\n".join(parts)
        + "\n\n"
        + "═══════════════════════════════════════════════\n"
        + "REPORT STRUCTURE — Write each section with depth (3-5 sentences minimum each):\n\n"
        + "1. EXECUTIVE SUMMARY\n"
        + "   - 4-6 sentences summarizing the entire topic. What is it? Why does it matter?\n\n"
        + "2. INTRODUCTION & DEFINITION\n"
        + "   - Clear explanation of what the topic is. Context and background.\n\n"
        + "3. KEY FINDINGS\n"
        + "   - 10-15 detailed bullet points covering the most important discoveries.\n"
        + "   - Each point should be 2-3 sentences with specific details.\n\n"
        + "4. DETAILED ANALYSIS\n"
        + "   - Sub-sections for: How It Works, Applications, Benefits, Challenges.\n"
        + "   - Each sub-section should have 2-3 paragraphs with concrete details.\n\n"
        + "5. KEY STATISTICS & DATA\n"
        + "   - Any numbers, percentages, statistics, or data points found.\n"
        + "   - Present them in a readable format.\n\n"
        + "6. FUTURE OUTLOOK\n"
        + "   - Trends, predictions, and emerging developments.\n\n"
        + "7. RECOMMENDED RESOURCES\n"
        + "   - Top 5 most useful sources with brief descriptions.\n\n"
        + "8. CONCLUSION\n"
        + "   - 3-4 sentences wrapping up the key takeaways.\n\n"
        + "RULES:\n"
        + "- Use ONLY facts from the provided content. Do NOT make up information.\n"
        + "- Cite sources inline like [1], [2] referring to the source list.\n"
        + "- Be thorough and specific, not vague.\n"
        + "- Write in clear, professional language.\n"
    )

    return prompt


def _generate_research_summary(aggregate: dict, topic: str,
                               summary_type: str, api_key: str,
                               provider: str) -> str:
    """Generate summary — built-in (no key) or AI (with key)."""
    if api_key and summary_type == "ai":
        try:
            return _ai_summary(aggregate, topic, api_key, provider)
        except Exception as e:
            logger.warning("AI summary failed: %s. Falling back to built-in.", e)

    return _built_in_summary(aggregate, topic)


def _ai_summary(aggregate: dict, topic: str, api_key: str, provider: str) -> str:
    """Generate a detailed AI research report."""
    prompt = _build_research_prompt(aggregate, topic)

    config = PROVIDERS.get(provider, PROVIDERS["groq"])
    logger.info(
        "Generating AI research report via %s/%s...",
        provider, config["model"],
    )
    logger.info("Building prompt from %d paragraphs...", len(aggregate.get("all_paragraphs", [])))

    summary = _call_ai(prompt, api_key, provider, max_tokens=4000)

    logger.info("AI report generated (%d chars)", len(summary))
    return summary


def _built_in_summary(aggregate: dict, topic: str) -> str:
    """Generate a structured summary without any API key."""
    headings = aggregate.get("all_headings", [])
    paragraphs = aggregate.get("all_paragraphs", [])
    links = aggregate.get("all_links", [])
    tables = aggregate.get("all_tables", [])
    key_facts = aggregate.get("key_facts", [])
    categorized = aggregate.get("categorized_headings", {})
    total_pages = aggregate.get("total_pages", 0)

    parts = []
    parts.append(f"RESEARCH REPORT: {topic}")
    parts.append(f"Sources: {total_pages} pages scraped")
    parts.append(f"Date: {time.strftime('%Y-%m-%d')}")
    parts.append("")

    # Executive Overview
    parts.append("1. EXECUTIVE OVERVIEW")
    parts.append("-" * 40)
    if paragraphs:
        parts.append(paragraphs[0]["text"][:500])
    if len(paragraphs) > 1:
        parts.append(paragraphs[1]["text"][:400])
    parts.append("")

    # Categorized sections
    cat_names = {
        "definition": "2. DEFINITION & OVERVIEW",
        "history_background": "3. HISTORY & BACKGROUND",
        "applications": "4. APPLICATIONS & USE CASES",
        "benefits_advantages": "5. BENEFITS & ADVANTAGES",
        "challenges_limitations": "6. CHALLENGES & LIMITATIONS",
        "future_trends": "7. FUTURE TRENDS",
        "technical_details": "8. TECHNICAL DETAILS",
        "other": "9. ADDITIONAL SECTIONS",
    }

    section_num = 2
    for cat_key, cat_headings in categorized.items():
        name = cat_names.get(cat_key, f"{section_num}. {cat_key.replace('_', ' ').title()}")
        parts.append(name)
        parts.append("-" * 40)
        for h in cat_headings[:8]:
            # Find the best paragraph after this heading
            parts.append(f"  - {h['text']} (from {h.get('source', '')[:40]})")
        parts.append("")
        section_num += 1

    # Key Findings
    parts.append(f"{section_num}. KEY FINDINGS")
    parts.append("-" * 40)
    for p in paragraphs[:8]:
        first_sent = p["text"].split(".")[0].strip()
        if first_sent and len(first_sent) > 20:
            parts.append(f"  - {first_sent}.")
            parts.append(f"    Source: {p['source'][:50]}")
    parts.append("")
    section_num += 1

    # Key Facts & Statistics
    if key_facts:
        parts.append(f"{section_num}. KEY FACTS & STATISTICS")
        parts.append("-" * 40)
        for kf in key_facts[:10]:
            parts.append(f"  - {kf['fact']}")
            parts.append(f"    Source: {kf['source'][:50]}")
        parts.append("")
        section_num += 1

    # Important Links
    ext_links = [l for l in links if l.get("is_external")][:10]
    if ext_links:
        parts.append(f"{section_num}. IMPORTANT LINKS")
        parts.append("-" * 40)
        for l in ext_links:
            parts.append(f"  - {l['text']} -> {l['url']}")
        parts.append("")
        section_num += 1

    # Data Tables
    if tables:
        parts.append(f"{section_num}. DATA TABLES")
        parts.append("-" * 40)
        for idx, t in enumerate(tables[:5], 1):
            parts.append(f"  Table {idx} (from {t.get('source', '')[:40]}):")
            for row in t.get("rows", [])[:6]:
                parts.append(f"    | {'  |  '.join(row[:6])} |")
            parts.append("")
        section_num += 1

    # Sources
    page_scores = aggregate.get("page_scores", [])
    if page_scores:
        parts.append(f"{section_num}. SOURCES")
        parts.append("-" * 40)
        for i, ps in enumerate(page_scores, 1):
            parts.append(f"  [{i}] {ps['title']}")
            parts.append(f"      {ps['url']}")
            parts.append(f"      Quality: {ps.get('content_score', 0):.0f}/100, {ps['paragraphs']} paragraphs")

    return "\n".join(parts)


# ── Main Research Pipeline ─────────────────────────────


def research_topic(
    topic: str,
    max_pages: int = 5,
    summary_type: str = "built-in",
    api_key: str = "",
    provider: str = "groq",
    progress_callback=None,
) -> dict:
    """
    Full research pipeline:
    1. Generate multiple search queries
    2. Search across all queries
    3. Score and rank results
    4. Scrape top pages
    5. Aggregate and categorize content
    6. Generate detailed AI report

    Args:
        topic: The research topic
        max_pages: Maximum pages to scrape
        summary_type: "ai" or "built-in"
        api_key: API key (falls back to API_KEY constant)
        provider: "groq", "deepseek", or "openai"
        progress_callback: Optional callback(step, total, url, title)

    Returns:
        dict with: topic, pages_scraped, sources, pages, aggregate, summary
    """
    logger.info("=" * 50)
    logger.info("RESEARCH MODE: '%s'", topic)
    logger.info("=" * 50)

    # Use hardcoded key if no CLI key provided
    if not api_key and API_KEY and API_KEY != "paste-your-groq-key-here":
        api_key = API_KEY
        logger.info("Using hardcoded API key from researcher.py")

    # Step 1: Generate queries
    queries = _generate_search_queries(topic)
    logger.info("Generated %d search queries", len(queries))

    if progress_callback:
        progress_callback(0, 0, "", f"Searching across {len(queries)} queries...")

    # Step 2: Search
    scored_results = _search_all_queries(queries, max_results_per_query=max_pages)
    if not scored_results:
        return {
            "topic": topic,
            "error": "No search results found. Try a different topic or check your internet connection.",
            "pages": [],
            "aggregate": {},
            "summary": "No results found.",
        }

    if progress_callback:
        progress_callback(0, 0, "", f"Found {len(scored_results)} results. Scraping top pages...")

    # Step 3: Scrape pages
    pages = _scrape_pages(scored_results, max_pages, topic, progress_callback)

    if not pages:
        return {
            "topic": topic,
            "error": "All pages were blocked or failed to load. Try a different topic.",
            "pages": [],
            "aggregate": {},
            "summary": "Could not scrape any pages.",
        }

    # Step 4: Aggregate
    aggregate = _aggregate(pages, topic)
    logger.info(
        "Aggregated: %d headings, %d paragraphs, %d key facts",
        len(aggregate["all_headings"]),
        len(aggregate["all_paragraphs"]),
        len(aggregate["key_facts"]),
    )

    if progress_callback:
        progress_callback(0, 0, "", "Generating research report...")

    # Step 5: Generate report
    summary = _generate_research_summary(aggregate, topic, summary_type, api_key, provider)

    return {
        "topic": topic,
        "pages_scraped": len(pages),
        "pages_total_requested": min(len(scored_results), max_pages * 2),
        "sources": [p["url"] for p in pages],
        "pages": pages,
        "aggregate": aggregate,
        "summary": summary,
    }