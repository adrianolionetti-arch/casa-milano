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
import html as html_lib
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "annunci_visti.json"
PREFERITI_PATH = ROOT / "preferiti.json"
OUT_PATH = ROOT / "index.html"

GITHUB_REPO = "adrianolionetti-arch/casa-milano"

URL_REGEX = re.compile(r"^https://www\.immobiliare\.it/annunci/\d+/?$")
DAYS_WINDOW = 30
MIN_SCORE = 6.0

CHATBOT_MODEL = "claude-haiku-4-5"
CHATBOT_SYSTEM_PROMPT = """Sei "Casa Milano Assistant", un assistente che aiuta Adriano Lionetti e Alessia Curtopelle a esplorare la dashboard di annunci immobiliari a Milano.

Hai accesso al dataset completo degli annunci attualmente in dashboard (vedi "DATI ANNUNCI" più sotto). Gli annunci sono già pre-filtrati: score ≥ 6, ultimi 30 giorni, su Immobiliare.it.

Criteri dell'utente (per contesto):
- Budget: max €450k, ideale €230-310k
- 80-120mq, almeno 2 camere, ascensore obbligatorio
- No piano terra/seminterrato (salvo giardino), no aste
- Zone escluse: Quarto Oggiaro, Lorenteggio, Corvetto, Gratosoglio, Stadera, Baggio
- Zone top: Pratocentenaro, Turro, Precotto, Gorla, Niguarda, NoLo
- Zone ottime: Bicocca, Isola, Loreto, Cenisio, Procaccini, Adriano

Come rispondere:
1. Sempre in italiano, concise (max 3-4 frasi nel campo "message")
2. Usa SEMPRE il formato JSON strutturato: { "message": "...", "filter_ids": [...] }
3. Se l'utente chiede di filtrare/mostrare/vedere annunci specifici → popola "filter_ids" con gli ID degli annunci pertinenti (ordinati per rilevanza)
4. Se l'utente chiede info generali/statistiche/calcoli → "filter_ids": [] (vuoto = mostra tutti)
5. Quando filtri, sii inclusivo ma rigoroso: meglio 5 risultati buoni che 20 mediocri
6. Cita prezzo+mq+zona quando consigli annunci specifici nel campo "message"
7. Mai inventare dati. Se un campo manca nel dataset, dillo.

Esempi:
- "mostrami solo NoLo sotto 380k" → filter_ids con tutti gli annunci NoLo con prezzo < 380000
- "qual è il rapporto qualità/prezzo migliore?" → message con analisi, filter_ids con top 3-5
- "quanti hanno 2 bagni?" → message con il numero, filter_ids vuoto (a meno che l'utente chieda di mostrarli)
- "ce ne sono con terrazzo?" → cerca "terrazzo"/"terrazza" nelle descrizioni, filter_ids con quelli che matchano

Schema dataset (un oggetto per annuncio):
- id (string), titolo, prezzo (int EUR), mq (int), locali, bagni, piano, zona, indirizzo, agenzia, punteggio (float 0-10), url, ascensore (bool), descrizione (estratto max 400 char)
"""

