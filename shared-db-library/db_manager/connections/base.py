"""
Abstract base class für Datenbankverbindungen
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Union


class DatabaseConnection(ABC):
    """Abstract base class für Datenbankverbindungen"""
    
    @abstractmethod
    async def get_connection(self) -> Any:
        """Gibt eine Datenbankverbindung zurück"""
        pass
    
    @abstractmethod
    async def create_tables(self, schema: Optional[Dict[str, str]] = None) -> None:
        """Erstellt Tabellen basierend auf Schema"""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Schließt die Datenbankverbindung"""
        pass