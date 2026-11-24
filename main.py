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

COMMUNITY_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?zealy\.io/c/([A-Za-z0-9_-]+)",
    re.IGNORECASE
)

ZEALY_PATTERN = re.compile(
    r"\bzealy\b|zealy\.io",
    re.IGNORECASE
)


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
                print(f"\nChecking Zealy: {url}")

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

                print(f"Zealy links found: {len(anchors)}")

                for item in anchors:
                    if not item["href"]:
                        continue

                    full_url = urljoin(BASE_URL, item["href"])
                    parsed = urlparse(full_url)

                    if parsed.netloc.lower() not in (
                        "zealy.io", "www.zealy.io"
                    ):
                        continue

                    match = re.match(
                        r"/c/([^/]+)",
                        parsed.path
                    )

                    if not match:
                        continue

                    slug = match.group(1)

                    if slug.lower() in (
                        "login", "signup", "create"
                    ):
                        continue

                    name = " ".join(
                        (item["name"] or slug).split()
                    )

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
    discovered_projects = {}
    project_leads = []

    if not feed_urls:
        print("No RSS feeds configured.")
        return discovered_projects, project_leads, seen_posts

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

                # Collect text and links from the feed entry
                for element in entry.iter():
                    tag = element.tag.split("}")[-1]
                    value = "".join(element.itertext()).strip()

                    if value:
                        fields[tag] = value

                    href = element.attrib.get("href")
                    if href:
                        links.append(href)

                post_id = (
                    fields.get("id")
                    or fields.get("guid")
                    or fields.get("link")
                    or fields.get("title")
                )

                title = fields.get("title") or "Zealy discovery"

                summary = (
                    fields.get("summary")
                    or fields.get("description")
                    or fields.get("encoded")
                    or fields.get("content")
                    or ""
                )

                post_link = (
                    fields.get("link")
                    or (links[0] if links else "")
                )

                searchable_text = html.unescape(
                    " ".join([
                        title,
                        summary,
                        " ".join(fields.values()),
                        " ".join(links)
                    ])
                )

                # Ignore anything that does not mention Zealy
                # or contain a direct Zealy community link.
                direct_matches = list(
                    COMMUNITY_PATTERN.finditer(searchable_text)
                )

                mentions_zealy = bool(
                    ZEALY_PATTERN.search(searchable_text)
                )

                if not direct_matches and not mentions_zealy:
                    continue

                if not post_id:
                    post_id = post_link or title

                if post_id in seen_posts:
                    continue

                seen_posts.add(post_id)

                # Direct Zealy community links
                for match in direct_matches:
                    slug = match.group(1)

                    if slug.lower() in (
                        "login", "signup", "create"
                    ):
                        continue

                    if slug not in discovered_projects:
                        discovered_projects[slug] = {
                            "name": slug.replace("-", " ").title(),
                            "url": f"{BASE_URL}/c/{slug}",
                            "source": "Google/Bing/RSS discovery",
                            "source_link": post_link
                        }

                # Zealy mentioned, but no community link found
                if not direct_matches:
                    clean_summary = re.sub(
                        r"<[^>]+>",
                        " ",
                        html.unescape(summary)
                    )

                    project_leads.append({
                        "id": post_id,
                        "title": title[:200],
                        "summary": " ".join(
                            clean_summary.split()
                        )[:500],
                        "link": post_link
                    })

            print("Checked RSS feed successfully.")

        except Exception as error:
            print(f"RSS feed scan failed: {error}")

    return discovered_projects, project_leads, seen_posts


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

    print("\n========== ZEALY HUNTER ==========")

    # Scan Zealy's public pages
    projects = discover_zealy()

    # Scan Google and Bing RSS results
    feed_projects, project_leads, seen_x_posts = (
        scan_x_alert_feeds()
    )

    # Combine direct community discoveries
    projects.update(feed_projects)

    new_projects = [
        (slug, project)
        for slug, project in projects.items()
        if slug not in seen
    ]

    print(f"Communities found: {len(projects)}")
    print(f"New communities: {len(new_projects)}")
    print(f"Zealy mentions without links: {len(project_leads)}")

    # Send direct community discoveries
    for slug, project in new_projects:
        message = (
            "⭐ PROMISING ZEALY PROJECT\n\n"
            f"Community: {project['name']}\n"
            f"Link: {project['url']}\n"
            f"Source: {project['source']}\n"
        )

        if project.get("source_link"):
            message += (
                f"Original source: {project['source_link']}\n"
            )

        message += "\nNew Zealy community discovered."

        try:
            send_telegram(message)
            print(f"Community alert sent: {slug}")
        except Exception as error:
            print(f"Telegram alert failed: {error}")
            continue

        seen.add(slug)

    # Send Zealy mentions without direct community links
    for lead in project_leads:
        message = (
            "⭐ PROMISING ZEALY PROJECT\n\n"
            f"Announcement: {lead['title']}\n\n"
            f"{lead['summary']}\n\n"
            "Community link: Not found yet.\n"
            f"Original source: {lead['link']}"
        )

        try:
            send_telegram(message)
            print(f"Zealy lead alert sent: {lead['title']}")
        except Exception as error:
            print(f"Telegram lead alert failed: {error}")

    # Save discovery history
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen), file, indent=2)

    with open(X_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen_x_posts), file, indent=2)

    print("\nZealy Hunter scan completed.")


if __name__ == "__main__":
    main()
                
