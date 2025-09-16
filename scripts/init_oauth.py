from __future__ import annotations
import json, pathlib, datetime as dt, webbrowser
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
SECRETS_DIR = pathlib.Path("secrets")
CREDS = SECRETS_DIR / "credentials.json"
TOKEN = SECRETS_DIR / "token.json"

def main():
    assert CREDS.exists(), "Missing secrets/credentials.json"
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
    # Opens a local server and browser for consent (Installed App)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print("Token saved to secrets/token.json")
    print("Issued at:", dt.datetime.now().isoformat())

if __name__ == "__main__":
    main()
