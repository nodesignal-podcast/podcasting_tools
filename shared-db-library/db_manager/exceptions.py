"""
Custom Exceptions für die Datenbankbibliothek
"""

class DatabaseError(Exception):
    """Basis Exception für Datenbankfehler"""
    pass


class ConnectionError(DatabaseError):
    """Exception für Verbindungsfehler"""
    pass


class QueryError(DatabaseError):
    """Exception für SQL Query Fehler"""
    pass


class ConfigurationError(DatabaseError):
    """Exception für Konfigurationsfehler"""
    pass