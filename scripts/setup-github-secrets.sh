#!/usr/bin/env bash
# Setup degli GitHub Secrets per il workflow Casa Milano.
# Eseguilo una sola volta dopo aver autenticato `gh` come `adrianolionetti-arch`.
#
# Tutti i valori devono essere passati come env vars — niente è hardcoded in
# questo file, così il file può vivere nel repo senza leak di credenziali.
#
# Prerequisiti:
#   1. gh CLI installato:   brew install gh
#   2. Autenticazione:      gh auth login   (utente: adrianolionetti-arch)
#   3. Tutte le env qui sotto devono essere settate prima di lanciarlo.
#
# Esempio (esportare le var nel tuo shell, poi lanciare):
#   export ANTHROPIC_API_KEY="sk-ant-..."        # da https://console.anthropic.com/settings/keys
#   export APIFY_TOKEN="apify_api_..."           # da https://console.apify.com/account#/integrations
#   export GMAIL_CLIENT_ID="...apps.googleusercontent.com"
#   export GMAIL_CLIENT_SECRET="GOCSPX-..."
#   export GMAIL_REFRESH_TOKEN="1//..."
#   export GMAIL_FROM="adriano.lionetti@nextdifferent.com"
#   bash scripts/setup-github-secrets.sh

set -euo pipefail

REPO="adrianolionetti-arch/casa-milano"

# Verifica auth + accesso
gh auth status >/dev/null 2>&1 || { echo "ERR: esegui prima 'gh auth login'"; exit 1; }
gh repo view "$REPO" >/dev/null 2>&1 || {
  echo "ERR: utente gh non ha accesso a $REPO. Autenticati come adrianolionetti-arch.";
  exit 1;
}

# Tutte le env devono essere definite
required=(ANTHROPIC_API_KEY APIFY_TOKEN GMAIL_CLIENT_ID GMAIL_CLIENT_SECRET GMAIL_REFRESH_TOKEN GMAIL_FROM)
missing=()
for v in "${required[@]}"; do
  if [[ -z "${!v:-}" ]]; then missing+=("$v"); fi
done
if (( ${#missing[@]} > 0 )); then
  echo "ERR: env mancanti: ${missing[*]}"
  echo "Definisci tutte le var (vedi commento in cima al file) e rilancia."
  exit 1
fi

echo "Imposto i 6 secrets su $REPO..."
for v in "${required[@]}"; do
  printf '%s ' "$v"
  gh secret set "$v" --repo "$REPO" --body "${!v}" >/dev/null
  echo "ok"
done

echo ""
echo "Verifica:"
gh secret list --repo "$REPO"

echo ""
echo "Prossimo step:"
echo "  gh workflow run casa-milano.yml --repo $REPO"
echo "Oppure dalla UI: https://github.com/$REPO/actions/workflows/casa-milano.yml"
