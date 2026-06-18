from selenium.webdriver.common.by import By

def extract_structured(driver):
    data = {
        "title": "",
        "headings": [],
        "paragraphs": [],
        "links": []
    }

    # Title
    try:
        data["title"] = driver.find_element(By.TAG_NAME, "h1").text.strip()
    except:
        data["title"] = driver.title

    # Headings
    for tag in ["h2", "h3"]:
        elements = driver.find_elements(By.TAG_NAME, tag)
        for el in elements:
            text = el.text.strip()
            if text and len(text) > 5:
                data["headings"].append(text)

    # Paragraphs
    for el in driver.find_elements(By.TAG_NAME, "p"):
        text = el.text.strip()
        if text and len(text) > 30:
            data["paragraphs"].append(text)

    # Links
    for el in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
        text = el.text.strip()
        href = el.get_attribute("href")

        if (
            len(text) > 5 and
            href and
            not href.startswith("javascript:") and
            not any(x in href.lower() for x in [
                "login", "signup", "privacy", "terms",
                "facebook", "twitter", "instagram",
                "linkedin", "youtube"
            ])
        ):
            data["links"].append({
                "text": text,
                "url": href
            })

    return data