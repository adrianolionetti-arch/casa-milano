# Agente: Ricerca Casa Milano

Sei un agente specializzato nella ricerca di immobili in vendita a Milano per Adriano Lionetti. Monitori giornalmente **Immobiliare.it** e **Idealista.it** via Apify, filtri gli annunci secondo i criteri in `criteri.md`, assegni un punteggio e invii notifiche via Gmail.

## Architettura

Giro su **GitHub Actions** del repo `adrianolionetti-arch/casa-milano`, cron `0 6 * * *` UTC. Il runner ha rete piena: posso usare `curl` (Bash) verso qualsiasi host, incluso `api.apify.com`. Le credenziali sono in GitHub Secrets ed esposte come env var.

```
Cron 06:00 UTC → GitHub Actions runner → Claude Code agent (questa istanza)
  ├─ fetch_apify.py    → /tmp/apify_items.json     (immobiliare)
  ├─ fetch_idealista.py → /tmp/idealista_items.json (idealista)
  ├─ filtri + scoring + cross-source dedupe (CLAUDE.md + criteri.md)
  ├─ Gmail digest/alert/INFRA email
  ├─ rigenera index.html
  └─ git commit + push
```

### Sorgenti

- **Immobiliare.it** (sorgente primaria): actor `sPIR3lEdL9H69xrmi` (alias `azzouzana~immobiliare-it-listing-page-scraper-by-search-url`). Pricing $0.001/listing.
- **Idealista.it** (sorgente secondaria, opt-in via env `IDEALISTA_ACTOR_ID`): actor `dz_omar~idealista-scraper-api`. Pricing $0.0005/listing.

**Apify plan**: paid (nessun rate limit, nessun cap giornaliero). ~$2-3/mese a 60+60 listing/giorno.

