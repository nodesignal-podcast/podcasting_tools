#!/bin/bash

# =============================================================================
# Geyser Fund Goal Monitor
# =============================================================================
#Import Config
source ./geyser_monitor_config.conf
# Functions
print_message() {
    local color=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${color}[$timestamp] $message${NC}"
    echo "[$timestamp] $message" >> "$LOG_FILE"
}

debug_log() {
    local message=$1
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] DEBUG: $message" >> "$DEBUG_LOG"
    if [ "$DEBUG_MODE" = true ]; then
        print_message "$PURPLE" "DEBUG: $message"
    fi
}

setup_directories() {
    mkdir -p "$TEMP_DIR"
    print_message "$BLUE" "Monitor-Verzeichnis erstellt: $TEMP_DIR"
    debug_log "Temp directory created at: $TEMP_DIR"
}

# Timeout-Funktion
run_with_timeout() {
    local timeout_duration=$1
    local command_to_run=("${@:2}")
    
    debug_log "Running with timeout: ${timeout_duration}s - ${command_to_run[*]}"
    
    # Starte Kommando im Hintergrund
    "${command_to_run[@]}" &
    local command_pid=$!
    
    # Warte mit Timeout
    local count=0
    while [ $count -lt "$timeout_duration" ]; do
        if ! kill -0 "$command_pid" 2>/dev/null; then
            # Prozess ist beendet
            wait "$command_pid"
            return $?
        fi
        sleep 1
        count=$((count + 1))
    done
    
    # Timeout erreicht - töte Prozess
    debug_log "Timeout reached, killing process $command_pid"
    kill -TERM "$command_pid" 2>/dev/null
    sleep 2
    
    # Falls noch nicht tot, force kill
    if kill -0 "$command_pid" 2>/dev/null; then
        kill -KILL "$command_pid" 2>/dev/null
    fi
    
    wait "$command_pid" 2>/dev/null
    return 124  # Timeout exit code
}

check_dependencies() {
    local missing_deps=()
    
    debug_log "Checking dependencies..."
    
    if ! command -v curl >/dev/null 2>&1; then
        missing_deps+=("curl")
    fi
    
    if [ "$USE_JAVASCRIPT" = true ]; then
        debug_log "Checking Node.js dependencies..."
        
        if ! command -v node >/dev/null 2>&1; then
            missing_deps+=("node.js")
            debug_log "Node.js not found"
        else
            local node_version=$(node --version)
            debug_log "Node.js version: $node_version"
            
            # Prüfe Node.js Version (mindestens v14)
            local node_major=$(echo "$node_version" | sed 's/v//' | cut -d. -f1)
            if [ "$node_major" -lt 14 ]; then
                print_message "$YELLOW" "⚠️  Node.js Version $node_version ist alt. Empfohlen: v16+"
            fi
        fi
        
        if ! command -v npm >/dev/null 2>&1; then
            missing_deps+=("npm")
            debug_log "npm not found"
        fi
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        print_message "$RED" "❌ Fehlende Abhängigkeiten: ${missing_deps[*]}"
        print_message "$YELLOW" "Installation:"
        for dep in "${missing_deps[@]}"; do
            case $dep in
                "curl")
                    echo "  - curl ist normalerweise bereits auf macOS installiert"
                    ;;
                "node.js"|"npm")
                    echo "macOS:  - brew install node"
                    echo "Linux:  - sudo apt install npm"
                    echo "  - oder von https://nodejs.org/ herunterladen"
                    ;;
            esac
        done
        return 1
    fi
    
    return 0
}

install_puppeteer() {
    print_message "$BLUE" "Installiere Puppeteer lokal..."
    debug_log "Starting Puppeteer installation in $TEMP_DIR"
    
    cd "$TEMP_DIR" || return 1
    
    # Erstelle package.json mit spezifischen Konfigurationen
    cat > package.json << 'EOF'
{
  "name": "geyser-monitor",
  "version": "1.0.0",
  "description": "Geyser Fund Monitor with JavaScript support",
  "dependencies": {
    "puppeteer": "^21.0.0"
  },
  "puppeteer": {
    "skipChromiumDownload": false
  }
}
EOF
    
    # Setze npm Konfiguration für bessere Stabilität
    npm config set fetch-timeout 600000
    npm config set fetch-retry-mintimeout 10000
    npm config set fetch-retry-maxtimeout 60000
    
    print_message "$YELLOW" "Installiere Puppeteer... (Das kann einige Minuten dauern)"
    
    if npm install --silent 2>"$DEBUG_LOG.npm" 1>/dev/null; then
        print_message "$GREEN" "✅ Puppeteer erfolgreich installiert"
        debug_log "Puppeteer installation successful"
        return 0
    else
        print_message "$RED" "❌ Fehler beim Installieren von Puppeteer"
        debug_log "Puppeteer installation failed"
        cat "$DEBUG_LOG.npm" >> "$DEBUG_LOG"
        return 1
    fi
}

