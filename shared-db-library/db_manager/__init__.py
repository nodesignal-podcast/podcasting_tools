"""
Wiederverwendbare Datenbankbibliothek für PostgreSQL und SQLite
"""

from .manager import DatabaseManager
from .connections.base import DatabaseConnection
from .connections.postgresql import PostgreSQLConnection
from .connections.sqlite import SQLiteConnection
from .exceptions import DatabaseError, ConnectionError
from .podhome import PodHomeEpisode, Episode, AlbyWalletBalance

__version__ = "1.0.0"
__all__ = [
    "DatabaseManager",
    "DatabaseConnection", 
    "PostgreSQLConnection",
    "SQLiteConnection",
    "DatabaseError",
    "ConnectionError",
    "PodHomeEpisode",
    "Episode",
    "AlbyWalletBalance"
]