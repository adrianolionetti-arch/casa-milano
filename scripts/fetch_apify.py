#!/usr/bin/env python3
"""Fa UNA SOLA chiamata Apify run-sync-get-dataset-items e scrive il risultato.

Sostituisce il curl Bash in CLAUDE.md Step 2 — l'agente faceva doppia chiamata
(2026-05-16 e 5-17 hanno generato 2 run Apify in 17-40 sec → 2° colpiva il
rate limit free 30-min → INFRA email anche se la 1ª era SUCCEEDED).

Logica:
- POST run-sync con timeout 120s
- Se HTTP != 201 → exit 2 (INFRA)
- Se risposta non è JSON array → exit 3 (INFRA)
- Se array vuoto → exit 4 (INFRA)
- Se nessun item ha `id` + `directLink` → exit 5 (INFRA: rate-limit response wrapped come item)
- Altrimenti scrive items in OUTPUT_PATH e stampa il count → exit 0

Output: /tmp/apify_items.json (array di oggetti listing Apify)
Env richiesti: APIFY_TOKEN, APIFY_ACTOR_ID

NON FA RETRY. Una chiamata sola. Se fallisce, l'agente deve mandare email INFRA
e abortire — la 2° chiamata interna a 30 min becca il rate limit del free plan.
"""
import json
import os
import sys
import urllib.error
import urllib.request

SEARCH_URL = (
    "https://www.immobiliare.it/vendita-case/milano/"
    "?prezzoMassimo=360000&superficieMinima=80"
    "&ordinamento=data_pubblicazione_decrescente"
)
MAX_LISTINGS = 60
OUTPUT_PATH = "/tmp/apify_items.json"
TIMEOUT_SEC = 150  # un po' più del timeout=120 Apify-side


def main() -> int:
    token = os.environ.get("APIFY_TOKEN")
    actor_id = os.environ.get("APIFY_ACTOR_ID")
    if not token or not actor_id:
        print("ERROR: APIFY_TOKEN o APIFY_ACTOR_ID mancanti", file=sys.stderr)
        return 1

    url = (
        f"https://api.apify.com/v2/acts/{actor_id}"
        f"/run-sync-get-dataset-items?token={token}&timeout=120"
    )
    body = json.dumps({"startUrl": SEARCH_URL, "maxListings": MAX_LISTINGS}).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT_SEC)
        http_code = resp.getcode()
        raw = resp.read()
    except urllib.error.HTTPError as e:
        http_code = e.code
        raw = e.read()
    except Exception as e:
        print(f"INFRA: network error: {e}", file=sys.stderr)
        return 6

    if http_code != 201:
        print(f"INFRA: HTTP {http_code}\nBody (first 500): {raw[:500].decode('utf-8', errors='replace')}", file=sys.stderr)
        return 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"INFRA: response not JSON: {e}\nBody (first 500): {raw[:500].decode('utf-8', errors='replace')}", file=sys.stderr)
        return 3

    if not isinstance(data, list) or len(data) == 0:
        print(f"INFRA: empty or non-list response: {str(data)[:500]}", file=sys.stderr)
        return 4

    valid = [it for it in data if isinstance(it, dict) and it.get("id") and it.get("directLink")]
    if not valid:
        # Caso tipico: rate limit free wrappato come item: [{"message": "Rate limit active..."}]
        print(f"INFRA: 0 item validi su {len(data)} ricevuti. Probabile rate limit. Item[0]: {str(data[0])[:300]}", file=sys.stderr)
        return 5

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(valid, f, ensure_ascii=False)
    print(f"OK: {len(valid)} listing salvati in {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
