#!/usr/bin/env python3
"""Chiama Apify run-sync-get-dataset-items sull'attore Idealista e scrive il risultato.

Attore: dz_omar/idealista-scraper-api (alias `dz_omar~idealista-scraper-api`).
Pricing: $0.5/1000 risultati (paid plan, no rate limit).

Su piano paid Apify, fa fino a 3 tentativi su errori transienti
(HTTP 408 timeout, 429, 5xx, 400 con type=run-failed) con backoff 5s/15s.

Logica identica a fetch_apify.py ma con:
- Actor id da env IDEALISTA_ACTOR_ID
- Input body: {"Property_urls": [{"url": SEARCH_URL}], "desiredResults": N}
- Output: /tmp/idealista_items.json (array di item idealista)
- Exit code 0 se OK, 1-6 in caso di failure (vedi fetch_apify.py)

NOTA: se IDEALISTA_ACTOR_ID non è settato → exit 0 silenzioso (idealista è
sorgente opt-in, l'assenza non è un errore).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

SEARCH_URL = (
    "https://www.idealista.it/vendita-case/milano-milano/"
    "con-prezzo_450000,dimensione_80/?ordine=publicacion-desc"
)
MAX_LISTINGS = 60
OUTPUT_PATH = "/tmp/idealista_items.json"
APIFY_TIMEOUT = 180
TIMEOUT_SEC = APIFY_TIMEOUT + 40
MAX_ATTEMPTS = 3
BACKOFFS_SEC = [5, 15]
RETRIABLE_CODES = {408, 429, 500, 502, 503, 504}


def _is_run_failed(http_code: int, raw: bytes) -> bool:
    if http_code != 400:
        return False
    try:
        payload = json.loads(raw)
        return (payload.get("error") or {}).get("type") == "run-failed"
    except Exception:
        return False


def fetch_with_retry(url: str, body: bytes) -> tuple[int, bytes]:
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
    actor_id = os.environ.get("IDEALISTA_ACTOR_ID")
    if not actor_id:
        # Sorgente opt-in: assenza non è errore. Scrive output vuoto e exit 0.
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        print("IDEALISTA_ACTOR_ID non settato → idealista disabilitato, output vuoto")
        return 0
    if not token:
        print("ERROR: APIFY_TOKEN mancante", file=sys.stderr)
        return 1

    url = (
        f"https://api.apify.com/v2/acts/{actor_id}"
        f"/run-sync-get-dataset-items?token={token}&timeout={APIFY_TIMEOUT}"
    )
    body = json.dumps({
        "Property_urls": [{"url": SEARCH_URL}],
        "desiredResults": MAX_LISTINGS,
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
        print(
            f"INFRA: response not JSON: {e}\nBody (first 500): {raw[:500].decode('utf-8', errors='replace')}",
            file=sys.stderr,
        )
        return 3

    if not isinstance(data, list):
        print(f"INFRA: non-list response: {str(data)[:500]}", file=sys.stderr)
        return 4

    # idealista è opt-in: array vuoto valido (es. nessun match)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"OK: {len(data)} listing idealista salvati in {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
