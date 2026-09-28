# Criteri di ricerca casa — Milano

> Modifica liberamente questo file per aggiornare i tuoi criteri.
> Le regole operative sono codificate in `scripts/process_session.py`:
> se cambi qualcosa qui, allinea le costanti lì.
>
> Ultima revisione: 2026-09-28 (metratura, budget, mappa, impianto di punteggio).

## Tipo di operazione
- **Acquisto** (non affitto)
- Immobili residenziali (appartamenti, trilocali, quadrilocali, loft)

## Budget
- **Massimo assoluto**: € 455.000
- Non esistono più "fasce ideali" di prezzo assoluto: un immobile non è
  valutato per quanto costa, ma per **quanto costa rispetto alla sua zona**
  (vedi *Come si calcola il punteggio*).

## Caratteristiche obbligatorie
- Superficie: **minimo 99 mq, massimo 120 mq**
- Camere da letto: almeno 2
- Bagni: almeno 1
- **Ascensore: obbligatorio** (escludi se assente)
- Stato: abitabile, ristrutturato o da ristrutturare — tutti accettati
- Distanza dalla MM: entro 10 minuti a piedi

## Caratteristiche preferibili (aumentano il punteggio)
- Balcone o terrazzino (+0,5)
- 2 bagni (+0,5)
- Piano 3° o superiore (+0,5)
- Box auto o posto auto incluso (+0,25)
- Classe energetica A o B (+0,25)

## Zone di Milano — preferenza, non esclusione

> L'utente abita in Via Pianell 56, Pratocentenaro (MM Turro, Zona 9).
> **Tutto il territorio del comune di Milano è in gioco**: la preferenza per
> il corridoio nord si esprime come punteggio, non come filtro.

### Zona 1 — Top (+3 punti)
Pratocentenaro, Turro, Precotto, Gorla, Crescenzago, Niguarda, Affori, Maggiolina, NoLo

### Zona 2 — Ottima (+2 punti)
Greco, Segnano, Bicocca, Isola, Loreto, Cenisio, Chinatown (Procaccini / Monumentale), Cimiano, Casoretto, Viale Monza, Viale Padova, Centrale, Adriano

### Zona 3 — Buona (+1 punto)
Lambrate, Udine, Città Studi, Bovisa, Dergano, Pasteur, Bruzzano, Zara, Maciachini, Porta Garibaldi, Buenos Aires, Navigli, Porta Romana, Porta Vittoria, Prati, Certosa

### Zona 4 — Resto di Milano (+0,5 punti)
Qualsiasi altro quartiere del comune. Sesto San Giovanni solo se max 5 min a piedi da MM.

### Zone penalizzate (−1 punto, non più escluse)
Quarto Oggiaro, Lorenteggio, Corvetto, Gratosoglio, Stadera, Baggio.
Un affare eccezionale in queste zone può ancora emergere, ma parte in salita.

## Zone di interesse speciale (difficili ma da monitorare)
- **Via Sant'Eusebio e limitrofe** (NoLo/Loreto) — notifica anche se sopra budget
- **Via Procaccini e limitrofe** (Cenisio/Chinatown) — notifica anche se sopra budget

## Esclusioni assolute
- Immobili senza ascensore
- Piano terra, rialzato o seminterrato (salvo giardino privato esclusivo)
- Immobili in aste giudiziarie
- Superficie < 99 mq o > 120 mq
- Prezzo > € 455.000
- Fuori dal comune di Milano (salvo Sesto San Giovanni con MM a max 5 min)
- Annunci più vecchi di 45 giorni o già venduti/ritirati (REGOLA #0)

## Come si calcola il punteggio (0-10)

Rivisto il 2026-09-28. Il vecchio impianto assegnava fino a 3 punti al prezzo
assoluto, pieni solo sotto € 310.000: alzando budget e metratura penalizzava
proprio gli immobili che ora cerchiamo, e in 74 giorni nessun annuncio ha mai
superato 7/10. Oggi il prezzo conta in termini **relativi**.

| Voce | Punti | Come |
|---|---|---|
| **Convenienza** | 0 – 3,5 | scarto del €/mq rispetto alla **mediana della sua microzona**: −25% o meglio → 3,5 · −15% → 2,75 · −5% → 2 · in linea → 1,25 · +15% → 0,5 · oltre → 0 |
| **Zona** | −1 – 3 | corridoio nord (vedi sopra), meno 1 nelle zone penalizzate |
| **Metratura** | 0 – 1,5 | cresce linearmente da 99 a 120 mq |
| **Preferibili** | 0 – 2 | balcone, 2° bagno, piano alto, box, classe A/B |

Le mediane €/mq sono calcolate a ogni run dallo storico di
`annunci_visti.json` (mediana per microzona, minimo 5 osservazioni; fallback
sulla mediana cittadina). Il metro di giudizio si aggiorna da sé man mano che
il database cresce: oggi copre 97 microzone su 2.285 annunci, mediana
cittadina ≈ 3.667 €/mq.

## Soglie di punteggio per notifica
- **Alert immediato** (email in evidenza): punteggio ≥ 7,0
- **Digest giornaliero**: punteggio ≥ 5,5
- **Ignorato silenziosamente**: punteggio < 5,5
- **Eccezione**: Via Sant'Eusebio e Via Procaccini notificate sempre

Sui 74 giorni fra il 16/07 e il 28/09 queste soglie avrebbero prodotto
**4 notifiche (1,6 al mese)**, di cui 1 alert. Con i criteri e il punteggio
precedenti le notifiche erano state 5 in 74 giorni, ma quasi tutte su
immobili sotto i 99 mq.
