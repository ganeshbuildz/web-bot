"""
bot.py — Web scraper driver (Playwright).
"""

import logging

logger = logging.getLogger(__name__)

_EMPTY_DATA = {
    "url": "",
    "title": "",
    "description": "",
    "headings": [],
    "paragraphs": [],
    "links": [],
    "images": [],
    "tables": [],
    "lists": [],
    "metadata": {},
}

_BLOCK_PHRASES = [
    "vercel security",
    "failed to verify your browser",
    "just a moment",
    "checking your browser",
    "cloudflare",
    "are you a robot",
    "captcha",
    "access denied",
    "blocked",
]


def _is_blocked(page) -> bool:
    try:
        body = (page.locator("body").text_content() or "").lower()
        title = (page.title() or "").lower()
        return any(p in body + " " + title for p in _BLOCK_PHRASES)
    except Exception:
        return False


def _scroll_to_bottom(page, pause_ms=800, max_scrolls=4):
    for _ in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        page.wait_for_timeout(pause_ms)


def scrape_url(url, timeout_seconds=35):
    from playwright.sync_api import sync_playwright
    from extractor import extract_structured

    result = _EMPTY_DATA.copy()
    result["url"] = url

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            try:
                logger.info("Navigating to %s", url)
                page.goto(url, wait_until="commit", timeout=timeout_seconds * 1000)
                page.wait_for_timeout(3000)

                if _is_blocked(page):
                    result["error"] = (
                        "Bot detection page (Vercel/Cloudflare/CAPTCHA). "
                        f"Redirected to: {page.url}"
                    )
                    result["title"] = page.title()
                    result["url"] = page.url
                    logger.warning("Blocked: %s", page.url)
                    return result

                _scroll_to_bottom(page)
                data = extract_structured(page)
                data["url"] = page.url
                logger.info(
                    "Done: %d headings, %d paragraphs, %d links, %d images",
                    len(data["headings"]), len(data["paragraphs"]),
                    len(data["links"]), len(data["images"]),
                )
                return data
            finally:
                browser.close()
    except Exception as exc:
        result["error"] = str(exc)
        logger.error("Failed: %s", exc)
        return result