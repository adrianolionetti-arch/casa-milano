# Bookmarklet "❤️ Casa Milano"

Aggiungi annunci ai preferiti con 2 click dal tuo browser, da qualsiasi portale.

## Installazione (una sola volta, ~2 min)

1. Apri `scripts/bookmarklet.min.txt` e **copia tutto il contenuto** (è una linea che inizia con `javascript:`)
2. Nel browser apri la barra dei segnalibri (Cmd+Shift+B su Mac)
3. Click destro sulla barra → "Aggiungi pagina…" o "Nuovo segnalibro…"
4. Compila:
   - **Nome**: `❤️ Casa Milano` (o quello che preferisci)
   - **URL**: incolla il contenuto del file
5. Salva

Ora il bookmark è disponibile nella barra. Si può anche metterlo nella cartella "Preferiti" del browser.

## Uso

1. Navighi su qualsiasi pagina annuncio (Immobiliare, Tempocasa, Gabetti, RE/MAX, Idealista, Casa.it, ecc.)
2. Click sul bookmark `❤️ Casa Milano`
3. Si apre una nuova tab su GitHub con la **issue prefillata** (URL, titolo, prezzo, mq estratti automaticamente dove possibile)
4. Verifica i campi (se qualcosa è vuoto puoi riempirlo a mano) e click **"Submit new issue"**
5. Entro ~30 sec l'annuncio appare nella sezione "❤️ Preferiti" della [dashboard](https://adrianolionetti-arch.github.io/casa-milano/), con la issue auto-chiusa

## Cosa estrae automaticamente

- **Immobiliare.it**: titolo (da og:title), prezzo, mq
- **Tempocasa.it**: prezzo, mq (titolo da `document.title`)
- **Idealista.it**: prezzo, mq
- **Casa.it**: prezzo, mq
- **Altri portali** (Gabetti, RE/MAX, Toscano, ecc.): fallback su regex generica del testo della pagina, può funzionare o no

Per URL Immobiliare con dati mancanti, il workflow tenta arricchimento via Apify (recupera anche foto, zona, agenzia).

## Limiti

- Funziona solo se sei loggato a GitHub nel browser (gestione issue richiede auth)
- Se il sito ha un layout particolarmente personalizzato, l'estrazione può sbagliare — verifica sempre i campi prima di Submit
- Per portali esoterici (sito agenzia singola con CMS proprietario) potresti dover compilare a mano

## Aggiornare il bookmarklet

Se evolviamo l'estrazione per nuovi portali, rigenero `bookmarklet.min.txt` e dovrai sostituirlo nel bookmark del browser.