create_js_scraper() {
    debug_log "Creating robust JavaScript scraper"
    
    cat > "$TEMP_DIR/scraper.js" << 'EOF'
const fs = require('fs');
const path = require('path');

async function scrapePage(url, outputFile, maxRetries = 3) {
    let browser;
    const puppeteer = require('puppeteer');
    
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            console.log(`Attempt ${attempt}/${maxRetries}: Starting browser...`);
            
            browser = await puppeteer.launch({
                headless: 'new',
                timeout: 60000,
                protocolTimeout: 60000,
                args: [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-extensions',
                    '--disable-plugins',
                    '--disable-images',
                    '--no-first-run',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-background-timer-throttling',
                    '--disable-renderer-backgrounding',
                    '--disable-backgrounding-occluded-windows',
                    '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ]
            });
            
            console.log('Browser started, creating page...');
            const page = await browser.newPage();
            
            // Erweiterte Konfiguration für bessere Stabilität
            await page.setDefaultNavigationTimeout(60000);
            await page.setDefaultTimeout(30000);
            await page.setViewport({ width: 1920, height: 1080 });
            
            // Request Interception für bessere Performance
            await page.setRequestInterception(true);
            page.on('request', (request) => {
                const resourceType = request.resourceType();
                if (['image', 'stylesheet', 'font', 'media'].includes(resourceType)) {
                    request.abort();
                } else {
                    request.continue();
                }
            });
            
            // Error handling für Page Events
            page.on('error', err => {
                console.log('Page error:', err.message);
            });
            
            page.on('pageerror', err => {
                console.log('Page script error:', err.message);
            });
            
            console.log(`Navigating to: ${url}`);
            
            // Robuste Navigation
            let navigationSuccess = false;
            const strategies = [
                { waitUntil: 'domcontentloaded', timeout: 30000 },
                { waitUntil: 'load', timeout: 45000 },
                { waitUntil: 'networkidle2', timeout: 60000 }
            ];
            
            for (const strategy of strategies) {
                try {
                    await page.goto(url, strategy);
                    navigationSuccess = true;
                    console.log(`Navigation successful with strategy: ${strategy.waitUntil}`);
                    break;
                } catch (navError) {
                    console.log(`Navigation failed with ${strategy.waitUntil}: ${navError.message}`);
                    if (strategy === strategies[strategies.length - 1]) {
                        throw navError;
                    }
                }
            }
            
            if (!navigationSuccess) {
                throw new Error('All navigation strategies failed');
            }
            
            // Warte auf Content
            console.log('Waiting for content to load...');
            
            try {
                await Promise.race([
                    page.waitForSelector('body', { timeout: 10000 }),
                    page.waitForTimeout(8000)
                ]);
                
                // Zusätzliche Wartezeit für JavaScript-Rendering
                await page.waitForTimeout(5000);
                
            } catch (waitError) {
                console.log('Wait warning:', waitError.message);
            }
            
            console.log('Extracting content...');
            
            // Robuste Content-Extraktion
            const content = await page.evaluate(() => {
                try {
                    // Entferne störende Elemente
                    const unwantedSelectors = ['script', 'style', 'noscript', 'iframe', 'embed', 'object'];
                    unwantedSelectors.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => el.remove());
                    });
                    
                    // Sammle alle relevanten Texte
                    const relevantTexts = new Set();
                    
                    // Strategie 1: Suche nach spezifischen Klassen und IDs
                    const goalSelectors = [
                        '[class*="goal" i]', '[id*="goal" i]',
                        '[class*="progress" i]', '[id*="progress" i]',
                        '[class*="fund" i]', '[id*="fund" i]',
                        '[class*="target" i]', '[id*="target" i]',
                        '[class*="amount" i]', '[id*="amount" i]',
                        '[class*="raised" i]', '[id*="raised" i]',
                        '[class*="percent" i]', '[id*="percent" i]',
                        '[class*="campaign" i]', '[id*="campaign" i]',
                        '[data-testid*="goal" i]',
                        '[data-testid*="progress" i]'
                    ];
                    
                    goalSelectors.forEach(selector => {
                        try {
                            const elements = document.querySelectorAll(selector);
                            elements.forEach(el => {
                                if (el && el.textContent) {
                                    const text = el.textContent.trim();
                                    if (text && text.length > 0 && text.length < 500) {
                                        relevantTexts.add(text);
                                    }
                                }
                            });
                        } catch (e) {
                            console.log('Selector error:', selector, e.message);
                        }
                    });
                    
                    // Strategie 2: Text-basierte Suche
                    const bodyText = document.body.textContent || document.body.innerText || '';
                    const lines = bodyText.split(/[\n\r]+/)
                        .map(line => line.trim())
                        .filter(line => line.length > 0 && line.length < 200)
                        .filter(line => /goal|target|raised|funded|%|bitcoin|btc|sats|progress|funding|campaign/i.test(line));
                    
                    lines.forEach(line => relevantTexts.add(line));
                    
                    // Strategie 3: Numerische Werte finden
                    const numericMatches = bodyText.match(/\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|btc|sats|bitcoin|\$|€|USD)/gi);
                    if (numericMatches) {
                        numericMatches.forEach(match => relevantTexts.add(match.trim()));
                    }
                    
                    // Konvertiere zu Array und sortiere
                    const finalContent = Array.from(relevantTexts)
                        .filter(text => text.length > 2)
                        .sort()
                        .join('\n');
                    
                    console.log('Content extraction completed, found', relevantTexts.size, 'unique elements');
                    return finalContent || 'No relevant content found';
                    
                } catch (evalError) {
                    console.error('Content extraction error:', evalError.message);
                    return `Error during content extraction: ${evalError.message}`;
                }
            });
            
            console.log('Content extracted, length:', content.length);
            
            // Schreibe Content in Datei
            fs.writeFileSync(outputFile, content);
            console.log('Content written to:', outputFile);
            
            console.log('JavaScript rendering completed successfully');
            
            // Erfolgreich - Browser schließen und zurückkehren
            await browser.close();
            return;
            
        } catch (error) {
            console.error(`Attempt ${attempt}/${maxRetries} failed:`, error.message);
            
            if (browser) {
                try {
                    await browser.close();
                } catch (closeError) {
                    console.error('Error closing browser:', closeError.message);
                }
                browser = null;
            }
            
            if (attempt === maxRetries) {
                // Letzter Versuch - schreibe Fehler-Info
                const errorInfo = `Error after ${maxRetries} attempts: ${error.message}\nStack: ${error.stack}\nTime: ${new Date().toISOString()}`;
                fs.writeFileSync(outputFile + '.error', errorInfo);
                console.error('All attempts failed. Final error:', error.message);
                process.exit(1);
            } else {
                // Warte vor dem nächsten Versuch
                console.log(`Waiting 10 seconds before retry...`);
                await new Promise(resolve => setTimeout(resolve, 10000));
            }
        }
    }
}

