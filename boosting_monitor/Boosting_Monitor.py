#!/usr/bin/env python3
"""
Boosting Monitor - Python Version
"""
import asyncio
import logging
import signal
import sys
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict
import requests
import configparser
from dateutil import parser as date_parser
import pytz
from abc import ABC, abstractmethod
import asyncpg
from contextlib import asynccontextmanager

class DatabaseConnection(ABC):
    """Abstract base class für Datenbankverbindungen"""
    
    @abstractmethod
    async def get_connection(self):
        pass

class PostgreSQLConnection(DatabaseConnection):
    """PostgreSQL Datenbankverbindung"""
    
    def __init__(self, config):
        self.host = config['postgresql']['host']
        self.port = int(config['postgresql']['port'])
        self.database = config['postgresql']['database']
        self.user = config['postgresql']['user']
        self.password = config['postgresql']['password']
        self.pool = None
        
    async def get_connection(self):
        """Erstellt oder gibt bestehende PostgreSQL Verbindung zurück"""
        if self.pool is None:
            try:
                self.pool = await asyncpg.create_pool(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.user,
                    password=self.password,
                    min_size=5,
                    max_size=20
                )
                logging.info("PostgreSQL Connection Pool erfolgreich erstellt")
            except Exception as e:
                logging.error(f"PostgreSQL Verbindungsfehler: {e}")
                raise
        return self.pool
    
    async def close(self):
        """Schließt den Connection Pool"""
        if self.pool:
            await self.pool.close()
            logging.info("PostgreSQL Connection Pool geschlossen")