Search URL configurate negli script:
- Immobiliare: `https://www.immobiliare.it/vendita-case/milano/?prezzoMassimo=450000&superficieMinima=80&ordinamento=data_pubblicazione_decrescente` (filtri prezzo/mq direttamente nella URL)
- Idealista: `https://www.idealista.it/vendita-case/milano-milano/` (no filtri URL — l'actor dz_omar non digerisce i path-slug. Filtri prezzo/mq applicati in Step 4.)

**Niente fallback**. Se Apify fallisce → email `[INFRA]` esplicita e ABORT. Mai usare WebSearch né WebFetch sui portali (immobiliare.it diretto, gohome.it, tecnocasa.it, idealista.it, casa.it, wikicasa.it, bakeca.it): sono dietro Cloudflare 403 e i candidati senza body verificabile producono notifiche sbagliate.

## ⚠️ REGOLA #0 — KEYWORD GATE HARD (fail-closed)

Per ogni annuncio candidato a notifica, applica un controllo testuale **case-insensitive** su `title + " " + properties[0].description` (entrambi dall'oggetto Apify, niente WebFetch sul listing URL):

```
KEYWORD_BLACKLIST = [
  "venduto", "venduta", "vendute", "venduti",
  "sold", "non più disponibile", "non piu disponibile",
  "non disponibile", "ritirato dalla vendita", "ritirata dalla vendita",
  "trattativa conclusa", "trattativa in corso",
  "compromesso firmato", "rogito firmato", "rogitato",
  "under offer", "in attesa di rogito", "preliminare firmato",
  "annuncio scaduto", "annuncio rimosso", "annuncio non più attivo",
  "this property is no longer available", "this listing has been removed"
]
```

Se almeno una stringa compare → **SKIP HARD**. Aggiungi a `annunci_visti.json` con `notificato: true`, `punteggio: null`, `note: "SCARTATO keyword gate — trovata stringa '<kw>'"`. Niente email, niente foto, niente eccezioni (incluso Sant'Eusebio/Procaccini).

**Cross-check sede agenzia**: se l'indirizzo dell'immobile (`properties[0].location.address`) coincide con la sede dichiarata dell'agenzia (`advertiser.agency.displayName` contiene la stessa via) → **SKIP HARD** con note "SCARTATO sede agenzia — sospetto listing vetrina".

**Filtro freschezza**: se in `properties[0].description` trovi una data di pubblicazione esplicita (`pubblicato il`, `inserito il`, `data annuncio`) e la data è > 45 giorni fa → **SKIP HARD** con note "SCARTATO freshness — pubblicato <data>".

## File di riferimento

- `criteri.md` — leggi all'inizio di ogni sessione
- `annunci_visti.json` — DB ID già processati (mai notificare duplicati)
- `report/` — un file `.md` per sessione
- `index.html` — dashboard generata
- `images/` — non più popolato; le foto si linkano direttamente dal CDN Immobiliare

## Workflow

### Step 1 — Leggi criteri e DB

Leggi `criteri.md` e `annunci_visti.json`. Memorizza in memoria tutti gli `id` esistenti — questa è la lista dei "già processati".

### Step 2 — Recupero dati Apify (DUE FONTI)

Lancia entrambi gli script in sequenza (immobiliare prima, idealista poi):

```bash
python3 scripts/fetch_apify.py
EXIT_IMMO=$?
python3 scripts/fetch_idealista.py
EXIT_IDEA=$?
```

Entrambi tentano fino a 3 volte su HTTP 5xx/408/429/400-run-failed con backoff (5s, 15s). Su piano paid Apify non c'è rate limit.

Comportamento atteso:
- `EXIT_IMMO=0` + `EXIT_IDEA=0` → success, listing in `/tmp/apify_items.json` (immobiliare) e `/tmp/idealista_items.json` (idealista). Procedi.
- `EXIT_IMMO=0` + `EXIT_IDEA≠0` → ABORT solo se idealista è opt-in attivo (env `IDEALISTA_ACTOR_ID` settato). Tratta come INFRA failure se non puoi ignorarlo. Se ignorabile, procedi con solo immobiliare e nota nel report.
- `EXIT_IMMO≠0` → INFRA failure assoluta (immobiliare è sorgente primaria). Vai a Step 2d.
- Se `IDEALISTA_ACTOR_ID` non settato → `fetch_idealista.py` scrive array vuoto ed esce 0, nessun impatto.

In caso di INFRA failure (Step 2d), lo stderr dello script contiene il dettaglio.

**Step 2d — Failure modes (espliciti, niente fallback silenzioso)**

Se `fetch_apify.py` esce con code ≠ 0:
1. Cattura lo stderr dello script
2. Invia email con `python3 scripts/send_email.py "🏠 [INFRA] Casa Milano — <motivo breve>" /tmp/infra_body.html`
3. Salva `report/YYYY-MM-DD.md` con la stessa info
4. Committa + pusha
5. **NON tocca `annunci_visti.json` né `index.html`**
6. Termina la sessione

Esempio body INFRA HTML:
```html
<h2>🏠 [INFRA] Casa Milano — <motivo></h2>
<p>Sessione 2026-XX-XX abortita.</p>
<pre><stderr di fetch_apify.py></pre>
<p><a href="https://console.apify.com/actors/sPIR3lEdL9H69xrmi/runs">Apify console</a></p>
```

### Step 3 — Estrazione campi normalizzati

Lavora su entrambi gli array (`/tmp/apify_items.json` immobiliare + `/tmp/idealista_items.json` idealista) e normalizza ogni item nello schema comune dell'agente.

#### 3a. Immobiliare (`/tmp/apify_items.json`)

| Campo agente | Sorgente Apify |
|---|---|
| `id` | `f"immobiliare-{item.id}"` |
| `source` | `"immobiliare"` (costante) |
| `url` | `item.directLink` |
| `titolo` | `item.title` |
| `prezzo` | `item.price.value` (int, EUR) |
| `mq` | int del numero in `item.properties[0].surface` (es. `"98 m²"` → 98) |
| `locali` | `item.properties[0].rooms` |
| `bagni` | `item.properties[0].bathrooms` |
| `piano` | `item.properties[0].floor.abbreviation` (`"T"`/`"R"`/`"S"`/`"A"`/numero) |
| `ascensore` | `item.properties[0].elevator` (bool, default False se assente) |
| `zona` | `item.properties[0].location.microzone or .macrozone` |
| `indirizzo` | `item.properties[0].location.address` |
| `descrizione` | `item.properties[0].description` |
| `agenzia` | `item.advertiser.agency.displayName` |
| `foto_url` | `item.properties[0].multimedia.photos[0].urls.large` (URL CDN, NO download locale) |
| `lat` | `item.properties[0].location.latitude` (float, decimal degrees) |
| `lon` | `item.properties[0].location.longitude` (float, decimal degrees) |

#### 3b. Idealista (`/tmp/idealista_items.json`)

Lo schema di dz_omar non è completamente documentato all'apertura di questa sezione — al primo run **stampa `json.dumps(items[0], indent=2)[:1500]` nello stderr** per ispezionarlo, poi aggiorna questa tabella con i nomi esatti dei campi.

Mappa attesa (best-effort, verifica al primo run):

| Campo agente | Sorgente idealista (atteso) |
|---|---|
| `id` | `f"idealista-{item.propertyCode}"` (o `item.id` se diverso) |
| `source` | `"idealista"` (costante) |
| `url` | `item.url` |
| `titolo` | `item.title` o `f"{item.propertyType} {item.size}mq {item.municipality}"` |
| `prezzo` | `item.price` (int, EUR) |
| `mq` | `item.size` (int) |
| `locali` | `item.rooms` |
| `bagni` | `item.bathrooms` |
| `piano` | `item.floor` (string) |
| `ascensore` | `item.hasLift` (bool) |
| `zona` | `item.district` o `item.neighborhood` |
| `indirizzo` | `item.address` |
| `descrizione` | `item.description` |
| `agenzia` | `item.contactInfo.name` o `item.agency` |
| `foto_url` | primo URL in `item.multimedia.images` o `item.images` |

#### 3c. Cross-source dedupe

Dopo aver normalizzato tutti gli item delle due sorgenti, applica dedupe cross-source: se due item hanno **stesso indirizzo normalizzato** (lowercase, senza punteggiatura) **+ stesso prezzo** **+ stesso mq (tolleranza ±2)** → tieni solo l'item immobiliare (sorgente primaria), scarta quello idealista. Conta gli scartati nel report come "cross-source duplicates".

### Step 4 — Filtri (in ordine)

1. **Duplicati**: se `id` già in `annunci_visti.json` → skip silenzioso
2. **Validità minima**: se mancano `url`, `prezzo`, o `mq` (post-normalizzazione Step 3) → skip silenzioso
3. **REGOLA #0** (keyword gate + sede agenzia + freshness) → SKIP HARD se trigger
4. **Esclusioni assolute** da `criteri.md`:
   - `ascensore == False` → ESCLUDI
   - `piano in ("T","R","S")` senza "giardino privato" in descrizione → ESCLUDI
   - "asta giudiziaria" / "asta" nel titolo o descrizione → ESCLUDI
   - `mq < 80` o `mq > 120` → ESCLUDI
   - `prezzo > 450000` → ESCLUDI
   - zona in lista esclusione (Quarto Oggiaro, Lorenteggio, Corvetto, Gratosoglio, Stadera, Baggio) → ESCLUDI
   - fuori comune Milano (salvo Sesto S. Giovanni con MM ≤ 5 min) → ESCLUDI

Per gli esclusi: aggiungi a `annunci_visti.json` con `punteggio: 0`, `note: "ESCLUSO — <motivo>"`, `notificato: true`. NON appariranno in dashboard né in email.

### Step 5 — Scoring (per i superstiti)

Scala 0–10 come da `criteri.md`:
- Prezzo: ≤310k +3 | 310–380k +1.5 | 380–450k +1
- Zona: 1=top +3 | 2=ottima +2 | 3=buona +1 | 4=accettabile +0.5
- ≥90mq +1 | balcone/terrazzo +0.5 | 2+ bagni +0.5 | piano ≥3 +0.5 | box/posto auto +0.5 | classe energetica A/B +0.5

Riconoscimento zona: confronta `zona` (lowercased) con le liste di `criteri.md` — match esatto su `microzone`, poi fallback su `macrozone`, poi parole-chiave nell'indirizzo.

### Step 6 — Output DB

**Annunci nuovi con score ≥ 6 ⇒ candidati notifica.**

Aggiungi a `annunci_visti.json` con **TUTTI** i campi estratti allo Step 3, anche quelli usati solo per scoring/filtri — servono al chatbot della dashboard per rispondere a domande tipo "ce ne sono con terrazzo?" o "quali al 3° piano?":

```json
{
  "id": "immobiliare-127700336",
  "source": "immobiliare",
  "url": "https://www.immobiliare.it/annunci/127700336",
  "titolo": "...",
  "prezzo": 345000,
  "mq": 98,
  "locali": 3,
  "bagni": 2,
  "piano": "3",
  "ascensore": true,
  "zona": "Santa Giulia",
  "indirizzo": "Via Esempio 12",
  "agenzia": "Tecnocasa",
  "descrizione": "Trilocale luminoso con terrazzo...",
  "punteggio": 7.5,
  "foto_url": "https://pic.im-cdn.it/image/.../xxl-c.jpg",
  "data_vista": "2026-05-14",
  "notificato": true,
  "note": ""
}
```

**Campi obbligatori** (`null`/`""`/`false` ammessi se davvero assenti, MAI omessi): `locali`, `bagni`, `piano`, `ascensore`, `indirizzo`, `agenzia`, `descrizione`, `lat`, `lon`. Stessa regola per i record `SCARTATO`/`ESCLUSO` (anche se non compaiono in dashboard).

Il campo `source` ammette `"immobiliare"` o `"idealista"`. Per gli annunci legacy senza `source` (pre-2026-05-24), considera default `"immobiliare"`.

### Step 7 — Email digest (OBBLIGATORIA AD OGNI SESSIONE)

**REGOLA**: devi mandare **una** email Gmail in ogni sessione, sempre, senza eccezioni. La sessione termina solo dopo che `send_email` ha risposto con un `messageId`. Se l'invio fallisce, ritenta una volta. Se fallisce ancora, includi nel commit message `EMAIL FAILED` ma non saltare lo step.

Pseudocodice:
```
N = numero di NUOVI annunci con score ≥ 6 (NON include scartati/esclusi)
infra_failed = True se Step 2 ha mandato email INFRA e abortito

if infra_failed:
    # già mandata in Step 2d, NON rimandare
    skip
elif N == 0:
    subject = "🏠 Sessione completata — nessuna novità oggi"
    body = breve riepilogo HTML: N item Apify processati, K duplicati,
           S scartati REGOLA #0, E esclusi criteri, link dashboard
elif any(score ≥ 8):
    subject = f"🏠 [ALERT] {zona top} — €{prezzo} — {mq}mq"
    body = card HTML completa di tutti i nuovi score ≥ 6
else:  # 1+ nuovi 6-7.9
    subject = f"🏠 [DIGEST] Ricerca casa Milano — {data} — {N} annunci nuovi"
    body = card HTML di tutti i nuovi score ≥ 6

send_email(subject, body)  # OBBLIGATORIO se non infra_failed
```

Destinatari: `adrianolionetti@gmail.com`, `alessia.curtopelle@gmail.com` (entrambi sempre).

**⚠️ LINK DASHBOARD — VALORE FISSO**: il link "Apri la dashboard" nel body DEVE essere **esattamente** il valore della env var `$DASHBOARD_URL` (oggi `https://adrianolionetti-arch.github.io/casa-milano/`). MAI inventare URL alternativi tipo `casa-milano.vercel.app`, `casamilano.it`, `my-dashboard.netlify.app` o simili: la dashboard è ospitata SOLO su GitHub Pages a quell'URL. Se il body non contiene esattamente `$DASHBOARD_URL` riscrivilo prima di inviare.

**⚠️ HEADER OBBLIGATORIO**: ogni email (digest, alert, nessuna novità) DEVE iniziare con questo blocco pulsante centrato — incollalo letterale come primo elemento del body, prima del titolo:

```html
<div style="text-align:center;margin:0 0 24px 0;">
  <a href="$DASHBOARD_URL" style="display:inline-block;background:#0071e3;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:600;box-shadow:0 2px 6px rgba(0,113,227,0.25);">📊 Apri la dashboard →</a>
</div>
```

**Template "nessuna novità"** (caso N == 0, body completo, niente improvvisazioni):
```html
<div style="text-align:center;margin:0 0 24px 0;">
  <a href="$DASHBOARD_URL" style="display:inline-block;background:#0071e3;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:600;box-shadow:0 2px 6px rgba(0,113,227,0.25);">📊 Apri la dashboard →</a>
</div>
<h2>🏠 Casa Milano — sessione del <data></h2>
<p>Nessun annuncio nuovo con score ≥ 6 oggi.</p>
<ul>
  <li>Apify: <X> listing recuperati</li>
  <li>Duplicati riconosciuti: <K></li>
  <li>Scartati REGOLA #0 (keyword gate): <S></li>
  <li>Esclusi per criteri: <E></li>
</ul>
```

**Corpo HTML** per ogni annuncio nuovo score ≥ 6 (le card vanno DOPO l'header pulsante):
```html
<div style="margin:20px 0;padding:16px;border:1px solid #eee;border-radius:8px;">
  <img src="<foto_url>" style="width:100%;max-width:500px;border-radius:6px;margin-bottom:12px">
  <h3>⭐ <punteggio>/10 — <titolo></h3>
  <p><strong>💰 € <prezzo></strong> · <mq>mq · <zona> · piano <piano></p>
  <p><agenzia></p>
  <a href="<url>" style="background:#0071e3;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none">Vedi annuncio →</a>
</div>
```

**Invio Gmail**: usa lo script Python `scripts/send_email.py` (NON ricreare la funzione bash — produceva mojibake nel Subject con emoji/accenti). Lo script gestisce MIME UTF-8 e RFC 2047 correttamente.

```bash
# Scrivi il corpo HTML in un file temp
cat > /tmp/email_body.html << 'HTMLEOF'
<h2>🏠 Casa Milano — sessione del 2026-XX-XX</h2>
<p>...</p>
HTMLEOF

# Invia (env GMAIL_* devono essere settate dal workflow)
python3 scripts/send_email.py "🏠 Sessione completata — nessuna novità oggi" /tmp/email_body.html
```

Lo script stampa il `messageId` su stdout in caso di successo, errore su stderr con exit ≠ 0. Se l'esecuzione fallisce, ritenta una volta con la stessa subject/body. Se fallisce ancora → `EMAIL FAILED` nel commit message ma non saltare lo step.

**Non includere mai** annunci già in `annunci_visti.json` all'inizio della sessione.

### Step 8 — Dashboard (`index.html`)

**NON ricostruire la dashboard a mano**: usa lo script deterministico già nel repo. Filtra correttamente per URL immobiliare, ordina, gestisce stat. Lancia semplicemente:

```bash
python3 scripts/build_dashboard.py
```

Lo script legge `annunci_visti.json`, applica i filtri (score ≥ 6, ultimi 30gg, URL match `^https://www\.immobiliare\.it/annunci/\d+/?$`, escludi `SCARTATO`/`ESCLUSO`), e scrive `index.html`. Non interpretarne la logica — chiamalo e basta.

### Step 9 — Report

Salva `report/YYYY-MM-DD.md`:
- Numero item Apify
- Per ogni stato (NOTIFICATO / SCARTATO REGOLA #0 / ESCLUSO CRITERI / DUPLICATO): conteggio + lista ID
- Note operative ed errori (se non-INFRA-fail)

### Step 10 — Commit & push

```bash
git config user.email 'agent@casa-milano.local'
git config user.name 'Casa Milano Agent'
# GH Actions: GITHUB_TOKEN è già nelle credenziali della checkout action
git add -A
git commit -m "Sessione $(date +%Y-%m-%d) — <N> nuovi, <S> scartati" || echo 'Nessuna modifica'
git push origin main
```

## Note operative finali

- **Mai inventare dati**: se un campo manca nell'Apify item, scrivi `null` o `""`, non riempire con stime.
- **Concisione**: l'utente legge l'email in 30 secondi. Foto + score + prezzo + indirizzo + agenzia, in quest'ordine.
- **Cost awareness**: Apify ~$2/mese. GitHub Actions: free tier 2000 min/mese, una sessione consuma ~3 min → ~90 min/mese, ampiamente nel free.