// Graceful shutdown
process.on('SIGINT', async () => {
    console.log('Received SIGINT, shutting down gracefully...');
    process.exit(0);
});

process.on('SIGTERM', async () => {
    console.log('Received SIGTERM, shutting down gracefully...');
    process.exit(0);
});

// Get command line arguments
const url = process.argv[2];
const outputFile = process.argv[3];
const maxRetries = parseInt(process.argv[4]) || 3;

if (!url || !outputFile) {
    console.error('Usage: node scraper.js <url> <output_file> [max_retries]');
    process.exit(1);
}

console.log(`Starting scraper with URL: ${url}, Output: ${outputFile}, Max retries: ${maxRetries}`);
scrapePage(url, outputFile, maxRetries);
EOF

    debug_log "Robust JavaScript scraper created at $TEMP_DIR/scraper.js"
}

test_network_connectivity() {
    debug_log "Testing network connectivity to $URL"
    
    # Teste basic connectivity
    if ! ping -c 1 -W 5000 geyser.fund >/dev/null 2>&1; then
        print_message "$YELLOW" "⚠️  Ping zu geyser.fund fehlgeschlagen"
        debug_log "Ping test failed"
        return 1
    fi
    
    # Teste HTTP connectivity
    local http_status
    http_status=$(curl -s -o /dev/null -w "%{http_code}" -m 10 "$URL")
    debug_log "HTTP status code: $http_status"
    
    if [ "$http_status" = "200" ]; then
        debug_log "HTTP connectivity test successful"
        return 0
    else
        print_message "$YELLOW" "⚠️  HTTP Test fehlgeschlagen (Status: $http_status)"
        return 1
    fi
}

