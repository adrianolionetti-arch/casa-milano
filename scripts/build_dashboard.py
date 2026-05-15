#!/usr/bin/env python3
"""Genera index.html dalla DB annunci_visti.json.

Filtri (TUTTI obbligatori — niente eccezioni):
- punteggio numerico ≥ 6
- data_vista negli ultimi 30 giorni
- URL match esatto: https://www.immobiliare.it/annunci/<digits>[/]
- note NON inizia con SCARTATO o ESCLUSO

Uso:
    python3 scripts/build_dashboard.py            # scrive index.html
    python3 scripts/build_dashboard.py --dry-run  # stampa solo il count senza scrivere
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "annunci_visti.json"
OUT_PATH = Path(__file__).resolve().parent.parent / "index.html"

URL_REGEX = re.compile(r"^https://www\.immobiliare\.it/annunci/\d+/?$")
DAYS_WINDOW = 30
MIN_SCORE = 6.0


def parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def stars(p: float) -> str:
    full = int(round(p))
    return "★" * full + "☆" * (10 - full)


def fmt_eur(v) -> str:
    if not v:
        return "—"
    return "€" + format(int(v), ",d").replace(",", ".")


def card(a: dict) -> str:
    pts = a.get("punteggio") or 0
    foto = a.get("foto_url") or ""
    img_html = (
        f'<img src="{foto}" loading="lazy" style="width:100%;max-width:100%;border-radius:6px;'
        f'margin-bottom:10px;object-fit:cover;max-height:280px">'
        if foto and foto.startswith("http")
        else ""
    )
    notif_html = (
        '<span style="background:#3b82f6;color:#fff;padding:2px 8px;border-radius:4px;'
        'font-size:11px;margin-left:8px">📩 NOTIFICATO</span>'
        if a.get("notificato")
        else ""
    )
    mq_part = f"{a.get('mq')}mq" if a.get("mq") else "—"
    return (
        '<div style="border:1px solid #3b82f6;background:#eff6ff;border-radius:8px;padding:16px;'
        'margin-bottom:12px">'
        f"{img_html}"
        '<div style="display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:6px">'
        f'<strong>{stars(pts)} {pts}/10</strong>{notif_html}</div>'
        '<div style="font-size:14px;color:#1e293b;margin-bottom:4px"><strong>'
        f'{a.get("titolo", "(senza titolo)") or ""}</strong></div>'
        '<div style="font-size:13px;color:#475569;margin-bottom:4px">💰 '
        f'{fmt_eur(a.get("prezzo"))} · {mq_part} · {a.get("zona") or "—"} · {a.get("data_vista") or ""}'
        f' · Piano {a.get("piano") or "—"}</div>'
        '<div style="font-size:12px;color:#64748b;margin-bottom:8px">'
        f'{a.get("agenzia") or ""}</div>'
        f'<a href="{a.get("url") or ""}" style="font-size:12px;color:#3b82f6;text-decoration:none" '
        'target="_blank">Vedi annuncio →</a></div>'
    )


def build(dry_run: bool = False) -> int:
    with open(DB_PATH) as f:
        db = json.load(f)
    ann = db.get("annunci", [])

    today = date.today()
    cutoff = today - timedelta(days=DAYS_WINDOW)

    dash = []
    for a in ann:
        note = (a.get("note") or "")
        if note.startswith(("SCARTATO", "ESCLUSO")):
            continue
        pts = a.get("punteggio")
        if pts is None or pts < MIN_SCORE:
            continue
        dv = parse_date(a.get("data_vista"))
        if not dv or dv < cutoff:
            continue
        if not URL_REGEX.match(a.get("url") or ""):
            continue
        dash.append(a)

    dash.sort(key=lambda a: (-(a.get("punteggio") or 0), a.get("data_vista", "")))

    total_30d = sum(1 for a in ann if parse_date(a.get("data_vista") or "") and parse_date(a["data_vista"]) >= cutoff)
    nuovi_oggi = sum(1 for a in dash if a.get("data_vista") == today.strftime("%Y-%m-%d"))
    score_max = max((a.get("punteggio") or 0) for a in dash) if dash else 0
    today_str = today.strftime("%d/%m/%Y")

    cards = "\n".join(card(a) for a in dash)
    empty = (
        '<div class="empty">Nessun annuncio attivo. La prossima sessione Apify popolerà la lista.</div>'
    )
    content = cards if dash else empty

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Casa Milano — Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f1f5f9; color: #1e293b; }}
    .header {{ background: linear-gradient(135deg,#1e293b,#334155); color: #fff; padding: 24px 20px; }}
    .header h1 {{ font-size: 22px; margin-bottom: 4px; }}
    .header p {{ font-size: 13px; color: #94a3b8; }}
    .stats {{ display: flex; gap: 12px; padding: 16px 20px; flex-wrap: wrap; max-width:800px; margin:0 auto; }}
    .stat {{ background: #fff; border-radius: 8px; padding: 12px 18px; flex: 1; min-width: 100px; box-shadow: 0 1px 3px rgba(0,0,0,.07); }}
    .stat-val {{ font-size: 28px; font-weight: 700; color: #1e293b; }}
    .stat-lbl {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
    .main {{ padding: 0 20px 40px; max-width: 800px; margin: 0 auto; }}
    .section-title {{ font-size: 13px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: .5px; margin: 20px 0 10px; }}
    .empty {{ background:#fff; padding:24px; border-radius:8px; text-align:center; color:#64748b; }}
    @media(max-width:600px) {{ .stats {{ gap: 8px; }} .stat-val {{ font-size: 22px; }} }}
  </style>
</head>
<body>
  <div class="header">
    <h1>🏠 Casa Milano — Dashboard</h1>
    <p>Aggiornato: {today_str} · Ultimi 30 giorni · Solo annunci attivi su Immobiliare.it</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="stat-val">{len(dash)}</div><div class="stat-lbl">In dashboard</div></div>
    <div class="stat"><div class="stat-val">{total_30d}</div><div class="stat-lbl">Processati (30gg)</div></div>
    <div class="stat"><div class="stat-val">{nuovi_oggi}</div><div class="stat-lbl">Nuovi oggi</div></div>
    <div class="stat"><div class="stat-val">{score_max}</div><div class="stat-lbl">Score max</div></div>
  </div>
  <div class="main">
    <div class="section-title">Annunci attivi — score ≥ {MIN_SCORE}, ultimi {DAYS_WINDOW} giorni</div>
    {content}
  </div>
</body>
</html>"""

    if dry_run:
        print(f"DRY RUN: dashboard avrebbe {len(dash)} card")
        return 0

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"index.html scritto: {len(dash)} card, {len(html)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(build(dry_run="--dry-run" in sys.argv))
