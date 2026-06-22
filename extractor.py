"""
extractor.py — Extract data using page.evaluate() (JavaScript).
"""

import json
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def extract_structured(page):
    current_domain = urlparse(page.url).netloc

    js_result = page.evaluate("""() => {
        const data = {};

        const h1s = [...document.querySelectorAll('h1')].map(e => e.textContent.trim()).filter(Boolean);
        data.h1_texts = h1s.length ? h1s : [document.title];

        const descEl = document.querySelector('meta[name="description"]');
        data.description = descEl ? (descEl.getAttribute('content') || '').trim() : '';

        data.headings = [];
        ['h2','h3','h4','h5','h6'].forEach((tag, idx) => {
            document.querySelectorAll(tag).forEach(el => {
                const t = el.textContent.trim();
                if (t) data.headings.push({level: idx + 2, text: t});
            });
        });

        data.paragraphs = [];
        const seen = new Set();
        document.querySelectorAll('p, blockquote').forEach(el => {
            const t = el.textContent.trim();
            if (t && t.length > 20 && !seen.has(t)) {
                seen.add(t);
                data.paragraphs.push(t);
            }
        });

        data.lists = [];
        document.querySelectorAll('ul, ol').forEach(listEl => {
            const items = [...listEl.querySelectorAll('li')]
                .map(li => li.textContent.trim())
                .filter(t => t && t.length > 10);
            if (items.length) {
                data.lists.push({type: listEl.tagName === 'OL' ? 'ordered' : 'unordered', items});
            }
        });

        data.links = [];
        const currentHost = window.location.hostname;
        const socialDomains = ["facebook.com","twitter.com","x.com","instagram.com","linkedin.com","youtube.com","tiktok.com","pinterest.com"];
        const utilityPaths = ["login","signup","register","privacy","terms","cookie","unsubscribe","forgot-password","reset-password"];
        document.querySelectorAll('a[href]').forEach(el => {
            const text = el.textContent.trim();
            const href = el.getAttribute('href') || '';
            if (!text || text.length < 5 || !href || href.startsWith('javascript:')) return;
            try {
                const u = new URL(href, window.location.href);
                if (socialDomains.some(s => u.hostname.includes(s))) return;
                if (utilityPaths.some(p => u.pathname.toLowerCase().includes(p))) return;
                data.links.push({text, url: href, is_external: u.hostname !== currentHost});
            } catch(e) {}
        });

        data.images = [];
        document.querySelectorAll('img').forEach(img => {
            const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
            const alt = (img.getAttribute('alt') || '').trim();
            if (src && !src.startsWith('data:') && src.length > 10) {
                data.images.push({src, alt});
            }
        });

        data.tables = [];
        document.querySelectorAll('table').forEach(table => {
            const rows = [];
            table.querySelectorAll('tr').forEach(tr => {
                const cells = [...tr.querySelectorAll('th, td')].map(td => td.textContent.trim());
                if (cells.some(c => c)) rows.push(cells);
            });
            if (rows.length) data.tables.push(rows);
        });

        data.meta = {};
        ['og:title','og:description','og:image','og:type','og:url'].forEach(prop => {
            const el = document.querySelector(`meta[property="${prop}"]`);
            if (el) data.meta[prop] = (el.getAttribute('content') || '').trim();
        });
        ['twitter:card','twitter:title','twitter:description','twitter:image'].forEach(name => {
            const el = document.querySelector(`meta[name="${name}"]`);
            if (el) data.meta[name] = (el.getAttribute('content') || '').trim();
        });

        data.json_ld = [];
        document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
            try { data.json_ld.push(JSON.parse(s.textContent)); } catch(e) {}
        });

        return data;
    }""")

    data = {
        "title": " | ".join(js_result.get("h1_texts", [])),
        "description": js_result.get("description", ""),
        "headings": js_result.get("headings", []),
        "paragraphs": js_result.get("paragraphs", []),
        "links": js_result.get("links", []),
        "images": js_result.get("images", []),
        "tables": js_result.get("tables", []),
        "lists": js_result.get("lists", []),
        "metadata": js_result.get("meta", {}),
    }

    if js_result.get("json_ld"):
        data["metadata"]["json_ld"] = js_result["json_ld"]

    return data