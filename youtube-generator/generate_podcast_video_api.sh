#!/bin/bash
set -e
set -o pipefail

# --- Konfiguration ---
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

IMAGE="$SCRIPT_DIR/cover-youtube.mp4"
OUTPUT="$SCRIPT_DIR/output.mp4"
TEMP_AUDIO_FILE="$SCRIPT_DIR/temp_audio.mp3"

# Neue API-basierte Konfiguration
PODHOME_API_KEY="feKybWxmPYdwanZKOgmFklTgxUBLbr"  # Hier deinen API-Key eintragen
PODHOME_API_BASE_URL="https://serve.podhome.fm"
PODHOME_API_ENDPOINT="/api/episodes"  # Alle Episoden abrufen (ohne Status-Filter)

if ! command -v ffmpeg >/dev/null 2>&1
then
    echo "ffmpeg could not be found"
    echo "Please run sudo apt install ffmpeg under Linux"
    echo "Please run sudo brew install ffmpeg under MacOS"
    exit 1
fi

# --- Logik für die Stapelverarbeitung ---
DESIRED_EPISODE_NR=${1:-1}
echo "--- Starte Verarbeitung für Episode mit der Nummer: $DESIRED_EPISODE_NR ---"

# --- Hauptlogik ---
echo "Lade Episoden über die podhome.fm API..."
API_RESPONSE=$(curl -sL \
  --header "X-API-KEY: $PODHOME_API_KEY" \
  "$PODHOME_API_BASE_URL$PODHOME_API_ENDPOINT")

if [ -z "$API_RESPONSE" ]; then
  echo "Error: Konnte API-Antwort nicht laden." >&2
  exit 1
fi

# Prüfe ob jq verfügbar ist, sonst verwende Python
if command -v jq &> /dev/null; then
  echo "Verwende jq für JSON-Parsing..."
  
  # Extrahiere Daten mit jq - suche nach der gewünschten Episodennummer
  AUDIO_URL=$(echo "$API_RESPONSE" | jq -r ".[] | select(.episode_nr == $DESIRED_EPISODE_NR) | .enclosure_url // empty")
  TITLE=$(echo "$API_RESPONSE" | jq -r ".[] | select(.episode_nr == $DESIRED_EPISODE_NR) | .title // empty")
  RAW_DESCRIPTION=$(echo "$API_RESPONSE" | jq -r ".[] | select(.episode_nr == $DESIRED_EPISODE_NR) | .description // empty")
  EPISODE_NR=$(echo "$API_RESPONSE" | jq -r ".[] | select(.episode_nr == $DESIRED_EPISODE_NR) | .episode_nr // empty")
  
else
  echo "jq nicht verfügbar, verwende Python für JSON-Parsing..."
  
  # Erstelle temporäres Python-Skript für JSON-Parsing
  cat > /tmp/parse_api_response.py << 'EOF'
import json
import sys

try:
    data = json.loads(sys.argv[1])
    desired_episode_nr = int(sys.argv[2])
    
    # Suche nach der gewünschten Episodennummer
    episode = None
    for item in data:
        if item.get('episode_nr') == desired_episode_nr:
            episode = item
            break
    
    if episode is None:
        print(f"Error: Episode mit der Nummer {desired_episode_nr} nicht gefunden", file=sys.stderr)
        sys.exit(1)
    
    print(f"TITLE:{episode.get('title', '')}")
    print(f"DESCRIPTION:{episode.get('description', '')}")
    print(f"AUDIO_URL:{episode.get('enclosure_url', '')}")
    print(f"EPISODE_NR:{episode.get('episode_nr', '')}")
    
except Exception as e:
    print(f"Error beim JSON-Parsing: {e}", file=sys.stderr)
    sys.exit(1)
EOF

  # Verwende Python für JSON-Parsing
  PARSED_DATA=$(python3 /tmp/parse_api_response.py "$API_RESPONSE" "$DESIRED_EPISODE_NR")
  
  # Extrahiere die einzelnen Werte
  TITLE=$(echo "$PARSED_DATA" | grep "^TITLE:" | cut -d: -f2-)
  RAW_DESCRIPTION=$(echo "$PARSED_DATA" | grep "^DESCRIPTION:" | cut -d: -f2-)
  AUDIO_URL=$(echo "$PARSED_DATA" | grep "^AUDIO_URL:" | cut -d: -f2-)
  EPISODE_NR=$(echo "$PARSED_DATA" | grep "^EPISODE_NR:" | cut -d: -f2-)
  
  # Räume temporäres Python-Skript auf
  rm -f /tmp/parse_api_response.py
