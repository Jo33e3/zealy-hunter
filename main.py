
import os
import re
import json
import html
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

                    if slug.lower() in ("login", "signup", "create"):
                        continue

                    name = " ".join(
                        (item["name"] or slug).split()
                    )

                    projects[slug] = {
                        "name": name[:100],
                        "url": f"{BASE_URL}/c/{slug}",
                        "source": "Zealy Explore"
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
    discovered_projects = {}

    if not feed_urls:
        print("X_ALERT_FEED_URL is missing; skipping feeds.")
        return discovered_projects, new_posts, seen_posts

    community_pattern = re.compile(
        r"(?:https?://)?(?:www\.)?zealy\.io/c/([A-Za-z0-9_-]+)",
        re.IGNORECASE
    )

    for feed_url in feed_urls:
        try:
            response = requests.get(
                feed_url,
                headers={
                    "User-Agent": "Mozilla/5.0 ZealyHunter/1.0"
                },
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
                links = []

                for child in list(entry):
                    tag = child.tag.split("}")[-1]
                    value = "".join(child.itertext()).strip()

                    if value:
                        fields[tag] = value

                    if tag == "link":
                        href = child.attrib.get("href")
                        if href:
                            links.append(href)

                post_id = (
                    fields.get("id")
                    or fields.get("guid")
                    or fields.get("link")
                    or fields.get("title")
                )

                post_link = (
                    links[0] if links
                    else fields.get("link", "")
                )

                title = fields.get("title") or "Zealy-related post"

                summary = (
                    fields.get("summary")
                    or fields.get("description")
                    or fields.get("content")
                    or ""
                )

                searchable_text = html.unescape(
                    " ".join([
                        title,
                        summary,
                        post_link,
                        " ".join(links)
                    ])
                )

                clean_summary = re.sub(
                    r"<[^>]+>",
                    " ",
                    html.unescape(summary)
                )
                clean_summary = " ".join(clean_summary.split())

                for match in community_pattern.finditer(
                    searchable_text
                ):
                    slug = match.group(1)

                    if slug.lower() in (
                        "login", "signup", "create"
                    ):
                        continue

                    discovered_projects[slug] = {
                        "name": slug.replace("-", " ").title(),
                        "url": f"{BASE_URL}/c/{slug}",
                        "source": "RSS alert"
                    }

                if not post_id:
                    post_id = post_link or title

                if post_id not in seen_posts:
                    new_posts.append({
                        "id": post_id,
                        "title": title[:250],
                        "link": post_link,
                        "summary": clean_summary[:500]
                    })

                    seen_posts.add(post_id)

            print("Successfully checked an alert feed.")

        except Exception as error:
            print(f"Alert feed scan failed: {error}")

    return discovered_projects, new_posts, seen_posts


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

    # Discover communities from Zealy Explore
    projects = discover_zealy()

    # Discover communities from RSS alerts
    feed_projects, x_posts, seen_x_posts = scan_x_alert_feeds()

    # Combine discoveries
    projects.update(feed_projects)

    new_projects = [
        (key, project)
        for key, project in projects.items()
        if key not in seen
    ]

    print("\n========== ZEALY SCAN SUMMARY ==========")
    print(f"Total discoveries: {len(projects)}")
    print(f"New discoveries: {len(new_projects)}")

    # Send every new community discovery
    for key, project in new_projects:
        message = (
            "⭐ PROMISING ZEALY PROJECT\n\n"
            f"Community: {project['name']}\n"
            f"Link: {project['url']}\n\n"
            f"Discovery source: {project['source']}\n\n"
            "New discovery. Check its quests and opportunities."
        )

        try:
            send_telegram(message)
            print(f"Alert sent: {project['name']}")
        except Exception as error:
            print(f"Telegram project alert failed: {error}")

    seen.update(projects.keys())

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen), file, indent=2)

    # Send new Zealy-related posts as supporting information
    print(f"New X alert posts: {len(x_posts)}")

    for post in x_posts:
        message = (
            "🔎 NEW ZEALY-RELATED POST\n\n"
            f"{post['title']}\n\n"
            f"{post['summary']}\n\n"
            f"Open post/search result: {post['link']}"
        )

        try:
            send_telegram(message)
        except Exception as error:
            print(f"Telegram post alert failed: {error}")

    with open(X_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen_x_posts), file, indent=2)

    print("Zealy discovery scan completed.")


if __name__ == "__main__":
    main()
                    