fetch_js_content() {
    local output_file=$1
    local attempt=1
    
    print_message "$PURPLE" "🔧 Lade JavaScript-gerenderte Inhalte..."
    debug_log "Starting JavaScript content fetch to $output_file"
    
    # Teste Netzwerk-Konnektivität zuerst
    if ! test_network_connectivity; then
        print_message "$YELLOW" "⚠️  Netzwerk-Probleme erkannt, versuche trotzdem..."
    fi
    
    cd "$TEMP_DIR" || {
        debug_log "Failed to change directory to $TEMP_DIR"
        return 1
    }
    
    # Prüfe ob Puppeteer verfügbar ist
    if [ ! -d "node_modules/puppeteer" ]; then
        print_message "$YELLOW" "Puppeteer nicht gefunden. Installiere..."
        if ! install_puppeteer; then
            print_message "$RED" "❌ Puppeteer Installation fehlgeschlagen"
            return 1
        fi
    fi
    
    # Erstelle JavaScript scraper falls noch nicht vorhanden
    if [ ! -f "scraper.js" ]; then
        create_js_scraper
    fi
    
    # Retry-Schleife für robustes Scraping
    while [ $attempt -le $MAX_RETRIES ]; do
        debug_log "JavaScript fetch attempt $attempt/$MAX_RETRIES"
        print_message "$PURPLE" "🔄 Versuch $attempt/$MAX_RETRIES..."
        
        # Erstelle temporäre Dateien für Output-Sammlung
        local temp_output="$TEMP_DIR/scraper_output_$$.tmp"
        local scraper_exit_code
        
        # Führe Scraper mit macOS-kompatiblem Timeout aus
        debug_log "Starting scraper with timeout ${SCRAPER_TIMEOUT}s"
        
        # Sammle Output in temporärer Datei
        run_with_timeout "$SCRAPER_TIMEOUT" node scraper.js "$URL" "$output_file" $MAX_RETRIES > "$temp_output" 2>&1
        scraper_exit_code=$?
        
        # Zeige Output und logge es
        if [ -f "$temp_output" ]; then
            while IFS= read -r line; do
                debug_log "Scraper: $line"
                if [ "$DEBUG_MODE" = true ]; then
                    print_message "$PURPLE" "  $line"
                fi
            done < "$temp_output"
            rm -f "$temp_output"
        fi
        
        debug_log "Scraper exit code: $scraper_exit_code"
        
        # Prüfe auf Timeout
        if [ $scraper_exit_code -eq 124 ]; then
            print_message "$YELLOW" "⏰ Scraper-Timeout nach ${SCRAPER_TIMEOUT} Sekunden"
            debug_log "Scraper timed out"
        fi
        
        # Prüfe auf Fehler-Datei
        if [ -f "$output_file.error" ]; then
            local error_content=$(cat "$output_file.error")
            print_message "$RED" "❌ JavaScript Scraper Fehler: $error_content"
            debug_log "Error file content: $error_content"
            rm -f "$output_file.error"
        fi
        
        # Prüfe Erfolg
        if [ $scraper_exit_code -eq 0 ] && [ -f "$output_file" ] && [ -s "$output_file" ]; then
            local file_size=$(wc -c < "$output_file")
            debug_log "JavaScript content successfully fetched, file size: $file_size bytes"
            print_message "$GREEN" "✅ JavaScript-Inhalte erfolgreich geladen ($file_size Bytes)"
            
            # Zeige erste Zeilen für Debugging
            if [ "$DEBUG_MODE" = true ]; then
                print_message "$PURPLE" "Erste Zeilen der JavaScript-Inhalte:"
                head -3 "$output_file" | while read -r line; do
                    print_message "$PURPLE" "  $line"
                done
            fi
            
            return 0
        fi
        
        # Fehler aufgetreten - retry falls noch Versuche übrig
        if [ $attempt -lt $MAX_RETRIES ]; then
            print_message "$YELLOW" "⏳ Warte ${RETRY_DELAY} Sekunden vor nächstem Versuch..."
            sleep $RETRY_DELAY
        fi
        
        attempt=$((attempt + 1))
    done
    
    print_message "$RED" "❌ JavaScript Scraper fehlgeschlagen nach $MAX_RETRIES Versuchen"
    return 1
}

# Fallback-Modus ohne JavaScript
fallback_mode() {
    print_message "$YELLOW" "🔄 Wechsle in Fallback-Modus (nur HTML)"
    USE_JAVASCRIPT=false
    print_message "$BLUE" "JavaScript-Unterstützung temporär deaktiviert"
}

fetch_content() {
    local output_file=$1
    local attempt=1
    
    debug_log "Fetching HTML content to $output_file"
    
    while [ $attempt -le $MAX_RETRIES ]; do
        debug_log "HTML fetch attempt $attempt/$MAX_RETRIES"
        
        curl -s -L \
             --retry 2 \
             --retry-delay 5 \
             --connect-timeout 15 \
             --max-time 45 \
             -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
             -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
             -H "Accept-Language: en-US,en;q=0.5" \
             -H "Accept-Encoding: gzip, deflate" \
             "$URL" > "$output_file"
        
        local curl_exit_code=$?
        debug_log "curl exit code: $curl_exit_code"
        
        if [ $curl_exit_code -eq 0 ] && [ -f "$output_file" ] && [ -s "$output_file" ]; then
            local file_size=$(wc -c < "$output_file")
            debug_log "HTML file size: $file_size bytes"
            return 0
        fi
        
        if [ $attempt -lt $MAX_RETRIES ]; then
            print_message "$YELLOW" "⏳ HTML-Download fehlgeschlagen, warte ${RETRY_DELAY} Sekunden..."
            sleep $RETRY_DELAY
        fi
        
        attempt=$((attempt + 1))
    done
    
    return 1
}

extract_goals_info() {
    local file=$1
    
    if [ ! -f "$file" ]; then
        debug_log "extract_goals_info: file $file does not exist"
        return 1
    fi
    
    # Erweiterte Pattern für Goal-Erkennung
    grep -E -i "(goal|target|raised|funded|bitcoin|btc|sats|progress|funding|campaign)" "$file" | \
    sed 's/[[:space:]]\+/ /g' | \
    sed 's/^[[:space:]]*//' | \
    sed -z "s/,//g" | \
    sed 's/ sats//g' | \
    sed 's/[0-9]*[%]//g' | \
    #sed 's/[0-9]*[,][0-9]*//g' | \
    sed "s/$FINAL_GOAL//g" | \
    sed -z "s/\n//g" | \
    sort | \
    uniq | \
    head -50  # Begrenze auf 50 Zeilen um Output zu kontrollieren
}

