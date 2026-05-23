#!/usr/bin/env python3
"""Chiama Apify run-sync-get-dataset-items e scrive il risultato in /tmp.

Su piano paid Apify (no rate limit), fa fino a 3 tentativi su errori
transienti (HTTP 408 timeout, 429, 5xx) con backoff 5s/15s.

Logica:
- POST run-sync con timeout 120s
- HTTP 5xx/408/429 → retry (max 3 tentativi totali)
- HTTP 201 → check payload
- HTTP altro non-retriable → exit 2 (INFRA)
- Risposta non JSON array → exit 3 (INFRA)
- Array vuoto → exit 4 (INFRA)
- Nessun item con `id` + `directLink` → exit 5 (INFRA)
- Altrimenti scrive items in OUTPUT_PATH e stampa il count → exit 0

Output: /tmp/apify_items.json (array di oggetti listing Apify)
Env richiesti: APIFY_TOKEN, APIFY_ACTOR_ID
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

SEARCH_URL = (
    "https://www.immobiliare.it/vendita-case/milano/"
    "?prezzoMassimo=450000&superficieMinima=80"
    "&ordinamento=data_pubblicazione_decrescente"
)
MAX_LISTINGS = 60
OUTPUT_PATH = "/tmp/apify_items.json"
APIFY_TIMEOUT = 180  # secondi: timeout actor-side passato come querystring
TIMEOUT_SEC = APIFY_TIMEOUT + 40  # client HTTP timeout, un po' più dell'actor
MAX_ATTEMPTS = 3
BACKOFFS_SEC = [5, 15]  # tra tentativo 1→2 e 2→3
RETRIABLE_CODES = {408, 429, 500, 502, 503, 504}


def _is_run_failed(http_code: int, raw: bytes) -> bool:
    """HTTP 400 con error.type=run-failed = actor-side timeout/crash, retriable."""
    if http_code != 400:
        return False
    try:
        payload = json.loads(raw)
        return (payload.get("error") or {}).get("type") == "run-failed"
    except Exception:
        return False


def fetch_with_retry(url: str, body: bytes) -> tuple[int, bytes]:
    """POST con retry su HTTP 408/429/5xx e su HTTP 400 con run-failed.
    Ritorna (http_code, raw_bytes).

    Solleva RuntimeError se tutti i tentativi falliscono per errori di rete.
    Errori HTTP non-retriable vengono ritornati al chiamante (no raise).
    """
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=TIMEOUT_SEC)
            return resp.getcode(), resp.read()
        except urllib.error.HTTPError as e:
            code = e.code
            raw = e.read()
            if code not in RETRIABLE_CODES and not _is_run_failed(code, raw):
                return code, raw
            last_err = f"HTTP {code}" + (" (run-failed)" if _is_run_failed(code, raw) else "")
        except Exception as e:
            last_err = f"network error: {e}"

        if attempt < MAX_ATTEMPTS:
            sleep_sec = BACKOFFS_SEC[attempt - 1]
            print(
                f"WARN: tentativo {attempt}/{MAX_ATTEMPTS} fallito ({last_err}), retry in {sleep_sec}s",
                file=sys.stderr,
            )
            time.sleep(sleep_sec)

    raise RuntimeError(last_err or "exhausted retries")


def main() -> int:
    token = os.environ.get("APIFY_TOKEN")
    actor_id = os.environ.get("APIFY_ACTOR_ID")
    if not token or not actor_id:
        print("ERROR: APIFY_TOKEN o APIFY_ACTOR_ID mancanti", file=sys.stderr)
        return 1

    url = (
        f"https://api.apify.com/v2/acts/{actor_id}"
        f"/run-sync-get-dataset-items?token={token}&timeout={APIFY_TIMEOUT}"
    )
    body = json.dumps({"startUrl": SEARCH_URL, "maxListings": MAX_LISTINGS}).encode()

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
        print(
            f"INFRA: response not JSON: {e}\nBody (first 500): {raw[:500].decode('utf-8', errors='replace')}",
            file=sys.stderr,
        )
        return 3

    if not isinstance(data, list) or len(data) == 0:
        print(f"INFRA: empty or non-list response: {str(data)[:500]}", file=sys.stderr)
        return 4

    valid = [it for it in data if isinstance(it, dict) and it.get("id") and it.get("directLink")]
    if not valid:
        print(
            f"INFRA: 0 item validi su {len(data)} ricevuti. Item[0]: {str(data[0])[:300]}",
            file=sys.stderr,
        )
        return 5

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(valid, f, ensure_ascii=False)
    print(f"OK: {len(valid)} listing salvati in {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
