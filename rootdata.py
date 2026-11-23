
import os
import requests
from datetime import datetime

SEARCH_URL = "https://api.rootdata.com/open/ser_inv"
DETAIL_URL = "https://api.rootdata.com/open/get_item"

SEARCH_TERMS = [
    "Web3",
    "DeFi",
    "AI crypto",
    "Layer 2",
    "DePIN",
    "RWA",
    "Web3 gaming",
    "crypto infrastructure"
]

MAX_DETAILS = 3
MIN_SCORE = 5

SECTORS = [
    "defi", "depin", "rwa", "gaming", "infrastructure",
    "artificial intelligence", "layer 2", "zero knowledge",
    "restaking", "modular", "cross-chain", "web3"
]


def headers(api_key):
    return {
        "apikey": api_key,
        "language": "en",
        "Content-Type": "application/json"
    }


def preliminary_score(item):
    description = item.get("introduce") or ""
    text = description.lower()

    score = 0

    if len(description) >= 80:
        score += 1

    if any(word in text for word in SECTORS):
        score += 2

    if item.get("active") is True:
        score += 1

    return score


def get_details(api_key, project_id):
    response = requests.post(
        DETAIL_URL,
        headers=headers(api_key),
        json={"project_id": project_id, "include_investors": True},
        timeout=30
    )

    response.raise_for_status()
    result = response.json()

    if result.get("result") != 200:
        return None

    return result.get("data") or None


def score_details(data):
    score = 0
    reasons = []

    if data.get("active") is True:
        score += 1
        reasons.append("Active project")

    year_text = str(data.get("establishment_date") or "")[:4]

    try:
        age = datetime.now().year - int(year_text)

        if 0 <= age <= 3:
            score += 2
            reasons.append("Early-stage age")
        elif 0 <= age <= 5:
            score += 1
            reasons.append("Relatively young project")
    except (ValueError, TypeError):
        pass

    try:
        funding = float(data.get("total_funding") or 0)

        if funding > 0:
            score += 1
            reasons.append("Recorded funding")
    except (ValueError, TypeError):
        funding = 0

    investors = data.get("investors") or []

    if investors:
        score += 1
        reasons.append("Has listed investors")

    if len(investors) >= 3:
        score += 1
        reasons.append("Multiple listed investors")

    try:
        rd_score = float(data.get("rd_score") or 0)

        if rd_score > 0:
            score += 1
            reasons.append("RD Growth Index available")
    except (ValueError, TypeError):
        rd_score = 0

    tags = data.get("tags") or []

    if any(
        sector in str(tag).lower()
        for tag in tags
        for sector in SECTORS
    ):
        score += 2
        reasons.append("Relevant Web3 sector")

    social = data.get("social_media") or {}

    if isinstance(social, dict) and any(social.values()):
        score += 1
        reasons.append("Social or website presence")

    return score, reasons, funding, rd_score


def discover_rootdata(seen=None):
    seen = set(seen or [])
    api_key = os.environ.get("ROOTDATA_API_KEY")

    if not api_key:
        print("ROOTDATA_API_KEY is missing.")
        return {}

    candidates = {}

    for term in SEARCH_TERMS:
        try:
            response = requests.post(
                SEARCH_URL,
                headers=headers(api_key),
                json={"query": term},
                timeout=30
            )

            response.raise_for_status()
            result = response.json()

            if result.get("result") != 200:
                print(f"Search issue: {term}")
                continue

            items = result.get("data", [])

            if isinstance(items, dict):
                items = [items]

            for item in items:
                if item.get("type") != 1:
                    continue

                if item.get("active") is False:
                    continue

                project_id = item.get("id")

                if not project_id:
                    continue

                key = f"rootdata_{project_id}"

                if key in seen:
                    continue

                candidates[key] = item

            print(f"RootData searched: {term}")

        except Exception as error:
            print(f"RootData search error ({term}): {error}")

    ranked = sorted(
        candidates.items(),
        key=lambda item: preliminary_score(item[1]),
        reverse=True
    )

    selected = {}

    for key, item in ranked[:MAX_DETAILS]:
        try:
            details = get_details(api_key, item["id"])

            if not details:
                continue

            if details.get("active") is False:
                continue

            score, reasons, funding, rd_score = score_details(details)

            if score < MIN_SCORE:
                continue

            selected[key] = {
                "name": details.get("project_name") or item.get("name"),
                "url": details.get("rootdataurl") or item.get("rootdataurl", ""),
                "source": "RootData",
                "description": details.get("one_liner") or details.get("description") or item.get("introduce", ""),
                "score": score,
                "reasons": reasons,
                "establishment_date": details.get("establishment_date") or "Unknown",
                "funding": funding,
                "investor_count": len(details.get("investors") or []),
                "rd_score": rd_score,
                "tags": details.get("tags") or []
            }

        except Exception as error:
            print(f"Project detail error ({key}): {error}")

    selected = dict(
        sorted(
            selected.items(),
            key=lambda item: item[1]["score"],
            reverse=True
        )[:5]
    )

    print(f"RootData candidates: {len(candidates)}")
    print(f"RootData detailed checks: {min(len(ranked), MAX_DETAILS)}")
    print(f"Promising projects selected: {len(selected)}")

    return selected
    
