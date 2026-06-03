#!/usr/bin/env python3
"""Pipeline deterministica giornaliera Casa Milano (sostituisce l'agente LLM).

Legge /tmp/apify_items.json (output di fetch_apify.py), applica filtri + scoring
secondo le regole in CLAUDE.md / criteri.md, aggiorna annunci_visti.json, scrive
il report del giorno e compone l'email digest.

Uso:
    APIFY env già consumate da fetch_apify.py
    GMAIL_* env → passate a send_email.py
    python3 scripts/process_session.py

Exit code:
    0 = successo (anche con 0 nuovi notificati)
    1 = errore di processamento
    2 = INFRA (input mancante / corrotto)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "annunci_visti.json"
APIFY_PATH = Path("/tmp/apify_items.json")
REPORT_DIR = ROOT / "report"
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://adrianolionetti-arch.github.io/casa-milano/")

# ===== Regole da criteri.md (hardcoded, deterministico) =====

ZONE_TIER = {
    # Top (+3)
    "pratocentenaro": 1, "prato centenaro": 1, "turro": 1, "precotto": 1, "gorla": 1,
    "crescenzago": 1, "niguarda": 1, "affori": 1, "maggiolina": 1,
    "nolo": 1, "nord loreto": 1,
    # Ottima (+2)
    "greco": 2, "segnano": 2, "bicocca": 2, "isola": 2, "loreto": 2,
    "cenisio": 2, "chinatown": 2, "procaccini": 2, "cimiano": 2, "casoretto": 2,
    "viale monza": 2, "viale padova": 2, "centrale": 2,
    "adriano": 2, "quartiere adriano": 2,
    # Buona (+1)
    "lambrate": 3, "udine": 3, "città studi": 3, "citta studi": 3, "bovisa": 3,
    "dergano": 3, "pasteur": 3, "bruzzano": 3, "zara": 3, "maciachini": 3,
    "porta garibaldi": 3, "buenos aires": 3, "navigli": 3, "porta romana": 3,
    "porta vittoria": 3, "prati": 3, "certosa": 3,
}

EXCLUDED_ZONES = {
    "quarto oggiaro", "lorenteggio", "corvetto",
    "gratosoglio", "stadera", "baggio",
}

BLACKLIST_KEYWORDS = [
    "venduto", "venduta", "vendute", "venduti",
    " sold ", "non più disponibile", "non piu disponibile",
    "non disponibile", "ritirato dalla vendita", "ritirata dalla vendita",
    "trattativa conclusa", "trattativa in corso",
    "compromesso firmato", "rogito firmato", "rogitato",
    "under offer", "in attesa di rogito", "preliminare firmato",
    "annuncio scaduto", "annuncio rimosso", "annuncio non più attivo",
    "this property is no longer available", "this listing has been removed",
]

MIN_MQ = 80
MAX_MQ = 120
MAX_PREZZO = 450_000
MIN_SCORE_NOTIFY = 6.0
ALERT_SCORE = 8.0
MAX_AGE_DAYS = 45


def parse_mq(surface_raw) -> int | None:
    """Estrae mq da stringhe tipo '98 m²'. ASCII-digit-only (isdigit() include ²)."""
    if surface_raw is None:
        return None
    digits = "".join(c for c in str(surface_raw) if c in "0123456789")
    return int(digits) if digits else None


def to_int(v) -> int | None:
    """Coerce a int. Apify a volte restituisce bagni/locali come string ('2', '2+', '3').
    Estrae il primo numero intero ASCII; ritorna None se non c'è."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    s = str(v)
    digits = "".join(c for c in s if c in "0123456789")
    return int(digits) if digits else None