fi

# Zuverlässige Fehlerprüfung nach der Extraktion
if [ -z "$AUDIO_URL" ]; then 
  echo "Error: Keine Audio-URL für Episode $DESIRED_EPISODE_NR gefunden." >&2
  echo "API Response: $API_RESPONSE" >&2
  exit 1
fi
if [ -z "$TITLE" ]; then 
  echo "Error: Keinen Titel für Episode $DESIRED_EPISODE_NR gefunden." >&2
  exit 1
fi
if [ -z "$RAW_DESCRIPTION" ]; then 
  echo "Error: Keine Beschreibung für Episode $DESIRED_EPISODE_NR gefunden." >&2
  exit 1
fi

echo "DEBUG: Gefundene Episode: $EPISODE_NR"
echo "DEBUG: TITLE: $TITLE"
echo "DEBUG: AUDIO_URL: $AUDIO_URL"
echo "DEBUG: RAW_DESCRIPTION length: ${#RAW_DESCRIPTION}"
echo "DEBUG: RAW_DESCRIPTION preview: ${RAW_DESCRIPTION:0:200}..."

echo "Wandle Podcast-Beschreibung (HTML) in formatierten Text um..."
source "$SCRIPT_DIR/venv/bin/activate"

# Write the raw description to a temporary file to avoid command line issues
echo "$RAW_DESCRIPTION" > /tmp/raw_description.html

# Use the separate Python script to clean the description
CLEANED_DESCRIPTION=$(python3 "$SCRIPT_DIR/clean_description.py" /tmp/raw_description.html)

echo "DEBUG: CLEANED_DESCRIPTION length: ${#CLEANED_DESCRIPTION}"
echo "DEBUG: CLEANED_DESCRIPTION preview: ${CLEANED_DESCRIPTION:0:200}..."

# Disclaimer in einer separaten Variable definieren
DISCLAIMER="Jeden Samstag sendet Nodesignal eine neue Folge mit Gesprächen und Interviews über Bitcoin hinaus in die Welt. 

Reines Signal, keine Störgeräusche, keine Werbung.
Focus on the signal, not on the noise!

www.nodesignal.space"

# Beschreibung sicher zusammensetzen
DESCRIPTION="$CLEANED_DESCRIPTION

$DISCLAIMER"

echo "DEBUG: FINAL DESCRIPTION length: ${#DESCRIPTION}"
echo "DEBUG: FINAL DESCRIPTION preview: ${DESCRIPTION:0:300}..."

echo "$DESCRIPTION" > /tmp/yt_description.txt

echo "Lade Audio-Datei herunter..."
curl -sL -o "$TEMP_AUDIO_FILE" "$AUDIO_URL"
if [ ! -f "$TEMP_AUDIO_FILE" ]; then
  echo "Error: Audio-Download fehlgeschlagen." >&2
  exit 1
fi

echo "Generiere Video mit ffmpeg..."
ffmpeg -y -stream_loop -1 -i "$IMAGE" -i "$TEMP_AUDIO_FILE" \
 -filter_complex "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[bg]; \
  [1:a]showwaves=s=1920x200:mode=line:colors=#000000@0.8[wave]; \
  [bg][wave]overlay=0:main_h-overlay_h:x=0:y=main_h-overlay_h[v]" \
  -map "[v]" -map 1:a \
  -c:v libx264 -c:a aac -shortest -aspect 16:9 "$OUTPUT" > /dev/null 2>&1

echo "Lade Video zu YouTube hoch..."
python "$SCRIPT_DIR/upload_to_youtube.py" "$OUTPUT" "$TITLE" "/tmp/yt_description.txt"
deactivate

echo "Räume auf..."
rm -f "$TEMP_AUDIO_FILE" "$OUTPUT"

echo "--- Verarbeitung für Episode $DESIRED_EPISODE_NR erfolgreich beendet! ---"
