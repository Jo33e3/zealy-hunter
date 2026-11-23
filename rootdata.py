
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


def discover_rootdata():
    api_key = os.environ["ROOTDATA_API_KEY"]
    projects = {}

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

                if not project_id:
                    continue

                key = f"rootdata_{project_id}"

                projects[key] = {
                    "name": item.get("name", "Unknown project"),
                    "url": item.get("rootdataurl", ""),
                    "source": "RootData",
                    "description": item.get("introduce", "")
                }

            print(f"RootData searched: {term}")

        except Exception as error:
            print(f"RootData error ({term}): {error}")

    return projects
  
