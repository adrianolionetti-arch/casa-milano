#!/usr/bin/env python3
"""Confronto fra l'actor Apify in produzione e memo23/immobiliare-scraper.

Legge /tmp/apify_items.json (azzouzana, produzione) e /tmp/memo23_items.json
e stampa un report: quanti listing, quanto si sovrappongono, e soprattutto
quanto sono popolati i campi da cui dipendono filtri e punteggio.

Il campo che pesa di più è `elevator`: oggi un valore assente viene trattato
come "niente ascensore" e l'annuncio esce dal flusso (43 esclusi su 152 fra
luglio e settembre). Se il nuovo actor lo popola meglio, la migrazione
recupera annunci oggi persi.
"""
import json
import re
import sys
from pathlib import Path

PROD = Path("/tmp/apify_items.json")
NUOVO = Path("/tmp/memo23_items.json")
CAMPI = ["prezzo", "mq", "zona", "indirizzo", "ascensore", "bagni", "piano", "descrizione", "lat", "lon"]


def carica(path: Path) -> list:
    if not path.exists():
        print(f"ATTENZIONE: {path} non trovato", file=sys.stderr)
        return []
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def norm_prod(item: dict) -> dict:
    """Mapping dell'actor in produzione (lo stesso di process_session.extract)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from process_session import extract
    return extract(item)


def pesca(obj, *nomi):
    """Cerca il primo dei nomi indicati a qualsiasi profondità del payload."""
    trovati = {}
    pila = [obj]
    while pila:
        corrente = pila.pop()
        if isinstance(corrente, dict):
            for k, v in corrente.items():
                kl = k.lower()
                for n in nomi:
                    if kl == n.lower() and n not in trovati and v not in (None, "", [], {}):
                        trovati[n] = v
                if isinstance(v, (dict, list)):
                    pila.append(v)
        elif isinstance(corrente, list):
            pila.extend(x for x in corrente if isinstance(x, (dict, list)))
    for n in nomi:
        if n in trovati:
            return trovati[n]
    return None


def norm_nuovo(item: dict) -> dict:
    """Mapping esplorativo: il payload di memo23 non è ancora documentato qui,
    quindi i campi vengono pescati per nome ovunque si trovino."""
    superficie = pesca(item, "surface", "surfaceValue", "superficie", "sqm")
    mq = None
    if isinstance(superficie, (int, float)):
        mq = int(superficie)
    elif isinstance(superficie, str):
        m = re.search(r"\d+", superficie.replace(".", ""))
        mq = int(m.group()) if m else None
    prezzo = pesca(item, "priceValue", "price", "prezzo")
    if isinstance(prezzo, dict):
        prezzo = prezzo.get("value")
    ascensore = pesca(item, "elevator", "ascensore", "hasElevator")
    return {
        "id": str(pesca(item, "id", "propertyId", "listingId") or ""),
        "url": pesca(item, "url", "directLink", "link"),
        "prezzo": prezzo if isinstance(prezzo, int) else None,
        "mq": mq,
        "zona": pesca(item, "microzone", "macrozone", "zona"),
        "indirizzo": pesca(item, "address", "indirizzo"),
        "ascensore": ascensore,
        "bagni": pesca(item, "bathrooms", "bagni"),
        "piano": pesca(item, "floor", "piano"),
        "descrizione": pesca(item, "description", "descrizione"),
        "lat": pesca(item, "latitude", "lat"),
        "lon": pesca(item, "longitude", "lng", "lon"),
    }


def copertura(righe: list, etichetta: str) -> None:
    n = len(righe)
    print(f"\n### {etichetta} — {n} listing")
    if not n:
        return
    for c in CAMPI:
        pieni = sum(1 for r in righe if r.get(c) not in (None, "", []))
        print(f"  {c:12} {pieni:3}/{n}  ({pieni / n * 100:.0f}%)")
    asc = [r.get("ascensore") for r in righe]
    print(f"  → ascensore True: {sum(1 for a in asc if a is True)} · False: {sum(1 for a in asc if a is False)} · assente: {sum(1 for a in asc if a is None)}")


def main() -> int:
    prod_raw, nuovo_raw = carica(PROD), carica(NUOVO)
    if not prod_raw or not nuovo_raw:
        print("Confronto impossibile: manca uno dei due dataset", file=sys.stderr)
        return 1

    prod = [norm_prod(i) for i in prod_raw if isinstance(i, dict)]
    nuovo = [norm_nuovo(i) for i in nuovo_raw if isinstance(i, dict)]

    print("# Confronto actor Apify —", "produzione (azzouzana) vs memo23")
    copertura(prod, "azzouzana (in produzione)")
    copertura(nuovo, "memo23 (candidato)")

    idp = {re.sub(r"\D", "", r["id"] or "") for r in prod}
    idn = {re.sub(r"\D", "", r["id"] or "") for r in nuovo}
    idp.discard(""); idn.discard("")
    print(f"\n### Sovrapposizione\n  solo azzouzana: {len(idp - idn)} · in entrambi: {len(idp & idn)} · solo memo23: {len(idn - idp)}")

    print("\n### Chiavi del payload memo23 (primo item)")
    if nuovo_raw:
        print("  " + ", ".join(sorted(nuovo_raw[0].keys())[:40]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
