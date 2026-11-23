
import os
import re
import json
import requests
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
from rootdata import discover_rootdata

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PAGES = [
    "https://zealy.io/explore/new-web3-communities",
    "https://zealy.io/explore",
    "https://zealy.io/explore/upcoming-web3-communities",
]

STATE_FILE = "seen_projects.json"
BASE_URL = "https://zealy.io"


def load_seen():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def discover_zealy():
    projects = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for url in PAGES:
            try:
                print(f"\nChecking: {url}")

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                page.wait_for_timeout(7000)

                for _ in range(3):
                    page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                    page.wait_for_timeout(1500)

                anchors = page.locator(
                    'a[href*="/c/"]'
                ).evaluate_all("""
                    elements => elements.map(a => ({
                        href: a.getAttribute("href"),
                        name: (a.innerText || "").trim()
                    }))
                """)

                print(f"Community links detected: {len(anchors)}")

                for item in anchors:
                    if not item["href"]:
                        continue

                    full_url = urljoin(BASE_URL, item["href"])
                    path = urlparse(full_url).path.strip("/")
                    match = re.match(r"c/([^/]+)", path)

                    if not match:
                        continue

                    slug = match.group(1)

                    if slug in ("login", "signup", "create"):
                        continue

                    name = item["name"] or slug
                    name = " ".join(name.split())

                    projects[slug] = {
                        "name": name[:100],
                        "url": f"{BASE_URL}/c/{slug}",
                        "source": "Zealy"
                    }

            except Exception as error:
                print(f"Zealy page scan failed: {error}")

        browser.close()

    return projects


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        },
        timeout=20
    )

    response.raise_for_status()


def main():
    seen = set(load_seen())

    projects = discover_zealy()

    try:
        rootdata_projects = discover_rootdata(seen)
        projects.update(rootdata_projects)
    except Exception as error:
        print(f"RootData scan failed: {error}")

    new_projects = [
        (key, project)
        for key, project in projects.items()
        if key not in seen
    ]

    print("\n========== SCAN SUMMARY ==========")
    print(f"Total discoveries: {len(projects)}")
    print(f"New discoveries: {len(new_projects)}")

    for key, project in new_projects:
        if project["source"] == "RootData":
            message = (
    "⭐ PROMISING WEB3 PROJECT\n\n"
    f"Project: {project['name']}\n"
    f"Score: {project['score']}/10\n"
    f"Signals: {', '.join(project['reasons'])}\n"
    f"Established: {project.get('establishment_date', 'Unknown')}\n"
    f"Listed investors: {project.get('investor_count', 0)}\n"
    f"RD Growth Index: {project.get('rd_score', 0)}\n"
    f"Tags: {', '.join(map(str, project.get('tags', [])))}\n"
    f"Link: {project['url'] or 'No profile link returned'}\n"
    f"Description: {project.get('description', '')[:300]}\n\n"
    "Research this project for early community and ambassador opportunities."

            )
        else:
            message = (
                "🟢 NEW ZEALY DISCOVERY\n\n"
                f"Project: {project['name']}\n"
                f"Link: {project['url']}\n"
                "Check its campaign and opportunities."
            )

        send_telegram(message)

    seen.update(projects.keys())

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen), file, indent=2)

    print("Discovery scan completed.")


if __name__ == "__main__":
    main()
    
