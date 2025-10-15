import requests
import time

TOKEN = "9ef42d11d56cba834b4bf01bdbbb3575"
BASE = "https://enever.nl/api"

# endpoints to try
ENDPOINTS = {
    "stroom_vandaag":   "stroomprijs_vandaag.php",
    "stroom_morgen":    "stroomprijs_morgen.php",
    "stroom_30dagen":   "stroomprijs_laatste30dagen.php",
    "gas_vandaag":      "gasprijs_vandaag.php",
    "gas_30dagen":      "gasprijs_laatste30dagen.php",
}

def fetch_feed(name, endpoint):
    url = f"{BASE}/{endpoint}"
    params = {"token": TOKEN}
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        print(f"Error fetching {name}: HTTP {resp.status_code} – {resp.text}")
        return None
    try:
        data = resp.json()
    except ValueError:
        print(f"Non-JSON response for {name}: {resp.text}")
        return None
    return data

def main():
    results = {}
    for name, endpoint in ENDPOINTS.items():
        print(f"Fetching {name} …")
        data = fetch_feed(name, endpoint)
        results[name] = data
        # optional: sleep a bit to avoid hammering the API
        time.sleep(0.2)
    # Now you have a dict `results` with all feeds
    # You can print, store as JSON, write to DB, etc.
    import json
    print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
