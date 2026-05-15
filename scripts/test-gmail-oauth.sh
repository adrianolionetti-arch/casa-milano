#!/usr/bin/env bash
# Testa che GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET + GMAIL_REFRESH_TOKEN siano
# coerenti, scambiando il refresh token con un access token al volo. Niente
# secrets sono scritti su disco né mandati a host diversi da Google.
#
# Uso:
#   export GMAIL_CLIENT_ID="...apps.googleusercontent.com"
#   export GMAIL_CLIENT_SECRET="GOCSPX-..."
#   export GMAIL_REFRESH_TOKEN="1//..."
#   bash scripts/test-gmail-oauth.sh

set -euo pipefail

required=(GMAIL_CLIENT_ID GMAIL_CLIENT_SECRET GMAIL_REFRESH_TOKEN)
for v in "${required[@]}"; do
  if [[ -z "${!v:-}" ]]; then echo "ERR: env $v non settata"; exit 1; fi
done

# Quick sanity: client_id formato canonico
if [[ ! "$GMAIL_CLIENT_ID" =~ \.apps\.googleusercontent\.com$ ]]; then
  echo "WARN: GMAIL_CLIENT_ID non termina con .apps.googleusercontent.com — probabile valore sbagliato"
fi
if [[ ! "$GMAIL_CLIENT_SECRET" =~ ^GOCSPX- ]]; then
  echo "WARN: GMAIL_CLIENT_SECRET non inizia con GOCSPX- — probabile valore sbagliato"
fi
if [[ ! "$GMAIL_REFRESH_TOKEN" =~ ^1// ]]; then
  echo "WARN: GMAIL_REFRESH_TOKEN non inizia con 1// — probabile valore sbagliato (i refresh token Google iniziano con 1//)"
fi

# Lunghezza visibile (no leak del valore)
echo "Lunghezze (debug, niente segreti in chiaro):"
echo "  GMAIL_CLIENT_ID: ${#GMAIL_CLIENT_ID} char"
echo "  GMAIL_CLIENT_SECRET: ${#GMAIL_CLIENT_SECRET} char"
echo "  GMAIL_REFRESH_TOKEN: ${#GMAIL_REFRESH_TOKEN} char"
echo ""

echo "Scambio refresh_token → access_token su oauth2.googleapis.com..."
RESPONSE=$(curl -sS -X POST https://oauth2.googleapis.com/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "client_id=$GMAIL_CLIENT_ID" \
  --data-urlencode "client_secret=$GMAIL_CLIENT_SECRET" \
  --data-urlencode "refresh_token=$GMAIL_REFRESH_TOKEN" \
  --data-urlencode "grant_type=refresh_token" \
  -w "\nHTTP_CODE=%{http_code}\n")

HTTP_CODE=$(echo "$RESPONSE" | grep '^HTTP_CODE=' | cut -d= -f2)
BODY=$(echo "$RESPONSE" | grep -v '^HTTP_CODE=')

echo "HTTP $HTTP_CODE"
# Maschera l'access_token nel body se presente
echo "$BODY" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    if 'access_token' in d:
        d['access_token'] = '<redacted, len ' + str(len(d['access_token'])) + '>'
    print(json.dumps(d, indent=2))
except Exception as e:
    print('(body non JSON):')
    print(sys.stdin.read() if False else '<raw output above>')
"

echo ""
if [[ "$HTTP_CODE" == "200" ]]; then
  echo "✅ OK — le credenziali sono valide e coerenti. Il problema NON è nei valori locali."
  echo "   Verifica che siano stati incollati identici nei GitHub Secrets (no spazi finali, no a-capo)."
else
  echo "❌ FAIL — Google ha rifiutato. Significato comune degli errori:"
  echo "   - unauthorized_client: GMAIL_CLIENT_ID errato o non corrisponde al secret"
  echo "   - invalid_client:      GMAIL_CLIENT_SECRET errato"
  echo "   - invalid_grant:       GMAIL_REFRESH_TOKEN scaduto/revocato o issued per altro client"
fi