CHATBOT_TEMPLATE = r"""
<style>
  #chat-fab { position: fixed; bottom: 20px; right: 20px; width: 56px; height: 56px; border-radius: 50%; background: #0071e3; color: #fff; border: none; box-shadow: 0 4px 14px rgba(0,113,227,.4); font-size: 26px; cursor: pointer; z-index: 999; transition: transform .15s; }
  #chat-fab:hover { transform: scale(1.08); }
  #chat-fab.open { background: #475569; }

  #chat-panel { position: fixed; bottom: 88px; right: 20px; width: 380px; max-width: calc(100vw - 40px); height: 560px; max-height: calc(100vh - 120px); background: #fff; border-radius: 16px; box-shadow: 0 12px 40px rgba(15,23,42,.25); display: none; flex-direction: column; overflow: hidden; z-index: 1000; }
  #chat-panel.open { display: flex; }

  .chat-header { background: linear-gradient(135deg,#0071e3,#005bb5); color: #fff; padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; }
  .chat-header h3 { font-size: 15px; font-weight: 600; margin: 0; }
  .chat-header-actions { display: flex; gap: 8px; }
  .chat-header button { background: rgba(255,255,255,.15); border: none; color: #fff; padding: 4px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; }
  .chat-header button:hover { background: rgba(255,255,255,.25); }

  .chat-messages { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; background: #f8fafc; }
  .chat-msg { max-width: 85%; padding: 9px 13px; border-radius: 14px; font-size: 14px; line-height: 1.4; word-wrap: break-word; }
  .chat-msg.user { align-self: flex-end; background: #0071e3; color: #fff; border-bottom-right-radius: 4px; }
  .chat-msg.assistant { align-self: flex-start; background: #fff; color: #0f172a; border: 1px solid #e2e8f0; border-bottom-left-radius: 4px; }
  .chat-msg.system { align-self: center; background: transparent; color: #64748b; font-size: 12px; font-style: italic; max-width: 100%; text-align: center; }
  .chat-msg.error { align-self: center; background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; font-size: 12px; max-width: 95%; }
  .chat-loading { align-self: flex-start; padding: 9px 13px; color: #64748b; font-size: 14px; }
  .chat-loading::after { content: '...'; animation: dots 1.2s infinite; }
  @keyframes dots { 0%,20%{content:'.'} 40%{content:'..'} 60%,100%{content:'...'} }

  .chat-input-row { display: flex; gap: 8px; padding: 12px; background: #fff; border-top: 1px solid #e2e8f0; }
  #chat-input { flex: 1; padding: 9px 12px; border: 1px solid #cbd5e1; border-radius: 10px; font-size: 14px; font-family: inherit; resize: none; min-height: 38px; max-height: 100px; outline: none; }
  #chat-input:focus { border-color: #0071e3; }
  #chat-send { padding: 0 16px; background: #0071e3; color: #fff; border: none; border-radius: 10px; font-size: 14px; font-weight: 600; cursor: pointer; }
  #chat-send:disabled { background: #cbd5e1; cursor: not-allowed; }
  #chat-send:hover:not(:disabled) { background: #005bb5; }

  .chat-setup { padding: 20px; flex: 1; overflow-y: auto; background: #f8fafc; font-size: 14px; line-height: 1.5; }
  .chat-setup h4 { margin: 0 0 10px; font-size: 14px; }
  .chat-setup p { margin: 8px 0; color: #475569; }
  .chat-setup a { color: #0071e3; }
  .chat-setup input { width: 100%; padding: 9px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13px; font-family: monospace; margin: 10px 0; }
  .chat-setup .save-btn { width: 100%; padding: 10px; background: #0071e3; color: #fff; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; }

  #chat-filter-banner { display: none; background: linear-gradient(135deg,#fef3c7,#fde68a); border: 1px solid #fbbf24; border-radius: 10px; padding: 10px 14px; margin: 12px 20px; font-size: 13px; color: #78350f; align-items: center; justify-content: space-between; gap: 12px; max-width: 900px; margin-left: auto; margin-right: auto; }
  #chat-filter-banner.show { display: flex; }
  #chat-filter-banner button { background: #fff; border: 1px solid #fbbf24; color: #78350f; padding: 4px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; font-weight: 600; }
  #chat-filter-banner button:hover { background: #fef3c7; }

  @media(max-width:600px) {
    #chat-panel { right: 10px; bottom: 78px; width: calc(100vw - 20px); height: calc(100vh - 100px); }
    #chat-fab { right: 14px; bottom: 14px; }
  }
</style>

<button id="chat-fab" onclick="toggleChat()" title="Apri chat">💬</button>

<div id="chat-panel">
  <div class="chat-header">
    <h3>💬 Casa Milano Assistant</h3>
    <div class="chat-header-actions">
      <button onclick="resetChat()" title="Nuova chat">↻</button>
      <button onclick="showSetup()" title="Impostazioni">⚙</button>
      <button onclick="toggleChat()" title="Chiudi">×</button>
    </div>
  </div>
  <div id="chat-body"></div>
  <div class="chat-input-row" id="chat-input-row">
    <textarea id="chat-input" placeholder="Chiedi qualcosa sugli annunci..." rows="1"></textarea>
    <button id="chat-send" onclick="sendChat()">Invia</button>
  </div>
</div>

<div id="chat-filter-banner">
  <span id="chat-filter-text"></span>
  <button onclick="clearChatFilter()">Mostra tutti</button>
</div>

<script id="dashboard-listings" type="application/json">__LISTINGS_JSON__</script>

<script>
(function() {
  const API_URL = 'https://api.anthropic.com/v1/messages';
  const MODEL = '__MODEL__';
  const SYSTEM_PROMPT = __SYSTEM_PROMPT__;
  const LISTINGS = JSON.parse(document.getElementById('dashboard-listings').textContent);
  const LISTINGS_JSON_STR = JSON.stringify(LISTINGS);

  const KEY_API = 'casa-milano-anthropic-key';
  const KEY_CHAT = 'casa-milano-chat-history';
  const MAX_HISTORY = 16;

  let conversation = [];

  function getApiKey() { return localStorage.getItem(KEY_API) || ''; }
  function setApiKey(k) { localStorage.setItem(KEY_API, k); }
  function loadHistory() {
    try { return JSON.parse(localStorage.getItem(KEY_CHAT) || '[]'); }
    catch (e) { return []; }
  }
  function saveHistory() { localStorage.setItem(KEY_CHAT, JSON.stringify(conversation.slice(-MAX_HISTORY))); }

  window.toggleChat = function() {
    const panel = document.getElementById('chat-panel');
    const fab = document.getElementById('chat-fab');
    const opening = !panel.classList.contains('open');
    panel.classList.toggle('open');
    fab.classList.toggle('open');
    fab.textContent = opening ? '×' : '💬';
    if (opening) renderChat();
  };

  function renderChat() {
    if (!getApiKey()) { showSetup(); return; }
    document.getElementById('chat-input-row').style.display = 'flex';
    const body = document.getElementById('chat-body');
    body.className = 'chat-messages';
    body.innerHTML = '';
    if (conversation.length === 0) {
      appendMsg('system', 'Ciao! Hai ' + LISTINGS.length + ' annunci in dashboard. Chiedi pure: "mostra solo NoLo", "i migliori 5 sotto 350k", "ce ne sono con terrazzo?"...');
    } else {
      for (const m of conversation) {
        if (m.role === 'user') {
          appendMsg('user', m.content);
        } else if (m.role === 'assistant') {
          appendMsg('assistant', m.displayText || '...');
        }
      }
    }
    setTimeout(() => { body.scrollTop = body.scrollHeight; }, 50);
    document.getElementById('chat-input').focus();
  }

  window.showSetup = function() {
    document.getElementById('chat-input-row').style.display = 'none';
    const body = document.getElementById('chat-body');
    body.className = 'chat-setup';
    const existing = getApiKey();
    body.innerHTML =
      '<h4>🔑 API Key Anthropic</h4>' +
      '<p>Per usare il chatbot serve una API key Anthropic. Salvata <strong>solo nel tuo browser</strong> (localStorage), mai inviata altrove. La key viene usata direttamente per chiamare api.anthropic.com.</p>' +
      '<p>Crea una key gratuita su <a href="https://console.anthropic.com/settings/keys" target="_blank">console.anthropic.com</a>. Il chatbot usa Haiku 4.5 (~0.005€ per domanda con cache attiva).</p>' +
      '<input type="password" id="api-key-input" placeholder="sk-ant-..." value="' + (existing ? existing.slice(0, 8) + '...' + existing.slice(-4) : '') + '">' +
      '<button class="save-btn" onclick="saveApiKey()">Salva e inizia</button>' +
      (existing ? '<p style="text-align:center;margin-top:14px"><a href="#" onclick="clearApiKey(); return false;" style="color:#dc2626;font-size:12px">Rimuovi key salvata</a></p>' : '');
    document.getElementById('api-key-input').focus();
  };

  window.saveApiKey = function() {
    const val = document.getElementById('api-key-input').value.trim();
    if (!val || val.includes('...')) { alert('Inserisci una API key valida (sk-ant-...)'); return; }
    if (!val.startsWith('sk-ant-')) { alert('La key dovrebbe iniziare con "sk-ant-"'); return; }
    setApiKey(val);
    renderChat();
  };

  window.clearApiKey = function() {
    if (!confirm('Rimuovere la API key dal browser?')) return;
    localStorage.removeItem(KEY_API);
    showSetup();
  };

  window.resetChat = function() {
    if (conversation.length && !confirm('Cancellare la chat corrente?')) return;
    conversation = [];
    saveHistory();
    clearChatFilter();
    renderChat();
  };

  function appendMsg(role, text) {
    const body = document.getElementById('chat-body');
    const el = document.createElement('div');
    el.className = 'chat-msg ' + role;
    el.textContent = text;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
    return el;
  }

  function appendError(text) {
    const body = document.getElementById('chat-body');
    const el = document.createElement('div');
    el.className = 'chat-msg error';
    el.textContent = text;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
  }

  function appendLoading() {
    const body = document.getElementById('chat-body');
    const el = document.createElement('div');
    el.className = 'chat-loading';
    el.id = 'chat-loading-el';
    el.textContent = 'Sto pensando';
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
  }

  function removeLoading() {
    const el = document.getElementById('chat-loading-el');
    if (el) el.remove();
  }

  window.applyChatFilter = function(ids) {
    const banner = document.getElementById('chat-filter-banner');
    if (!ids || ids.length === 0) { clearChatFilter(); return; }
    const idSet = new Set(ids);
    let shown = 0;
    document.querySelectorAll('.card').forEach(card => {
      const btn = card.querySelector('.heart-btn');
      const id = btn ? btn.dataset.id : null;
      if (id && idSet.has(id)) { card.dataset.chatHidden = ''; delete card.dataset.chatHidden; card.style.display = ''; shown++; }
      else { card.dataset.chatHidden = '1'; card.style.display = 'none'; }
    });
    document.getElementById('chat-filter-text').textContent = '🔍 Chatbot ha filtrato ' + shown + ' di ' + LISTINGS.length + ' annunci';
    banner.classList.add('show');
    window.scrollTo({ top: banner.offsetTop - 20, behavior: 'smooth' });
  };

  window.clearChatFilter = function() {
    document.querySelectorAll('.card').forEach(card => {
      delete card.dataset.chatHidden;
      card.style.display = '';
    });
    document.getElementById('chat-filter-banner').classList.remove('show');
  };

  window.sendChat = async function() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    const apiKey = getApiKey();
    if (!apiKey) { showSetup(); return; }

    input.value = '';
    input.style.height = 'auto';
    document.getElementById('chat-send').disabled = true;
    appendMsg('user', text);
    conversation.push({ role: 'user', content: text });
    appendLoading();

    try {
      const apiMessages = conversation
        .slice(-MAX_HISTORY)
        .map(m => ({ role: m.role, content: typeof m.content === 'string' ? m.content : (m.displayText || '') }));

      const body = {
        model: MODEL,
        max_tokens: 1024,
        system: [
          { type: 'text', text: SYSTEM_PROMPT },
          { type: 'text', text: 'DATI ANNUNCI:\n' + LISTINGS_JSON_STR, cache_control: { type: 'ephemeral' } }
        ],
        output_config: {
          format: {
            type: 'json_schema',
            schema: {
              type: 'object',
              properties: {
                message: { type: 'string', description: 'Risposta testuale in italiano, max 4 frasi' },
                filter_ids: {
                  type: 'array',
                  items: { type: 'string' },
                  description: 'ID degli annunci da mostrare. Vuoto = mostra tutti.'
                }
              },
              required: ['message', 'filter_ids'],
              additionalProperties: false
            }
          }
        },
        messages: apiMessages
      };

      const resp = await fetch(API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true'
        },
        body: JSON.stringify(body)
      });

      removeLoading();

      if (!resp.ok) {
        let err = 'Errore ' + resp.status;
        try { const j = await resp.json(); if (j.error && j.error.message) err += ' — ' + j.error.message; } catch(e) {}
        if (resp.status === 401) err = '🔑 API key non valida. Controlla in impostazioni (⚙).';
        if (resp.status === 429) err = '⏱ Rate limit. Aspetta qualche secondo e riprova.';
        appendError(err);
        conversation.pop();
        return;
      }

      const data = await resp.json();
      const textBlock = (data.content || []).find(b => b.type === 'text');
      if (!textBlock) { appendError('Risposta vuota dal modello.'); conversation.pop(); return; }

      let parsed;
      try { parsed = JSON.parse(textBlock.text); }
      catch (e) { appendError('Risposta non parseable: ' + textBlock.text.slice(0, 200)); conversation.pop(); return; }

      const message = parsed.message || '(nessun messaggio)';
      const filterIds = Array.isArray(parsed.filter_ids) ? parsed.filter_ids : [];

      appendMsg('assistant', message);
      conversation.push({ role: 'assistant', content: textBlock.text, displayText: message });
      saveHistory();

      if (filterIds.length > 0) applyChatFilter(filterIds);
    } catch (e) {
      removeLoading();
      appendError('Errore di rete: ' + (e.message || e));
      conversation.pop();
    } finally {
      document.getElementById('chat-send').disabled = false;
      document.getElementById('chat-input').focus();
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    conversation = loadHistory();
    const input = document.getElementById('chat-input');
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 100) + 'px';
    });
  });
})();
</script>
"""


