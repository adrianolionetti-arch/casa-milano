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

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "annunci_visti.json"
PREFERITI_PATH = ROOT / "preferiti.json"
OUT_PATH = ROOT / "index.html"

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


def card(a: dict, *, is_preferito: bool = False, in_preferiti_set: set | None = None) -> str:
    """Render una card stilizzata. is_preferito=True usa bordo rosa + cuore pieno.
    in_preferiti_set: se passato, marca le card normali che sono anche tra i preferiti."""
    pts = a.get("punteggio")
    foto = a.get("foto_url") or ""
    url = a.get("url") or ""

    # Photo
    img_html = (
        f'<img src="{foto}" loading="lazy" class="card-photo" alt="{a.get("titolo","")}">'
        if foto and foto.startswith("http")
        else '<div class="card-photo-placeholder">🏠</div>'
    )

    # Heart button — toggle localStorage. data-id richiesto dal JS.
    listing_id = a.get("id") or ""
    if is_preferito:
        # Card già nella sezione preferiti persistenti (preferiti.json gestiti da Claude)
        heart_html = '<div class="heart-badge filled" title="Preferito persistente">❤️</div>'
    else:
        heart_html = (
            f'<button class="heart-btn" data-id="{listing_id}" '
            'onclick="toggleFav(this)" title="Aggiungi/rimuovi dai preferiti">🤍</button>'
        )

    # Score badge
    score_html = (
        f'<div class="score-badge">⭐ {pts}/10</div>'
        if pts is not None and pts > 0
        else '<div class="score-badge manual">❤️ Preferito</div>' if is_preferito else ""
    )

    # Notified badge
    notif_html = (
        '<div class="notif-badge">📩 Notificato</div>'
        if a.get("notificato") and not is_preferito
        else ""
    )

    # Price (big)
    price_html = (
        f'<div class="price">{fmt_eur(a.get("prezzo"))}</div>'
        if a.get("prezzo")
        else '<div class="price">—</div>'
    )

    # Title
    title = a.get("titolo", "(senza titolo)") or ""

    # Details row (icons)
    parts = []
    if a.get("mq"): parts.append(f'📏 {a["mq"]}mq')
    if a.get("locali"): parts.append(f'🚪 {a["locali"]} locali')
    if a.get("bagni"): parts.append(f'🛁 {a["bagni"]} bagni')
    if a.get("piano"): parts.append(f'🏢 piano {a["piano"]}')
    details = '  ·  '.join(parts)

    # Zone + date
    zone = a.get("zona") or "—"
    dv = a.get("data_vista") or a.get("data_aggiunto") or ""
    location_html = f'<div class="location">📍 <strong>{zone}</strong>  ·  📅 {dv}</div>'

    # Agency
    agency = a.get("agenzia") or ""
    agency_html = f'<div class="agency">🏪 {agency}</div>' if agency else ""

    # Note personali (preferiti only)
    note_pers = a.get("note_personali") or ""
    note_html = (
        f'<div class="note-pers">📝 {note_pers}</div>'
        if note_pers
        else ""
    )

    card_class = "card-fav" if is_preferito else "card"
    return f"""<div class="{card_class}">
  {img_html}
  <div class="card-top">
    {price_html}
    <div class="badges">
      {score_html}{notif_html}
    </div>
    {heart_html}
  </div>
  <div class="title">{title}</div>
  {location_html}
  <div class="details">{details}</div>
  {agency_html}
  {note_html}
  <a class="cta" href="{url}" target="_blank">Vedi su Immobiliare.it →</a>
</div>"""


