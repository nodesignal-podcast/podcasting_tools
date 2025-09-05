import logging
import sqlite3
import requests
import json
import configparser
import qrcode
import io
import os
import tempfile
from urllib.parse import urlparse
from pathlib import Path
from typing import List, Dict, Optional
from telegram import LinkPreviewOptions, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler
)
import asyncio
import aiohttp
import aiofiles
from db_manager import DatabaseManager
import nest_asyncio

# Logging konfigurieren
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
    filename='telegram_bot.log'
)
logger = logging.getLogger(__name__)
nest_asyncio.apply()

WAITING_FOR_DONATION = 1
    
# Globale Instanzen
db = DatabaseManager('telegram_bot_config.conf')
config_data = {}

# Bot-Funktionen 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start-Command Handler"""
    welcome_text = """
🎙️ **Willkommen beim Nodesignal-Podcast Bot!**

Verfügbare Befehle:
• `/episodes` - Letzte und künftige Episoden auflisten
• `/next_episode` - Infos über die nächste Folge anzeigen
• `/donation` - Lightning Invoices für das Release Boosting generieren
• `/help` - Diese Hilfe

Verwende die Befehle um zu starten!
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hilfe-Command"""
    help_text = """
🎙️ **Nodesignal-Podcast Bot Befehle:**

**📺 Episode verwalten:**
• `/episodes` - Letzte und künftige Episoden auflisten
• `/next_episode` - Infos über die nächste Folge anzeigen
• `/donation` - Lightning Invoices für das Release Boosting generieren

**ℹ️ Weitere Befehle:**
• `/help` - Diese Hilfe
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_donation_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Verarbeitet die numerische Eingabe des Benutzers"""
    user_input = update.message.text
    
    try:
        # Versuche die Eingabe in eine Zahl umzuwandeln
        amount = int(user_input)
        # Validierung für positive Zahlen
        if amount <= 0:
            await update.message.reply_text(
                'Bitte gib einen positiven Betrag ein. Versuche es erneut:'
            )
            return WAITING_FOR_DONATION
        
        lightning_invoice = request_donation((amount*1000))
        invoice_string=lightning_invoice.get("invoice", {}).get("pr", "")
        donation_text = f"""
    📻 **Invoice über {amount} Sats für das Release Boosting:**
Deine Spende zieht die kommende Folge um {round((amount/21), 1)} Minuten vor. Vielen Dank dafür!

        **`{invoice_string}`
        """
        qr_bio = generate_qr_code(invoice_string)

        # Erfolgsmeldung mit der eingegebenen Zahl
        await update.message.reply_text(donation_text, parse_mode='Markdown')
        await update.message.reply_photo(
                photo=qr_bio
            )
        await update.message.reply_text(
            f'⚡ QR-Code für eine {amount} Sats Spende. Verwende /donation um eine neue Spende einzugeben.'
        )        
        return ConversationHandler.END
        
    except ValueError:
        # Fehlerbehandlung bei ungültiger Eingabe
        await update.message.reply_text(
            'Das ist keine gültige Zahl. Bitte gib eine ganze Zahl ein (z.B. 2100 Sats), Verwende /cancel um den Vorgang abzubrechen.'
        )
        return WAITING_FOR_DONATION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bricht die Konversation ab"""
    await update.message.reply_text('Spendeneingabe abgebrochen.')
    return ConversationHandler.END

async def donation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Donation-Command"""
    episode = await db.get_next_episode()
    if not episode:
        message_text = f"""
📭 Aktuell keine Episode fürs Releaseboosting vorhanden vorhanden. 

Gerne kannst du trotzdem schonmal was für die nächste Folge in den Top geben.🧡

Bitte gib den Spendenbetrag als Zahl ein (z.B. 21 Sats)
Abbruch mit /cancel
"""
        await update.message.reply_text(message_text)
        return
    else:
        message_text = f"""
📺 Du willst die nächste Episode: "{episode[0][2][:100].split(' - ')[1]} - {episode[0][2][:100].split(' - ')[2]}" früher hören? 

📅 Aktuelle geplante Veröffentlichung: {episode[0][4]}

Dann lass hier min. 21 Sats da und die Veröffentlichung wird um eine Minute vorgezogen (frühestens Freitag 12:00)
Alternativ kannst du auch direkt Sats an releaseboosting@getalby.com schicken!

Bitte gib den Spendenbetrag als Zahl ein (z.B. 21 Sats)
Abbruch mit /cancel
"""
    await update.message.reply_text(message_text)
    return WAITING_FOR_DONATION            