def extract(item: dict) -> dict:
    """Mappa item Apify → schema agente (CLAUDE.md Step 3)."""
    props = (item.get("properties") or [{}])[0]
    loc = props.get("location") or {}
    photos = (props.get("multimedia") or {}).get("photos") or []
    floor = props.get("floor") or {}
    advertiser = item.get("advertiser") or {}
    agency = advertiser.get("agency") or {}
    return {
        "id": f"immobiliare-{item.get('id')}",
        "source": "immobiliare",
        "url": item.get("directLink"),
        "titolo": item.get("title") or "",
        "prezzo": to_int((item.get("price") or {}).get("value")),
        "mq": parse_mq(props.get("surface")),
        "locali": to_int(props.get("rooms")),
        "bagni": to_int(props.get("bathrooms")),
        "piano": floor.get("abbreviation"),
        "ascensore": bool(props.get("elevator")) if props.get("elevator") is not None else False,
        "zona": loc.get("microzone") or loc.get("macrozone"),
        "indirizzo": loc.get("address"),
        "descrizione": (props.get("description") or "")[:1000],
        "agenzia": agency.get("displayName"),
        "foto_url": (photos[0].get("urls", {}).get("large") if photos and photos[0] else None),
        "lat": loc.get("latitude"),
        "lon": loc.get("longitude"),
    }


def zone_tier(zona: str | None, indirizzo: str | None) -> int:
    """Restituisce 1/2/3/4 in base alla mappa criteri.md, default 4."""
    if zona:
        z = zona.lower()
        for key, tier in ZONE_TIER.items():
            if key in z:
                return tier
    if indirizzo:
        a = indirizzo.lower()
        for key, tier in ZONE_TIER.items():
            if key in a:
                return tier
    return 4


def is_in_excluded_zone(zona: str | None, indirizzo: str | None) -> str | None:
    """Se zona o indirizzo matcha lista esclusa, restituisce il nome zona; altrimenti None."""
    for z in (zona, indirizzo):
        if z:
            zl = z.lower()
            for ex in EXCLUDED_ZONES:
                if ex in zl:
                    return ex
    return None


def is_in_milano(loc_text: str | None) -> bool:
    """Heuristica: indirizzo o zona contiene 'milano' (o microzone milanese)."""
    if not loc_text:
        return True  # default open
    t = loc_text.lower()
    if "milano" in t:
        return True
    # Sesto San Giovanni accettato (esplicito in criteri.md)
    if "sesto" in t and "giovanni" in t:
        return True
    return True  # Apify restituisce solo Milano provincia → conservativo


def keyword_gate(L: dict) -> str | None:
    """REGOLA #0: blacklist keyword sul titolo + descrizione."""
    text = (L.get("titolo", "") + " " + L.get("descrizione", "")).lower()
    for kw in BLACKLIST_KEYWORDS:
        if kw in text:
            return kw.strip()
    return None


def agency_hq_match(L: dict) -> bool:
    """Cross-check: indirizzo immobile coincide con sede agenzia."""
    addr = (L.get("indirizzo") or "").lower()
    agency = (L.get("agenzia") or "").lower()
    if not addr or not agency:
        return False
    # Estrae "via X N" dall'indirizzo, controlla se appare nel nome agenzia
    m = re.search(r"(via|viale|piazza|corso)\s+([^,\d]{3,30})", addr)
    if not m:
        return False
    via_name = m.group(2).strip()
    if len(via_name) < 4:
        return False
    return via_name in agency


def freshness_age_days(descrizione: str) -> int | None:
    """Cerca data 'pubblicato il GG/MM/AAAA' in descrizione; restituisce età in giorni o None."""
    if not descrizione:
        return None
    pat = re.compile(
        r"(?:pubblicat[oa]\s+il|inserit[oa]\s+il|data\s+annuncio)[\s:]*(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})",
        re.IGNORECASE,
    )
    m = pat.search(descrizione)
    if not m:
        return None
    try:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        pub = date(y, mo, d)
        return (date.today() - pub).days
    except (ValueError, OverflowError):
        return None


