"""
SQLite Datenbankverbindung
"""
import sqlite3
import logging
import os
from typing import Dict, Optional
from .base import DatabaseConnection
from ..exceptions import DatabaseError, ConnectionError


class SQLiteConnection(DatabaseConnection):
    """SQLite Datenbankverbindung"""
    
    def __init__(self, config: Dict[str, str]):
        self.db_path = config['sqlite']['db_path']
        self.connection = None
        self.logger = logging.getLogger(__name__)
        
        # Erstelle Verzeichnis falls nicht vorhanden
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
    async def get_connection(self) -> sqlite3.Connection:
        """Erstellt oder gibt bestehende SQLite Verbindung zurück"""
        if self.connection is None:
            try:
                self.connection = sqlite3.connect(self.db_path)
                self.connection.row_factory = sqlite3.Row
                self.logger.info(f"✅ SQLite Verbindung zu {self.db_path} hergestellt")
            except Exception as e:
                error_msg = f"SQLite Verbindungsfehler: {e}"
                self.logger.error(f"❌ {error_msg}")
                raise ConnectionError(error_msg) from e
        return self.connection
    
    async def create_tables(self, schema: Optional[Dict[str, str]] = None) -> None:
        """Erstellt Tabellen basierend auf Schema"""
        if schema is None:
            schema = self._get_default_schema()
            
        conn = await self.get_connection()
        cursor = conn.cursor()
        
        try:
            for table_name, table_sql in schema.items():
                cursor.execute(table_sql)
                self.logger.info(f"✅ SQLite Tabelle '{table_name}' erstellt")
            conn.commit()
        except Exception as e:
            conn.rollback()
            error_msg = f"Fehler beim Erstellen der Tabellen: {e}"
            self.logger.error(f"❌ {error_msg}")
            raise DatabaseError(error_msg) from e
    
    def _get_default_schema(self) -> Dict[str, str]:
        """Standard Schema für episodes Tabelle"""
        return {
            "episodes": """
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    episode_nr INTEGER,                       
                    title TEXT,
                    description TEXT,
                    status INTEGER,                       
                    publish_date TEXT,
                    duration TEXT,
                    enclosure_url TEXT,
                    season_nr INTEGER,
                    link TEXT,
                    image_url TEXT,
                    donations INTEGER DEFAULT 0
                );
            """
        }

    async def close(self) -> None:
        """Schließt die SQLite Verbindung"""
        if self.connection:
            self.connection.close()
            self.connection = None
            self.logger.info("✅ SQLite Verbindung geschlossen")