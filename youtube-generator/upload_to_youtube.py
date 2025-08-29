import os
import pickle
import sys
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError  # KORRIGIERT: Tippfehler behoben
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# --- Konfiguration ---
# NEU: Robuste Pfade, die immer funktionieren, egal von wo das Skript gestartet wird
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(SCRIPT_DIR, "client_secrets.json")
TOKEN_PICKLE_FILE = os.path.join(SCRIPT_DIR, "token.pickle")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

def get_authenticated_service():
    """Stellt die Authentifizierung sicher und gibt ein nutzbares API-Service-Objekt zurück."""
    credentials = None
    if os.path.exists(TOKEN_PICKLE_FILE):
        with open(TOKEN_PICKLE_FILE, "rb") as token:
            credentials = pickle.load(token)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            credentials = flow.run_local_server(port=0)
        with open(TOKEN_PICKLE_FILE, "wb") as token:
            pickle.dump(credentials, token)
            
    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

def upload_video(video_file, title, description_file):
    """Lädt ein Video zu YouTube hoch und behandelt mögliche Fehler."""
    try:
        # Read description from file to preserve formatting
        with open(description_file, 'r', encoding='utf-8') as f:
            description = f.read()
        
        youtube = get_authenticated_service()
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": ["Nodesignal", "Podcast", "Bitcoin", "Deutsch"],
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "private"
            }
        }
        media_body = MediaFileUpload(video_file, chunksize=-1, resumable=True)
        
        print(f"Lade '{video_file}' hoch...")
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media_body
        )
        response = request.execute()
        print(f"Video erfolgreich hochgeladen! Link: https://youtu.be/{response['id']}")

    except FileNotFoundError:
        print(f"Fehler: Die Videodatei '{video_file}' wurde nicht gefunden.", file=sys.stderr)
        sys.exit(1)
    except HttpError as e:
        print(f"Ein API-Fehler ist aufgetreten: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # NEU: Strikte Prüfung der Argumente, um fehlerhafte Uploads zu verhindern
    if len(sys.argv) != 4:
        print("Fehler: Falsche Anzahl an Argumenten.", file=sys.stderr)
        print(f"Verwendung: python {sys.argv[0]} <videodatei> <titel> <beschreibungsdatei>", file=sys.stderr)
        sys.exit(1)
    
    video_file_path = sys.argv[1]
    video_title = sys.argv[2]
    description_file_path = sys.argv[3]
    
    print("--- Starte YouTube Upload ---")
    print(f"Video: {video_file_path}")
    print(f"Titel: '{video_title}'")
    
    upload_video(video_file_path, video_title, description_file_path)
    
    print("--- YouTube Upload erfolgreich beendet ---")