async def next_episode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nächste Episode-Command"""
    episode = await db.get_next_episode()
    lightning_address = config_data['lightning_address']
    if not episode:
        await update.message.reply_text("📭 Noch keine Episoden vorhanden.")
        return

    episode_text = f"""
📻 **Die nächste Folge auf unserer Roadmap:**

**{episode[0][2][:100].split(' - ')[1]} - {episode[0][2][:100].split(' - ')[2]}**

📝 **Beschreibung:**
{episode[0][3].split('<br />Von und mit:')[0] or 'Keine Beschreibung verfügbar'}

**Aktueller Stand vom Release-Boosting-Ziel:** {episode[0][5]} Sats

📅 **Geplante Veröffentlichung:** {episode[0][4]}

Booste den Release der Folge über /donation oder Direktspende an: {lightning_address} 
"""

    await update.message.reply_text(episode_text, parse_mode='Markdown')

async def list_episodes(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """Alle Episoden auflisten mit Paginierung"""
    episodes = await db.get_all_episodes()
    
    if not episodes:
        if update.callback_query:
            await update.callback_query.edit_message_text("📭 Noch keine Episoden vorhanden.")
        else:
            await update.message.reply_text("📭 Noch keine Episoden vorhanden.")
        return
    
    # Paginierung konfigurieren
    items_per_page = 5
    total_pages = (len(episodes) + items_per_page - 1) // items_per_page
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    current_episodes = episodes[start_index:end_index]
    
    # Keyboard für aktuelle Episoden erstellen
    keyboard = []
    for episode in current_episodes:
        button_text = f"{episode[2][:62].split(' - ')[1]} - {episode[2][:62].split(' - ')[2]}..." if episode[6] == 1 else f"{episode[2][:62].split(' - ')[1]} - {episode[2][:62].split(' - ')[2]}...✅"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"episode_{episode[1]}")])
    
    # Navigationsbuttons hinzufügen
    navigation_row = []
    
    if page < total_pages - 1:
        navigation_row.append(InlineKeyboardButton("⬅️ Zurück", callback_data=f"episodes_page_{page+1}"))
    
    if page > 0:
        navigation_row.append(InlineKeyboardButton("Vorwärts ➡️", callback_data=f"episodes_page_{page-1}"))
    
    if navigation_row:
        keyboard.append(navigation_row)
    
    # Seitenanzeige hinzufügen
    if total_pages > 1:
        keyboard.append([InlineKeyboardButton(f"Seite {page + 1} von {total_pages}", callback_data="noop")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = f"📺 **Folgende Episoden stehen zur Auswahl:**\n✅ = bereits veröffentlicht.\n\nSeite {page + 1} von {total_pages} ({len(episodes)} Episoden gesamt)\n\nWähle eine Episode für Details:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

# Callback Handler für die Navigation
async def handle_episode_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler für Episode-Paginierung"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("episodes_page_"):
        page = int(query.data.split("_")[-1])
        await list_episodes(update, context, page)
    elif query.data == "noop":
        # Für den Seitenanzeige-Button (macht nichts)
        pass

async def episode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback für Episode-Details mit MP3-Download"""
    query = update.callback_query
    await query.answer()
    
    episode_id = query.data.split('_')[1]
    episode = await db.get_episode(episode_id)
    
    if not episode:
        await query.edit_message_text("❌ Episode nicht gefunden.")
        return
    try:
        # Episode-Informationen extrahieren
        episode_title = episode[0][2][:100].split(' - ')[1] if len(episode[0][2].split(' - ')) > 1 else episode[0][2][:100]
        episode_subtitle = episode[0][2][:100].split(' - ')[2] if len(episode[0][2].split(' - ')) > 2 else ""
        episode_description = episode[0][3].split('<br />Von und mit:')[0] if episode[0][3] else 'Keine Beschreibung verfügbar'
        episode_date = episode[0][4]
        episode_status = episode[0][6]
        episode_website = episode[0][10]
        mp3_url = episode[0][8] if len(episode[0]) > 8 and episode[0][8] else None
        if episode_status == 1:
            episode_text = f"""
📻 **{episode_title}**{f" - {episode_subtitle}" if episode_subtitle else ""}

📝 **Beschreibung:**
{episode_description}

📅 **Geplante Veröffentlichung:** {episode_date}
        """
        else:
             episode_text = f"""
📻 **{episode_title}**{f" - {episode_subtitle}" if episode_subtitle else ""}

📝 **Beschreibung:**
{episode_description}

📅 **Veröffentlichung:** {episode_date}

🌐 **Webseite:** {episode_website}
        """
        # Keyboard mit Download-Option wenn MP3 verfügbar
        keyboard = []
        if episode_status == 2:
            if mp3_url and mp3_url.strip():
                # Prüfe ob URL gültig ist
                if mp3_url.startswith(('http://', 'https://')):
                    keyboard.append([InlineKeyboardButton("🎧 MP3 herunterladen", callback_data=f"download_{episode_id}")])
                else:
                    episode_text += "\n⚠️ MP3-URL ungültig"
            else:
                episode_text += "\n❌ Keine MP3-Datei verfügbar"
        
        keyboard.append([InlineKeyboardButton("« Zurück zur Liste", callback_data="back_to_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        preview_options = LinkPreviewOptions(prefer_small_media=True)
    except Exception as e:
        logger.error(f"Error: {e}")
    
    await query.edit_message_text(episode_text, parse_mode='Markdown', reply_markup=reply_markup,link_preview_options = preview_options)

async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback für MP3-Download"""
    query = update.callback_query
    await query.answer()
    
    episode_id = query.data.split('_')[1]
    episode = await db.get_episode(episode_id)
    
    if not episode:
        await query.edit_message_text("❌ Episode nicht gefunden.")
        return
    
    mp3_url = episode[0][8] if len(episode[0]) > 8 and episode[0][8] else None
    
    if not mp3_url or not mp3_url.strip():
        await query.edit_message_text("❌ Keine MP3-URL verfügbar.")
        return
    
    # Zeige Download-Status
    status_message = await query.edit_message_text("📥 Lade MP3-Datei herunter...")
    
    try:
        # Episode-Titel für Dateiname bereinigen
        episode_title = episode[0][2][:50].split(' - ')[1] if len(episode[0][2].split(' - ')) > 1 else episode[0][2][:50]
        safe_filename = "".join(c for c in episode_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_filename = safe_filename.replace(' ', '_')
        
        # MP3-Datei herunterladen
        temp_file_path = await download_mp3_file(mp3_url, safe_filename)
        
        if not temp_file_path:
            await status_message.edit_text("❌ Download fehlgeschlagen. Datei nicht verfügbar.")
            return
        
        # Prüfe Dateigröße (Telegram Limit: 50MB)
        file_size = os.path.getsize(temp_file_path)
        max_size = 50 * 1024 * 1024  # 50MB in Bytes
        
        if file_size > max_size:
            os.unlink(temp_file_path)  # Temporäre Datei löschen
            await status_message.edit_text(
                f"❌ Datei zu groß für Telegram ({file_size / 1024 / 1024:.1f}MB > 50MB)\n"
                f"🔗 Direkter Link: {mp3_url}"
            )
            return
        
        await status_message.edit_text("📤 Sende MP3-Datei...")
        
        # Sende MP3-Datei als Audio
        with open(temp_file_path, 'rb') as audio_file:
            # Extrahiere Dateinamen aus URL als Fallback
            url_filename = os.path.basename(urlparse(mp3_url).path)
            final_filename = f"{safe_filename}.mp3" if safe_filename else url_filename
            
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=audio_file,
                filename=final_filename,
                title=episode[0][2][:100] if episode[0][2] else "Podcast Episode",
                performer="Podcast",
                caption=f"🎧 {episode[0][2][:100] if episode[0][2] else 'Episode'}\n📁 Größe: {file_size / 1024 / 1024:.1f}MB"
            )
        
        # Temporäre Datei löschen
        os.unlink(temp_file_path)
        
        # Success-Nachricht
        await status_message.edit_text("✅ MP3 erfolgreich gesendet!")
        
        # Zurück zur Episode-Details
        await asyncio.sleep(2)  # Kurz warten
        await episode_callback(update, context)  # Zurück zu Episode-Details
        
    except Exception as e:
        # Cleanup bei Fehler
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        
        error_msg = f"❌ Download-Fehler: {str(e)[:100]}"
        await status_message.edit_text(error_msg)
        
        # Log den Fehler
        print(f"MP3 Download Error: {e}")

async def download_mp3_file(url: str, filename: str) -> str:
    """
    Lädt MP3-Datei herunter und speichert sie temporär
    Returns: Pfad zur temporären Datei oder None bei Fehler
    """
    try:
        # Erstelle temporäres Verzeichnis falls nicht vorhanden
        temp_dir = tempfile.gettempdir()
        
        # Generiere eindeutigen temporären Dateinamen
        temp_filename = f"podcast_{filename}_{os.getpid()}.mp3"
        temp_file_path = os.path.join(temp_dir, temp_filename)
        
        # Download mit Timeout
        timeout = aiohttp.ClientTimeout(total=300)  # 5 Minuten Timeout
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                # Prüfe HTTP-Status
                if response.status != 200:
                    print(f"HTTP Error {response.status} for URL: {url}")
                    return None
                
                # Prüfe Content-Type
                content_type = response.headers.get('content-type', '').lower()
                if 'audio' not in content_type and 'mpeg' not in content_type:
                    print(f"Warning: Unexpected content-type: {content_type}")
                
                # Schreibe Datei
                async with aiofiles.open(temp_file_path, 'wb') as file:
                    async for chunk in response.content.iter_chunked(8192):
                        await file.write(chunk)
        
        # Prüfe ob Datei erstellt wurde und nicht leer ist
        if os.path.exists(temp_file_path) and os.path.getsize(temp_file_path) > 0:
            return temp_file_path
        else:
            return None
            
    except asyncio.TimeoutError:
        print(f"Timeout downloading MP3: {url}")
        return None
    except Exception as e:
        print(f"Error downloading MP3: {e}")
        return None

# Optional: Hilfsfunktion für URL-Validierung
def is_valid_mp3_url(url: str) -> bool:
    """Prüft ob URL eine gültige MP3-URL ist"""
    if not url or not url.strip():
        return False
    
    url = url.strip()
    
    # Basis URL-Validierung
    if not url.startswith(('http://', 'https://')):
        return False
    
    # Prüfe auf MP3-Endung oder Content-Type-Hints
    url_lower = url.lower()
    return (url_lower.endswith('.mp3') or 
            'audio' in url_lower or 
            'mp3' in url_lower or
            url_lower.endswith('.m4a'))

async def back_to_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Zurück zur Episoden-Liste"""
    await list_episodes(update, context)

# Hilfsfunktionen
def generate_qr_code(invoice):
        """QR-Code für Lightning Invoice generieren"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(invoice.upper())
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        return bio

async def insert_episodes_to_db(episodes: List[Dict]) -> int:
    if not episodes:
        logger.info("Keine Episoden zum Einfügen")
        return 0
    
    inserted_count = 0
    
    for episode in episodes:
        try:
            if not await db.get_episode(episode.get('episode_id')):
                await db.insert_episode(episode)
                inserted_count += 1
            else:
                await db.update_episode(episode)
                inserted_count += 1
        except sqlite3.Error as e:
            logger.error(f"Fehler beim Einfügen der Episode {episode.get('id', 'unbekannt')}: {e}")
    
    logger.info(f"{inserted_count} Episoden erfolgreich in die Datenbank eingefügt/aktualisiert")
    return inserted_count

def request_donation(amount: int, base_url: str = "https://api.getalby.com/lnurl") -> List[Dict]:
    lightning_address = config_data['lightning_address']
    headers = {'Content-Type': "application/json"}
    params = {"ln": lightning_address, "amount": amount}
    
    try:
        response = requests.get(f"{base_url}/generate-invoice", headers=headers, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        lightning_invoice = data 
        logger.info(f"Lightning Invoice erfolgreich abgerufen")
        return lightning_invoice
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Invoice: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Fehler beim Parsen der JSON-Antwort: {e}")
        return []

def fetch_episodes(api_key: str, status_filter: int, episode_limit: int = 21, base_url: str = "https://serve.podhome.fm") -> List[Dict]:
    headers = {'X-API-KEY': f'{api_key}'}
    params = {"status": f'{status_filter}'}
    
    try:
        response = requests.get(f"{base_url}/api/episodes", headers=headers, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        episodes = sorted(data, key=lambda x: x['publish_date'])[-episode_limit:]
        logger.info(f"Erfolgreich {len(episodes)} geplante Episoden abgerufen")
        return episodes
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Episoden: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Fehler beim Parsen der JSON-Antwort: {e}")
        return []

async def sync_planned_episodes(api_key: str) -> Dict[str, any]:
    try:
        episodes = fetch_episodes(api_key, 2) #First last 5 published episodes
        episodes.extend(fetch_episodes(api_key, 1)) #Second scheduled episodes
        
        if not episodes:
            return {
                'success': True,
                'message': 'Keine geplanten Episoden gefunden',
                'count': 0
            }
        
        count = await insert_episodes_to_db(episodes)
        
        return {
            'success': True,
            'message': f'Synchronisation erfolgreich: {count} Episoden verarbeitet',
            'count': count,
            'episodes': episodes
        }
        
    except Exception as e:
        logger.error(f"Fehler bei der Episoden-Synchronisation: {e}")
        return {
            'success': False,
            'message': f'Synchronisation fehlgeschlagen: {str(e)}',
            'count': 0
        }

def read_config():
    config = configparser.ConfigParser()
    config.read('telegram_bot_config.conf')

    bot_token = config.get('general', 'bot_token')
    podhome_api_token = config.get('general', 'podhome_api_token')
    temp_dir = Path(config.get('paths', 'temp_dir', fallback='/tmp/telegram_bot'))
    lightning_address = config.get('general', 'lightning_address')
    
    try:
        webhook_port = config.getint('Webhook', 'port', fallback=8000)
        webhook_host = config.get('Webhook', 'host', fallback='0.0.0.0')
        webhook_secret = config.get('Webhook', 'secret', fallback=None)
    except:
        webhook_port = 8000
        webhook_host = '0.0.0.0'
        webhook_secret = None
    
    return {
        'bot_token': bot_token,
        'podhome_api_token': podhome_api_token,
        'temp_dir': temp_dir,
        'lightning_address': lightning_address,
        'webhook_port': webhook_port,
        'webhook_host': webhook_host,
        'webhook_secret': webhook_secret
    }

def setup_directories(dir : str):
    """Erstellt notwendige Verzeichnisse"""
    dir.mkdir(parents=True, exist_ok=True)

async def main() -> None:
    """Hauptfunktion"""
    global config_data
    
    config_data = read_config()
    BOT_TOKEN = config_data['bot_token']
    API_KEY = config_data['podhome_api_token']
    TEMP_DIR = config_data['temp_dir']

    setup_directories(TEMP_DIR)
    await db._initialize_connection()

    # Telegram Bot erstellen
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command Handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("episodes", list_episodes))
    application.add_handler(CommandHandler("next_episode", next_episode))
    
    # Callback Handler
    application.add_handler(CallbackQueryHandler(handle_episode_pagination, pattern="^(episodes_page_|noop)"))
    application.add_handler(CallbackQueryHandler(episode_callback, pattern="^episode_"))
    application.add_handler(CallbackQueryHandler(back_to_list_callback, pattern="^back_to_list$"))
    application.add_handler(CallbackQueryHandler(episode_callback, pattern="^episode_"))
    application.add_handler(CallbackQueryHandler(download_callback, pattern="^download_"))
    
    # ConversationHandler für die Spendeneingabe
    donation_handler = ConversationHandler(
        entry_points=[CommandHandler('donation', donation_command)],
        states={
            WAITING_FOR_DONATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_donation_amount)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(donation_handler)
    
    # Initiale Synchronisation
    print("🎙️ Bot startet...")
    result = await sync_planned_episodes(API_KEY)
    print(f"📊 Initiale Synchronisation: {result['message']}")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        await db.close()

def start_bot():
    """Bot starter Funktion"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Event Loop läuft bereits
            loop.create_task(main())
        else:
            # Event Loop läuft nicht
            loop.run_until_complete(main())
    except RuntimeError:
        # Fallback
        exit

if __name__ == '__main__':
    start_bot()