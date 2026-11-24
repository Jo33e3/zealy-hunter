
import os
import re
import json
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PAGES = [
    "https://zealy.io/explore/new-web3-communities",
    "https://zealy.io/explore",
    "https://zealy.io/explore/upcoming-web3-communities",
]

STATE_FILE = "seen_projects.json"
X_STATE_FILE = "seen_x_posts.json"
BASE_URL = "https://zealy.io"


def load_seen(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return set(data if isinstance(data, list) else [])
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def discover_zealy():
    projects = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for url in PAGES:
            try:
                print(f"\nChecking: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(7000)

                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

                anchors = page.locator('a[href*="/c/"]').evaluate_all("""
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

                    name = " ".join((item["name"] or slug).split())

                    projects[slug] = {
                        "name": name[:100],
                        "url": f"{BASE_URL}/c/{slug}",
                        "source": "Zealy"
                    }

            except Exception as error:
                print(f"Zealy page scan failed: {error}")

        browser.close()

    return projects


def scan_x_alert_feeds():
    raw_urls = os.environ.get("X_ALERT_FEED_URL", "")
    feed_urls = [
        line.strip()
        for line in raw_urls.splitlines()
        if line.strip()
    ]

    seen_posts = load_seen(X_STATE_FILE)
    new_posts = []

    if not feed_urls:
        print("X_ALERT_FEED_URL is missing; skipping X feeds.")
        return new_posts, seen_posts

    for feed_url in feed_urls:
        try:
            response = requests.get(
                feed_url,
                headers={"User-Agent": "Mozilla/5.0 ZealyHunter/1.0"},
                timeout=30
            )
            response.raise_for_status()

            root = ET.fromstring(response.content)

            entries = [
                element for element in root.iter()
                if element.tag.split("}")[-1] == "entry"
            ]

            if not entries:
                entries = [
                    element for element in root.iter()
                    if element.tag.split("}")[-1] == "item"
                ]

            for entry in entries:
                fields = {}

                for child in list(entry):
                    fields[child.tag.split("}")[-1]] = (
                        child.text or ""
                    ).strip()

                post_id = (
                    fields.get("id")
                    or fields.get("guid")
                    or fields.get("link")
                )

                post_link = fields.get("link") or post_id or ""

                for child in list(entry):
                    if child.tag.split("}")[-1] == "link":
                        post_link = (
                            child.attrib.get("href")
                            or post_link
                        )

                title = fields.get("title") or "Zealy-related X post"

                summary = (
                    fields.get("summary")
                    or fields.get("description")
                    or fields.get("content")
                    or ""
                )

                if not post_id:
                    post_id = post_link or title

                if post_id in seen_posts:
                    continue

                new_posts.append({
                    "id": post_id,
                    "title": title[:250],
                    "link": post_link,
                    "summary": re.sub(
                        r"<[^>]+>", " ", summary
                    )[:500]
                })

                seen_posts.add(post_id)

            print("Successfully checked an X alert feed.")

        except Exception as error:
            print(f"X alert feed scan failed: {error}")

    return new_posts, seen_posts


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
    seen = load_seen(STATE_FILE)

    projects = discover_zealy()


    new_projects = [
        (key, project)
        for key, project in projects.items()
        if key not in seen
    ]

    print("\n========== SCAN SUMMARY ==========")
    print(f"Total discoveries: {len(projects)}")
    print(f"New discoveries: {len(new_projects)}")

    for key, project in new_projects:
                    message = (
            "⭐ PROMISING ZEALY PROJECT\n\n"
            f"Community: {project['name']}\n"
            f"Link: {project['url']}\n\n"
            "New discovery. Check its quests and opportunities."
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

    x_posts, seen_x_posts = scan_x_alert_feeds()

    print(f"New X alert posts: {len(x_posts)}")

    for post in x_posts:
        message = (
            "🔎 NEW ZEALY-RELATED X POST\n\n"
            f"{post['title']}\n\n"
            f"{post['summary']}\n\n"
            f"Open post/search result: {post['link']}"
        )

        send_telegram(message)

    with open(X_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen_x_posts), file, indent=2)

    print("Discovery scan completed.")


if __name__ == "__main__":
    main()
