import os
import re
import json
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PAGES = [
    "https://zealy.io/explore/new-web3-communities",
    "https://zealy.io/explore",
    "https://zealy.io/explore/upcoming-web3-communities",
]

STATE_FILE = "seen_projects.json"
BASE_URL = "https://zealy.io"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
}


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs = dict(attrs)
            href = attrs.get("href", "")
            if href:
                self.current = {"href": href, "text": ""}

    def handle_data(self, data):
        if self.current:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current:
            self.links.append(self.current)
            self.current = None


def load_seen():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def discover():
    projects = {}

    for page in PAGES:
        try:
            response = requests.get(
                page,
                headers=HEADERS,
                timeout=30
            )
            response.raise_for_status()

            parser = LinkParser()
            parser.feed(response.text)

            print("\n--- PAGE DIAGNOSTICS ---")
            print(f"Page: {page}")
            print(f"Status: {response.status_code}")
            print(f"Content type: {response.headers.get('Content-Type')}")
            print(f"HTML characters: {len(response.text)}")
            print(f"Anchor links: {len(parser.links)}")
            print(
                "Next.js data present:",
                "__NEXT_DATA__" in response.text
                or "self.__next_f" in response.text
            )

            print("Known listing names:")
            for term in [
                "Globe Markets",
                "HYSEN SI",
                "Fractionalised World Hub",
                "Maven Trading",
                "Injective"
            ]:
                index = response.text.lower().find(term.lower())
                print(f"  {term}: {'FOUND' if index >= 0 else 'not found'}")

            candidates = re.findall(
                r'/c/[A-Za-z0-9_-]+',
                response.text
            )
            print("Candidate community routes:", sorted(set(candidates))[:20])
            print("Sample links:")
            for sample in parser.links[:8]:
                print(f"  {sample['href'][:180]}")

            for link in parser.links:
                url = urljoin(BASE_URL, link["href"])
                path = urlparse(url).path.strip("/")

                match = re.match(r"c/([^/]+)", path)

                if not match:
                    continue

                slug = match.group(1)

                if slug in ("login", "signup", "create"):
                    continue

                name = link["text"].strip() or slug

                projects[slug] = {
                    "name": name,
                    "url": f"{BASE_URL}/c/{slug}",
                    "source": page
                }

            print(f"Communities detected on page: {len(projects)}")

        except requests.RequestException as error:
            print(f"Could not check {page}: {error}")

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
    projects = discover()

    new_projects = [
        (slug, project)
        for slug, project in projects.items()
        if slug not in seen
    ]

    print("\n========== SCAN SUMMARY ==========")
    print(f"Communities found: {len(projects)}")
    print(f"New discoveries: {len(new_projects)}")

    for slug, project in new_projects:
        message = (
            "🟢 NEW ZEALY DISCOVERY\n\n"
            f"Project: {project['name']}\n"
            f"Link: {project['url']}\n"
            f"Source: {project['source']}\n\n"
            "Check its campaign and opportunities."
        )

        send_telegram(message)

    seen.update(projects.keys())

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen), file, indent=2)

    print("Discovery scan completed.")


if __name__ == "__main__":
    main()
            