class SQLiteConnection(DatabaseConnection):
    """SQLite Datenbankverbindung"""
    
    def __init__(self, config):
        self.db_path = config['database']['db_path']
        self.connection = None
        
    async def get_connection(self):
        """Erstellt oder gibt bestehende SQLite Verbindung zurück"""
        if self.connection is None:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row  # Für dict-ähnliche Zugriffe
            logging.info(f"SQLite Verbindung zu {self.db_path} hergestellt")
        return self.connection
    
    async def create_tables(self):
        """Erstellt notwendige Tabellen in SQLite"""
        with await self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS "episodes" (
                    "episode_id"	TEXT,
                    "episode_nr"	INTEGER,                       
                    "title"	TEXT,
                    "description"	TEXT,
                    "status" INT,                       
                    "publish_date"	TEXT,
                    "duration"	TEXT,
                    "enclosure_url"	TEXT,
                    "season_nr"	INTEGER,
                    "link"	TEXT,
                    "image_url"	TEXT,
                    "donations"	INTEGER DEFAULT 0,
                    PRIMARY KEY("episode_id")
                    );
            """)
            conn.commit()

    async def close(self):
        """Schließt die SQLite Verbindung"""
        if self.connection:
            self.connection.close()
            logging.info("SQLite Verbindung geschlossen")

class DatabaseManager:
    """Manager für dynamische Datenbankverbindungen mit Fallback"""
    
    def __init__(self, config_file='Boosting_Monitor.conf'): 
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.db_connection = None
    
    async def _initialize_connection(self):
        """Initialisiert Datenbankverbindung basierend auf Konfiguration"""        
        db_mode = self.config['database']['db_mode'].lower()
        
        if db_mode == 'postgresql':
            try:
                self.db_connection = PostgreSQLConnection(self.config)
                # Teste die Verbindung
                await self.db_connection.get_connection()
                logging.info("PostgreSQL als primäre Datenbank initialisiert")
            except Exception as e:
                logging.warning(f"PostgreSQL nicht verfügbar: {e}")
                logging.info("Fallback auf SQLite")
                self.db_connection = SQLiteConnection(self.config)
        else:
            self.db_connection = SQLiteConnection(self.config)
            logging.info("SQLite als Datenbank gewählt")
            
    @asynccontextmanager
    async def get_db_connection(self):
        """Async context manager für sichere Datenbankoperationen"""
        if isinstance(self.db_connection, PostgreSQLConnection):
            pool = await self.db_connection.get_connection()
            async with pool.acquire() as conn:
                try:
                    async with conn.transaction():
                        yield conn
                except Exception as e:
                    logging.error(f"PostgreSQL Datenbankfehler: {e}")
                    raise
        else:
            # SQLite
            conn = await self.db_connection.get_connection()
            try:
                yield conn
            except Exception as e:
                conn.rollback()
                logging.error(f"SQLite Datenbankfehler: {e}")
                raise
    
    async def execute_query(self, query, params=None):
        """Führt eine SQL-Abfrage aus"""
        async with self.get_db_connection() as conn:
            if isinstance(self.db_connection, PostgreSQLConnection):
                # asyncpg verwendet $1, $2, etc. für Parameter
                if params:
                    if query.strip().upper().startswith('SELECT'):
                        return await conn.fetch(query, *params)
                    else:
                        result = await conn.execute(query, *params)
                        # asyncpg gibt zurück wie viele Zeilen betroffen waren
                        return int(result.split()[-1]) if result else 0
                else:
                    if query.strip().upper().startswith('SELECT'):
                        return await conn.fetch(query)
                    else:
                        result = await conn.execute(query)
                        return int(result.split()[-1]) if result else 0
            else:
                # SQLite (synchron)
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                
                if query.strip().upper().startswith('SELECT'):
                    return cursor.fetchall()
                else:
                    conn.commit()
                    return cursor.rowcount
    
    async def get_all_episodes(self):
        """Alle Episoden abrufen"""
        query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url FROM episodes ORDER BY episode_nr"
        if isinstance(self.db_connection, PostgreSQLConnection):
            query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url FROM episodes ORDER BY episode_nr"
        return await self.execute_query(query)
    
    async def get_episode(self, episode_id):
        """Einzelne Episode abrufen"""
        query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url FROM episodes WHERE episode_id = ?"
        if isinstance(self.db_connection, PostgreSQLConnection):
            query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url FROM episodes WHERE episode_id = $1"
        return await self.execute_query(query, (episode_id,))

    async def get_next_episode(self):
        """Nächste Episode abrufen"""
        query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url from episodes where publish_date = (SELECT MIN(publish_date) from episodes where status = 1)"
        if isinstance(self.db_connection, PostgreSQLConnection):
            query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url from episodes where publish_date = (SELECT MIN(publish_date) from episodes where status = 1)"
        return await self.execute_query(query)
    
    async def insert_episode(self, episode):
        """Neue Episode einfügen"""
        query = "INSERT INTO episodes (episode_id, episode_nr, title, description, status, publish_date, duration, enclosure_url, season_nr, link, image_url ) VALUES (?, ?, ?, ?, ?, datetime(?,'localtime'),?, ?, ?, ?, ?)"
        if isinstance(self.db_connection, PostgreSQLConnection):
            query = "INSERT INTO episodes (episode_id, episode_nr, title, description, status, publish_date, duration, enclosure_url, season_nr, link, image_url ) VALUES ($1, $2, $3, $4, $5, to_timestamp(regexp_replace(REPLACE($6, 'T', ' '), '[.]\d*', ''), 'YYYY-MM-DD HH24:MI:SS')+ interval '2 hour', $7, $8, $9, $10, $11)"
        return await self.execute_query(query, (episode.get('episode_id'), episode.get('episode_nr'), episode.get('title'), episode.get('description'), episode.get('status'), episode.get('publish_date'), episode.get('duration'), episode.get('enclosure_url'), episode.get('season_nr'), episode.get('link'), episode.get('image_url')))
   
    async def update_episode(self, episode):
        """Episoden aktualisieren"""
        query = "UPDATE episodes set title = ?, description = ?, status = ?, publish_date = datetime(?,'localtime'), duration = ?, enclosure_url = ?, season_nr = ?, link = ?, image_url = ? WHERE episode_id = ?"
        if isinstance(self.db_connection, PostgreSQLConnection):
            query = "UPDATE episodes set title = $1, description = $2, status = $3, publish_date = to_timestamp(regexp_replace(REPLACE($4, 'T', ' '), '[.]\d*', ''), 'YYYY-MM-DD HH24:MI:SS')+ interval '2 hour', duration = $5, enclosure_url = $6, season_nr = $7, link = $8, image_url = $9 WHERE episode_id = $10"
        return await self.execute_query(query, (episode.get('title'), episode.get('description'), episode.get('status'), episode.get('publish_date'), episode.get('duration'), episode.get('enclosure_url'), episode.get('season_nr'), episode.get('link'), episode.get('image_url'), episode.get('episode_id')))

    async def update_donations(self, amount, publish_date, episode_id):
        """Spendenstand aktualisieren"""
        query = "UPDATE episodes set donations = ?, publish_date = datetime(?,'localtime') WHERE episode_id = ?"
        if isinstance(self.db_connection, PostgreSQLConnection):
            query = "UPDATE episodes set donations = $1, publish_date = to_timestamp(regexp_replace(REPLACE($2, 'T', ' '), '[.]\d*', ''), 'YYYY-MM-DD HH24:MI:SS')+ interval '2 hour' WHERE episode_id = $3"
        return await self.execute_query(query, (amount, publish_date, episode_id))
    
    async def close(self):
        """Schließt die Datenbankverbindung"""
        if self.db_connection:
            await self.db_connection.close()            

class PodHomeEpisode:
    def __init__(self, episode: Dict):
        self.episode_id = episode.get('episode_id', '1')
        self.episode_nr = int(episode.get('episode_nr', '1'))
        self.title = episode.get('title', '')
        self.description = episode.get('description', '')
        self.status = int(episode.get('status', '0'))
        self.publish_date = episode.get('publish_date', '')
        self.duration = episode.get('duration', '')
        self.enclosure_url = episode.get('enclosure_url', '')
        self.season_nr = int(episode.get('season_nr', '1'))
        self.image_url = episode.get('image_url', '')
    
    def setPublishdate(self, publishDate: str):
        self.publish_date = publishDate

class Episode:
    def __init__(self, episode: Dict):
        self.episode_id = episode[0].get('episode_id', '')
        self.episode_nr = int(episode[0].get('episode_nr', '1'))
        self.title = episode[0].get('title', '')
        self.description = episode[0].get('description', '')
        self.status = int(episode[0].get('status', '0'))
        self.publish_date = episode[0].get('publish_date', '')
        self.duration = episode[0].get('duration', '')
        self.enclosure_url = episode[0].get('enclosure_url', '')
        self.season_nr = int(episode[0].get('season_nr', '1'))
        self.link = episode[0].get('link', '')
        self.image_url = episode[0].get('image_url', '')
        self.donations = int(episode[0].get('donations', '0'))

class AlbyWalletBalance:
    def __init__(self, wallet_balance: Dict):
        self.balance = int(wallet_balance.get('balance', ''))
        self.unit = wallet_balance.get('unit', '')
        self.currency = wallet_balance.get('currency', '')

class BoostingMonitor:
    def __init__(self, config_path: str = "Boosting_Monitor.conf"):
        self.config = self.load_config(config_path)
        
        current_directory = os.getcwd()
        print("Current directory using os.getcwd():", current_directory)
        # Konfiguration
        self.alby_wallet_api_token = self.config.get('monitoring', 'alby_wallet_api_token')
        self.alby_wallet_api_url = self.config.get('monitoring', 'alby_wallet_api_url')
        self.check_interval = self.config.getint('monitoring', 'check_interval', fallback=30)
        self.max_retries = self.config.getint('monitoring', 'max_retries', fallback=3)
        self.debug_mode = self.config.getboolean('monitoring', 'debug_mode', fallback=False)
        
        # Dateipfade
        self.temp_dir = Path(self.config.get('database', 'temp_dir', fallback='/tmp/boosting_monitor'))
        
        # API-Konfiguration PodHome
        self.podhome_api_key = self.config.get('api', 'podhome_api_key')
        self.podhome_get_episode_url = self.config.get('api', 'podhome_get_episode_url')
        self.podhome_post_episode_url = self.config.get('api', 'podhome_post_episode_url')
        
        # Telegram-Notification-Konfiguration
        self.use_telegram = self.config.getboolean('telegram_notification', 'enabled', fallback=False)
        self.notification_threshold = self.config.getint('telegram_notification', 'notification_threshold')
        if self.use_telegram:
            self.bot_token = self.config.get('telegram_notification', 'bot_token')
            self.chat_id = self.config.get('telegram_notification', 'chat_id')
            self.topic_id = self.config.get('telegram_notification', 'topic_id', fallback=None)

        # Berechnungsparameter
        self.final_goal = self.config.getint('calculation', 'final_goal')
        self.satoshis_per_minute = self.config.getint('calculation', 'satoshis_per_minute', fallback=21)
        self.max_reduction = self.config.getint('calculation', 'max_reduction_hours', fallback=12)
        self.earliest_time = self.config.getfloat('calculation', 'earliest_time', fallback=10)
        self.start_time = self.config.getfloat('calculation', 'start_time', fallback=22)
        
        self.session = requests.Session()

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
        self.logger = logging.getLogger('boosting_monitor')
        self.logger.setLevel(log_level)
        
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        
        # File Handler
        file_handler = logging.FileHandler(self.temp_dir / 'boosting_monitor.log')
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
        
    async def check_for_changes(self) -> bool:
        """Verarbeitet erkannte Änderungen"""
        # Hole Episoden-Informationen aus der PodHome API
        current_episode = await self.get_podhome_episode()
        # Hole Episoden-Informationen aus der Telegram Backend Datenbank
        previous_episode =  await self.get_previous_episode()
        # Hole Walletinformationen aus der Alby API
        wallet_balance = await self.get_alby_wallet_balance()
        if not current_episode or not previous_episode or not wallet_balance:
            return

        # Berechne neuen Zeitpunkt
        if wallet_balance.balance != previous_episode.donations:
            self.logger.info("🎉 Changes detected!")
            new_time = self.calculate_adjusted_time(wallet_balance.balance, current_episode) 
            if new_time:                
                # Prüfe ob Ziel erreicht
                current_episode.setPublishdate(new_time)
                if self.is_goal_reached(wallet_balance.balance) and datetime.timestamp(datetime.now()) >= datetime.timestamp(datetime.fromisoformat(new_time)):
                    self.logger.info("🏆 GOAL REACHED!")
                    await self.podhome_reschedule_episode(current_episode, donation_amount=self.final_goal, publish_now=True, new_publish_date=new_time)
                else:
                    await self.podhome_reschedule_episode(current_episode, donation_amount=wallet_balance.balance, new_publish_date=new_time)                
                # Zusätzliche deutsche Zeitanzeige für Benutzer
                german_time = self.convert_to_german_time(new_time)
                self.logger.info(f"🇩🇪 German time: {german_time}")
                await self.update_donation(current_episode, wallet_balance.balance)
            return True
        else:
            self.logger.info("📊 No changes detected")
            return False               

    async def get_podhome_episode(self) -> PodHomeEpisode:
        """Holt Episoden-Informationen von der PodHome API"""
        try:
            response = self.session.get(
                self.podhome_get_episode_url,
                headers={'X-API-KEY': self.podhome_api_key, 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            planned_episodes = response.json()
            if planned_episodes:
                # Sortiere nach Veröffentlichungsdatum und nimm das erste
                return PodHomeEpisode(sorted(planned_episodes, key=lambda x: x['publish_date'])[0])
            
        except Exception as e:
            self.logger.error(f"Error fetching episode info: {e}")
        
        return None
    
    async def get_previous_episode(self) -> Episode:
        """Holt Episoden-Informationen aus der Datenbank"""
        try:
            planned_episodes = await db.get_next_episode()
            
            if planned_episodes:
                return Episode(planned_episodes)
            
        except Exception as e:
            self.logger.error(f"Error fetching episode info: {e}")
        
        return None
    
    async def get_alby_wallet_balance(self) -> AlbyWalletBalance:
        """Holt aktuellen Wallet Stand von der Alby API"""
        try:
            response = self.session.get(
                self.alby_wallet_api_url,
                headers={'Authorization': self.alby_wallet_api_token, 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            wallet_balance = response.json()
            if wallet_balance:
                # Create AlbyWalletBalance object
                return AlbyWalletBalance(wallet_balance)
            
        except Exception as e:
            self.logger.error(f"Error fetching Alby wallet balance: {e}")
        
        return None

    def is_goal_reached(self, current_balance: int) -> bool:
        """Prüft ob das Ziel erreicht wurde"""
        if current_balance >= self.final_goal:
            return True
        else:
            return False

    def calculate_adjusted_time(self, donation_satoshis: int, episode: PodHomeEpisode) -> str:
        """Berechnet den angepassten Veröffentlichungszeitpunkt basierend auf dem ursprünglichen Datum"""
        try:
            # Parse das ursprüngliche publish_date aus episode
            original_publish_date_str = episode.publish_date
            if not original_publish_date_str:
                self.logger.error("No publish_date found in episode")
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
            
            # KORRIGIERTE BERECHNUNG: Arbeite direkt mit Minuten
            minutes_to_subtract = donation_satoshis // self.satoshis_per_minute
            
            # Begrenzung auf Maximum (in Minuten)
            max_minutes = self.max_reduction * 60
            if minutes_to_subtract > max_minutes:
                minutes_to_subtract = max_minutes
                self.logger.info(f"⚠️ Maximum reduction applied: {self.max_reduction} hours ({max_minutes} minutes)")
            
            # Debug: Zeige exakte Berechnung
            self.logger.debug(f"Satoshis: {donation_satoshis}, Per minute: {self.satoshis_per_minute}")
            self.logger.debug(f"Minutes to subtract: {minutes_to_subtract}")
            
            # Konvertiere start_time zu Minuten für präzise Berechnung
            start_time_minutes = int(self.start_time * 60)  # z.B. 20.0 -> 1200 Minuten
            earliest_time_minutes = int(self.earliest_time * 60)  # z.B. 18.0 -> 1080 Minuten
            
            # Berechne neue Zeit in Minuten
            new_time_minutes = start_time_minutes - minutes_to_subtract
            
            # Auf früheste Zeit begrenzen
            if new_time_minutes < earliest_time_minutes:
                new_time_minutes = earliest_time_minutes
                self.logger.warning("⚠️ Earliest possible time reached!")
            
            # Behandle Tag-Übertrag
            adjusted_days = 0
            if new_time_minutes < 0:
                # Zeit geht in den vorherigen Tag
                adjusted_days = -1
                new_time_minutes += 24 * 60  # 24 Stunden = 1440 Minuten
            elif new_time_minutes >= 24 * 60:
                # Zeit geht in den nächsten Tag
                adjusted_days = new_time_minutes // (24 * 60)
                new_time_minutes = new_time_minutes % (24 * 60)
            
            # Konvertiere Minuten zurück zu Stunden und Minuten
            hours = new_time_minutes // 60
            minutes = new_time_minutes % 60
            
            # Debug: Zeige exakte Konvertierung
            self.logger.debug(f"New time in minutes: {new_time_minutes}")
            self.logger.debug(f"Converted to: {hours}h {minutes}m")
            
            # Neues Datum/Zeit erstellen
            new_publish_date = original_datetime.replace(
                hour=int(hours), 
                minute=int(minutes), 
                second=0, 
                microsecond=0
            ) + timedelta(days=adjusted_days)
            
            # Berechne Statistiken
            original_goal_diff = self.final_goal - donation_satoshis
            time_reduction_hours = minutes_to_subtract / 60
            
            # Logging mit detaillierten Informationen
            self.logger.info(f"📊 Donation amount: {donation_satoshis:,} Satoshis")
            self.logger.info(f"📊 Target goal: {self.final_goal:,} Satoshis") 
            self.logger.info(f"📊 Remaining to goal: {original_goal_diff:,} Satoshis")
            self.logger.info(f"⏰ Time reduction: {time_reduction_hours:.2f} hours ({minutes_to_subtract} minutes)")
            self.logger.info(f"📅 Original publish time: {original_datetime.isoformat()}")
            self.logger.info(f"🎯 New publish time: {new_publish_date.isoformat()}")
            
            if adjusted_days != 0:
                day_text = "day earlier" if adjusted_days < 0 else f"{adjusted_days} days later"
                self.logger.info(f"📅 Date adjustment: {day_text}")
            
            # Zusätzliche Info bei Maximum
            max_satoshis = max_minutes * self.satoshis_per_minute
            if donation_satoshis >= max_satoshis:
                self.logger.info(f"✅ Maximum reduction reached ({max_satoshis:,}+ Satoshis = {self.max_reduction} hours reduction)")
            
            # Rückgabe nur wenn sich die Zeit geändert hat
            if new_publish_date.isoformat() != original_datetime.isoformat():
                return new_publish_date.isoformat()
            else:
                return ""            
            
        except Exception as e:
            self.logger.error(f"Error calculating adjusted time: {e}")
            return ""
        
    async def podhome_reschedule_episode(self, episode: PodHomeEpisode, donation_amount: int, publish_now: bool = False, new_publish_date: str = None):
        """Plant PodHomeEpisode um"""
        try:
            data = {"episode_id": episode.episode_id}
            
            if publish_now:
                data["publish_now"] = True
                action = "Published"
            else:
                data["publish_date"] = new_publish_date
                action = f"Rescheduled to {self.convert_to_german_time(new_publish_date)}"
            
            response = self.session.post(
                self.podhome_post_episode_url,
                json=data,
                headers={'X-API-KEY': self.podhome_api_key, 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            self.logger.info(f"PodHomeEpisode {episode.episode_nr} {action}")
            
            # Telegram-Benachrichtigung senden
            if self.use_telegram and donation_amount >= self.notification_threshold:
                await self.send_telegram_notification(episode, action)
                
        except Exception as e:
            self.logger.error(f"Error rescheduling episode: {e}")

    async def send_telegram_notification(self, episode: PodHomeEpisode, action: str):
        """Sendet Telegram-Benachrichtigung"""
        if not self.use_telegram:
            return
        
        try:
            message = f"""<b>Release-Boosting Update:</b>
