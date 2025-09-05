"""
Hauptmanager für Datenbankoperationen
"""
import configparser
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple, Union

from .connections.postgresql import PostgreSQLConnection
from .connections.sqlite import SQLiteConnection
from .exceptions import DatabaseError, ConfigurationError


class DatabaseManager:
    """Manager für dynamische Datenbankverbindungen mit Fallback"""
    
    def __init__(self, config_file: str = 'config.conf', schema: Optional[Dict[str, str]] = None):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.db_connection = None
        self.schema = schema
        self.logger = logging.getLogger(__name__)
    
    async def _initialize_connection(self):
        """Initialisiert Datenbankverbindung basierend auf Konfiguration"""
        db_mode = self.config['database']['db_mode'].lower()
        
        if db_mode == 'postgresql':
            try:
                self.db_connection = PostgreSQLConnection(self.config)
                # Teste die Verbindung
                await self.db_connection.get_connection()
                self.logger.info("PostgreSQL als primäre Datenbank initialisiert")
            except Exception as e:
                self.logger.warning(f"PostgreSQL nicht verfügbar: {e}")
                self.logger.info("Fallback auf SQLite")
                self.db_connection = SQLiteConnection(self.config)
        else:
            self.db_connection = SQLiteConnection(self.config)
            self.logger.info("SQLite als Datenbank gewählt")
        
        # Erstelle Tabellen
        await self.db_connection.create_tables()
    
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
                    self.logger.error(f"PostgreSQL Datenbankfehler: {e}")
                    raise
        else:
            # SQLite
            conn = await self.db_connection.get_connection()
            try:
                yield conn
            except Exception as e:
                conn.rollback()
                self.logger.error(f"SQLite Datenbankfehler: {e}")
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
        query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url FROM episodes ORDER BY episode_nr DESC"
        if isinstance(self.db_connection, PostgreSQLConnection):
            query = "SELECT episode_nr, episode_id, title, description, publish_date, donations, status, duration, enclosure_url, season_nr, link, image_url FROM episodes ORDER BY episode_nr DESC"
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