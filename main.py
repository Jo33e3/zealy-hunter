
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
    r"https?://(?:www\.)?zealy\.io/c/([A-Za-z0-9_-]+)",
    re.IGNORECASE
)

RESERVED_SLUGS = {
    "login", "signup", "create", "explore",
    "home", "about", "pricing", "blog"
}

GENERIC_PHRASES = [
    "make a living from web3",
    "join the next big thing",
    "the future of communities",
    "what is zealy",
    "how to use zealy",
    "getting started with zealy",
    "zealy platform",
    "zealy transforming",
    "zealy guide",
    "zealy tutorial",
    "welcome to zealy",
]


def load_seen(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return set(data if isinstance(data, list) else [])
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def is_valid_community_url(url):
    try:
        parsed = urlparse(url)

        if parsed.netloc.lower() not in (
            "zealy.io", "www.zealy.io"
        ):
            return None

        match = re.fullmatch(
            r"/c/([A-Za-z0-9_-]+)/?",
            parsed.path,
            re.IGNORECASE
        )

        if not match:
            return None

        slug = match.group(1)

        if slug.lower() in RESERVED_SLUGS:
            return None

        return slug

    except Exception:
        return None


def is_specific_zealy_announcement(title, summary, source):
    text = clean_text(title + " " + summary).lower()

    if "zealy" not in text:
        return False

    # Reject generic Zealy advertisements and guides.
    if any(phrase in text for phrase in GENERIC_PHRASES):
        return False

    # Reject pages hosted on Zealy itself unless they
    # are direct community URLs.
    try:
        host = urlparse(source).netloc.lower()
        path = urlparse(source).path.lower()

        if host in ("zealy.io", "www.zealy.io"):
            if not re.fullmatch(r"/c/[^/]+/?", path):
                return False
    except Exception:
        pass

    # Require wording that connects Zealy to a specific
    # project, community, campaign or quest.
    specific_patterns = [
        r"our\s+zealy",
        r"zealy\s+(?:community|campaign|quests|sprint)\s+(?:for|by|of)",
        r"(?:join|complete|check out|visit)\s+.{2,100}\s+on\s+zealy",
        r".{2,100}\s+on\s+zealy",
        r"zealy\s+(?:for|with)\s+.{2,100}",
        r"join\s+our\s+community\s+on\s+zealy",
    ]

    return any(
        re.search(pattern, text)
        for pattern in specific_patterns
    )


def discover_zealy():
    projects = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for url in PAGES:
            try:
                print(f"Checking: {url}")

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
                        href: a.href,
                        name: (a.innerText || "").trim()
                    }))
                """)

                for item in anchors:
                    slug = is_valid_community_url(
                        item.get("href", "")
                    )

                    if not slug:
                        continue

                    name = " ".join(
                        (item.get("name") or slug).split()
                    )

                    projects[slug] = {
                        "name": name[:100],
                        "url": f"{BASE_URL}/c/{slug}",
                        "source": "Zealy"
                    }

                print(f"Valid community links: {len(projects)}")

            except Exception as error:
                print(f"Zealy scan failed: {error}")

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
    projects = {}
    leads = []

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

                for element in entry.iter():
                    tag = element.tag.split("}")[-1]
                    value = "".join(element.itertext()).strip()

                    if value:
                        fields[tag] = value

                    href = element.attrib.get("href")

                    if href:
                        links.append(href)

                title = fields.get("title", "")
                summary = (
                    fields.get("summary")
                    or fields.get("description")
                    or fields.get("content")
                    or ""
                )

                post_link = (
                    fields.get("link")
                    or (links[0] if links else "")
                )

                post_id = (
                    fields.get("id")
                    or fields.get("guid")
                    or post_link
                    or title
                )

                searchable_text = html.unescape(
                    " ".join([
                        title,
                        summary,
                        " ".join(fields.values()),
                        " ".join(links)
                    ])
                )

                # First look for real community links.
                found_slugs = set()

                for match in COMMUNITY_PATTERN.finditer(
                    searchable_text
                ):
                    slug = match.group(1)

                    if slug.lower() not in RESERVED_SLUGS:
                        found_slugs.add(slug)

                for slug in found_slugs:
                    projects[slug] = {
                        "name": slug.replace("-", " ").title(),
                        "url": f"{BASE_URL}/c/{slug}",
                        "source": "RSS discovery",
                        "source_link": post_link
                    }

                # If there is no community link, only accept
                # a specific project-related Zealy announcement.
                if not found_slugs:
                    if is_specific_zealy_announcement(
                        title, summary, post_link
                    ):
                        if post_id not in seen_posts:
                            leads.append({
                                "id": post_id,
                                "title": clean_text(title)[:200],
                                "summary": clean_text(summary)[:500],
                                "link": post_link
                            })

                if post_id:
                    seen_posts.add(post_id)

            print("RSS feed checked.")

        except Exception as error:
            print(f"RSS feed failed: {error}")

    return projects, leads, seen_posts


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

    projects = discover_zealy()

    feed_projects, leads, seen_posts = scan_x_alert_feeds()

    projects.update(feed_projects)

    new_projects = [
        (slug, project)
        for slug, project in projects.items()
        if slug not in seen
    ]

    print(f"Communities found: {len(projects)}")
    print(f"New communities: {len(new_projects)}")
    print(f"Specific Zealy announcements: {len(leads)}")

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

        try:
            send_telegram(message)
            seen.add(slug)
            print(f"Community alert sent: {slug}")
        except Exception as error:
            print(f"Telegram alert failed: {error}")

    for lead in leads:
        message = (
            "⭐ PROMISING ZEALY PROJECT\n\n"
            f"Announcement: {lead['title']}\n\n"
            f"{lead['summary']}\n\n"
            "Community link: Not found yet.\n"
            f"Original source: {lead['link']}"
        )

        try:
            send_telegram(message)
            print(f"Zealy announcement sent: {lead['title']}")
        except Exception as error:
            print(f"Telegram announcement failed: {error}")

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen), file, indent=2)

    with open(X_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen_posts), file, indent=2)

    print("Zealy Hunter scan completed.")


if __name__ == "__main__":
    main()
                        