PodHomeEpisode: {episode.title}
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

    async def update_donation(self, episode: PodHomeEpisode, donation_amount: int):
        """Aktualisiert Spenden in der Datenbank"""        
        try:
            await db.update_donations(amount=donation_amount,publish_date=episode.publish_date, episode_id=episode.episode_id)
            self.logger.info(f"Donation for episode {episode.episode_nr} updated")
            
        except Exception as e:
            self.logger.error(f"Error update donation: {e}")                    

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
                
        # Entferne temporäre Dateien
        try:
            for tmp_file in self.temp_dir.glob('*.tmp'):
                tmp_file.unlink()
        except:
            pass     
        sys.exit(0)

    async def monitor_loop(self):
        """Haupt-Monitoring-Schleife"""
        self.logger.info("🚀 BoostingMonitor started")
        self.logger.info(f"Check interval: {self.check_interval}s")
        
        check_count = 0
        
        while True:
            try:
                check_count += 1
                self.logger.info(f"Check #{check_count}")

                await db._initialize_connection()  
                # Wallet Check
                self.logger.info("🔧 Getting next episode ...")
                await self.check_for_changes()
                
                self.logger.info(f"⏰ Waiting {self.check_interval} seconds...")
                await asyncio.sleep(self.check_interval)
            except KeyboardInterrupt:
                self.cleanup()
                db.close()

db = DatabaseManager('Boosting_Monitor.conf')

async def main():
    """Hauptfunktion"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Boosting Monitor')
    parser.add_argument('--config', default='Boosting_Monitor.conf',
                        help='Configuration file path')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode')
    
    args = parser.parse_args()
    
    # Erstelle Monitor-Instanz
    monitor = BoostingMonitor(args.config)
    
    # Überschreibe Konfiguration mit CLI-Argumenten
    if args.debug:
        monitor.debug_mode = True
        monitor.logger.setLevel(logging.DEBUG)
    
    try:
        await monitor.monitor_loop()
    except KeyboardInterrupt:
        monitor.cleanup()

if __name__ == "__main__":
    asyncio.run(main())