def apply_filters(L: dict, db_ids: set[str]) -> tuple[str, str | None]:
    """Restituisce (status, reason). Status ∈ {OK, DUPLICATE, INVALID, SCARTATO_*, ESCLUSO}."""
    if L["id"] in db_ids:
        return ("DUPLICATE", None)
    if not L.get("url") or not L.get("prezzo") or not L.get("mq"):
        return ("INVALID", "campi mancanti")
    # REGOLA #0
    kw = keyword_gate(L)
    if kw:
        return ("SCARTATO_KEYWORD", f"keyword '{kw}'")
    if agency_hq_match(L):
        return ("SCARTATO_SEDE", "indirizzo == sede agenzia")
    age = freshness_age_days(L.get("descrizione") or "")
    if age is not None and age > MAX_AGE_DAYS:
        return ("SCARTATO_FRESHNESS", f"pubblicato {age}gg fa")
    # Esclusioni assolute
    if not L.get("ascensore"):
        return ("ESCLUSO", "no ascensore")
    piano = L.get("piano")
    desc_lower = (L.get("descrizione") or "").lower()
    if piano in ("T", "R", "S") and "giardino privato" not in desc_lower:
        return ("ESCLUSO", f"piano {piano} senza giardino")
    if "asta" in (L.get("titolo") or "").lower() or "asta giudiziaria" in desc_lower:
        return ("ESCLUSO", "asta")
    if L["mq"] < MIN_MQ or L["mq"] > MAX_MQ:
        return ("ESCLUSO", f"mq={L['mq']} fuori [{MIN_MQ},{MAX_MQ}]")
    if L["prezzo"] > MAX_PREZZO:
        return ("ESCLUSO", f"prezzo={L['prezzo']} > {MAX_PREZZO}")
    ex_zone = is_in_excluded_zone(L.get("zona"), L.get("indirizzo"))
    if ex_zone:
        return ("ESCLUSO", f"zona esclusa {ex_zone}")
    return ("OK", None)


def score(L: dict) -> float:
    """Calcola punteggio 0-10 da criteri.md."""
    s = 0.0
    p = L["prezzo"]
    if p <= 310_000:
        s += 3
    elif p <= 380_000:
        s += 1.5
    else:
        s += 1  # <=450k (già filtrato sopra)

    tier = zone_tier(L.get("zona"), L.get("indirizzo"))
    s += {1: 3, 2: 2, 3: 1, 4: 0.5}[tier]

    if L.get("mq") and L["mq"] >= 90:
        s += 1

    desc = (L.get("descrizione") or "").lower()
    if any(k in desc for k in ("balcone", "terrazzo", "terrazza")):
        s += 0.5
    if L.get("bagni") and L["bagni"] >= 2:
        s += 0.5
    piano_str = str(L.get("piano") or "")
    if piano_str.isdigit() and int(piano_str) >= 3:
        s += 0.5
    if any(k in desc for k in ("box auto", "posto auto", "garage")):
        s += 0.5
    if "classe energetica a" in desc or "classe energetica b" in desc:
        s += 0.5

    return round(s, 1)


def fmt_eur(v) -> str:
    if v is None:
        return "—"
    return "€" + format(int(v), ",d").replace(",", ".")


def render_card_html(a: dict) -> str:
    img = f'<img src="{a["foto_url"]}" style="width:100%;max-width:500px;border-radius:6px;margin-bottom:12px">' if a.get("foto_url") else ""
    return f"""<div style="margin:20px 0;padding:16px;border:1px solid #eee;border-radius:8px;">
  {img}
  <h3>⭐ {a['punteggio']}/10 — {a['titolo']}</h3>
  <p><strong>💰 {fmt_eur(a['prezzo'])}</strong> · {a['mq']}mq · {a.get('zona') or '—'} · piano {a.get('piano') or '—'}</p>
  <p>{a.get('agenzia') or ''}</p>
  <a href="{a['url']}" style="background:#0071e3;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none">Vedi annuncio →</a>
</div>"""


def header_button() -> str:
    return f"""<div style="text-align:center;margin:0 0 24px 0;">
  <a href="{DASHBOARD_URL}" style="display:inline-block;background:#0071e3;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:600;box-shadow:0 2px 6px rgba(0,113,227,0.25);">📊 Apri la dashboard →</a>
</div>"""