compare_content() {
    local file_type=$1
    local current_file=$2
    local previous_file=$3
    local label=$4
    
    debug_log "Comparing $label content: current=$current_file, previous=$previous_file"
    
    if [ ! -f "$previous_file" ]; then
        print_message "$YELLOW" "Erstmaliger $label Check - keine Vergleichsdatei vorhanden"
        debug_log "$label: No previous file for comparison"
        return 1
    fi
    
    if [ ! -f "$current_file" ]; then
        print_message "$RED" "❌ Aktuelle $label Datei nicht gefunden: $current_file"
        debug_log "$label: Current file not found"
        return 1
    fi
    
    # Extrahiere strukturierte Informationen für besseren Vergleich
    local current_goals=$(extract_goals_info "$current_file")
    local previous_goals=$(extract_goals_info "$previous_file")
    
    local current_count=$(echo "$current_goals" | wc -l)
    local previous_count=$(echo "$previous_goals" | wc -l)
    
    debug_log "$label current goals count: $current_count"
    debug_log "$label previous goals count: $previous_count"
    
    if [ "$current_goals" != "$previous_goals" ]; then
        print_message "$GREEN" "🎯 $label ÄNDERUNG ERKANNT! Die Geyser-Seite hat sich verändert!"

        # Zeige Unterschiede an
        echo -e "${YELLOW}$label Unterschiede:${NC}"
        diff <(echo "$previous_goals") <(echo "$current_goals") | head -10

         # PodHome API aufrufen   
        json_response=$(curl -s \
            --request GET \
            -H "Content-Type: application/json" \
            -H "X-API-KEY: $API_KEY" \
            "$GET_EPISODE_API_URL")
        debug_log "=== Vollständige JSON-Response ==="
        debug_log "$json_response"
        
        # Einzelne Werte mit jq extrahieren
        episode_id=$(echo "$json_response" | jq -r 'sort_by(.publish_date) | .[0].episode_id')
        episode_nr=$(echo "$json_response" | jq -r 'sort_by(.publish_date) | .[0].episode_nr')
        episode_title=$(echo "$json_response" | jq -r 'sort_by(.publish_date) | .[0].title')
        current_publish_date=$(echo "$json_response" | jq -r 'sort_by(.publish_date) | .[0].publish_date')
        echo "Episoden ID: $episode_id";
        echo "Episoden Nr: $episode_nr";
        echo "Episoden Titel: $episode_title";
        echo "Aktuelles Veröffentlichungsdatum: $current_publish_date";
        
        # Prüfe auf spezifische Ziel-Erreichte Muster
        if echo "$current_goals" | grep -qE -i "(100%|completed|Abgeschlossen|reached|achieved|goal.*reached|target.*met)" || [ -z "$current_goals" ]; then
            print_message "$GREEN" "🏆 MÖGLICHES ZIEL ERREICHT ($label)! Prüfen Sie die Webseite!"
            calculate_adjusted_time $FINAL_GOAL
            #Call PodHome API 
            reschedule_episode_curl true
            if [ "$SEND_TELEGRAM_BOT_UPDATES" = true ]; then
                curl -s "$TELEGRAM_BOT_BACKEND_URL/update-donations" \
                --request POST \
                -H "Content-Type: application/json" \
                -H "X-API-KEY: $WEBHOOK_TOKEN" \
                -d "{
                    \"episode_id\": \"$episode_id\",
                    \"amount\": \"$FINAL_GOAL\"
                }"    
            fi
        else
            echo "Aktueller Spendenstand wird berechnet..."
            calculate_adjusted_time $current_goals
            # Just call and update the PodHome API when the publish_date has changed
            if [ "${new_publish_date%Z*}" != "${current_publish_date%.*}" ]; then
                reschedule_episode_curl false
            fi
            if [ "$SEND_TELEGRAM_BOT_UPDATES" = true -a diff_goals > 0 ]; then
                curl -s "$TELEGRAM_BOT_BACKEND_URL/update-donations" \
                --request POST \
                -H "Content-Type: application/json" \
                -H "X-API-KEY: $WEBHOOK_TOKEN" \
                -d "{
                    \"episode_id\": \"$episode_id\",
                    \"amount\": \"$current_goals\"
                }"     
            fi
        fi
        return 0
    fi
    debug_log "$label: No changes detected"
    return 1
}