def build(dry_run: bool = False) -> int:
    with open(DB_PATH) as f:
        db = json.load(f)
    ann = db.get("annunci", [])

    # Preferiti (file separato, opzionale)
    preferiti = []
    if PREFERITI_PATH.exists():
        with open(PREFERITI_PATH) as f:
            preferiti = json.load(f).get("annunci", [])
    preferiti_ids = {p.get("id") for p in preferiti if p.get("id")}

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

    # Preferiti section (ordina per data_aggiunto desc)
    preferiti_sorted = sorted(preferiti, key=lambda a: a.get("data_aggiunto", ""), reverse=True)
    preferiti_cards = "\n".join(card(a, is_preferito=True) for a in preferiti_sorted)
    preferiti_section = ""
    if preferiti_sorted:
        preferiti_section = (
            f'<div class="section-title" style="color:#ec4899">❤️ Preferiti — {len(preferiti_sorted)} salvati</div>\n'
            f'{preferiti_cards}'
        )

    cards = "\n".join(card(a, in_preferiti_set=preferiti_ids) for a in dash)
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
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #0f172a; line-height: 1.5; }}

    .header {{ background: linear-gradient(135deg,#1e293b,#475569); color: #fff; padding: 28px 20px; }}
    .header h1 {{ font-size: 24px; margin-bottom: 6px; font-weight: 700; }}
    .header p {{ font-size: 13px; color: #cbd5e1; }}

    .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; padding: 16px 20px 8px; max-width: 900px; margin: 0 auto; }}
    .stat {{ background: #fff; border-radius: 10px; padding: 14px 12px; box-shadow: 0 1px 3px rgba(15,23,42,.08); text-align: center; }}
    .stat-val {{ font-size: 26px; font-weight: 700; color: #0f172a; line-height: 1; }}
    .stat-lbl {{ font-size: 11px; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: .3px; }}

    .toolbar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 20px; max-width: 900px; margin: 0 auto; flex-wrap: wrap; }}
    .toggle {{ display: inline-flex; align-items: center; gap: 8px; font-size: 14px; color: #334155; cursor: pointer; user-select: none; }}
    .toggle input {{ width: 18px; height: 18px; cursor: pointer; accent-color: #ec4899; }}
    .clear-btn {{ background: #fff; border: 1px solid #fbcfe8; color: #be185d; padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; transition: background .15s; }}
    .clear-btn:hover {{ background: #fdf2f8; }}

    .main {{ padding: 0 20px 40px; max-width: 900px; margin: 0 auto; }}
    .section-title {{ font-size: 12px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: .8px; margin: 24px 0 12px; }}
    .empty {{ background:#fff; padding: 32px 24px; border-radius: 10px; text-align: center; color: #64748b; }}

    /* CARD */
    .card, .card-fav {{ background:#fff; border-radius: 12px; padding: 0; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(15,23,42,.07); overflow: hidden; transition: box-shadow .2s; }}
    .card:hover, .card-fav:hover {{ box-shadow: 0 4px 12px rgba(15,23,42,.12); }}
    .card-fav {{ border: 2px solid #ec4899; background: linear-gradient(180deg,#fdf2f8 0%,#fff 60px); }}

    .card-photo {{ width: 100%; height: 220px; object-fit: cover; display: block; }}
    .card-photo-placeholder {{ width: 100%; height: 160px; display: flex; align-items: center; justify-content: center; background: #f1f5f9; font-size: 56px; }}

    .card-top {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 16px 18px 8px; flex-wrap: wrap; }}
    .price {{ font-size: 28px; font-weight: 800; color: #0f172a; line-height: 1; flex-shrink: 0; }}
    .badges {{ display: flex; flex-direction: column; gap: 4px; align-items: flex-end; flex: 1; }}

    .score-badge {{ background: #1e40af; color:#fff; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .score-badge.manual {{ background: #ec4899; }}
    .notif-badge {{ background: #16a34a; color:#fff; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; white-space: nowrap; }}

    .heart-btn, .heart-badge {{ background: none; border: none; font-size: 26px; cursor: pointer; padding: 4px; border-radius: 50%; transition: transform .15s; line-height: 1; }}
    .heart-btn:hover {{ transform: scale(1.2); background: #fce7f3; }}
    .heart-btn.filled {{ transform: scale(1.1); }}
    .heart-badge.filled {{ cursor: default; }}

    .title {{ padding: 0 18px; font-size: 15px; font-weight: 600; color: #1e293b; margin-bottom: 8px; line-height: 1.35; }}
    .location {{ padding: 0 18px 6px; font-size: 13px; color: #475569; }}
    .location strong {{ color: #1e293b; }}
    .details {{ padding: 0 18px 10px; font-size: 13px; color: #475569; }}
    .agency {{ padding: 0 18px 10px; font-size: 12px; color: #64748b; }}
    .note-pers {{ padding: 8px 18px; font-size: 13px; color: #831843; background: #fdf2f8; border-top: 1px solid #fbcfe8; font-style: italic; }}

    .cta {{ display: block; margin: 12px 18px 18px; padding: 10px 16px; background: #0071e3; color:#fff; border-radius: 8px; text-decoration: none; text-align: center; font-size: 14px; font-weight: 600; transition: background .15s; }}
    .cta:hover {{ background: #005bb5; }}
    .card-fav .cta {{ background: #ec4899; }}
    .card-fav .cta:hover {{ background: #be185d; }}

    .toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: #1e293b; color:#fff; padding: 14px 20px; border-radius: 10px; box-shadow: 0 4px 16px rgba(15,23,42,.25); font-size: 14px; max-width: 90vw; z-index: 1000; display:none; }}
    .toast.show {{ display: block; animation: slideUp .3s ease-out; }}
    @keyframes slideUp {{ from {{ transform: translate(-50%, 20px); opacity: 0; }} to {{ transform: translate(-50%, 0); opacity: 1; }} }}

    @media(max-width:600px) {{
      .stats {{ grid-template-columns: repeat(2, 1fr); }}
      .price {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>🏠 Casa Milano — Dashboard</h1>
    <p>Aggiornato: {today_str} · Annunci attivi su Immobiliare.it · score ≥ {MIN_SCORE} · ultimi {DAYS_WINDOW} giorni</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="stat-val">{len(dash)}</div><div class="stat-lbl">In dashboard</div></div>
    <div class="stat"><div class="stat-val">{len(preferiti_sorted)}</div><div class="stat-lbl">❤️ Preferiti</div></div>
    <div class="stat"><div class="stat-val">{total_30d}</div><div class="stat-lbl">Processati 30gg</div></div>
    <div class="stat"><div class="stat-val">{nuovi_oggi}</div><div class="stat-lbl">Nuovi oggi</div></div>
    <div class="stat"><div class="stat-val">{score_max}</div><div class="stat-lbl">Score max</div></div>
  </div>
  <div class="toolbar">
    <label class="toggle">
      <input type="checkbox" id="filter-fav" onchange="applyFilter()">
      <span>Mostra solo ❤️ preferiti (<span id="fav-count">0</span>)</span>
    </label>
    <button class="clear-btn" onclick="clearFavs()" id="clear-btn" style="display:none">Svuota preferiti</button>
  </div>
  <div class="main">
    {preferiti_section}
    <div class="section-title">Annunci attivi</div>
    {content}
  </div>

  <div id="toast" class="toast"></div>

  <script>
  const FAVS_KEY = 'casa-milano-favs';

  function getFavs() {{
    try {{ return JSON.parse(localStorage.getItem(FAVS_KEY) || '[]'); }}
    catch(e) {{ return []; }}
  }}
  function saveFavs(arr) {{
    localStorage.setItem(FAVS_KEY, JSON.stringify(arr));
    updateFavCount();
  }}
  function updateFavCount() {{
    const n = getFavs().length;
    document.getElementById('fav-count').textContent = n;
    document.getElementById('clear-btn').style.display = n > 0 ? '' : 'none';
  }}
  function toggleFav(btn) {{
    const id = btn.dataset.id;
    if (!id) return;
    let favs = getFavs();
    const idx = favs.indexOf(id);
    if (idx === -1) {{
      favs.push(id);
      btn.textContent = '❤️';
      btn.classList.add('filled');
      showToast('❤️ Aggiunto ai preferiti');
    }} else {{
      favs.splice(idx, 1);
      btn.textContent = '🤍';
      btn.classList.remove('filled');
      showToast('Rimosso dai preferiti');
    }}
    saveFavs(favs);
    applyFilter();
  }}
  function applyFilter() {{
    const onlyFav = document.getElementById('filter-fav').checked;
    const favs = getFavs();
    document.querySelectorAll('.card, .card-fav').forEach(c => {{
      const btn = c.querySelector('.heart-btn');
      const isFav = btn && favs.includes(btn.dataset.id);
      const isPersistFav = c.classList.contains('card-fav');
      c.style.display = (!onlyFav || isFav || isPersistFav) ? '' : 'none';
    }});
  }}
  function clearFavs() {{
    if (!confirm('Sicuro di voler svuotare i preferiti (solo questo browser)?')) return;
    saveFavs([]);
    document.querySelectorAll('.heart-btn.filled').forEach(b => {{
      b.textContent = '🤍';
      b.classList.remove('filled');
    }});
    applyFilter();
    showToast('Preferiti svuotati');
  }}
  function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2500);
  }}

  // Init: marca i preferiti già salvati al load
  document.addEventListener('DOMContentLoaded', () => {{
    const favs = getFavs();
    document.querySelectorAll('.heart-btn').forEach(btn => {{
      if (favs.includes(btn.dataset.id)) {{
        btn.textContent = '❤️';
        btn.classList.add('filled');
      }}
    }});
    updateFavCount();
  }});
  </script>
</body>
</html>"""

    if dry_run:
        print(f"DRY RUN: dashboard avrebbe {len(dash)} card + {len(preferiti_sorted)} preferiti")
        return 0

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"index.html scritto: {len(dash)} card + {len(preferiti_sorted)} preferiti, {len(html)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(build(dry_run="--dry-run" in sys.argv))
