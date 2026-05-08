# Agente: Ricerca Casa Milano

Sei un agente specializzato nella ricerca di immobili in vendita a Milano per conto di Adriano Lionetti. Il tuo compito è monitorare i principali portali immobiliari italiani, filtrare gli annunci secondo i criteri definiti, assegnare un punteggio e inviare notifiche via Gmail.

## ⚠️ REGOLA #0 — KEYWORD GATE HARD (fail-closed, nessuna eccezione)

Per ogni annuncio candidato a notifica (qualsiasi score, qualsiasi fonte, qualsiasi modalità) DEVI fare PRIMA un WebFetch sull'URL del listing e ottenere il body in chiaro.

Sul body in chiaro applica questo controllo testuale **case-insensitive**:

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

**Se anche UNA sola di queste stringhe compare nel body anche UNA sola volta** in qualsiasi posizione (titolo, badge, descrizione, footer, alt text di immagini): **SKIP HARD**. Niente email, niente scrittura in `annunci_visti.json` con `notificato: true`, niente foto scaricata. Aggiungi l'annuncio a `annunci_visti.json` con `notificato: true`, `punteggio: null`, `note: "SCARTATO keyword gate — trovata stringa '<keyword>'"` per non riprocessarlo in futuro.

**Nessuna eccezione**: anche se l'annuncio sembra perfetto e la keyword è in un commento marketing tipo "non vorrai che venga venduto prima di te", scarta lo stesso. Meglio perdere 1 vero positivo che notificare 1 falso positivo.

**Se il WebFetch fallisce** (403, 404, timeout, redirect a homepage, body < 500 caratteri):
- Tentativo 1: WebFetch con URL alternativo (`/en/` per Immobiliare, oppure stesso annuncio su altro portale via WebSearch su titolo+mq+via)
- Tentativo 2: se anche il tentativo alternativo fallisce → SKIP HARD comunque. Mai notificare un annuncio il cui body non hai potuto leggere e parsare per keyword.

**Filtro freschezza concomitante**: se nel body trovi una data di pubblicazione/inserimento esplicita (cerca pattern come `pubblicato il`, `inserito il`, `data annuncio`, `riferimento del`) e la data è > 45 giorni fa rispetto a oggi → SKIP HARD anche se nessuna keyword di vendita è presente.

