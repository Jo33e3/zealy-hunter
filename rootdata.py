
import os
import requests

API_URL = "https://api.rootdata.com/open/ser_inv"

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

MAX_ALERTS = 5
MIN_SCORE = 4

SIGNALS = {
    "product": {
        "weight": 2,
        "words": [
            "protocol", "platform", "network", "infrastructure",
            "blockchain", "ecosystem", "application", "dapp",
            "exchange", "wallet", "marketplace", "rollup"
        ]
    },
    "development": {
        "weight": 2,
        "words": [
            "testnet", "mainnet", "devnet", "beta", "building",
            "developer", "sdk", "api", "open source", "github"
        ]
    },
    "funding": {
        "weight": 2,
        "words": [
            "funding", "raised", "backed", "investor",
            "investment", "seed round", "series a",
            "grant", "accelerator"
        ]
    },
    "sector": {
        "weight": 1,
        "words": [
            "defi", "depin", "rwa", "zero knowledge", "zk",
            "artificial intelligence", "gaming", "restaking",
            "modular", "cross-chain"
        ]
    },
    "credibility": {
        "weight": 1,
        "words": [
            "partnership", "partner", "audit", "validator",
            "foundation", "institutional"
        ]
    }
}


def score_project(name, description):
    text = f"{name} {description}".lower()

    score = 0
    reasons = []

    for category, signal in SIGNALS.items():
        matches = [
            word for word in signal["words"]
            if word in text
        ]

        if matches:
            score += signal["weight"]
            reasons.append(category.capitalize())

    return score, reasons


def discover_rootdata():
    api_key = os.environ.get("ROOTDATA_API_KEY")

    if not api_key:
        print("ROOTDATA_API_KEY is missing.")
        return {}

    candidates = {}

    for term in SEARCH_TERMS:
        try:
            response = requests.post(
                API_URL,
                headers={
                    "apikey": api_key,
                    "language": "en",
                    "Content-Type": "application/json"
                },
                json={"query": term},
                timeout=30
            )

            response.raise_for_status()
            result = response.json()

            if result.get("result") != 200:
                print(f"RootData search issue: {term}")
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
                name = item.get("name", "").strip()
                description = item.get("introduce", "").strip()

                if not project_id or not name:
                    continue

                if len(description) < 40:
                    continue

                score, reasons = score_project(
                    name, description
                )

                if score < MIN_SCORE:
                    continue

                key = f"rootdata_{project_id}"

                candidates[key] = {
                    "name": name,
                    "url": item.get("rootdataurl", ""),
                    "source": "RootData",
                    "description": description,
                    "score": score,
                    "reasons": reasons
                }

            print(f"RootData searched: {term}")

        except Exception as error:
            print(f"RootData error ({term}): {error}")

    ranked = sorted(
        candidates.items(),
        key=lambda item: item[1]["score"],
        reverse=True
    )

    selected = dict(ranked[:MAX_ALERTS])

    print(f"RootData qualifying projects: {len(candidates)}")
    print(f"RootData selected for alerts: {len(selected)}")

    return selected
    
