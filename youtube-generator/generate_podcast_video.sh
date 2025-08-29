#!/bin/bash
set -e
set -o pipefail

# --- Konfiguration ---
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

IMAGE="$SCRIPT_DIR/cover-youtube.mp4"
OUTPUT="$SCRIPT_DIR/output.mp4"
TEMP_AUDIO_FILE="$SCRIPT_DIR/temp_audio.mp3"

RSS_URL="https://serve.podhome.fm/rss/e8df0b13-47de-544a-99b7-ec7cbd960a16"

# --- Logik für die Stapelverarbeitung ---
EPISODE_NUMBER=${1:-1}
echo "--- Starte Verarbeitung für Folge Nummer: $EPISODE_NUMBER ---"

# --- Hauptlogik ---
echo "Lade RSS-Feed..."
RSS_CONTENT=$(curl -sL "$RSS_URL")
if [ -z "$RSS_CONTENT" ]; then
  echo "Error: Konnte RSS-Feed nicht laden." >&2
  exit 1
fi

echo "Extrahiere Daten aus dem RSS-Feed für Folge $EPISODE_NUMBER..."
AUDIO_URL=$(echo "$RSS_CONTENT" | xmlstarlet sel -t -v "//item[$EPISODE_NUMBER]/enclosure/@url" -n 2>/dev/null || echo "")
TITLE=$(echo "$RSS_CONTENT" | xmlstarlet sel -t -v "//item[$EPISODE_NUMBER]/title" -n 2>/dev/null || echo "")
RAW_DESCRIPTION=$(echo "$RSS_CONTENT" | xmlstarlet sel -t -v "//item[$EPISODE_NUMBER]/description" -n 2>/dev/null || echo "")

# Zuverlässige Fehlerprüfung nach der Extraktion
if [ -z "$AUDIO_URL" ]; then echo "Error: Keine Audio-URL für Folge $EPISODE_NUMBER gefunden." >&2; exit 1; fi
if [ -z "$TITLE" ]; then echo "Error: Keinen Titel für Folge $EPISODE_NUMBER gefunden." >&2; exit 1; fi
if [ -z "$RAW_DESCRIPTION" ]; then echo "Error: Keine Beschreibung für Folge $EPISODE_NUMBER gefunden." >&2; exit 1; fi

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

echo "--- Verarbeitung für Folge $EPISODE_NUMBER erfolgreich beendet! ---"