reschedule_episode_curl() {
    local publish_now=$1
    local earliest_schedule_date="${current_date}T${EARLIEST_TIME}:00:00Z"
    local current_timestamp=$(date +%s)
    local earliest_timestamp=$(date -d "$earliest_schedule_date" +%s)
    if [ "$publish_now" == "true" ]; then
        if [ $current_timestamp -gt $earliest_timestamp ]; then
            echo "Publish-Now Path!"
            curl "$POST_EPISODE_API_URL" \
                --request POST \
                -H "Content-Type: application/json" \
                -H "X-API-KEY: $API_KEY" \
                -d "{
                    \"episode_id\": \"$episode_id\",
                    \"publish_now\": true
                }"
            if [ "$USE_TELEGRAM_BOT" = true ]; then
                send_telegram_message "<b>Neuer Stand im Release-Boosting für Folge:</b>
            $episode_title
            Aktueller Spendenstand: $FINAL_GOAL Sats
            Folge wurde veröffentlicht!"
            fi
            #Inform the telegram bot about the rescheduling
            if [ "$SEND_TELEGRAM_BOT_UPDATES" = true ]; then
                curl "$TELEGRAM_BOT_BACKEND_URL\sync-episodes" \
                --request POST \
                -H "X-API-KEY: $WEBHOOK_TOKEN"            
            fi
        else
            echo "Reschedule-Path with earliest date!"
            curl "$POST_EPISODE_API_URL" \
                --request POST \ 
                -H "Content-Type: application/json" \
                -H "X-API-KEY: $API_KEY" \
                -d "{
                    \"episode_id\": \"$episode_id\",
                    \"publish_date\": \"$earliest_schedule_date\"
                }"
            adjusted_german_date=$(convert_utc_plus2_manual "$earliest_schedule_date")
            
            if [ "$USE_TELEGRAM_BOT" = true ]; then
                send_telegram_message "<b>Neuer Stand im Release-Boosting für Folge:</b>
            $episode_title
            Aktueller Spendenstand: $FINAL_GOAL Sats
            Folge wurde auf $adjusted_german_date vorgezogen!"
            fi
            #Inform the telegram bot about the rescheduling
            if [ "$SEND_TELEGRAM_BOT_UPDATES" = true ]; then
                curl "$TELEGRAM_BOT_BACKEND_URL\sync-episodes" \
                --request POST \
                -H "X-API-KEY: $WEBHOOK_TOKEN"
            fi
        fi
    else
        echo "Reschedule-Path!"
        curl "$POST_EPISODE_API_URL" \
             --request POST \
            -H "Content-Type: application/json" \
            -H "X-API-KEY: $API_KEY" \
            -d "{
                \"episode_id\": \"$episode_id\",
                \"publish_date\": \"$new_publish_date\"
            }"
        adjusted_german_date=$(convert_utc_plus2_manual "$new_publish_date")
        diff_goals=$(($current_goals-$previous_goals))
         
        if [ "$USE_TELEGRAM_BOT" = true -a diff_goals >= $NOTIFICATION_THRESHOLD ]; then
            send_telegram_message "<b>Neuer Stand im Release-Boosting für Folge:</b>
        $episode_title
        Aktueller Spendenstand: $current_goals Sats
        Fehlende Sats bis zum Ziel: $(($FINAL_GOAL-$current_goals))
        Folge wurde auf $adjusted_german_date vorgezogen!"
        fi
        #Inform the telegram bot about the rescheduling
        if [ "$SEND_TELEGRAM_BOT_UPDATES" = true ]; then
            curl -s "$TELEGRAM_BOT_BACKEND_URL/sync-episodes" \
            --request POST \
            -H "X-API-KEY: $WEBHOOK_TOKEN"         
        fi
    fi
}

calculate_adjusted_time() {
    local donation_satoshis=$1
    # Eingabe-Validierung
    if ! [[ "$donation_satoshis" =~ ^[0-9]+$ ]]; then
        echo "Fehler: Ungültige Eingabe. Nur positive Ganzzahlen erlaubt."
        return 1
    fi
    # Berechnung - 21 Satoshis = 1 Minute
    local minutes_to_subtract=$((donation_satoshis / SATOSHIS_PER_MINUTE))
    local hours_to_subtract=$(echo "scale=4; $minutes_to_subtract / 60" | bc -l)
    # Begrenzung auf Maximum
    if [ $minutes_to_subtract -gt $((MAX_REDUCTION * 60)) ]; then
        minutes_to_subtract=$((MAX_REDUCTION * 60))
        hours_to_subtract=$MAX_REDUCTION
    fi
    # Neue Zeit berechnen
    local new_time_hours=$(echo "$START_TIME - $hours_to_subtract" | bc -l)
    # Auf früheste Zeit begrenzen
    if (( $(echo "$new_time_hours < $EARLIEST_TIME" | bc -l) )); then
        new_time_hours=$EARLIEST_TIME
        echo "⚠️  Früheste mögliche Zeit erreicht!"
    fi
    # Tag und Uhrzeit bestimmen
    local day=""
    local hours_in_day=""
    if (( $(echo "$new_time_hours >= 24" | bc -l) )); then
        day="Samstag"
        hours_in_day=$(echo "$new_time_hours - 24" | bc -l)
    else
        day="Freitag"
        hours_in_day=$new_time_hours
    fi

    local hours_int=$(printf "%.0f" $(echo "$hours_in_day" | cut -d'.' -f1))
    local decimal_part=$(echo "$hours_in_day - $hours_int" | bc -l)
    local minutes_calc=$(echo "$decimal_part * 60" | bc -l)
    local minutes=$(printf "%.0f" $minutes_calc)
    current_date=${current_publish_date%T*}
    debug_log "$current_date"
    new_publish_date="${current_date}T$(printf "%02d:%02d" $hours_int $minutes):00Z"
    debug_log "$new_publish_date"
    # Ausgabe
    echo "📊 Spendenstand: $(printf "%'d" $donation_satoshis) Satoshis"
    echo "📊 Zielspendenstand: $(printf "%'d" $FINAL_GOAL) Satoshis"
    echo "📊 Betrag bis zum Ziel: $(printf "%'d" $(($FINAL_GOAL-$donation_satoshis))) Satoshis"
    echo "🎯 Veröffentlichungszeitpunkt GMT+0: $current_date $(printf "%02d:%02d" $hours_int $minutes)"
    # Zusätzliche Info bei Maximum - angepasst für neue Berechnung
    local max_satoshis=$((MAX_REDUCTION * 60 * SATOSHIS_PER_MINUTE))
    if [ $donation_satoshis -ge $max_satoshis ]; then
        echo "✅ Maximum erreicht ($max_satoshis+ Satoshis = $MAX_REDUCTION Stunden Reduktion)"
    fi
}