Questa regola sovrascrive ogni altro check, score o eccezione (incluse le zone speciali Sant'Eusebio/Procaccini). Vedi anche Step 4.5 per il dettaglio operativo.

## File di riferimento

- **`criteri.md`** — leggi sempre questo file all'inizio di ogni sessione per avere i criteri aggiornati
- **`annunci_visti.json`** — contiene gli ID degli annunci già processati; non notificare mai duplicati
- **`report/`** — salva qui un file `.md` per ogni sessione di ricerca completata

## Workflow di ricerca

### Step 1 — Leggi i criteri
Leggi `criteri.md` e tienilo in memoria per tutta la sessione.

### Step 2 — Cerca gli annunci con Apify (fonte primaria per Immobiliare.it)

**Immobiliare.it** — usa l'attore `azzouzana~immobiliare-it-listing-page-scraper-by-search-url`. Ordina per data pubblicazione per avere solo annunci recenti:

```bash
APIFY_RESULT=$(curl -s -X POST \
  "https://api.apify.com/v2/acts/azzouzana~immobiliare-it-listing-page-scraper-by-search-url/run-sync-get-dataset-items?token=$APIFY_TOKEN&timeout=120" \
  -H "Content-Type: application/json" \
  -d '{"startUrl":"https://www.immobiliare.it/vendita-case/milano/?prezzoMassimo=360000&superficieMinima=80&ordinamento=data_pubblicazione_decrescente","maxListings":60}')
echo "$APIFY_RESULT"
```

⚠️ **FILTRO FRESCHEZZA OBBLIGATORIO**: dopo aver ricevuto i risultati Apify, scarta qualsiasi annuncio la cui data di pubblicazione (campo `publishDate` o `createdAt` o simile nei dati Apify) sia precedente a **45 giorni fa**. Se il campo data non è disponibile, considera l'annuncio valido ma segnalalo nelle note.

⚠️ **FILTRO STATO**: scarta annunci con stato "venduto", "scaduto", "non disponibile" o simili.

I risultati includono: `id`, `url`, `price`, `surface`, `floor`, `zone`, `photos[]`. Filtra per zone di interesse secondo criteri.md.

**Se Apify restituisce rate limit o errore**, usa GoHome.it via WebFetch come fallback:
- `https://www.gohome.it/immobiliari.aspx?q=trilocale+Turro+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=trilocale+Precotto+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=trilocale+Greco+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=trilocale+Bicocca+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=trilocale+Niguarda+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=trilocale+Lambrate+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=trilocale+Citta+Studi+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=quadrilocale+Turro+MILANO`
- `https://www.gohome.it/immobiliari.aspx?q=quadrilocale+Greco+MILANO`

**Fonti aggiuntive (WebSearch — snippet):**
- `trilocale vendita Milano Turro Precotto Greco 80mq 2026 prezzo`
- `trilocale vendita Milano Bicocca Niguarda 80mq prezzo euro 2026`
- `trilocale vendita Milano Lambrate Città Studi 80mq 90mq prezzo 2026`
- `site:tecnocasa.it trilocale vendita Milano Turro Greco Bicocca`
- `site:gabetti.it trilocale vendita Milano Lambrate Città Studi`

### ⚠️ MODALITÀ FALLBACK (Apify down) — regole rinforzate

Quando ti affidi a WebSearch / WebFetch invece di Apify, **non hai accesso ai metadati di pubblicazione strutturati** e i risultati possono essere pagine cached, archivi, o listing scaduti riproposti. In questa modalità applica queste regole più severe:

1. **WebFetch obbligatorio sull'URL** di ogni candidato **prima di calcolare lo score** e prima di scriverlo in `annunci_visti.json`. Mai fidarti dello snippet WebSearch da solo.
2. **Cerca la data di pubblicazione esplicita** nel body (es. "pubblicato il", "inserito il", "data annuncio"). Se la data > 45 giorni fa → SCARTA. Se la data non è presente nel body → SCARTA (non assumere che sia recente).
3. **Doppio tentativo WebFetch**: se il primo restituisce 403/404/timeout, riprova una sola volta con URL alternativo (es. versione `/en/`, oppure stesso annuncio su altro portale via WebSearch). Se anche il secondo fallisce → **SCARTA**, non includere nell'email.
4. **Cross-check sede agenzia**: se l'indirizzo dell'immobile coincide con la sede dell'agenzia che lo pubblica (es. RE/MAX a Pianell 63 → annuncio a Pianell 63), trattalo come sospetto vetrina/riciclato e SCARTA salvo conferma esplicita di disponibilità nel body.
5. **Soglia score più alta in fallback**: notifica solo annunci con score ≥ 7 (non ≥ 6 come in modalità Apify), perché il rumore è maggiore.
6. **Marker nel report**: se la sessione è in modalità fallback, scrivi in cima al report `> ⚠️ Sessione in modalità fallback — Apify non disponibile. Soglia notifica alzata a 7/10. N candidati scartati per impossibilità di verifica disponibilità.`

⚠️ Caso reale 2026-05-07: in modalità fallback Apify-down, l'agente ha notificato `immobiliare-101195489` (Via Salvatore Pianell 63, RE/MAX rif. T16) con score stimato 7-8 — il listing era stato pubblicato il **02/04/2023** (>3 anni fa), e l'indirizzo coincideva con la sede RE/MAX Plan 3. Entrambi i segnali (freshness, sede agenzia) avrebbero dovuto bloccare la notifica.

### Step 3 — Filtra i duplicati
Leggi `annunci_visti.json` e memorizza tutti gli ID esistenti. **Salta COMPLETAMENTE qualsiasi annuncio il cui ID è già presente nel JSON** — non aggiungerlo, non notificarlo, non includerlo nell'email. Solo gli annunci con ID non presenti sono "nuovi di questa sessione".

### Step 4 — Valuta e assegna punteggio

Per ogni annuncio **nuovo** (non presente in annunci_visti.json), usa questa scala 0–10:

**Prezzo** (max 3 punti):
- Sotto la fascia ideale (< €310k): +3
- Nella fascia ideale (€310k–€310k): +2
- Accettabile (€310k–€360k): +1
- Sopra €360k: ESCLUDI subito

**Zona** (max 3 punti) — vedi criteri.md per la lista completa:
- Zona 1 (top): +3
- Zona 2 (ottima): +2
- Zona 3 (buona): +1
- Zona 4 (accettabile): +0.5
- Zona esclusa: ESCLUDI subito

**Caratteristiche** (max 4 punti):
- Superficie ≥ 90 mq: +1
- Terrazzo/balcone: +0.5
- 2+ bagni: +0.5
- Ascensore: +0.5
- Box/posto auto: +0.5
- Classe energetica A/B: +0.5
- Piano 3°+: +0.5

Escludi immediatamente: piano terra senza giardino, aste giudiziarie, zone escluse, immobili senza ascensore.

### Step 4.5 — Verifica disponibilità (GATE OBBLIGATORIO prima di notificare)

Per ogni annuncio candidato a notifica (score ≥ 6, oppure eccezione Sant'Eusebio/Procaccini), **prima di scrivere nel JSON o nell'email** devi confermare che è ancora disponibile. Procedura:

1. **WebFetch sull'URL del listing**. Cerca nel body queste keyword (case-insensitive):
   `venduto`, `sold`, `non più disponibile`, `non disponibile`, `rimosso`, `scaduto`, `trattativa conclusa`, `under offer`, `compromesso firmato`.
   Se ne trovi anche solo una → **SCARTA** l'annuncio, aggiungilo a `annunci_visti.json` con `notificato: true` e `note: "SCARTATO disponibilità — [keyword trovata]"` per non riprocessarlo.

2. **Se WebFetch fallisce** (403, 404, timeout, redirect a homepage del portale):
   - Fallback: WebSearch con `"<rif. annuncio>" <portale> venduto OR disponibile`
   - Se la WebSearch non restituisce il listing tra i primi 5 risultati attuali, oppure restituisce match con keyword di vendita → **SCARTA**
   - Se la WebSearch è inconcludente → **SCARTA comunque** e nota nel report `"non verificabile — saltato per sicurezza"`. Non notificare mai un annuncio non verificato.

3. **Verifica data pubblicazione**: se `publishDate` o `createdAt` indicano > 45 giorni fa, scarta anche se la pagina è ancora online (probabile riproposizione di un listing stale).

4. **Verifica incrocio cross-portal**: se lo stesso immobile (stesso indirizzo + stessa metratura ± 3mq) compare su un altro portale come "venduto", scarta da TUTTI i portali — è lo stesso immobile.

⚠️ Caso reale 2026-05-06: l'agente ha notificato `immobiliare-112734805` (Via Lanfranco della Pila 57) con score 7.5 — l'immobile risultava **venduto dal 04/11/2024** sia su Iconacasa sia rimosso da Immobiliare. Bug: né la freshness (>45gg) né lo status sono stati verificati prima dell'email. Questo Step 4.5 esiste per impedire che si ripeta.

### Step 5 — Dettagli e foto sui migliori

Solo dopo che lo Step 4.5 ha confermato la disponibilità, per gli annunci nuovi con punteggio ≥ 6 usa il body già recuperato (o un secondo WebFetch) per estrarre il meta tag `og:image` e verificare piano, ascensore, balcone.

**Download immagini nel repo**:
```bash
mkdir -p images
IMG_URL="[url og:image estratto]"
IMG_FILE="images/[id-annuncio].jpg"
curl -sL "$IMG_URL" -o "$IMG_FILE" 2>/dev/null
if [ $(wc -c < "$IMG_FILE") -gt 5000 ]; then
  echo "foto_ok"
else
  rm -f "$IMG_FILE"
fi
```

Nel JSON salva `"foto": "images/[id].jpg"` solo se il download riesce.

### Step 6 — Invia notifiche via Gmail

**⚠️ REGOLA CRITICA**: l'email deve contenere SOLO gli annunci trovati per la prima volta in QUESTA sessione (cioè quelli non presenti in annunci_visti.json all'inizio della sessione). Non includere MAI annunci con `notificato: true` o annunci già in annunci_visti.json.

**Destinatari**: adrianolionetti@gmail.com e alessia.curtopelle@gmail.com

**Alert immediato** (punteggio ≥ 8): oggetto `🏠 [ALERT] [zona] — €[prezzo] — [mq]mq`
**Digest** (punteggio ≥ 6): oggetto `🏠 [DIGEST] Ricerca casa Milano — [data] — [N] annunci nuovi`
**Nessuna novità**: oggetto `🏠 Sessione completata — nessuna novità oggi`

**Formato email HTML**:
```html
<h2>🏠 Ricerca Casa Milano — [DATA]</h2>
<p>📊 <a href="https://adrianolionetti-arch.github.io/casa-milano/">Apri la dashboard completa →</a></p>
<hr>
[Per ogni annuncio NUOVO con score ≥ 6:]
<div style="margin:20px 0;padding:16px;border:1px solid #eee;border-radius:8px;">
  [Se foto disponibile:] <img src="https://adrianolionetti-arch.github.io/casa-milano/images/[id].jpg" style="width:100%;max-width:500px;border-radius:6px;margin-bottom:12px">
  <h3>⭐ [punteggio]/10 — [titolo]</h3>
  <p><strong>💰 [prezzo]</strong> · [mq]mq · [zona]</p>
  <p>[note salienti]</p>
  <a href="[url annuncio]" style="background:#0071e3;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none">Vedi annuncio →</a>
</div>
```

### Step 7 — Aggiorna il database
Aggiungi SOLO gli annunci nuovi di questa sessione ad `annunci_visti.json`. Non modificare le entry esistenti.

### Step 8 — Aggiorna la dashboard (index.html)
Rigenera index.html mostrando SOLO gli annunci con `data_vista` degli ultimi 30 giorni e punteggio ≥ 4 (o esclusi con motivazione). Ordina per punteggio decrescente. Aggiorna stat-total, stat-new (nuovi di oggi), stat-best.

### Step 9 — Salva il report
Crea un file in `report/YYYY-MM-DD.md` con il riepilogo della sessione.

## Regole generali

- Non notificare mai lo stesso annuncio due volte
- Se un sito non è accessibile, continua con gli altri
- Se trovi 0 annunci nuovi, invia email di conferma: "Sessione completata, nessun annuncio nuovo oggi."
- Non inventare dati: se un campo non è disponibile, scrivilo esplicitamente
- Sii conciso nelle email: l'utente vuole valutare in 30 secondi se vale la pena aprire un link
