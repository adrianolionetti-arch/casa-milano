// ❤️ Casa Milano — bookmarklet
//
// Quando lo clicchi su una pagina di annuncio (immobiliare/tempocasa/idealista/ecc.),
// estrae i dati visibili nel DOM e apre una GitHub issue prefillata.
// Tu clicchi "Submit new issue" su GitHub → workflow processa → preferito in dashboard.
//
// Per installarlo: copia tutto il contenuto del file bookmarklet.min.js,
// crea un nuovo bookmark nel browser, e incolla quel testo come URL.
// Trascina il bookmark sulla barra dei segnalibri.

(function() {
  const url = location.href;
  const host = location.host.replace(/^www\./, '');
  let titolo = document.title.replace(/\s+\|.*$/, '').trim();
  let prezzo = '';
  let mq = '';
  let zona = '';
  let indirizzo = '';

  // ---- Immobiliare.it ----
  if (host.includes('immobiliare.it')) {
    const priceEl = document.querySelector('[class*="re-overview__price"], [class*="price"]');
    const mPrice = (priceEl ? priceEl.textContent : '').match(/€\s*([\d.,]+)/);
    if (mPrice) prezzo = mPrice[1].replace(/[.,]/g, '');
    const surfaceEl = document.querySelector('[class*="re-detail__surface"], [class*="surface"]');
    const mSurf = (surfaceEl ? surfaceEl.textContent : '').match(/(\d+)\s*m/);
    if (mSurf) mq = mSurf[1];
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) titolo = ogTitle.content.replace(/\s+-\s*Immobiliare\.it.*$/, '').trim();
  }
  // ---- Tempocasa.it ----
  else if (host.includes('tempocasa')) {
    const priceEl = document.querySelector('[class*="price"], [data-prezzo]');
    const mPrice = (priceEl ? priceEl.textContent : '').match(/€\s*([\d.,]+)/);
    if (mPrice) prezzo = mPrice[1].replace(/[.,]/g, '');
    const surfTxt = document.body.innerText.match(/(\d+)\s*m[q²]/);
    if (surfTxt) mq = surfTxt[1];
  }
  // ---- Idealista.it ----
  else if (host.includes('idealista')) {
    const priceEl = document.querySelector('[class*="price"], .info-data-price');
    const mPrice = (priceEl ? priceEl.textContent : '').match(/([\d.]+)\s*€/);
    if (mPrice) prezzo = mPrice[1].replace(/[.,]/g, '');
    const surf = document.body.innerText.match(/(\d+)\s*m²/);
    if (surf) mq = surf[1];
  }
  // ---- Casa.it ----
  else if (host.includes('casa.it')) {
    const priceMatch = document.body.innerText.match(/€\s*([\d.,]+)/);
    if (priceMatch) prezzo = priceMatch[1].replace(/[.,]/g, '');
    const surfMatch = document.body.innerText.match(/(\d+)\s*m[q²]/);
    if (surfMatch) mq = surfMatch[1];
  }
  // ---- Fallback generic (Gabetti, RE/MAX, Toscano, ecc.) ----
  else {
    const text = document.body.innerText;
    const priceMatch = text.match(/€\s*([\d.,]+)/);
    if (priceMatch) prezzo = priceMatch[1].replace(/[.,]/g, '');
    const surfMatch = text.match(/(\d+)\s*m[q²]/);
    if (surfMatch) mq = surfMatch[1];
  }

  // Costruisci issue body
  const body = [
    'URL: ' + url,
    'Titolo: ' + titolo,
    'Sito: ' + host,
    'Prezzo: ' + prezzo,
    'Mq: ' + mq,
    'Zona: ' + zona,
    'Indirizzo: ' + indirizzo,
    'Note: ',
    '',
    '<!-- Verifica i campi e clicca "Submit new issue". Il workflow aggiungerà l\'annuncio ai preferiti entro ~30 sec. -->'
  ].join('\n');

  const issueUrl = 'https://github.com/adrianolionetti-arch/casa-milano/issues/new?'
    + 'labels=preferito'
    + '&title=' + encodeURIComponent('preferito: ' + titolo.slice(0, 50))
    + '&body=' + encodeURIComponent(body);

  window.open(issueUrl, '_blank');
})();
