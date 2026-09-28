#!/usr/bin/env python3
"""Fetch di prova dall'actor memo23/immobiliare-scraper (p9QZzUdBCGXMDuKad).

Serve al confronto in parallelo con l'actor in produzione
(azzouzana, sPIR3lEdL9H69xrmi) prima di un'eventuale migrazione: stesso
search URL, stesso numero di listing, output grezzo su /tmp/memo23_items.json.

Differenze di input rispetto all'actor attuale:
    startUrls (array) invece di startUrl (stringa)
    sortBy="mostRecent" per avere in cima i più recenti

Exit code: 0 ok · 1 config mancante · 2-6 come fetch_apify.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_apify import (  # noqa: E402  riuso della logica di retry
    APIFY_TIMEOUT,
    MAX_ATTEMPTS,
    MAX_LISTINGS,
    SEARCH_URL,
    fetch_with_retry,
)

ACTOR_ID = os.environ.get("MEMO23_ACTOR_ID", "p9QZzUdBCGXMDuKad")
OUTPUT_PATH = os.environ.get("MEMO23_OUTPUT", "/tmp/apify_items.json")


def main() -> int:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("ERROR: APIFY_TOKEN mancante", file=sys.stderr)
        return 1

    url = (
        f"https://api.apify.com/v2/acts/{ACTOR_ID}"
        f"/run-sync-get-dataset-items?token={token}&timeout={APIFY_TIMEOUT}"
    )
    body = json.dumps({
        "startUrls": [SEARCH_URL],
        "maxItems": MAX_LISTINGS,
        "sortBy": "mostRecent",
    }).encode()

    try:
        http_code, raw = fetch_with_retry(url, body)
    except RuntimeError as e:
        print(f"INFRA: tutti i {MAX_ATTEMPTS} tentativi falliti: {e}", file=sys.stderr)
        return 6

    if http_code != 201:
        print(
            f"INFRA: HTTP {http_code}\nBody (first 500): {raw[:500].decode('utf-8', errors='replace')}",
            file=sys.stderr,
        )
        return 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"INFRA: response not JSON: {e}", file=sys.stderr)
        return 3

    if not isinstance(data, list) or not data:
        print(f"INFRA: empty or non-list response: {str(data)[:500]}", file=sys.stderr)
        return 4

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"OK: {len(data)} item salvati in {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
