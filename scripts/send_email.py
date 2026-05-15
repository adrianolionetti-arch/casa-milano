#!/usr/bin/env python3
"""Invia un'email HTML via Gmail API usando MIME corretto (UTF-8 + RFC 2047).

Sostituisce l'helper bash send_email() che produceva mojibake nel Subject.

Uso:
    python3 scripts/send_email.py SUBJECT BODY_HTML_PATH
    python3 scripts/send_email.py "🏠 Sessione completata" /tmp/body.html

Env richiesti: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN, GMAIL_FROM.
Destinatari: adrianolionetti@gmail.com, alessia.curtopelle@gmail.com.
Stampa il messageId Gmail su stdout in caso di successo; exit code 0.
Stampa l'errore su stderr; exit code != 0.
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

TO = "adrianolionetti@gmail.com, alessia.curtopelle@gmail.com"


def main(subject: str, body_html_path: str) -> int:
    for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_FROM"):
        if not os.environ.get(var):
            print(f"ERROR: env {var} mancante", file=sys.stderr)
            return 2

    with open(body_html_path, encoding="utf-8") as f:
        body_html = f.read()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_FROM"]
    msg["To"] = TO
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")

    try:
        token_req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=urllib.parse.urlencode({
                "client_id": os.environ["GMAIL_CLIENT_ID"],
                "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
                "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
                "grant_type": "refresh_token",
            }).encode(),
        )
        token_resp = json.loads(urllib.request.urlopen(token_req, timeout=15).read())
        access_token = token_resp["access_token"]
    except Exception as e:
        print(f"ERROR: OAuth refresh failed: {e}", file=sys.stderr)
        return 3

    try:
        send_req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=json.dumps({"raw": raw_b64}).encode(),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        send_resp = json.loads(urllib.request.urlopen(send_req, timeout=15).read())
    except Exception as e:
        print(f"ERROR: Gmail send failed: {e}", file=sys.stderr)
        return 4

    print(send_resp.get("id", "(no messageId)"))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: send_email.py SUBJECT BODY_HTML_PATH", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
