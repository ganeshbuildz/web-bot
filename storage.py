"""
storage.py — Save data to TXT, JSON, CSV.
"""

import json
import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def save_txt(data, filepath, max_links=0):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"URL: {data.get('url', '')}\n")
        f.write(f"TITLE: {data['title']}\n")
        if data.get("description"):
            f.write(f"DESCRIPTION: {data['description']}\n\n")

        f.write(f"HEADINGS ({len(data['headings'])}):\n")
        for h in data["headings"]:
            prefix = "#" * h.get("level", 2)
            f.write(f"  {prefix} {h['text']}\n")

        f.write(f"\nPARAGRAPHS ({len(data['paragraphs'])}):\n")
        for p in data["paragraphs"]:
            f.write(f"  - {p}\n\n")

        if data.get("lists"):
            f.write(f"LISTS ({len(data['lists'])}):\n")
            for lst in data["lists"]:
                f.write(f"  [{lst.get('type')}]\n")
                for item in lst["items"]:
                    f.write(f"    - {item}\n")
                f.write("\n")

        links_out = data["links"][:max_links] if max_links > 0 else data["links"]
        f.write(f"LINKS ({len(links_out)} of {len(data['links'])}):\n")
        for l in links_out:
            badge = "[EXT]" if l.get("is_external") else "[INT]"
            f.write(f"  {badge} {l['text']} -> {l['url']}\n")

        if data.get("images"):
            f.write(f"\nIMAGES ({len(data['images'])}):\n")
            for img in data["images"]:
                f.write(f"  {img['alt'] or '(no alt)'} -> {img['src']}\n")

        if data.get("tables"):
            f.write(f"\nTABLES ({len(data['tables'])}):\n")
            for idx, table in enumerate(data["tables"], 1):
                f.write(f"  Table {idx} ({len(table)} rows):\n")
                for row in table[:20]:
                    f.write(f"    | {'  |  '.join(row)} |\n")

        if data.get("metadata"):
            f.write("\nMETADATA:\n")
            for k, v in data["metadata"].items():
                if k == "json_ld":
                    f.write(f"  {k}: (structured data, see JSON output)\n")
                else:
                    f.write(f"  {k}: {str(v)[:200]}\n")

    logger.info("TXT saved -> %s", filepath)


def save_json(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("JSON saved -> %s", filepath)


def save_to_csv(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    rows = []

    for i, h in enumerate(data.get("headings", []), 1):
        rows.append({"section": "heading", "index": i, "content": h.get("text", ""), "level": h.get("level", ""), "url": "", "is_external": "", "alt": ""})

    for i, p in enumerate(data.get("paragraphs", []), 1):
        rows.append({"section": "paragraph", "index": i, "content": p, "level": "", "url": "", "is_external": "", "alt": ""})

    for i, l in enumerate(data.get("links", []), 1):
        rows.append({"section": "link", "index": i, "content": l.get("text", ""), "level": "", "url": l.get("url", ""), "is_external": l.get("is_external", ""), "alt": ""})

    for i, img in enumerate(data.get("images", []), 1):
        rows.append({"section": "image", "index": i, "content": img.get("src", ""), "level": "", "url": img.get("src", ""), "is_external": "", "alt": img.get("alt", "")})

    for lst in data.get("lists", []):
        for j, item in enumerate(lst.get("items", []), 1):
            rows.append({"section": f"list ({lst.get('type', '')})", "index": j, "content": item, "level": "", "url": "", "is_external": "", "alt": ""})

    df = pd.DataFrame(rows)
    df.to_csv(filepath, index=False, encoding="utf-8")
    logger.info("CSV saved -> %s (%d rows)", filepath, len(df))