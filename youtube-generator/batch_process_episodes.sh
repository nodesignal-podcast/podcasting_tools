#!/bin/bash
set -e
set -o pipefail

# --- Konfiguration ---
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
GENERATOR_SCRIPT="$SCRIPT_DIR/generate_podcast_video_api.sh"

# --- Hilfsfunktionen ---
show_usage() {
    echo "Batch Podcast Video Generator"
    echo ""
    echo "Verwendung:"
    echo "  $0 <episode_numbers>"
    echo ""
    echo "Beispiele:"
    echo "  $0 1-10          # Episoden 1 bis 10 verarbeiten"
    echo "  $0 1,3,5,7       # Einzelne Episoden verarbeiten"
    echo "  $0 1-5,10,15-20  # Kombination aus Bereichen und Einzelnummern"
    echo "  $0 1              # Nur eine Episode verarbeiten"
    echo ""
    echo "Optionen:"
    echo "  --dry-run         # Nur anzeigen, was verarbeitet würde (ohne Ausführung)"
    echo "  --continue        # Bei Fehlern mit der nächsten Episode fortfahren"
    echo "  --help            # Diese Hilfe anzeigen"
    echo ""
}

parse_episode_range() {
    local input="$1"
    local episodes=()
    
    # Teile durch Kommas
    IFS=',' read -ra parts <<< "$input"
    
    for part in "${parts[@]}"; do
        part=$(echo "$part" | tr -d ' ')  # Leerzeichen entfernen
        
        if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            # Bereich: 1-10
            local start=${BASH_REMATCH[1]}
            local end=${BASH_REMATCH[2]}
            
            if [ "$start" -le "$end" ]; then
                for ((i=start; i<=end; i++)); do
                    episodes+=("$i")
                done
            else
                echo "Error: Ungültiger Bereich $part (Start muss <= Ende sein)" >&2
                return 1
            fi
            
        elif [[ "$part" =~ ^[0-9]+$ ]]; then
            # Einzelne Nummer: 5
            episodes+=("$part")
            
        else
            echo "Error: Ungültiges Format: $part" >&2
            return 1
        fi
    done
    
    # Duplikate entfernen und sortieren
    printf '%s\n' "${episodes[@]}" | sort -nu
}

# --- Hauptlogik ---
main() {
    local dry_run=false
    local continue_on_error=false
    local episode_input=""
    
    # Parameter verarbeiten
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                dry_run=true
                shift
                ;;
            --continue)
                continue_on_error=true
                shift
                ;;
            --help|-h)
                show_usage
                exit 0
                ;;
            -*)
                echo "Error: Unbekannte Option $1" >&2
                show_usage
                exit 1
                ;;
            *)
                if [ -z "$episode_input" ]; then
                    episode_input="$1"
                else
                    echo "Error: Mehrere Episode-Eingaben nicht erlaubt" >&2
                    show_usage
                    exit 1
                fi
                shift
                ;;
        esac
    done
    
    # Prüfe ob Episode-Eingabe vorhanden ist
    if [ -z "$episode_input" ]; then
        echo "Error: Keine Episodennummern angegeben" >&2
        show_usage
        exit 1
    fi
    
    # Prüfe ob Generator-Skript existiert
    if [ ! -f "$GENERATOR_SCRIPT" ]; then
        echo "Error: Generator-Skript nicht gefunden: $GENERATOR_SCRIPT" >&2
        exit 1
    fi
    
    # Prüfe ob Generator-Skript ausführbar ist
    if [ ! -x "$GENERATOR_SCRIPT" ]; then
        echo "Error: Generator-Skript ist nicht ausführbar: $GENERATOR_SCRIPT" >&2
        echo "Führe 'chmod +x $GENERATOR_SCRIPT' aus" >&2
        exit 1
    fi
    
    # Episodennummern parsen
    echo "Parse Episodennummern: $episode_input"
    local episodes
    episodes=$(parse_episode_range "$episode_input")
    
    if [ $? -ne 0 ]; then
        echo "Error: Fehler beim Parsen der Episodennummern" >&2
        exit 1
    fi
    
    # Anzahl der zu verarbeitenden Episoden
    local total_episodes=$(echo "$episodes" | wc -l)
    local current=0
    local successful=0
    local failed=0
    
    echo "Gefundene Episoden:"
    echo "$episodes" | nl
    echo ""
    echo "Gesamt: $total_episodes Episoden"
    echo ""
    
    if [ "$dry_run" = true ]; then
        echo "DRY-RUN: Würde folgende Episoden verarbeiten:"
        while read -r episode; do
            echo "  Episode $episode: $GENERATOR_SCRIPT $episode"
        done <<< "$episodes"
        exit 0
    fi
    
    # Bestätigung vom Benutzer
    read -p "Möchtest du fortfahren? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Abgebrochen."
        exit 0
    fi
    
    echo ""
    echo "Starte Batch-Verarbeitung..."
    echo "=================================="
    
    # Verarbeite jede Episode
    echo "DEBUG: Starte Schleife mit Episoden:"
    echo "$episodes" | nl
    echo "DEBUG: Ende der Episoden-Liste"
    
    while read -r episode; do
        current=$((current + 1))
        echo ""
        echo "[$current/$total_episodes] Verarbeite Episode $episode..."
        echo "----------------------------------------"
        
        if "$GENERATOR_SCRIPT" "$episode"; then
            echo "✅ Episode $episode erfolgreich verarbeitet!"
            successful=$((successful + 1))
        else
            echo "❌ Fehler bei Episode $episode!"
            failed=$((failed + 1))
            
            if [ "$continue_on_error" = false ]; then
                echo ""
                echo "Batch-Verarbeitung wegen Fehler abgebrochen."
                echo "Verwende --continue um bei Fehlern fortzufahren."
                exit 1
            fi
        fi
        
        echo "----------------------------------------"
    done <<< "$episodes"
    
    # Zusammenfassung
    echo ""
    echo "=================================="
    echo "Batch-Verarbeitung abgeschlossen!"
    echo "Erfolgreich: $successful"
    echo "Fehlgeschlagen: $failed"
    echo "Gesamt: $total_episodes"
    
    if [ $failed -gt 0 ]; then
        exit 1
    fi
}

# Skript ausführen
main "$@"
