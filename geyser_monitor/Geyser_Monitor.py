#!/usr/bin/env python3
"""
Geyser Fund Goal Monitor - Python Version
Überwacht Webseiten auf Änderungen und verwaltet Episode-Veröffentlichungen
"""
import asyncio
import logging
import re
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict
import subprocess
import shutil
import requests
from bs4 import BeautifulSoup
import configparser
from dateutil import parser as date_parser
import pytz
from playwright.async_api import async_playwright

class GeyserMonitor:
    def __init__(self, config_path: str = "Geyser_Monitor.conf"):
        self.config = self.load_config(config_path)
        
        # Konfiguration
        self.url = self.config.get('monitoring', 'url')
        self.check_interval = self.config.getint('monitoring', 'check_interval', fallback=30)
        self.max_retries = self.config.getint('monitoring', 'max_retries', fallback=3)
        self.scraper_timeout = self.config.getint('monitoring', 'scraper_timeout', fallback=120)
        self.use_javascript = self.config.getboolean('monitoring', 'use_javascript', fallback=True)
        self.debug_mode = self.config.getboolean('monitoring', 'debug_mode', fallback=False)
        
        # Dateipfade
        self.temp_dir = Path(self.config.get('paths', 'temp_dir', fallback='/tmp/geyser_monitor'))
        self.current_file = self.temp_dir / "current.html"
        self.previous_file = self.temp_dir / "previous.html"
        self.current_js_file = self.temp_dir / "current_js.html"
        self.previous_js_file = self.temp_dir / "previous_js.html"
        
        # API-Konfiguration
        self.api_key = self.config.get('api', 'key')
        self.get_episode_url = self.config.get('api', 'get_episode_url')
        self.post_episode_url = self.config.get('api', 'post_episode_url')
        
        # Telegram-Konfiguration
        self.use_telegram = self.config.getboolean('telegram', 'enabled', fallback=False)
        self.notification_threshold = self.config.getint('telegram', 'notification_threshold')
        if self.use_telegram:
            self.bot_token = self.config.get('telegram', 'bot_token')
            self.chat_id = self.config.get('telegram', 'chat_id')
            self.topic_id = self.config.get('telegram', 'topic_id', fallback=None)

        # Telegram-Bot Backend
        self.use_telegram_backend = self.config.getboolean('telegram_bot_backend', 'enabled', fallback=False)
        if self.use_telegram_backend:
            self.telegram_bot_update_donations_url = self.config.get('telegram_bot_backend', 'telegram_bot_update_donations_url')
            self.telegram_bot_sync_episodes_url = self.config.get('telegram_bot_backend', 'telegram_bot_sync_episodes_url')
            self.webhook_token = self.config.get('telegram_bot_backend', 'webhook_token')

        # Berechnungsparameter
        self.final_goal = self.config.getint('calculation', 'final_goal')
        self.satoshis_per_minute = self.config.getint('calculation', 'satoshis_per_minute', fallback=21)
        self.max_reduction = self.config.getint('calculation', 'max_reduction_hours', fallback=12)
        self.earliest_time = self.config.getfloat('calculation', 'earliest_time', fallback=10)
        self.start_time = self.config.getfloat('calculation', 'start_time', fallback=22)
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        self.setup_directories()
        self.setup_logging()

        # Graceful shutdown
        signal.signal(signal.SIGINT, self.cleanup)
        signal.signal(signal.SIGTERM, self.cleanup)

    def load_config(self, config_path: str) -> configparser.ConfigParser:
        """Lädt die Konfigurationsdatei"""
        config = configparser.ConfigParser()
        config.read(config_path)
        return config

    def setup_logging(self):
        """Konfiguriert das Logging-System"""
        log_level = logging.DEBUG if self.debug_mode else logging.INFO
        
        # Erstelle Logger
        self.logger = logging.getLogger('geyser_monitor')
        self.logger.setLevel(log_level)
        
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        
        # File Handler
        file_handler = logging.FileHandler(self.temp_dir / 'geyser_monitor.log')
        file_handler.setLevel(logging.DEBUG)
        
        # Formatter
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def setup_directories(self):
        """Erstellt notwendige Verzeichnisse"""
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_html_content(self, output_file: Path) -> bool:
        """Lädt HTML-Inhalte mit Retry-Mechanismus"""
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.debug(f"HTML fetch attempt {attempt}/{self.max_retries}")
                
                response = self.session.get(
                    self.url,
                    timeout=45,
                    headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate'
                    }
                )
                response.raise_for_status()
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                
                self.logger.debug(f"HTML content saved to {output_file}")
                return True
                
            except Exception as e:
                self.logger.warning(f"HTML fetch attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(5)
        
        return False

    async def fetch_js_content(self, output_file: Path) -> bool:
        """Playwright-basierte JavaScript-Content-Erstellung (Container-optimiert)"""
        if not self.use_javascript:
            return False
            
        for attempt in range(1, self.max_retries + 1):
            try:
                async with async_playwright() as p:
                    # Nutze Chromium in Container
                    browser = await p.chromium.launch(
                        headless=True,
                        args=[
                            '--no-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-gpu',
                            '--single-process'  # Wichtig für Container
                        ]
                    )
                    
                    context = await browser.new_context(
                        viewport={'width': 1280, 'height': 720},
                        user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
                    )
                    
                    page = await context.new_page()
                    
                    # Navigiere zur Seite
                    await page.goto(self.url, wait_until='domcontentloaded', timeout=30000)
                    
                    # Warte auf Content
                    await asyncio.sleep(3)
                    
                    # Extrahiere Content (gleiche JavaScript-Logik)
                    content = await page.evaluate('''() => {
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
                            const lines = bodyText.split(/[\\n\\r]+/)
                                .map(line => line.trim())
                                .filter(line => line.length > 0 && line.length < 200)
                                .filter(line => /goal|target|raised|funded|%|bitcoin|btc|sats|progress|funding|campaign/i.test(line));
                            
                            lines.forEach(line => relevantTexts.add(line));
                            
                            // Strategie 3: Numerische Werte finden
                            const numericMatches = bodyText.match(/\\d+(?:,\\d{3})*(?:\\.\\d+)?\\s*(?:%|btc|sats|bitcoin|\\$|€|USD)/gi);
                            if (numericMatches) {
                                numericMatches.forEach(match => relevantTexts.add(match.trim()));
                            }
                            
                            // Konvertiere zu Array und sortiere
                            const finalContent = Array.from(relevantTexts)
                                .filter(text => text.length > 2)
                                .sort()
                                .join('\\n');
                            
                            console.log('Content extraction completed, found', relevantTexts.size, 'unique elements');
                            console.log('Numeric matches found:', numericMatches ? numericMatches.length : 0);
                            
                            return finalContent || 'No relevant content found';
                            
                        } catch (evalError) {
                            console.error('Content extraction error:', evalError.message);
                            return `Error during content extraction: ${evalError.message}`;
                        }
                    }''')
                    
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(content or 'No content')
                    
                    await browser.close()
                    return True
                    
            except Exception as e:
                self.logger.warning(f"Playwright attempt {attempt} failed: {e}")
                await asyncio.sleep(3)
        
        return False

    def extract_goals_info(self, file_path: Path) -> str:
        """Extrahiert Goal-relevante Informationen aus einer Datei (mit numerischer Suche)"""
        if not file_path.exists():
            return ""
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Verwende BeautifulSoup für besseres HTML-Parsing
            soup = BeautifulSoup(content, 'html.parser')
            text = soup.get_text()
            
            relevant_texts = set()
            
            # Strategie 1: Textbasierte Suche nach relevanten Zeilen
            for line in text.split('\n'):
                line = line.strip()
                if line and len(line) < 200:
                    if re.search(r'goal|target|raised|funded|bitcoin|btc|sats|progress|funding|campaign', line, re.I):
                        relevant_texts.add(line)
            
            # Strategie 2: Numerische Werte finden (Python-Regex)
            numeric_pattern = r'\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|btc|sats|bitcoin|\$|€|USD)'
            numeric_matches = re.findall(numeric_pattern, text, re.IGNORECASE)
            
            for match in numeric_matches:
                relevant_texts.add(match.strip())
            
            # Bereite finalen Text vor
            final_text = '\n'.join(sorted(relevant_texts)[:50])
            
            # NEUE FUNKTIONALITÄT: Bereinigung und Zahlen-Extraktion
            final_text = self.process_and_clean_text(final_text)
            
            # Debug-Info
            if self.debug_mode:
                self.logger.debug(f"Found {len(numeric_matches)} numeric matches in HTML")
                if numeric_matches:
                    self.logger.debug(f"Sample numeric matches: {numeric_matches[:5]}")
                self.logger.debug(f"Final processed text: {final_text[:200]}...")
            
            return final_text
            
        except Exception as e:
            self.logger.error(f"Error extracting goals info from {file_path}: {e}")
            return ""

    def process_and_clean_text(self, text: str) -> str:
        """
        Bereinigt Text und extrahiert Ziel und aktuellen Spendenstand
        Erste erkannte Zahl = Ziel, zweite = aktueller Stand
        """
        if not text:
            return ""
        
        try:
            # Schritt 1: Entferne " sats" Zeichenketten
            cleaned_text = re.sub(r'\s+sats\b', '', text, flags=re.IGNORECASE)
            
            # Schritt 2: Entferne Zeilenumbrüche und normalisiere Leerzeichen
            cleaned_text = re.sub(r'\n+', ' ', cleaned_text)
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
            
            # Schritt 3: Extrahiere alle Zahlen (auch mit Kommas)
            number_pattern = r'\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b'
            all_numbers = re.findall(number_pattern, cleaned_text)
            
            if self.debug_mode:
                self.logger.debug(f"Found numbers in text: {all_numbers[:10]}")
            
            # Schritt 4: Konvertiere zu Integers und filtere plausible Werte
            extracted_numbers = []
            for num_str in all_numbers:
                try:
                    # Entferne Kommas für Konvertierung
                    clean_num = num_str.replace(',', '')
                    num_value = int(float(clean_num))
                    
                    # Filtere nur plausible Spendenwerte (zwischen 1 und 10 Millionen Sats)
                    if 1 <= num_value <= 10_000_000:
                        extracted_numbers.append(num_value)
                except (ValueError, TypeError):
                    continue
            
            # Schritt 5: Bestimme Ziel und aktuellen Stand
            goal_amount = None
            current_amount = None
            
            if len(extracted_numbers) >= 2:
                # Sortiere nach Größe (größere Zahl ist meist das Ziel)
                sorted_numbers = sorted(set(extracted_numbers), reverse=True)
                
                # Erste (größte) Zahl = Ziel, zweite = aktueller Stand
                goal_amount = sorted_numbers[0]
                current_amount = sorted_numbers[1] if len(sorted_numbers) > 1 else None
                
                # Alternative Logik: Wenn die Zahlen sehr nah beieinander sind,
                # nehme die Reihenfolge im Text als Maßstab
                if goal_amount and current_amount and abs(goal_amount - current_amount) < goal_amount * 0.1:
                    # Zahlen sind sehr ähnlich - verwende Text-Reihenfolge
                    unique_numbers = []
                    seen = set()
                    for num in extracted_numbers:
                        if num not in seen:
                            unique_numbers.append(num)
                            seen.add(num)
                    
                    if len(unique_numbers) >= 2:
                        goal_amount = unique_numbers[0]     # Erste im Text = Ziel
                        current_amount = unique_numbers[1]   # Zweite im Text = aktuell
            
            elif len(extracted_numbers) == 1:
                # Nur eine Zahl gefunden - könnte aktueller Stand sein
                current_amount = extracted_numbers[0]
                goal_amount = self.final_goal  # Verwende konfigurierten final_goal
            
            # Schritt 6: Erstelle strukturierte Ausgabe
            result_parts = []
            
            if goal_amount:
                result_parts.append(f"Goal: {goal_amount:,}")
            
            if current_amount:
                result_parts.append(f"Current: {current_amount:,}")
            
            # Füge bereinigten Text hinzu (gekürzt)
            if cleaned_text:
                # Kürze Text auf 300 Zeichen für bessere Übersichtlichkeit
                text_preview = cleaned_text[:300] + "..." if len(cleaned_text) > 300 else cleaned_text
                result_parts.append(f"Text: {text_preview}")
            
            result = " | ".join(result_parts)
            
            # Debug-Ausgabe
            if self.debug_mode:
                self.logger.debug(f"Processed numbers: {extracted_numbers}")
                self.logger.debug(f"Goal: {goal_amount}, Current: {current_amount}")
                self.logger.debug(f"Final result: {result[:100]}...")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error processing and cleaning text: {e}")
            return text  # Fallback: Gib ursprünglichen Text zurück
        
    def extract_goal_and_current_from_text(self, text: str) -> tuple[Optional[int], Optional[int]]:
        """
        Extrahiert Ziel und aktuellen Stand aus verarbeitetem Text
        Returns: (goal_amount, current_amount)
        """
        if not text:
            return None, None
        
        try:
            # Suche nach "Goal: X" und "Current: Y" Pattern
            goal_match = re.search(r'Goal:\s*(\d{1,3}(?:,\d{3})*)', text)
            current_match = re.search(r'Current:\s*(\d{1,3}(?:,\d{3})*)', text)
            
            goal_amount = None
            current_amount = None
            
            if goal_match:
                goal_amount = int(goal_match.group(1).replace(',', ''))
            
            if current_match:
                current_amount = int(current_match.group(1).replace(',', ''))
            
            return goal_amount, current_amount
        
        except Exception as e:
            self.logger.error(f"Error extracting goal and current from text: {e}")
            return None, None

    def compare_content(self, current_file: Path, previous_file: Path, label: str) -> bool:
        """Vergleicht aktuellen mit vorherigem Inhalt"""
        if not previous_file.exists():
            self.logger.warning(f"First time {label} check - no previous file")
            return False
        
        if not current_file.exists():
            self.logger.error(f"Current {label} file not found: {current_file}")
            return False
        
        current_goals = self.extract_goals_info(current_file)
        previous_goals = self.extract_goals_info(previous_file)
        
        if current_goals != previous_goals:
            self.logger.info(f"🎯 {label} CHANGE DETECTED!")
            
            # Zeige Unterschiede
            self.show_differences(previous_goals, current_goals, label)
            
            # Verarbeite Änderung
            asyncio.create_task(self.process_change(current_goals))
            return True
        
        self.logger.debug(f"{label}: No changes detected")
        return False

    def show_differences(self, previous: str, current: str, label: str):
        """Zeigt Unterschiede zwischen vorherigem und aktuellem Inhalt"""
        import difflib
        
        diff = list(difflib.unified_diff(
            previous.splitlines(),
            current.splitlines(),
            fromfile=f'Previous {label}',
            tofile=f'Current {label}',
            lineterm=''
        ))
        
        for line in diff[:10]:  # Zeige nur erste 10 Zeilen
            print(line)

    async def process_change(self, current_goals: str):
        """Verarbeitet erkannte Änderungen"""
        # Hole Episode-Informationen
        episode_info = await self.get_episode_info()
        if not episode_info:
            return
        
        # Berechne neuen Zeitpunkt
        donation_amount = self.extract_donation_amount(current_goals)
        if donation_amount:
            new_time = self.calculate_adjusted_time(donation_amount, episode_info)  # Jetzt mit episode_info
            if new_time:                
                # Prüfe ob Ziel erreicht
                if self.is_goal_reached(current_goals) and datetime.timestamp(datetime.now()) >= datetime.timestamp(datetime.fromisoformat(new_time)):
                    self.logger.info("🏆 GOAL POSSIBLY REACHED!")
                    await self.reschedule_episode(episode_info, donation_amount=self.final_goal, publish_now=True, new_publish_date=new_time)
                else:
                    await self.reschedule_episode(episode_info, donation_amount, new_publish_date=new_time)                
                # Zusätzliche deutsche Zeitanzeige für Benutzer
                german_time = self.convert_to_german_time(new_time)
                self.logger.info(f"🇩🇪 German time: {german_time}")
            # Telegram-Backend verwenden
            if self.use_telegram_backend:
                await self.send_donation_update(episode_info, donation_amount)
                await self.call_sync_episodes()                    

    async def get_episode_info(self) -> Optional[Dict]:
        """Holt Episode-Informationen von der API"""
        try:
            response = self.session.get(
                self.get_episode_url,
                headers={'X-API-KEY': self.api_key, 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            episodes = response.json()
            if episodes:
                # Sortiere nach Veröffentlichungsdatum und nimm das erste
                latest_episode = sorted(episodes, key=lambda x: x['publish_date'])[0]
                return latest_episode
            
        except Exception as e:
            self.logger.error(f"Error fetching episode info: {e}")
        
        return None

    def is_goal_reached(self, content: str) -> bool:
        """Prüft ob das Ziel erreicht wurde"""
        goal_patterns = [
            r'100%',
            r'Abgeschlossen'
        ]
        
        for pattern in goal_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        
        return not content.strip()  # Leerer Content könnte auch Ziel erreicht bedeuten

    def extract_donation_amount(self, content: str) -> Optional[int]:
        """Extrahiert den Spendenbetrag aus dem verarbeiteten Inhalt"""
        if not content:
            return None
        
        # Versuche zuerst strukturierte Extraktion
        goal, current = self.extract_goal_and_current_from_text(content)
        
        if current is not None:
            self.logger.debug(f"Extracted current donation amount: {current:,}")
            return current
        
        if goal is not None and goal != self.final_goal:
            # Falls kein aktueller Stand aber ein Ziel gefunden wurde
            self.logger.debug(f"Using goal as current amount: {goal:,}")
            return goal
        
        # Fallback auf ursprüngliche Methode
        return self._extract_donation_amount_fallback(content)

    def _extract_donation_amount_fallback(self, content: str) -> Optional[int]:
        """Fallback-Methode für Donation-Extraktion"""
        # Hier die ursprüngliche extract_donation_amount Logik als Fallback
        patterns = [
            r'(\d+(?:,\d{3})*)\s*(?:sats?|satoshis?)\b',
            r'(\d+(?:\.\d+)?)\s*btc\b',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                try:
                    amount_str = match.replace(',', '')
                    if 'btc' in pattern.lower():
                        return int(float(amount_str) * 100_000_000)
                    else:
                        return int(float(amount_str))
                except (ValueError, TypeError):
                    continue
        
        return None

    def calculate_adjusted_time(self, donation_satoshis: int, episode_info: Dict) -> str:
        """Berechnet den angepassten Veröffentlichungszeitpunkt basierend auf dem ursprünglichen Datum"""
        if donation_satoshis <= 0:
            return ""
        
        try:
            # Parse das ursprüngliche publish_date aus episode_info
            original_publish_date_str = episode_info.get('publish_date', '')
            if not original_publish_date_str:
                self.logger.error("No publish_date found in episode_info")
                return ""
            
            # Parse das ursprüngliche Datum (verschiedene Formate unterstützen)
            try:
                # Versuche ISO Format mit Z (UTC)
                if original_publish_date_str.endswith('Z'):
                    original_datetime = datetime.fromisoformat(original_publish_date_str[:-1]).replace(tzinfo=timezone.utc)
                else:
                    # Versuche ISO Format oder verwende dateutil parser als Fallback
                    try:
                        original_datetime = datetime.fromisoformat(original_publish_date_str)
                    except ValueError:
                        original_datetime = date_parser.parse(original_publish_date_str)
            except Exception as parse_error:
                self.logger.error(f"Failed to parse publish_date '{original_publish_date_str}': {parse_error}")
                return ""
            
            # Stelle sicher, dass wir UTC haben
            if original_datetime.tzinfo is None:
                original_datetime = original_datetime.replace(tzinfo=timezone.utc)
            elif original_datetime.tzinfo != timezone.utc:
                original_datetime = original_datetime.astimezone(timezone.utc)
            
            self.logger.debug(f"Original publish date: {original_datetime.isoformat()}")
            
            # Berechnung: satoshis_per_minute Satoshis = 1 Minute
            minutes_to_subtract = donation_satoshis // self.satoshis_per_minute
            hours_to_subtract = minutes_to_subtract / 60
            
            # Begrenzung auf Maximum
            max_minutes = self.max_reduction * 60
            if minutes_to_subtract > max_minutes:
                minutes_to_subtract = max_minutes
                hours_to_subtract = self.max_reduction
                self.logger.info(f"⚠️ Maximum reduction applied: {self.max_reduction} hours")
            
            # Neue Zeit berechnen (ausgehend von start_time)
            new_time_hours = self.start_time - hours_to_subtract
            new_time_hours = round(new_time_hours, 2)
            # Auf früheste Zeit begrenzen
            if new_time_hours < self.earliest_time:
                new_time_hours = self.earliest_time
                self.logger.warning("⚠️ Earliest possible time reached!")
            
            # Behandle Tag-Übertrag (falls neue Zeit vor Mitternacht liegt)
            adjusted_days = 0
            if new_time_hours < 0:
                # Zeit geht in den vorherigen Tag
                adjusted_days = -1
                new_time_hours += 24
            elif new_time_hours >= 24:
                # Zeit geht in den nächsten Tag
                adjusted_days = int(new_time_hours // 24)
                new_time_hours = new_time_hours % 24
            
            # Zeit formatieren
            hours = int(new_time_hours)
            minutes = int((new_time_hours - hours) * 60)
            
            # Neues Datum/Zeit erstellen: Ursprüngliches Datum + angepasste Zeit + eventuelle Tage-Verschiebung
            new_publish_date = original_datetime.replace(
                hour=hours, 
                minute=minutes, 
                second=0, 
                microsecond=0
            ) + timedelta(days=adjusted_days)
            
            # Berechne Statistiken
            original_goal_diff = self.final_goal - donation_satoshis
            time_reduction_minutes = minutes_to_subtract
            time_reduction_hours = time_reduction_minutes / 60
            
            # Logging mit detaillierten Informationen
            self.logger.info(f"📊 Donation amount: {donation_satoshis:,} Satoshis")
            self.logger.info(f"📊 Target goal: {self.final_goal:,} Satoshis") 
            self.logger.info(f"📊 Remaining to goal: {original_goal_diff:,} Satoshis")
            self.logger.info(f"⏰ Time reduction: {time_reduction_hours:.2f} hours ({time_reduction_minutes} minutes)")
            self.logger.info(f"📅 Original publish time: {original_datetime.isoformat()}")
            self.logger.info(f"🎯 New publish time: {new_publish_date.isoformat()}")
            
            if adjusted_days != 0:
                day_text = "day earlier" if adjusted_days < 0 else f"{adjusted_days} days later"
                self.logger.info(f"📅 Date adjustment: {day_text}")
            
            # Zusätzliche Info bei Maximum
            max_satoshis = max_minutes * self.satoshis_per_minute
            if donation_satoshis >= max_satoshis:
                self.logger.info(f"✅ Maximum reduction reached ({max_satoshis:,}+ Satoshis = {self.max_reduction} hours reduction)")
            
            if new_publish_date.isoformat() != original_datetime.isoformat():
                return new_publish_date.isoformat()
            else:
                return ""            
            
        except Exception as e:
            self.logger.error(f"Error calculating adjusted time: {e}")
            return ""
        
    async def reschedule_episode(self, episode_info: Dict, donation_amount: int, publish_now: bool = False, new_publish_date: str = None):
        """Plant Episode um"""
        try:
            data = {"episode_id": episode_info['episode_id']}
            
            if publish_now:
                data["publish_now"] = True
                action = "Published"
            else:
                data["publish_date"] = new_publish_date
                action = f"Rescheduled to {new_publish_date}"
            
            response = self.session.post(
                self.post_episode_url,
                json=data,
                headers={'X-API-KEY': self.api_key, 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            self.logger.info(f"Episode {episode_info['episode_nr']} {action}")
            
            # Telegram-Benachrichtigung senden
            if self.use_telegram and donation_amount >= self.notification_threshold:
                await self.send_telegram_notification(episode_info, action)
                
        except Exception as e:
            self.logger.error(f"Error rescheduling episode: {e}")

    async def send_telegram_notification(self, episode_info: Dict, action: str):
        """Sendet Telegram-Benachrichtigung"""
        if not self.use_telegram:
            return
        
        try:
            message = f"""<b>Release-Boosting Update:</b>
Episode: {episode_info['title']}
Action: {action}
"""      
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_notification': True
            }
            
            if self.topic_id:
                data['message_thread_id'] = self.topic_id
            
            response = self.session.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json=data
            )
            response.raise_for_status()
            
        except Exception as e:
            self.logger.error(f"Error sending Telegram notification: {e}")

    async def send_donation_update(self, episode_info: Dict, donation_amount: int):
        """Sendet Spenden ins Telegram Datenbank Backend"""
        if not self.use_telegram_backend:
            return
        
        try:
            data = {"episode_id": episode_info['episode_id'],
                    "amount": donation_amount}
                    
            response = self.session.post(
                self.telegram_bot_update_donations_url,
                json=data,
                headers={'X-API-KEY': self.webhook_token, 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            self.logger.info(f"Donation for episode {episode_info['episode_nr']} updated")
            
        except Exception as e:
            self.logger.error(f"Error sending update donation: {e}")    

    async def call_sync_episodes(self):
        """Aktualisiert Telegram Datenbank Backend"""
        if not self.use_telegram_backend:
            return
        
        try:    
            response = self.session.post(
                self.telegram_bot_sync_episodes_url,
                headers={'X-API-KEY': self.webhook_token, 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            self.logger.info(f"Telegram Bot Backend synced")
            
        except Exception as e:
            self.logger.error(f"Error syncing Telegram Bot Backend: {e}")                     

    def convert_to_german_time(self, utc_datetime_str: str) -> str:
        """Konvertiert UTC Zeit zu deutscher Zeit für Anzeige"""
        try:
            if utc_datetime_str.endswith('Z'):
                utc_dt = datetime.fromisoformat(utc_datetime_str[:-1]).replace(tzinfo=timezone.utc)
            else:
                utc_dt = datetime.fromisoformat(utc_datetime_str).replace(tzinfo=timezone.utc)
            
            # Konvertiere zu deutscher Zeit (Europe/Berlin berücksichtigt automatisch Sommer/Winterzeit)
            german_tz = pytz.timezone('Europe/Berlin')
            german_dt = utc_dt.astimezone(german_tz)
            
            return german_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception as e:
            self.logger.error(f"Error converting to German time: {e}")
            return utc_datetime_str

    def cleanup(self, signum=None, frame=None):
        """Cleanup beim Beenden"""
        self.logger.info("Shutting down monitor...")
        
        # Töte eventuell laufende Browser-Prozesse
        try:
            subprocess.run(['pkill', '-f', 'chrome'], check=False)
        except:
            pass
        
        # Entferne temporäre Dateien
        try:
            for tmp_file in self.temp_dir.glob('*.tmp'):
                tmp_file.unlink()
        except:
            pass
        
        sys.exit(0)

    async def monitor_loop(self):
        """Haupt-Monitoring-Schleife"""
        self.logger.info("🚀 Geyser Fund Monitor started")
        self.logger.info(f"URL: {self.url}")
        self.logger.info(f"Check interval: {self.check_interval}s")
        self.logger.info(f"JavaScript support: {'✅' if self.use_javascript else '❌'}")
        
        check_count = 0
        js_failures = 0
        max_js_failures = 3
        
        while True:
            try:
                check_count += 1
                self.logger.info(f"Check #{check_count}")
                
                html_changed = False
                js_changed = False
                
                # HTML Check
                self.logger.info("📄 Fetching HTML content...")
                if await self.fetch_html_content(self.current_file):
                    if self.current_file.stat().st_size > 0:
                        html_changed = self.compare_content(
                            self.current_file, self.previous_file, "HTML"
                        )
                        shutil.copy2(self.current_file, self.previous_file)
                
                # JavaScript Check
                if self.use_javascript:
                    self.logger.info("🔧 Fetching JavaScript content...")
                    if await self.fetch_js_content(self.current_js_file):
                        js_failures = 0
                        if self.current_js_file.stat().st_size > 0:
                            js_changed = self.compare_content(
                                self.current_js_file, self.previous_js_file, "JAVASCRIPT"
                            )
                            shutil.copy2(self.current_js_file, self.previous_js_file)
                    else:
                        js_failures += 1
                        if js_failures >= max_js_failures:
                            self.logger.warning("🔄 Switching to fallback mode (HTML only)")
                            self.use_javascript = False
                
                # Zusammenfassung
                if html_changed or js_changed:
                    self.logger.info("🎉 Changes detected!")
                    # Hier könnten weitere Benachrichtigungen erfolgen
                else:
                    self.logger.info("📊 No changes detected")
                
                self.logger.info(f"⏰ Waiting {self.check_interval} seconds...")
                await asyncio.sleep(self.check_interval)
            except KeyboardInterrupt:
                self.cleanup()

async def main():
    """Hauptfunktion"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Geyser Fund Monitor')
    parser.add_argument('--config', default='Geyser_Monitor.conf',
                        help='Configuration file path')
    parser.add_argument('--no-js', action='store_true',
                        help='Disable JavaScript rendering')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode')
    
    args = parser.parse_args()
    
    # Erstelle Monitor-Instanz
    monitor = GeyserMonitor(args.config)
    
    # Überschreibe Konfiguration mit CLI-Argumenten
    if args.no_js:
        monitor.use_javascript = False
    if args.debug:
        monitor.debug_mode = True
        monitor.logger.setLevel(logging.DEBUG)
    
    try:
        await monitor.monitor_loop()
    except KeyboardInterrupt:
        monitor.cleanup()

if __name__ == "__main__":
    asyncio.run(main())