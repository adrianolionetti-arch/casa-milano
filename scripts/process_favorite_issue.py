#!/usr/bin/env python3
"""Processa una GitHub issue 'preferito' e aggiunge l'annuncio a preferiti.json.

Eseguito dal workflow .github/workflows/process-preferiti.yml quando viene
aperta una issue con label 'preferito'.

Input: il body della issue ha questo formato (chiave: valore per riga):
  URL: https://www.immobiliare.it/annunci/127700336/
  Titolo: Trilocale Via X
  Sito: immobiliare.it
  Prezzo: 345000          (opzionale)
  Mq: 98                  (opzionale)
  Zona: NoLo              (opzionale)
  Note: piace ad alessia  (opzionale)

Per URL immobiliare.it, tenta di arricchire i dati via Apify single-listing actor.
Per altri portali, salva con i campi forniti (può essere solo URL + titolo).

Uso:
  python3 scripts/process_favorite_issue.py <issue_number> <issue_body_path>
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFERITI_PATH = ROOT / "preferiti.json"

APIFY_SINGLE_ACTOR = "azzouzana~immobiliare-it-listing-page-scraper-by-items-urls"


def parse_issue_body(body: str) -> dict:
    """Estrae i campi 'key: value' dalla issue body."""
    out = {}
    for line in body.splitlines():
        m = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.+?)\s*$", line)
        if m:
            key = m.group(1).lower()
            val = m.group(2).strip()
            if val and val.lower() not in ("(opzionale)", "tbd", "—", ""):
                out[key] = val
    return out


def extract_id_from_url(url: str) -> str | None:
    """Estrae l'id Immobiliare.it dall'URL se possibile."""
    m = re.search(r"immobiliare\.it/annunci/(\d+)", url or "")
    if m:
        return f"immobiliare-{m.group(1)}"
    return None


def enrich_via_apify(url: str) -> dict:
    """Tenta di recuperare dati pieni da Apify single-listing actor.
    Ritorna dict (vuoto se fallisce). Best-effort, fail silently."""
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return {}
    api_url = (
        f"https://api.apify.com/v2/acts/{APIFY_SINGLE_ACTOR}"
        f"/run-sync-get-dataset-items?token={token}&timeout=90"
    )
    body = json.dumps({"startUrls": [url]}).encode()
    req = urllib.request.Request(
        api_url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
    except Exception as e:
        print(f"[apify enrich] failed: {e}", file=sys.stderr)
        return {}

    if not isinstance(data, list):
        print(f"[apify enrich] unexpected response type: {type(data).__name__}", file=sys.stderr)
        return {}

    print(f"[apify enrich] {len(data)} item(s) returned for {url}", file=sys.stderr)
    target_id = extract_id_from_url(url)
    target_num = target_id.split("-")[-1] if target_id else None

    item = None
    for it in data:
        if isinstance(it, dict) and str(it.get("id")) == target_num:
            item = it
            break
    if not item:
        if data:
            snippet = json.dumps(data[0], ensure_ascii=False)[:600]
            print(
                f"[apify enrich] no item matches id={target_num}; first item payload: {snippet}",
                file=sys.stderr,
            )
        return {}

    props = (item.get("properties") or [{}])[0]
    loc = props.get("location") or {}
    photos = (props.get("multimedia") or {}).get("photos") or []
    surface_str = props.get("surface") or ""
    mq_match = re.search(r"(\d+)", surface_str)
    mq = int(mq_match.group(1)) if mq_match else None

    return {
        "titolo": item.get("title"),
        "prezzo": (item.get("price") or {}).get("value"),
        "mq": mq,
        "zona": loc.get("microzone") or loc.get("macrozone"),
        "indirizzo": loc.get("address"),
        "agenzia": ((item.get("advertiser") or {}).get("agency") or {}).get("displayName"),
        "foto_url": (photos[0].get("urls", {}).get("large") if photos else None),
        "lat": loc.get("latitude"),
        "lon": loc.get("longitude"),
    }


def main(issue_body_path: str) -> int:
    with open(issue_body_path, encoding="utf-8") as f:
        body = f.read()

    fields = parse_issue_body(body)
    url = fields.get("url")
    if not url:
        print("ERROR: URL field missing in issue body", file=sys.stderr)
        return 1

    # Distingue modalità add vs remove dal titolo della issue (env ISSUE_TITLE)
    title = os.environ.get("ISSUE_TITLE", "")
    is_remove = title.lower().startswith("rimuovi preferito:")

    listing_id = extract_id_from_url(url) or fields.get("id") or f"manual-{date.today().strftime('%Y%m%d-%H%M%S')}"

    # Carica preferiti esistenti
    with open(PREFERITI_PATH, encoding="utf-8") as f:
        pj = json.load(f)
    annunci_list = pj.setdefault("annunci", [])

    # ===== Modalità REMOVE =====
    if is_remove:
        before = len(annunci_list)
        pj["annunci"] = [a for a in annunci_list if a.get("id") != listing_id]
        removed = before - len(pj["annunci"])
        if removed > 0:
            with open(PREFERITI_PATH, "w", encoding="utf-8") as f:
                json.dump(pj, f, indent=2, ensure_ascii=False)
            print(f"OK: rimosso preferito {listing_id} ({removed} entry)")
        else:
            print(f"NOOP: {listing_id} non era nei preferiti")
        return 0
    existing_idx = next(
        (i for i, a in enumerate(annunci_list) if a.get("id") == listing_id),
        None,
    )
    if existing_idx is not None:
        existing = annunci_list[existing_idx]
        ENRICH_FIELDS = ("prezzo", "mq", "zona", "foto_url", "indirizzo", "agenzia", "lat", "lon")
        missing = [k for k in ENRICH_FIELDS if not existing.get(k)]
        existing_url = existing.get("url") or url
        if missing and "immobiliare.it" in existing_url:
            print(
                f"Listing {listing_id} già presente, campi vuoti: {missing} — retry enrichment...",
                file=sys.stderr,
            )
            enriched = enrich_via_apify(existing_url)
            updated_fields = []
            for k, v in enriched.items():
                if v and not existing.get(k):
                    existing[k] = v
                    updated_fields.append(k)
            if updated_fields:
                with open(PREFERITI_PATH, "w", encoding="utf-8") as f:
                    json.dump(pj, f, indent=2, ensure_ascii=False)
                print(
                    f"OK: preferito {listing_id} arricchito — aggiornati: {updated_fields}"
                )
            else:
                print(
                    f"Listing {listing_id}: enrichment non ha prodotto dati nuovi — skip"
                )
            return 0
        print(f"Listing {listing_id} già nei preferiti — skip")
        return 0

    # Costruisci entry
    entry = {
        "id": listing_id,
        "url": url,
        "titolo": fields.get("titolo") or "(senza titolo)",
        "prezzo": int(fields["prezzo"]) if fields.get("prezzo", "").isdigit() else None,
        "mq": int(fields["mq"]) if fields.get("mq", "").isdigit() else None,
        "zona": fields.get("zona"),
        "indirizzo": fields.get("indirizzo"),
        "foto_url": fields.get("foto_url"),
        "agenzia": fields.get("agenzia") or fields.get("sito"),
        "data_aggiunto": date.today().isoformat(),
        "note_personali": fields.get("note") or "",
    }

    # Se è un URL Immobiliare e mancano dati, prova Apify
    if "immobiliare.it" in url and (not entry["prezzo"] or not entry["mq"]):
        print(f"Tentativo enrichment Apify per {url}...", file=sys.stderr)
        enriched = enrich_via_apify(url)
        for k, v in enriched.items():
            if v and not entry.get(k):
                entry[k] = v

    pj.setdefault("annunci", []).append(entry)
    with open(PREFERITI_PATH, "w", encoding="utf-8") as f:
        json.dump(pj, f, indent=2, ensure_ascii=False)

    print(f"OK: preferito aggiunto — {listing_id} — {entry.get('titolo')[:60]}")
    print(f"   prezzo={entry.get('prezzo')} mq={entry.get('mq')} zona={entry.get('zona')}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: process_favorite_issue.py <issue_body_path>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
