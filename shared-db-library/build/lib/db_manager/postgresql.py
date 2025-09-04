"""
PostgreSQL Datenbankverbindung mit asyncpg
"""
import logging
import asyncpg
from typing import Dict, Optional
from .base import DatabaseConnection
from ..exceptions import DatabaseError, ConnectionError


class PostgreSQLConnection(DatabaseConnection):
    """PostgreSQL Datenbankverbindung mit asyncpg"""
    
    def __init__(self, config: Dict[str, str], pool_config: Optional[Dict[str, int]] = None):
        self.host = config['postgresql']['host']
        self.port = int(config['postgresql']['port'])
        self.database = config['postgresql']['database']
        self.user = config['postgresql']['user']
        self.password = config['postgresql']['password']
        
        # Pool Konfiguration
        pool_config = pool_config or {}
        self.min_size = pool_config.get('min_size', 5)
        self.max_size = pool_config.get('max_size', 20)
        
        self.pool = None
        self.logger = logging.getLogger(__name__)
        
    async def get_connection(self) -> asyncpg.Pool:
        """Erstellt oder gibt bestehende PostgreSQL Connection Pool zurück"""
        if self.pool is None:
            try:
                self.pool = await asyncpg.create_pool(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.user,
                    password=self.password,
                    min_size=self.min_size,
                    max_size=self.max_size
                )
                self.logger.info("✅ PostgreSQL Connection Pool erfolgreich erstellt")
            except Exception as e:
                error_msg = f"PostgreSQL Verbindungsfehler: {e}"
                self.logger.error(f"❌ {error_msg}")
                raise ConnectionError(error_msg) from e
        return self.pool
    
    async def create_tables(self, schema: Optional[Dict[str, str]] = None) -> None:
        """Erstellt Tabellen basierend auf Schema"""
        if schema is None:
            schema = self._get_default_schema()
            
        pool = await self.get_connection()
        async with pool.acquire() as conn:
            try:
                for table_name, table_sql in schema.items():
                    await conn.execute(table_sql)
                    self.logger.info(f"✅ PostgreSQL Tabelle '{table_name}' erstellt")
            except Exception as e:
                error_msg = f"Fehler beim Erstellen der Tabellen: {e}"
                self.logger.error(f"❌ {error_msg}")
                raise DatabaseError(error_msg) from e
    
    def _get_default_schema(self) -> Dict[str, str]:
        """Standard Schema für episodes Tabelle"""
        return {
            "episodes": """
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id VARCHAR(100) PRIMARY KEY,
                    episode_nr INTEGER,                       
                    title VARCHAR(210),
                    description VARCHAR(21000),
                    status INTEGER,                       
                    publish_date TIMESTAMP,
                    duration VARCHAR(21),
                    enclosure_url VARCHAR(210),
                    season_nr INTEGER,
                    link VARCHAR(210),
                    image_url VARCHAR(210),
                    donations INTEGER DEFAULT 0
                );
            """
        }

    async def close(self) -> None:
        """Schließt den Connection Pool"""
        if self.pool:
            await self.pool.close()
            self.logger.info("✅ PostgreSQL Connection Pool geschlossen")