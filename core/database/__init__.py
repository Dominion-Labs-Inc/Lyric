"""Database module for Lyric.

Provides unified PostgreSQL access (with pgvector) and the logging database.

MySQL-based implementations have been fully migrated to PostgreSQL and moved
to archive/mysql_deprecated_*/ for historical reference only.
"""

# PostgreSQL is the default (and only) active database backend.
from .unified_database_postgres import (
    LyricUnifiedDatabasePostgres,
    LyricUnifiedDatabasePostgres as LyricUnifiedDatabase,
    get_unified_db,
)

from .logging_database import LoggingDatabase

# Singleton instance
_database_instance = None


def get_database_manager():
    """Get singleton PostgreSQL database manager instance"""
    global _database_instance
    if _database_instance is None:
        _database_instance = LyricUnifiedDatabase()
    return _database_instance


__all__ = [
    'LyricUnifiedDatabase',
    'LyricUnifiedDatabasePostgres',
    'LoggingDatabase',
    'get_database_manager',
    'get_unified_db',
]