def compose_email(notified: list, stats: dict, today_str: str) -> tuple[str, str]:
    n = len(notified)
    has_alert = any(a["punteggio"] >= ALERT_SCORE for a in notified)

    if n == 0:
        subject = f"🏠 Sessione completata — nessuna novità oggi"
        body = (
            header_button()
            + f"<h2>🏠 Casa Milano — sessione del {today_str}</h2>"
            + "<p>Nessun annuncio nuovo con score ≥ 6 oggi.</p>"
            + "<ul>"
            + f"<li>Apify: {stats['n_items']} listing recuperati</li>"
            + f"<li>Duplicati riconosciuti: {stats['n_duplicate']}</li>"
            + f"<li>Scartati REGOLA #0: {stats['n_scartati']}</li>"
            + f"<li>Esclusi per criteri: {stats['n_esclusi']}</li>"
            + f"<li>Sotto soglia (score < 6): {stats['n_sotto_soglia']}</li>"
            + "</ul>"
        )
    elif has_alert:
        top = max(notified, key=lambda a: a["punteggio"])
        subject = f"🏠 [ALERT] {top.get('zona') or 'Milano'} — {fmt_eur(top['prezzo'])} — {top['mq']}mq"
        body = (
            header_button()
            + f"<h2>🏠 ALERT — {n} nuovi annunci, top score {top['punteggio']}/10</h2>"
            + "\n".join(render_card_html(a) for a in sorted(notified, key=lambda x: -x["punteggio"]))
        )
    else:
        subject = f"🏠 [DIGEST] Ricerca casa Milano — {today_str} — {n} {'annuncio' if n == 1 else 'annunci'} nuov{'o' if n == 1 else 'i'}"
        body = (
            header_button()
            + f"<h2>🏠 DIGEST — {n} {'annuncio' if n == 1 else 'annunci'} con score ≥ 6</h2>"
            + "\n".join(render_card_html(a) for a in sorted(notified, key=lambda x: -x["punteggio"]))
        )
    return subject, body


def write_report(stats: dict, today_str: str) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"{today_str}.md"
    lines = [
        f"# Sessione {today_str}",
        "",
        "## Riepilogo",
        "",
        "| Stato | Conteggio |",
        "|---|---|",
        f"| Listing Apify recuperati | {stats['n_items']} |",
        f"| Duplicati | {stats['n_duplicate']} |",
        f"| Non validi | {stats['n_invalid']} |",
        f"| Scartati REGOLA #0 | {stats['n_scartati']} |",
        f"| Esclusi per criteri | {stats['n_esclusi']} |",
        f"| Sotto soglia (score < 6) | {stats['n_sotto_soglia']} |",
        f"| **Notificati (score ≥ 6)** | **{stats['n_notified']}** |",
        "",
    ]
    if stats["notified_list"]:
        lines.append("## Notificati")
        lines.append("")
        lines.append("| Score | Prezzo | mq | Zona | Titolo |")
        lines.append("|---|---|---|---|---|")
        for a in sorted(stats["notified_list"], key=lambda x: -x["punteggio"]):
            lines.append(f"| {a['punteggio']} | {fmt_eur(a['prezzo'])} | {a.get('mq') or '—'} | {a.get('zona') or '—'} | {a.get('titolo','')[:60]} |")
        lines.append("")
    if stats["esclusi_list"]:
        lines.append(f"## Esclusi criteri ({len(stats['esclusi_list'])})")
        lines.append("")
        for a in stats["esclusi_list"][:30]:
            lines.append(f"- `{a['id']}` — {a.get('titolo','')[:60]} — {a.get('note','')}")
        if len(stats["esclusi_list"]) > 30:
            lines.append(f"- ... + altri {len(stats['esclusi_list']) - 30}")
        lines.append("")
    if stats["scartati_list"]:
        lines.append(f"## Scartati REGOLA #0 ({len(stats['scartati_list'])})")
        lines.append("")
        for a in stats["scartati_list"]:
            lines.append(f"- `{a['id']}` — {a.get('note','')}")
        lines.append("")
    if stats["email_message_id"]:
        lines.append(f"## Email")
        lines.append(f"- messageId: `{stats['email_message_id']}`")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report scritto: {path}")


