"""
main.py — CLI entry point for the web scraper & topic researcher.

Usage:
    # URL mode (scrape a single page)
    python main.py https://example.com
    python main.py https://example.com --summary

    # Research mode (give a topic, auto-search + scrape + summary)
    python main.py "artificial intelligence" --research
    python main.py "quantum computing" --research --pages 3
    python main.py "machine learning" -r -p 3 --summary

    # Interactive mode (asks URL or Topic)
    python main.py
"""

import argparse
import json
import os
import re
import sys
import time
import logging
from datetime import datetime
from bot import scrape_url
from storage import save_txt, save_json, save_to_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _safe_filename(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", text)[:40]


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


# ── Progress Display ───────────────────────────────────


def _progress_callback(step: int, total: int, url: str, title: str):
    """Show real-time progress during research."""
    if not url and title:
        # Status message
        print(f"\n  >> {title}")
        return

    if url:
        short_url = url[:60] + "..." if len(url) > 60 else url
        short_title = title[:50] if title else "(no title)"
        print(f"  [{step}/{total}] {short_title}")
        print(f"           {short_url}")


# ── Preview Displays ───────────────────────────────────


def _print_scrape_preview(data: dict, summary=None) -> None:
    print("\n" + "=" * 60)
    print(f"  TITLE: {data['title'][:100]}")
    if data.get("description"):
        print(f"  DESC:  {data['description'][:100]}")
    print(f"  URL:   {data.get('url', '')}")
    print("=" * 60)

    print(f"\nHEADINGS ({len(data['headings'])}):")
    for i, h in enumerate(data["headings"][:8], 1):
        indent = "  " * (h.get("level", 2) - 1)
        print(f"  {i}. {indent}{h['text'][:70]}")

    print(f"\nPARAGRAPHS ({len(data['paragraphs'])}):")
    for p in data["paragraphs"][:3]:
        print(f"  - {p[:100]}...")

    print(f"\nLINKS ({len(data['links'])}):")
    for l in data["links"][:5]:
        badge = "[EXT]" if l.get("is_external") else "[INT]"
        print(f"  {badge} {l['text'][:40]} -> {l['url'][:60]}")

    if data.get("images"):
        print(f"\nIMAGES ({len(data['images'])}):")
        for img in data["images"][:3]:
            print(f"  {img['alt'][:40]} -> {img['src'][:60]}")

    if data.get("tables"):
        print(f"\nTABLES: {len(data['tables'])} table(s) extracted")

    if data.get("lists"):
        total_items = sum(len(l["items"]) for l in data["lists"])
        print(f"LISTS: {len(data['lists'])} list(s), {total_items} total items")

    if summary:
        print("\n" + "=" * 60)
        print("  AI SUMMARY")
        print("=" * 60)
        print(summary)

    print()


def _print_research_preview(result: dict) -> None:
    agg = result.get("aggregate", {})

    print("\n" + "=" * 64)
    print(f"  RESEARCH REPORT: {result['topic']}")
    print(f"  Pages scraped: {result.get('pages_scraped', 0)} / {result.get('pages_total_requested', 0)} attempted")
    print("=" * 64)

    # Source quality table
    page_scores = agg.get("page_scores", [])
    if page_scores:
        print("\n  SOURCE QUALITY:")
        print(f"  {'#':<3} {'Score':>5}  {'Paragraphs':>9}  Title")
        print(f"  {'-'*3}  {'-'*5}  {'-'*9}  {'-'*40}")
        for i, ps in enumerate(page_scores, 1):
            score = ps.get("content_score", 0)
            bar = "#" * int(score / 10)
            print(f"  {i:<3} [{bar:<10}] {ps['paragraphs']:>9}  {ps['title'][:40]}")

    # Aggregate stats
    print(f"\n  CONTENT STATS:")
    print(f"    - {len(agg.get('all_headings', []))} sections / headings")
    print(f"    - {len(agg.get('all_paragraphs', []))} content paragraphs")
    print(f"    - {len(agg.get('all_links', []))} links")
    print(f"    - {len(agg.get('all_images', []))} images")
    print(f"    - {len(agg.get('all_tables', []))} data tables")
    print(f"    - {len(agg.get('key_facts', []))} key facts/statistics")

    # Categorized headings
    categorized = agg.get("categorized_headings", {})
    if categorized:
        cat_names = {
            "definition": "Definition & Overview",
            "history_background": "History & Background",
            "applications": "Applications",
            "benefits_advantages": "Benefits",
            "challenges_limitations": "Challenges",
            "future_trends": "Future Trends",
            "technical_details": "Technical Details",
            "other": "Other",
        }
        print(f"\n  CONTENT CATEGORIES FOUND:")
        for cat_key, items in categorized.items():
            name = cat_names.get(cat_key, cat_key.replace("_", " ").title())
            print(f"    - {name}: {len(items)} sections")

    # Key facts
    key_facts = agg.get("key_facts", [])
    if key_facts:
        print(f"\n  KEY FACTS & STATISTICS ({len(key_facts)} found):")
        for kf in key_facts[:5]:
            print(f"    - {kf['fact'][:80]}")

    # Full report
    if result.get("summary"):
        print("\n" + "=" * 64)
        print("  FULL RESEARCH REPORT")
        print("=" * 64)
        print(result["summary"])

    print()


# ── Save Research Report ───────────────────────────────


def _save_research_report(result: dict, base_path: str) -> None:
    """Save full research report to JSON + TXT + summary files."""
    os.makedirs(os.path.dirname(base_path) if os.path.dirname(base_path) else ".", exist_ok=True)
    agg = result.get("aggregate", {})

    # ── JSON — full structured data ──
    json_path = f"{base_path}_research.json"
    report_data = {
        "topic": result["topic"],
        "pages_scraped": result.get("pages_scraped", 0),
        "sources": result.get("sources", []),
        "aggregate": {
            "total_headings": len(agg.get("all_headings", [])),
            "total_paragraphs": len(agg.get("all_paragraphs", [])),
            "total_links": len(agg.get("all_links", [])),
            "total_images": len(agg.get("all_images", [])),
            "total_tables": len(agg.get("all_tables", [])),
            "key_facts": agg.get("key_facts", []),
            "categorized_headings": {
                k: len(v) for k, v in agg.get("categorized_headings", {}).items()
            },
            "page_scores": agg.get("page_scores", []),
        },
        "summary": result.get("summary", ""),
        "pages": [
            {
                "url": p.get("url", ""),
                "title": p.get("title", ""),
                "paragraphs": len(p.get("paragraphs", [])),
                "headings": len(p.get("headings", [])),
            }
            for p in result.get("pages", [])
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    logger.info("Research JSON saved -> %s", json_path)

    # ── TXT — full readable report with AI summary ──
    txt_path = f"{base_path}_research.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"RESEARCH TOPIC: {result['topic']}\n")
        f.write(f"Pages scraped: {result.get('pages_scraped', 0)}\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Generated by: Web Bot Research Agent\n")
        f.write("\n" + "=" * 64 + "\n")

        # Sources with quality scores
        page_scores = agg.get("page_scores", [])
        f.write(f"\nSOURCES ({len(page_scores)} pages):\n")
        f.write(f"{'-' * 64}\n")
        for i, ps in enumerate(page_scores, 1):
            f.write(f"  [{i}] {ps['title']}\n")
            f.write(f"      {ps['url']}\n")
            f.write(f"      Quality: {ps.get('content_score', 0):.0f}/100, "
                    f"{ps['paragraphs']} paragraphs, {ps['headings']} headings\n\n")

        # Categorized headings
        categorized = agg.get("categorized_headings", {})
        if categorized:
            cat_names = {
                "definition": "DEFINITION & OVERVIEW",
                "history_background": "HISTORY & BACKGROUND",
                "applications": "APPLICATIONS & USE CASES",
                "benefits_advantages": "BENEFITS & ADVANTAGES",
                "challenges_limitations": "CHALLENGES & LIMITATIONS",
                "future_trends": "FUTURE TRENDS",
                "technical_details": "TECHNICAL DETAILS",
                "other": "OTHER SECTIONS",
            }
            f.write(f"\nCONTENT STRUCTURE ({len(agg.get('all_headings', []))} total sections):\n")
            f.write(f"{'-' * 64}\n")
            for cat_key, items in categorized.items():
                name = cat_names.get(cat_key, cat_key.upper())
                f.write(f"\n  {name} ({len(items)} sections):\n")
                for h in items[:6]:
                    f.write(f"    - {h['text']} [{h.get('source', '')[:30]}]\n")

        # Key Facts
        key_facts = agg.get("key_facts", [])
        if key_facts:
            f.write(f"\n\nKEY FACTS & STATISTICS ({len(key_facts)} found):\n")
            f.write(f"{'-' * 64}\n")
            for kf in key_facts[:15]:
                f.write(f"  - {kf['fact']}\n")
                f.write(f"    Source: {kf['source'][:60]}\n\n")

        # Content blocks
        f.write(f"\n\nFULL CONTENT ({len(agg.get('all_paragraphs', []))} paragraphs):\n")
        f.write(f"{'-' * 64}\n")
        for p in agg.get("all_paragraphs", [])[:40]:
            f.write(f"  [{p['source'][:30]}]\n")
            f.write(f"  {p['text']}\n\n")

        # Tables
        tables = agg.get("all_tables", [])
        if tables:
            f.write(f"\nDATA TABLES ({len(tables)}):\n")
            f.write(f"{'-' * 64}\n")
            for idx, t in enumerate(tables[:5], 1):
                f.write(f"  Table {idx} (from {t.get('source', '')[:40]}):\n")
                for row in t.get("rows", [])[:10]:
                    f.write(f"    | {'  |  '.join(row[:6])} |\n")
                f.write("\n")

        # Important links
        ext_links = [l for l in agg.get("all_links", []) if l.get("is_external")][:15]
        if ext_links:
            f.write(f"\nIMPORTANT EXTERNAL LINKS:\n")
            f.write(f"{'-' * 64}\n")
            for l in ext_links:
                f.write(f"  - {l['text']}: {l['url']}\n")

        # AI Report
        if result.get("summary"):
            f.write("\n\n" + "=" * 64 + "\n")
            f.write("AI-GENERATED RESEARCH REPORT\n")
            f.write("=" * 64 + "\n\n")
            f.write(result["summary"])

    logger.info("Research TXT saved -> %s", txt_path)

    # ── Summary only ──
    if result.get("summary"):
        summary_path = f"{base_path}_summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"RESEARCH TOPIC: {result['topic']}\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Sources: {result.get('pages_scraped', 0)} pages\n\n")
            f.write("=" * 64 + "\n\n")
            f.write(result["summary"])
        logger.info("Summary saved -> %s", summary_path)


# ── Main Entry Point ───────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Web Scraper & Topic Researcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Scrape a single URL
  python main.py https://example.com
  python main.py https://example.com --summary

  # Research a topic (auto-search + multi-page scrape + AI report)
  python main.py "artificial intelligence" --research
  python main.py "quantum computing" --research --pages 3
  python main.py "machine learning" -r -p 5 --summary

  # Interactive mode (shows menu)
  python main.py
""",
    )

    parser.add_argument(
        "target", nargs="?",
        help="URL to scrape OR topic to research (auto-detected)",
    )
    parser.add_argument(
        "--research", "-r",
        action="store_true",
        help="Research mode: give a topic, auto-search + scrape multiple pages",
    )
    parser.add_argument(
        "--pages", "-p",
        type=int,
        default=5,
        help="Max pages to scrape in research mode (default: 5)",
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="Generate AI summary (single page or research)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["txt", "json", "csv", "all"],
        default="all",
        help="Output format for URL mode (default: all)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--max-links",
        type=int,
        default=0,
        help="Max links in TXT output (0 = no limit)",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="AI API key for Groq/DeepSeek/OpenAI (or set in researcher.py / summarizer.py)",
    )
    parser.add_argument(
        "--ai-provider",
        default="groq",
        choices=["groq", "deepseek", "openai"],
        help="AI provider for summary (default: groq, free)",
    )

    args = parser.parse_args()

    # ── Get input: from argument or interactive menu ──
    target = args.target

    if not target:
        print()
        print("+" + "-" * 56 + "+")
        print("|" + "  WEB SCRAPER & TOPIC RESEARCHER".center(54) + "|")
        print("|" + "  Playwright + Multi-Source Research + AI Report".center(54) + "|")
        print("+" + "-" * 56 + "+")
        print()
        print("  What would you like to do?")
        print()
        print("    [1]  Scrape a URL")
        print("         Extract all content from a single webpage")
        print()
        print("    [2]  Research a Topic")
        print("         Auto-search from multiple sources, scrape pages,")
        print("         and generate a detailed AI research report")
        print()

        while True:
            choice = input("  Enter choice (1 or 2): ").strip()
            if choice in ("1", "2"):
                break
            print("  Invalid choice. Please enter 1 or 2.")

        print()

        if choice == "1":
            print("  Mode: URL Scraper")
            print("  " + "-" * 40)
            target = input("  Enter URL: ").strip()
            if not target:
                print("  No URL provided. Exiting.")
                sys.exit(1)
            if not target.startswith(("http://", "https://")):
                target = "https://" + target
                print(f"  URL corrected to: {target}")
        else:
            args.research = True
            print("  Mode: Topic Researcher")
            print("  " + "-" * 40)
            target = input("  Enter Topic: ").strip()
            if not target:
                print("  No topic provided. Exiting.")
                sys.exit(1)
            pages_input = input(f"  How many pages to scrape? (default {args.pages}): ").strip()
            if pages_input.isdigit() and int(pages_input) > 0:
                args.pages = int(pages_input)

            summary_choice = input("  Generate AI research report? (Y/n): ").strip().lower()
            if summary_choice != "n":
                args.summary = True

        print()

    if not target:
        print("No input provided. Exiting.")
        sys.exit(1)

    # ── Auto-detect mode if not specified ──
    if not args.research and not _is_url(target):
        args.research = True
        logger.info("Topic detected (not a URL) — switching to research mode")

    os.makedirs(args.output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    start_time = time.time()

    # ══════════════════════════════════════════════════
    # RESEARCH MODE: Topic -> Search -> Scrape -> Report
    # ══════════════════════════════════════════════════
    if args.research:
        topic = target
        print("+" + "-" * 56 + "+")
        print(f"|  RESEARCHING: {topic[:46].center(46)} |")
        print("+" + "-" * 56 + "+")
        print()

        logger.info("=" * 40)
        logger.info("RESEARCH MODE: %s", topic)
        logger.info("=" * 40)

        from researcher import research_topic

        result = research_topic(
            topic=topic,
            max_pages=args.pages,
            summary_type="ai" if (args.summary or args.api_key) else "built-in",
            api_key=args.api_key,
            provider=args.ai_provider,
            progress_callback=_progress_callback,
        )

        elapsed = time.time() - start_time

        if result.get("error"):
            print(f"\n  WARNING: {result['error']}", file=sys.stderr)

        # Save research report
        stub = _safe_filename(topic)
        base = os.path.join(args.output_dir, f"{stub}_{ts}")
        _save_research_report(result, base)

        # Print preview
        _print_research_preview(result)

        print(f"  Completed in {elapsed:.1f} seconds")
        print(f"  Files saved to: {args.output_dir}/")

    # ══════════════════════════════════════════════════
    # URL MODE: Scrape single page
    # ══════════════════════════════════════════════════
    else:
        url = target
        logger.info("URL MODE: %s", url)
        data = scrape_url(url)

        if "error" in data:
            logger.error("Scrape failed: %s", data["error"])
            print(f"\nERROR: {data['error']}", file=sys.stderr)
            sys.exit(1)

        stub = _safe_filename(url)
        base = os.path.join(args.output_dir, f"{stub}_{ts}")

        if args.format in ("txt", "all"):
            save_txt(data, f"{base}.txt", max_links=args.max_links)
        if args.format in ("json", "all"):
            save_json(data, f"{base}.json")
        if args.format in ("csv", "all"):
            save_to_csv(data, f"{base}.csv")

        # Summary for single page
        summary = None
        if args.summary:
            try:
                from summarizer import generate_summary
                summary = generate_summary(data, api_key=args.api_key, provider=args.ai_provider)
                with open(f"{base}_summary.txt", "w", encoding="utf-8") as f:
                    f.write(f"URL: {data.get('url', '')}\n")
                    f.write(f"TITLE: {data['title']}\n\n")
                    f.write(summary)
                logger.info("Summary saved -> %s_summary.txt", base)
            except Exception as e:
                print(f"\nSummary failed: {e}")

        _print_scrape_preview(data, summary=summary)


if __name__ == "__main__":
    main()