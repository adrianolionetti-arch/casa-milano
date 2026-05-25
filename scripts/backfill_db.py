#!/usr/bin/env python3
"""Backfill one-shot di annunci_visti.json con campi mancanti via Apify.

Per ogni annuncio "attivo" (punteggio >= 6, ultimi 30 giorni, no SCARTATO/ESCLUSO)
i cui campi piano/locali/bagni/ascensore/indirizzo/agenzia/descrizione sono assenti,
chiama l'actor single-listing di Apify per recuperarli e li mergia nel record.

Da lanciare via workflow_dispatch (vedi .github/workflows/backfill.yml).
Idempotente: rilanciare due volte non causa duplicati ne sovrascrive campi gia' pieni.

ENV richiesti: APIFY_TOKEN
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "annunci_visti.json"

APIFY_ACTOR = "azzouzana~immobiliare-it-listing-page-scraper-by-items-urls"
DAYS_WINDOW = 30
MIN_SCORE = 6.0
BATCH_SIZE = 10  # quante URL per chiamata Apify
ENRICH_FIELDS = ("locali", "bagni", "piano", "ascensore", "indirizzo", "agenzia", "descrizione")


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def needs_backfill(a: dict) -> bool:
    """Vero se il record manca di almeno uno dei campi target."""
    for f in ENRICH_FIELDS:
        if a.get(f) in (None, "", 0):
            return True
    return False


def extract_fields(item: dict) -> dict:
    """Estrae i campi dal payload Apify (CLAUDE.md Step 3)."""
    props = (item.get("properties") or [{}])[0]
    floor = props.get("floor") or {}
    location = props.get("location") or {}
    advertiser = item.get("advertiser") or {}
    agency = advertiser.get("agency") or {}

    surface_raw = props.get("surface")
    mq = None
    if surface_raw:
        digits = "".join(c for c in str(surface_raw) if c.isdigit())
        if digits:
            mq = int(digits)

    return {
        "mq": mq,
        "locali": props.get("rooms"),
        "bagni": props.get("bathrooms"),
        "piano": floor.get("abbreviation"),
        "ascensore": props.get("elevator") if props.get("elevator") is not None else False,
        "indirizzo": location.get("address"),
        "agenzia": agency.get("displayName"),
        "descrizione": props.get("description"),
    }


def apify_batch(urls: list[str], token: str) -> list[dict]:
    """Chiama Apify single-listing actor con un batch di URL."""
    api_url = (
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR}"
        f"/run-sync-get-dataset-items?token={token}&timeout=180"
    )
    body = json.dumps({"startUrls": urls}).encode()
    req = urllib.request.Request(
        api_url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=200)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[apify] HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[apify] {type(e).__name__}: {e}", file=sys.stderr)
        raise


def main():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("APIFY_TOKEN non in env. Abort.", file=sys.stderr)
        return 2

    with open(DB_PATH) as f:
        db = json.load(f)
    annunci = db.get("annunci", [])

    cutoff = date.today() - timedelta(days=DAYS_WINDOW)

    candidates = []
    for a in annunci:
        note = (a.get("note") or "")
        if note.startswith(("SCARTATO", "ESCLUSO")):
            continue
        pts = a.get("punteggio")
        if pts is None or pts < MIN_SCORE:
            continue
        dv = parse_date(a.get("data_vista"))
        if not dv or dv < cutoff:
            continue
        if not (a.get("url") or "").startswith("https://www.immobiliare.it/annunci/"):
            continue
        if needs_backfill(a):
            candidates.append(a)

    print(f"Candidati al backfill: {len(candidates)}/{len(annunci)}")
    if not candidates:
        print("Niente da fare.")
        return 0

    # Index per URL per merge veloce
    by_url = {a["url"]: a for a in candidates}

    enriched = 0
    failed = []
    urls = list(by_url.keys())

    for i in range(0, len(urls), BATCH_SIZE):
        batch = urls[i:i + BATCH_SIZE]
        print(f"Batch {i // BATCH_SIZE + 1}: {len(batch)} URL...")
        try:
            items = apify_batch(batch, token)
        except Exception:
            failed.extend(batch)
            continue

        for item in items:
            url = item.get("directLink") or item.get("url")
            # Tenta match per URL esatto, poi per ID nell'URL
            target = by_url.get(url)
            if not target:
                # fallback: cerca per id immobiliare nell'URL
                item_id = item.get("id")
                if item_id:
                    for u, a in by_url.items():
                        if str(item_id) in u:
                            target = a
                            break
            if not target:
                continue

            extracted = extract_fields(item)
            # Mergia solo campi mancanti (idempotente)
            for k, v in extracted.items():
                if target.get(k) in (None, "", 0) and v not in (None, "", 0):
                    target[k] = v
            enriched += 1

    print(f"Arricchiti: {enriched}, falliti: {len(failed)}")
    if failed:
        print("URL falliti:", failed[:5], "..." if len(failed) > 5 else "")

    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"DB salvato: {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