def send_email(subject: str, body_html: str) -> str | None:
    """Chiama send_email.py e restituisce il messageId o None su failure."""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(body_html)
        body_path = f.name
    try:
        result = subprocess.run(
            ["python3", str(ROOT / "scripts/send_email.py"), subject, body_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            mid = result.stdout.strip()
            print(f"Email OK: {mid}")
            return mid
        print(f"Email FAIL ({result.returncode}): {result.stderr[:500]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Email FAIL exception: {e}", file=sys.stderr)
        return None


def main() -> int:
    if not APIFY_PATH.exists():
        print(f"INFRA: {APIFY_PATH} not found", file=sys.stderr)
        return 2

    with open(APIFY_PATH) as f:
        items = json.load(f)
    if not isinstance(items, list):
        print(f"INFRA: {APIFY_PATH} not a list", file=sys.stderr)
        return 2

    with open(DB_PATH) as f:
        db = json.load(f)
    db_ids = {a.get("id") for a in db.get("annunci", []) if a.get("id")}

    today = date.today()
    today_str = today.isoformat()

    new_entries: list[dict] = []
    notified: list[dict] = []
    esclusi_list: list[dict] = []
    scartati_list: list[dict] = []
    n_duplicate = n_invalid = n_sotto_soglia = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            L = extract(item)
        except Exception as e:
            print(f"WARN: extract failed item id={item.get('id')}: {e}", file=sys.stderr)
            continue

        status, reason = apply_filters(L, db_ids)

        if status == "DUPLICATE":
            n_duplicate += 1
            continue
        if status == "INVALID":
            n_invalid += 1
            continue

        if status.startswith("SCARTATO"):
            note = f"SCARTATO {status[9:].replace('_', ' ').lower()} — {reason}"
            entry = {**L, "punteggio": None, "data_vista": today_str, "notificato": True, "note": note}
            new_entries.append(entry)
            scartati_list.append(entry)
            continue

        if status == "ESCLUSO":
            entry = {**L, "punteggio": 0, "data_vista": today_str, "notificato": True, "note": f"ESCLUSO — {reason}"}
            new_entries.append(entry)
            esclusi_list.append(entry)
            continue

        # OK → scoring
        s = score(L)
        if s < MIN_SCORE_NOTIFY:
            entry = {**L, "punteggio": s, "data_vista": today_str, "notificato": False, "note": f"Score {s} — sotto soglia {MIN_SCORE_NOTIFY}"}
            new_entries.append(entry)
            n_sotto_soglia += 1
            continue

        entry = {**L, "punteggio": s, "data_vista": today_str, "notificato": True, "note": ""}
        new_entries.append(entry)
        notified.append(entry)

    stats = {
        "n_items": len(items),
        "n_duplicate": n_duplicate,
        "n_invalid": n_invalid,
        "n_scartati": len(scartati_list),
        "n_esclusi": len(esclusi_list),
        "n_sotto_soglia": n_sotto_soglia,
        "n_notified": len(notified),
        "notified_list": notified,
        "esclusi_list": esclusi_list,
        "scartati_list": scartati_list,
        "email_message_id": None,
    }

    # Update DB
    db["annunci"].extend(new_entries)
    db.setdefault("meta", {})
    db["meta"]["ultimo_aggiornamento"] = today_str
    db["meta"]["ultima_sessione"] = datetime.now().isoformat()
    db["meta"]["totale_annunci"] = len(db["annunci"])
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"DB aggiornato: +{len(new_entries)} entry, totale {len(db['annunci'])}")

    # Email
    subject, body = compose_email(notified, stats, today_str)
    mid = send_email(subject, body)
    if mid is None:
        # Retry una volta (CLAUDE.md Step 7)
        print("Retry email...", file=sys.stderr)
        mid = send_email(subject, body)
    stats["email_message_id"] = mid

    # Report
    write_report(stats, today_str)

    print(f"Sessione completata: {stats['n_notified']} notificati, {stats['n_esclusi']} esclusi, {stats['n_scartati']} scartati")
    return 0


if __name__ == "__main__":
    sys.exit(main())
