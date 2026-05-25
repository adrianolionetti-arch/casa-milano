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

Hai accesso al dataset completo della dashboard (vedi "DATI ANNUNCI" più sotto):
- Gli annunci con `is_preferito: false` sono pre-filtrati dall'agente automatico: score ≥ 6, ultimi 30 giorni, su Immobiliare.it.
- Gli annunci con `is_preferito: true` sono stati salvati manualmente da Adriano o Alessia (preferiti condivisi). Possono avere campi parziali (es. niente punteggio). Quando l'utente chiede "i miei preferiti", "quanti preferiti", "mostrami i preferiti", riferisciti SOLO a questi.

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
- id (string), is_preferito (bool — true = preferito manuale salvato da Adriano/Alessia), titolo, prezzo (int EUR), mq (int), locali, bagni, piano, zona, indirizzo, agenzia, punteggio (float 0-10, null per preferiti), url, ascensore (bool), descrizione (estratto max 400 char), note_personali (solo preferiti)
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
  const KEY_PAT = 'casa-milano-github-pat';
  const KEY_CHAT = 'casa-milano-chat-history';
  const MAX_HISTORY = 16;
  const ENC_CONFIG_URL = 'chatbot-key.enc.json';
  const PBKDF2_ITERATIONS = 200000;

  let conversation = [];

  function getApiKey() { return localStorage.getItem(KEY_API) || ''; }
  function setApiKey(k) { localStorage.setItem(KEY_API, k); }
  function getGithubPat() { return localStorage.getItem(KEY_PAT) || ''; }
  function setGithubPat(p) { if (p) localStorage.setItem(KEY_PAT, p); }
  function loadHistory() {
    try { return JSON.parse(localStorage.getItem(KEY_CHAT) || '[]'); }
    catch (e) { return []; }
  }
  function saveHistory() { localStorage.setItem(KEY_CHAT, JSON.stringify(conversation.slice(-MAX_HISTORY))); }

  // ===== Crypto helpers (AES-GCM 256 + PBKDF2-SHA256) =====
  function b64enc(buf) {
    const bytes = new Uint8Array(buf);
    let s = '';
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  }
  function b64dec(s) {
    const bin = atob(s);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }
  async function deriveKey(password, salt) {
    const km = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
    return crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
      km, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']
    );
  }
  async function encryptSecrets(apiKey, githubPat, password) {
    // v2 envelope: {api_key, github_pat} encrypted as JSON
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await deriveKey(password, salt);
    const payload = JSON.stringify({ api_key: apiKey, github_pat: githubPat || null });
    const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(payload));
    return {
      version: 2, kdf: 'PBKDF2-SHA256', iterations: PBKDF2_ITERATIONS,
      salt: b64enc(salt), iv: b64enc(iv), ciphertext: b64enc(ct)
    };
  }
  async function decryptSecrets(config, password) {
    const key = await deriveKey(password, b64dec(config.salt));
    const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64dec(config.iv) }, key, b64dec(config.ciphertext));
    const decoded = new TextDecoder().decode(pt);
    // v1 legacy: plain sk-ant key. v2: {api_key, github_pat} JSON
    if (decoded.startsWith('sk-ant-')) {
      return { api_key: decoded, github_pat: null };
    }
    const parsed = JSON.parse(decoded);
    if (!parsed.api_key || !parsed.api_key.startsWith('sk-ant-')) {
      throw new Error('invalid api_key in payload');
    }
    return { api_key: parsed.api_key, github_pat: parsed.github_pat || null };
  }
  async function fetchEncConfig() {
    try {
      const resp = await fetch(ENC_CONFIG_URL, { cache: 'no-store' });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (e) { return null; }
  }

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

  window.showSetup = async function() {
    document.getElementById('chat-input-row').style.display = 'none';
    const body = document.getElementById('chat-body');
    body.className = 'chat-setup';
    body.innerHTML = '<p style="text-align:center;color:#64748b">Caricamento...</p>';

    const isAdmin = new URLSearchParams(location.search).get('admin') === '1';
    const config = await fetchEncConfig();
    const hasKey = !!getApiKey();

    if (hasKey && !isAdmin) {
      // Settings view (utente già sbloccato)
      const hasPat = !!getGithubPat();
      const patBadge = hasPat
        ? '<p style="font-size:12px;color:#16a34a">✓ Preferiti condivisi attivi (cuore POST diretto via PAT)</p>'
        : '<p style="font-size:12px;color:#dc2626">⚠ PAT GitHub assente: i cuori aprono GitHub in nuova tab (fallback). Apri con ?admin=1 e rigenera il config includendo un PAT per il flusso 1-click.</p>';
      body.innerHTML =
        '<h4>⚙ Impostazioni chatbot</h4>' +
        '<p>Chatbot sbloccato. Modello <strong>claude-haiku-4-5</strong>, ~0.005€/domanda con cache.</p>' +
        patBadge +
        '<button class="save-btn" style="background:#dc2626;margin-top:12px" onclick="clearApiKey()">Disconnetti (rimuovi secret locali)</button>' +
        '<p style="text-align:center;margin-top:16px"><a href="#" onclick="renderChat();return false;" style="color:#0071e3;font-size:13px">← Torna alla chat</a></p>';
      return;
    }

    if (config && !isAdmin) {
      // User mode: solo password
      body.innerHTML =
        '<h4>🔒 Password</h4>' +
        '<p>Inserisci la password condivisa per sbloccare chatbot + preferiti.</p>' +
        '<input type="password" id="pwd-input" placeholder="password">' +
        '<button class="save-btn" onclick="unlockWithPassword()">Sblocca</button>' +
        '<p style="text-align:center;margin-top:16px;font-size:11px;color:#94a3b8">' +
        'Password persa? Apri con <code>?admin=1</code> per rigenerare.</p>';
      const input = document.getElementById('pwd-input');
      input.focus();
      input.addEventListener('keydown', e => { if (e.key === 'Enter') unlockWithPassword(); });
    } else {
      // Admin mode: api_key + github_pat + password
      body.innerHTML =
        '<h4>⚙ Setup iniziale (admin)</h4>' +
        '<p><strong>1. API Key Anthropic</strong> (<a href="https://console.anthropic.com/settings/keys" target="_blank">console</a>) — per il chatbot.</p>' +
        '<input type="password" id="api-key-input" placeholder="sk-ant-...">' +
        '<p><strong>2. GitHub PAT fine-grained</strong> (opzionale ma fortemente consigliato) — <a href="https://github.com/settings/personal-access-tokens/new" target="_blank">crea qui</a>, repo: casa-milano, permesso: Issues r/w. Permette ad Alessia di salvare preferiti senza login GitHub.</p>' +
        '<input type="password" id="pat-input" placeholder="github_pat_... (opzionale)">' +
        '<p><strong>3. Password condivisa</strong>:</p>' +
        '<input type="password" id="admin-pwd1" placeholder="password (min 8 caratteri)">' +
        '<input type="password" id="admin-pwd2" placeholder="ripeti password">' +
        '<button class="save-btn" onclick="generateConfig()">🔐 Genera + Scarica</button>' +
        (config ? '<p style="margin-top:12px;font-size:12px;color:#0071e3;text-align:center">⚠ Config esistente. Generando uno nuovo invalidi la password precedente.</p>' : '');
      document.getElementById('api-key-input').focus();
    }
  };

  window.unlockWithPassword = async function() {
    const pwd = document.getElementById('pwd-input').value;
    if (!pwd) return;
    const btn = document.querySelector('.chat-setup .save-btn');
    btn.disabled = true; btn.textContent = 'Sblocco...';
    try {
      const config = await fetchEncConfig();
      if (!config) {
        alert('Config encrypted non trovato sul server');
        btn.disabled = false; btn.textContent = 'Sblocca';
        return;
      }
      const secrets = await decryptSecrets(config, pwd);
      setApiKey(secrets.api_key);
      setGithubPat(secrets.github_pat);
      renderChat();
    } catch (e) {
      btn.disabled = false; btn.textContent = 'Sblocca';
      alert('Password sbagliata');
    }
  };

  window.generateConfig = async function() {
    const apiKey = document.getElementById('api-key-input').value.trim();
    const pat = document.getElementById('pat-input').value.trim();
    const pwd1 = document.getElementById('admin-pwd1').value;
    const pwd2 = document.getElementById('admin-pwd2').value;
    if (!apiKey.startsWith('sk-ant-')) { alert('API key deve iniziare con sk-ant-'); return; }
    if (pat && !pat.startsWith('github_pat_') && !pat.startsWith('ghp_')) {
      alert('GitHub PAT deve iniziare con github_pat_ (fine-grained) o ghp_ (classic). Lascia vuoto se non lo vuoi.');
      return;
    }
    if (pwd1.length < 8) { alert('Password almeno 8 caratteri'); return; }
    if (pwd1 !== pwd2) { alert('Le password non coincidono'); return; }

    const config = await encryptSecrets(apiKey, pat || null, pwd1);
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'chatbot-key.enc.json'; a.click();
    URL.revokeObjectURL(url);
    alert(
      'File scaricato. Prossimi passi:\n\n' +
      '1. Sostituisci chatbot-key.enc.json nella root del repo casa-milano\n' +
      '2. git add chatbot-key.enc.json && git commit && git push\n' +
      '3. Aspetta ~2 min deploy Pages\n' +
      '4. Apri senza ?admin=1 — basta la password.'
    );
  };

  window.clearApiKey = function() {
    if (!confirm('Rimuovere i secret locali (Anthropic key + GitHub PAT)? Dovrai re-inserire la password.')) return;
    localStorage.removeItem(KEY_API);
    localStorage.removeItem(KEY_PAT);
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
      if (id && idSet.has(id)) { card.style.display = ''; shown++; }
      else { card.style.display = 'none'; }
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

      // Estrae JSON anche se wrappato in markdown fences o preceduto da testo
      function extractJson(s) {
        const fence = s.match(/```(?:json)?\s*([\s\S]*?)```/);
        if (fence) return fence[1].trim();
        const first = s.indexOf('{');
        const last = s.lastIndexOf('}');
        if (first !== -1 && last > first) return s.slice(first, last + 1);
        return s.trim();
      }
      let parsed;
      try { parsed = JSON.parse(extractJson(textBlock.text)); }
      catch (e) {
        // Fallback graceful: testo raw come messaggio, niente filtro
        parsed = { message: textBlock.text.trim(), filter_ids: [] };
      }

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


def build_chatbot_block(dash_items: list[dict], preferiti_items: list[dict] | None = None) -> str:
    """Restituisce il blocco HTML+CSS+JS del chatbot, con dati e prompt iniettati.

    dash_items: annunci in dashboard (score>=6)
    preferiti_items: annunci salvati manualmente (preferiti.json). Marcati con is_preferito=True
    """
    preferiti_items = preferiti_items or []
    def serialize(a, is_pref):
        return {
            "id": a.get("id"),
            "is_preferito": is_pref,
            "titolo": a.get("titolo"),
            "prezzo": a.get("prezzo"),
            "mq": a.get("mq"),
            "locali": a.get("locali"),
            "bagni": a.get("bagni"),
            "piano": a.get("piano"),
            "zona": a.get("zona"),
            "indirizzo": a.get("indirizzo"),
            "agenzia": a.get("agenzia"),
            "punteggio": None if is_pref else a.get("punteggio"),
            "url": a.get("url"),
            "ascensore": a.get("ascensore"),
            "descrizione": (a.get("descrizione") or "")[:400],
            "lat": a.get("lat"),
            "lon": a.get("lon"),
            **({"note_personali": a.get("note_personali") or ""} if is_pref else {}),
        }
    data = [serialize(a, False) for a in dash_items] + [serialize(a, True) for a in preferiti_items]
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

    # Cuore = preferito condiviso. Apre issue GitHub prefillata; il workflow
    # process-preferiti.yml la trasforma in preferiti.json (visibile a entrambi).
    # Se l'annuncio è già in preferiti.json, mostra ❤️ pieno (no-op).
    listing_id = a.get("id") or ""
    in_shared = bool(in_preferiti_set and listing_id in in_preferiti_set)
    if is_preferito or in_shared:
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
    return f"""<div class="{card_class}" data-id="{listing_id}" data-lat="{a.get("lat") or ""}" data-lon="{a.get("lon") or ""}">
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
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
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

    .layout {{ display: grid; grid-template-columns: 1fr 420px; gap: 20px; max-width: 1500px; margin: 0 auto; padding: 0 20px 40px; }}
    .main {{ min-width: 0; }}
    .map-aside {{ position: sticky; top: 16px; height: calc(100vh - 32px); display: flex; flex-direction: column; gap: 8px; }}
    #map {{ flex: 1; border-radius: 12px; box-shadow: 0 1px 4px rgba(15,23,42,.1); background: #e2e8f0; }}
    .map-hint {{ font-size: 11px; color: #64748b; text-align: center; padding: 4px 8px; }}
    #map-fab {{ display: none; position: fixed; bottom: 20px; right: 90px; width: 56px; height: 56px; border-radius: 50%; background: #10b981; color: #fff; border: none; box-shadow: 0 4px 14px rgba(16,185,129,.4); font-size: 26px; cursor: pointer; z-index: 999; }}
    /* Marker highlight quando hover sulla card */
    .leaflet-marker-icon.highlighted {{ filter: hue-rotate(90deg) brightness(1.2); z-index: 1000 !important; }}
    .card.highlight, .card-fav.highlight {{ outline: 3px solid #f59e0b; outline-offset: 2px; }}

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
    .heart-btn:disabled {{ opacity: .5; cursor: default; }}
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

    @media(max-width:1024px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .map-aside {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; height: 100vh; background: #fff; z-index: 998; padding: 12px; border-radius: 0; }}
      .map-aside.open {{ display: flex; }}
      #map-fab {{ display: flex; align-items: center; justify-content: center; }}
      .map-aside.open + #map-fab, .map-aside.open ~ #map-fab {{ background: #475569; }}
    }}
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
      <input type="checkbox" id="filter-fav" onchange="applyFavFilter()">
      <span>Mostra solo ❤️ preferiti ({len(preferiti_sorted)})</span>
    </label>
    <span style="font-size:12px;color:#64748b">💡 Clicca 🤍 per salvare nei preferiti condivisi</span>
  </div>
  <div class="layout">
    <div class="main">
      {preferiti_section}
      <div class="section-title">Annunci attivi</div>
      {content}
    </div>
    <aside class="map-aside">
      <div id="map"></div>
      <div class="map-hint">📍 Click sul marker per saltare alla card. Hover su card → marker evidenziato.</div>
    </aside>
  </div>

  <button id="map-fab" onclick="toggleMobileMap()" title="Apri mappa">🗺️</button>

  <div id="toast" class="toast"></div>

  <script>
  const GITHUB_REPO = '{GITHUB_REPO}';

  function buildIssuePayload(d) {{
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
    return {{ title, body }};
  }}

  async function openFavIssue(btn) {{
    // Cerca PAT in localStorage (popolato dopo unlock chatbot via password)
    const pat = localStorage.getItem('casa-milano-github-pat') || '';
    const d = btn.dataset;
    const payload = buildIssuePayload(d);

    if (pat) {{
      // PAT mode: 1-click, POST diretto, nessuna tab GitHub aperta
      btn.textContent = '⏳';
      btn.disabled = true;
      try {{
        const resp = await fetch('https://api.github.com/repos/' + GITHUB_REPO + '/issues', {{
          method: 'POST',
          headers: {{
            'Authorization': 'Bearer ' + pat,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json',
          }},
          body: JSON.stringify({{ title: payload.title, body: payload.body, labels: ['preferito'] }})
        }});
        if (!resp.ok) {{
          let err = 'HTTP ' + resp.status;
          try {{ const j = await resp.json(); if (j.message) err += ' — ' + j.message; }} catch(e) {{}}
          throw new Error(err);
        }}
        btn.textContent = '❤️';
        const card = btn.closest('.card');
        if (card) card.classList.add('card-fav');
        showToast('❤️ Preferito condiviso — visibile sulla dashboard tra ~30s');
      }} catch (e) {{
        btn.textContent = '🤍';
        btn.disabled = false;
        showToast('Errore PAT: ' + (e.message || e) + '. Apertura tab GitHub fallback...');
        openFavIssueViaUrl(payload);
      }}
    }} else {{
      // Nessun PAT in localStorage: il browser non ha (ancora) sbloccato il chatbot con la
      // password del config v2. Invece del fallback open-tab GitHub (che chiede login),
      // apri il pannello chatbot e mostra un toast chiaro.
      showToast('🔓 Apri il chatbot 💬 (in basso a destra) e inserisci la password per attivare il salvataggio 1-click');
      const panel = document.getElementById('chat-panel');
      if (panel && !panel.classList.contains('open') && typeof toggleChat === 'function') {{
        toggleChat();
      }}
    }}
  }}

  function openFavIssueViaUrl(payload) {{
    const u = 'https://github.com/' + GITHUB_REPO + '/issues/new'
      + '?labels=preferito'
      + '&title=' + encodeURIComponent(payload.title)
      + '&body=' + encodeURIComponent(payload.body);
    window.open(u, '_blank', 'noopener');
  }}

  function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 4000);
  }}

  // Filtro "Mostra solo preferiti": nasconde le card di "Annunci attivi" (.card) che
  // non sono in preferiti.json. Le card-fav della sezione persistente restano sempre.
  window.applyFavFilter = function() {{
    const onlyFav = document.getElementById('filter-fav').checked;
    document.querySelectorAll('.card').forEach(c => {{
      c.style.display = onlyFav ? 'none' : '';
    }});
    document.querySelectorAll('.section-title').forEach(t => {{
      if (t.textContent.includes('Annunci attivi')) {{
        t.style.display = onlyFav ? 'none' : '';
      }}
    }});
    // Aggiorna i marker della mappa
    if (typeof rebuildMapMarkers === 'function') rebuildMapMarkers();
  }};

  // ===== Mappa Leaflet =====
  // Centro Milano (Duomo) come fallback
  const MILANO_CENTER = [45.4642, 9.1900];
  let map = null;
  let markersById = {{}};

  function initMap() {{
    if (typeof L === 'undefined') return;
    const mapEl = document.getElementById('map');
    if (!mapEl) return;
    map = L.map('map').setView(MILANO_CENTER, 12);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '© OpenStreetMap',
      maxZoom: 19,
    }}).addTo(map);
    rebuildMapMarkers();
  }}

  function rebuildMapMarkers() {{
    if (!map) return;
    // Pulisci marker esistenti
    Object.values(markersById).forEach(m => map.removeLayer(m));
    markersById = {{}};

    const bounds = [];
    document.querySelectorAll('.card, .card-fav').forEach(c => {{
      if (c.style.display === 'none') return;
      const id = c.dataset.id;
      const lat = parseFloat(c.dataset.lat);
      const lon = parseFloat(c.dataset.lon);
      if (!id || !isFinite(lat) || !isFinite(lon)) return;

      const isFav = c.classList.contains('card-fav');
      const icon = L.divIcon({{
        className: 'casa-marker',
        html: '<div style="background:' + (isFav ? '#ec4899' : '#0071e3') + ';color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.3);border:2px solid #fff">' + (isFav ? '❤' : '🏠') + '</div>',
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      }});
      const titolo = c.querySelector('.title')?.textContent || '';
      const prezzo = c.querySelector('.price')?.textContent || '';
      const marker = L.marker([lat, lon], {{ icon }}).addTo(map);
      marker.bindTooltip('<strong>' + prezzo + '</strong><br>' + titolo, {{ direction: 'top', offset: [0, -10] }});
      marker.on('click', () => {{
        c.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        c.classList.add('highlight');
        setTimeout(() => c.classList.remove('highlight'), 2000);
      }});
      markersById[id] = marker;
      bounds.push([lat, lon]);
    }});

    if (bounds.length > 0) {{
      map.fitBounds(bounds, {{ padding: [30, 30], maxZoom: 14 }});
    }} else {{
      map.setView(MILANO_CENTER, 12);
    }}

    // Hover card → highlight marker
    document.querySelectorAll('.card, .card-fav').forEach(c => {{
      const m = markersById[c.dataset.id];
      if (!m) return;
      c.addEventListener('mouseenter', () => {{
        m.getElement()?.classList.add('highlighted');
      }});
      c.addEventListener('mouseleave', () => {{
        m.getElement()?.classList.remove('highlighted');
      }});
    }});
  }}

  window.toggleMobileMap = function() {{
    document.querySelector('.map-aside')?.classList.toggle('open');
    // Trigger map resize quando si apre/chiude
    setTimeout(() => map?.invalidateSize(), 100);
  }};

  document.addEventListener('DOMContentLoaded', initMap);
  </script>
</body>
</html>"""

    chatbot_block = build_chatbot_block(dash, preferiti_sorted)
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