def build_chatbot_block(dash_items: list[dict]) -> str:
    """Restituisce il blocco HTML+CSS+JS del chatbot, con dati e prompt iniettati."""
    data = []
    for a in dash_items:
        data.append({
            "id": a.get("id"),
            "titolo": a.get("titolo"),
            "prezzo": a.get("prezzo"),
            "mq": a.get("mq"),
            "locali": a.get("locali"),
            "bagni": a.get("bagni"),
            "piano": a.get("piano"),
            "zona": a.get("zona"),
            "indirizzo": a.get("indirizzo"),
            "agenzia": a.get("agenzia"),
            "punteggio": a.get("punteggio"),
            "url": a.get("url"),
            "ascensore": a.get("ascensore"),
            "descrizione": (a.get("descrizione") or "")[:400],
        })
    listings_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # Difensivo: in caso una descrizione contenesse </script>
    listings_json = listings_json.replace('</', '<\\/')
    system_json = json.dumps(CHATBOT_SYSTEM_PROMPT, ensure_ascii=False)
    return (CHATBOT_TEMPLATE
            .replace('__LISTINGS_JSON__', listings_json)
            .replace('__MODEL__', CHATBOT_MODEL)
            .replace('__SYSTEM_PROMPT__', system_json))


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

    # Heart button — apre issue GitHub prefillata. Workflow process-preferiti la
    # processa e aggiunge a preferiti.json (visibile a entrambi gli utenti).
    listing_id = a.get("id") or ""
    if is_preferito or (in_preferiti_set and listing_id in in_preferiti_set):
        heart_html = '<div class="heart-badge filled" title="Preferito condiviso">❤️</div>'
    else:
        esc = lambda v: html_lib.escape(str(v) if v is not None else "", quote=True)
        heart_html = (
            f'<button class="heart-btn"'
            f' data-id="{esc(listing_id)}"'
            f' data-url="{esc(a.get("url"))}"'
            f' data-titolo="{esc(a.get("titolo"))}"'
            f' data-prezzo="{esc(a.get("prezzo"))}"'
            f' data-mq="{esc(a.get("mq"))}"'
            f' data-zona="{esc(a.get("zona"))}"'
            f' onclick="openFavIssue(this)"'
            f' title="Salva tra i preferiti condivisi (apre issue GitHub)">🤍</button>'
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
    <span style="font-size:12px;color:#64748b">💡 Clicca 🤍 su un annuncio per salvarlo nei preferiti condivisi</span>
  </div>
  <div class="main">
    {preferiti_section}
    <div class="section-title">Annunci attivi</div>
    {content}
  </div>

  <div id="toast" class="toast"></div>

  <script>
  const GITHUB_REPO = '{GITHUB_REPO}';

  function openFavIssue(btn) {{
    const d = btn.dataset;
    const titolo = d.titolo || '(senza titolo)';
    const prezzo = d.prezzo && d.prezzo !== 'None' ? d.prezzo : '';
    const mq = d.mq && d.mq !== 'None' ? d.mq : '';
    const zona = d.zona && d.zona !== 'None' ? d.zona : '';
    const title = 'preferito: ' + titolo.slice(0, 80);
    const body = [
      'URL: ' + (d.url || ''),
      'Titolo: ' + titolo,
      'Sito: immobiliare.it',
      'Prezzo: ' + prezzo,
      'Mq: ' + mq,
      'Zona: ' + zona,
      'Note: (opzionale — scrivi qui perché ti piace)',
    ].join('\\n');
    const u = 'https://github.com/' + GITHUB_REPO + '/issues/new'
      + '?labels=preferito'
      + '&title=' + encodeURIComponent(title)
      + '&body=' + encodeURIComponent(body);
    window.open(u, '_blank', 'noopener');
    btn.textContent = '⏳';
    btn.disabled = true;
    showToast('🔗 Conferma "Submit new issue" su GitHub → preferito visibile a entrambi tra ~30s');
  }}

  function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 4000);
  }}
  </script>
</body>
</html>"""

    chatbot_block = build_chatbot_block(dash)
    html = html.replace('</body>', chatbot_block + '\n</body>')

    if dry_run:
        print(f"DRY RUN: dashboard avrebbe {len(dash)} card + {len(preferiti_sorted)} preferiti")
        return 0

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"index.html scritto: {len(dash)} card + {len(preferiti_sorted)} preferiti, {len(html)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(build(dry_run="--dry-run" in sys.argv))