# Funktion zum Senden von Nachrichten
send_telegram_message() {
    local message="$1"
    local parse_mode="${2:-HTML}"  # HTML oder Markdown
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d chat_id="$CHAT_ID" \
        -d message_thread_id="$TOPIC_ID" \
        -d text="$message" \
        -d parse_mode="$parse_mode" \
        -d disable_notification=true \
        > /dev/null
}

convert_utc_plus2_manual() {
    local utc_time="$1"
    # Zeitzone temporär auf GMT+2 setzen und konvertieren
    TZ='Europe/Berlin' date -d "$utc_time" '+%Y-%m-%d %H:%M:%S'
}

cleanup() {
    print_message "$BLUE" "Monitor wird beendet..."
    debug_log "Cleanup initiated"
    
    # Töte eventuell noch laufende Node-Prozesse
    pkill -f "scraper.js" 2>/dev/null || true
    
    # Entferne temporäre Dateien
    rm -f "$TEMP_DIR"/*.tmp 2>/dev/null || true
    
    exit 0
}

show_debug_info() {
    print_message "$PURPLE" "🔍 Debug-Informationen:"
    echo -e "${PURPLE}Temp-Verzeichnis: $TEMP_DIR${NC}"
    echo -e "${PURPLE}Debug-Log: $DEBUG_LOG${NC}"
    
    if [ -f "$DEBUG_LOG" ]; then
        echo -e "${PURPLE}Letzte Debug-Einträge:${NC}"
        tail -10 "$DEBUG_LOG" | while read -r line; do
            echo -e "${PURPLE}  $line${NC}"
        done
    fi
    
    if [ -d "$TEMP_DIR/node_modules" ]; then
        echo -e "${GREEN}✅ Node modules installiert${NC}"
    else
        echo -e "${RED}❌ Node modules fehlen${NC}"
    fi
    
    # Zeige Netzwerk-Status
    echo -e "${PURPLE}Netzwerk-Test:${NC}"
    if ping -c 1 -W 3000 geyser.fund >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Ping zu geyser.fund erfolgreich${NC}"
    else
        echo -e "${RED}❌ Ping zu geyser.fund fehlgeschlagen${NC}"
    fi
    
    # Zeige macOS Version
    echo -e "${PURPLE}macOS Version: $(sw_vers -productVersion)${NC}"
}

main() {
    print_message "$BLUE" "🚀 Geyser Fund Monitor gestartet"
    print_message "$BLUE" "URL: $URL"
    print_message "$BLUE" "Check-Interval: ${CHECK_INTERVAL}s"
    print_message "$BLUE" "Max Retries: $MAX_RETRIES"
    print_message "$BLUE" "Scraper Timeout: ${SCRAPER_TIMEOUT}s"
    print_message "$BLUE" "JavaScript Support: $([[ $USE_JAVASCRIPT == true ]] && echo "✅ Aktiviert" || echo "❌ Deaktiviert")"
    print_message "$BLUE" "Debug Mode: $([[ $DEBUG_MODE == true ]] && echo "✅ Aktiviert" || echo "❌ Deaktiviert")"
    print_message "$BLUE" "Drücken Sie Ctrl+C zum Beenden"
    echo ""
        
    setup_directories
    debug_log "Monitor started with JavaScript=$USE_JAVASCRIPT, Debug=$DEBUG_MODE, MaxRetries=$MAX_RETRIES"
    
    # Trap für sauberes Beenden
    trap cleanup SIGINT SIGTERM
    
    local check_count=0
    local html_changed=false
    local js_changed=false
    local js_failures=0
    local max_js_failures=3
    
    while true; do
        check_count=$((check_count + 1))
        html_changed=false
        js_changed=false
        
        print_message "$BLUE" "Check #$check_count"
        debug_log "Starting check #$check_count"
        
        # Standard HTML Check
        print_message "$BLUE" "📄 Lade Standard HTML Inhalt..."
        if fetch_content "$CURRENT_FILE"; then
            if [ -s "$CURRENT_FILE" ]; then
                if compare_content "html" "$CURRENT_FILE" "$PREVIOUS_FILE" "HTML"; then
                    html_changed=true
                fi
                cp "$CURRENT_FILE" "$PREVIOUS_FILE"
            else
                print_message "$RED" "❌ Fehler: Leere HTML-Antwort erhalten"
            fi
        else
            print_message "$RED" "❌ Fehler beim Laden der HTML-Webseite"
        fi
        
        # JavaScript-rendered Content Check
        if [ "$USE_JAVASCRIPT" = true ]; then
            if fetch_js_content "$CURRENT_JS_FILE"; then
                js_failures=0  # Reset failure counter on success
                if [ -s "$CURRENT_JS_FILE" ]; then
                    if compare_content "js" "$CURRENT_JS_FILE" "$PREVIOUS_JS_FILE" "JAVASCRIPT"; then
                        js_changed=true
                    fi
                    cp "$CURRENT_JS_FILE" "$PREVIOUS_JS_FILE"
                else
                    print_message "$RED" "❌ Fehler: Leere JavaScript-Antwort erhalten"
                fi
            else
                js_failures=$((js_failures + 1))
                print_message "$RED" "❌ Fehler beim Laden der JavaScript-gerenderten Inhalte (Fehler $js_failures/$max_js_failures)"
                
                if [ "$DEBUG_MODE" = true ]; then
                    show_debug_info
                fi
                
                # Nach mehreren Fehlern zu Fallback-Modus wechseln
                if [ $js_failures -ge $max_js_failures ]; then
                    fallback_mode
                fi
            fi
        fi
        
        # Zusammenfassung der Änderungen
        if [ "$html_changed" = true ] || [ "$js_changed" = true ]; then
            print_message "$GREEN" "🎉 GESAMTFAZIT: Änderungen erkannt!"
            
            if [ "$html_changed" = true ]; then
                print_message "$GREEN" "  - HTML Änderungen: ✅"
            fi
            if [ "$js_changed" = true ]; then
                print_message "$GREEN" "  - JavaScript Änderungen: ✅"
            fi
            
            # Benachrichtigung senden
            if command -v osascript >/dev/null 2>&1; then
                local notification_msg="Geyser Fund Seite hat sich geändert!"
                if [ "$js_changed" = true ]; then
                    notification_msg="$notification_msg (JavaScript-Inhalte aktualisiert)"
                fi
                osascript -e "display notification \"$notification_msg\" with title \"NodeSignal Monitor\""
            fi
            
            # Sound abspielen
            if command -v afplay >/dev/null 2>&1; then
                afplay /System/Library/Sounds/Glass.aiff 2>/dev/null &
            fi
        else
            print_message "$BLUE" "📊 Keine Änderungen in HTML oder JavaScript erkannt"
        fi
        
        print_message "$BLUE" "⏰ Warte ${CHECK_INTERVAL} Sekunden bis zum nächsten Check..."
        echo "─────────────────────────────────────────────────────────"
        debug_log "Check #$check_count completed"
        sleep "$CHECK_INTERVAL"
    done
}

show_setup_help() {
    echo "🔧 Setup-Hilfe für JavaScript-Monitor:"
    echo ""
    echo "1. Node.js installieren (v16+ empfohlen):"
    echo "   sudo apt install npm"
    echo ""
    echo "2. Verschiedene Ausführungsmodi:"
    echo "   ./geyser_monitor.sh                          # Standard"
    echo "   ./geyser_monitor.sh --debug                  # Mit Debug"
    echo "   ./geyser_monitor.sh --no-js                  # Nur HTML"
    echo "   ./geyser_monitor.sh --debug --retries 5      # 5 Retry-Versuche"
    echo "   ./geyser_monitor.sh --timeout 300            # 5min Timeout"
    echo ""
    echo "3. Troubleshooting:"
    echo "   cat /tmp/geyser_monitor/debug.log            # Debug-Log"
    echo "   ls -la /tmp/geyser_monitor/                  # Dateien prüfen"
    echo ""
}
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-js|--no-javascript)
            USE_JAVASCRIPT=false
            shift
            ;;
        --debug)
            DEBUG_MODE=true
            shift
            ;;
        --retries)
            MAX_RETRIES="$2"
            if ! [[ "$MAX_RETRIES" =~ ^[0-9]+$ ]] || [ "$MAX_RETRIES" -lt 1 ] || [ "$MAX_RETRIES" -gt 10 ]; then
                print_message "$RED" "❌ Ungültiger Retry-Wert: $MAX_RETRIES (1-10 erlaubt)"
                exit 1
            fi
            shift 2
            ;;
        --timeout)
            SCRAPER_TIMEOUT="$2"
            if ! [[ "$SCRAPER_TIMEOUT" =~ ^[0-9]+$ ]] || [ "$SCRAPER_TIMEOUT" -lt 30 ] || [ "$SCRAPER_TIMEOUT" -gt 600 ]; then
                print_message "$RED" "❌ Ungültiger Timeout-Wert: $SCRAPER_TIMEOUT (30-600 Sekunden erlaubt)"
                exit 1
            fi
            shift 2
            ;;
        --help|-h)
            show_setup_help
            exit 0
            ;;
        *)
            print_message "$RED" "Unbekannter Parameter: $1"
            echo ""
            show_setup_help
            exit 1
            ;;
    esac
done

# Prüfe Abhängigkeiten
if ! check_dependencies; then
    exit 1
fi

# Starte Monitor
main
