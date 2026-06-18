import json
import os
import re
from bot import scrape_url

url = input("Enter URL: ")
print(f"\nScraping: {url}\n")

data = scrape_url(url)

os.makedirs("output", exist_ok=True)
filename = re.sub(r'[^a-zA-Z0-9._-]', '_', url.replace("https://","").replace("http://",""))[:40]

# TXT save
txt_path = f"output/{filename}.txt"
with open(txt_path, "w", encoding="utf-8") as f:
    f.write(f"URL: {url}\n\n")
    f.write(f"TITLE:\n{data['title']}\n\n")

    f.write("MAIN HEADINGS:\n")
    for i, h in enumerate(data["headings"], 1):
        f.write(f"  {i}. {h}\n")

    f.write("\nIMPORTANT PARAGRAPHS:\n")
    for p in data["paragraphs"]:
        f.write(f"  - {p}\n")

    f.write("\nIMPORTANT LINKS:\n")
    for l in data["links"][:15]:
        f.write(f"  - {l}\n")

# JSON save
json_path = f"output/{filename}.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"TXT saved  → {txt_path}")
print(f"JSON saved → {json_path}")

print("\n--- PREVIEW ---\n")
print(f"TITLE:\n{data['title']}\n")
print("MAIN HEADINGS:")
for i, h in enumerate(data["headings"][:5], 1):
    print(f"  {i}. {h}")
print("\nIMPORTANT PARAGRAPHS:")
for p in data["paragraphs"][:3]:
    print(f"  - {p[:80]}...")