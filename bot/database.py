import aiosqlite
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple, AsyncGenerator

from bot.config import DATABASE_FILE

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages the SQLite database connection and operations."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Establishes the database connection."""
        if self._connection is None or self._connection._running is False: # type: ignore[attr-defined]
            logger.info(f"Connecting to database at {self._db_path}...")
            self._connection = await aiosqlite.connect(self._db_path)
            self._connection.row_factory = aiosqlite.Row
            try:
                await self._connection.execute("PRAGMA journal_mode=WAL;")
                logger.info("WAL mode enabled for database connection.")
            except aiosqlite.Error as e:
                logger.warning(f"Could not enable WAL mode: {e}")
        else:
            logger.debug("Database connection already established.")

    async def close(self) -> None:
        """Closes the database connection."""
        if self._connection:
            logger.info("Closing database connection...")
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed.")

    async def _get_connection(self) -> aiosqlite.Connection:
        """Ensures the connection is active and returns it."""
        if self._connection is None or self._connection._running is False: # type: ignore[attr-defined]
            # This case should ideally be handled by application lifecycle,
            # but as a fallback, we can try to reconnect.
            logger.warning("Attempting to re-establish lost database connection.")
            await self.connect()
        if self._connection is None: # Still None after attempt
            raise ConnectionError("Database connection is not available.")
        return self._connection

    @staticmethod
    def sync_init_db(db_path: str = DATABASE_FILE) -> None:
        """
        Synchronously initializes the database and creates tables if they don't exist.
        Uses standard sqlite3, intended for startup only.
        """
        logger.info(f"Synchronously initializing database schema at {db_path}...")
        try:
            with sqlite3.connect(db_path) as db:
                try:
                    db.execute("PRAGMA journal_mode=WAL;")
                except sqlite3.Error as e:
                    logger.warning(f"Could not enable WAL mode during sync init: {e}")

                # Create users table
                db.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT NOT NULL,
                        last_name TEXT,
                        last_seen TEXT NOT NULL
                    );
                """)
                # Create interactions table
                db.execute("""
                    CREATE TABLE IF NOT EXISTS interactions (
                        interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER,
                        interaction_type TEXT NOT NULL CHECK(interaction_type IN ('command', 'url_message', 'reply_message', 'callback_query', 'status_update')),
                        content TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    );
                """)
                # Create downloads table
                db.execute("""
                    CREATE TABLE IF NOT EXISTS downloads (
                        download_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        interaction_id INTEGER,
                        user_id INTEGER NOT NULL,
                        youtube_url TEXT NOT NULL,
                        selected_quality TEXT NOT NULL,
                        video_title TEXT,
                        status TEXT NOT NULL CHECK(status IN ('requested', 'info_fetched', 'download_started', 'downloading', 'conversion_started', 'converting', 'upload_started', 'completed', 'failed')),
                        status_timestamp TEXT NOT NULL,
                        error_message TEXT,
                        final_file_size INTEGER,
                        FOREIGN KEY (interaction_id) REFERENCES interactions (interaction_id),
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    );
                """)
                db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_user_id ON downloads (user_id);")
                db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads (status);")

            logger.info("Synchronous database schema initialization complete.")
        except sqlite3.Error as e:
            logger.critical(f"Failed to initialize database schema synchronously: {e}", exc_info=True)
            raise

    @staticmethod
    def _now_iso() -> str:
        """Returns the current time in UTC ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()

    async def upsert_user(self, user_id: int, username: Optional[str], first_name: str, last_name: Optional[str]) -> None:
        """Adds/updates user."""
        now = self._now_iso()
        db = await self._get_connection()
        await db.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                last_seen = excluded.last_seen;
        """, (user_id, username, first_name, last_name, now))
        await db.commit()
        logger.debug(f"Upserted user {user_id} ({username or 'No username'})")

    async def log_interaction(
        self,
        user_id: int,
        chat_id: int,
        interaction_type: str,
        content: str,
        message_id: Optional[int] = None
    ) -> Optional[int]:
        """Logs an interaction."""
        now = self._now_iso()
        interaction_id = None
        db = await self._get_connection()
        cursor = await db.execute("""
            INSERT INTO interactions (user_id, chat_id, message_id, interaction_type, content, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, chat_id, message_id, interaction_type, content, now))
        await db.commit()
        interaction_id = cursor.lastrowid
        logger.debug(f"Logged interaction (ID: {interaction_id}): User={user_id}, Type={interaction_type}, Chat={chat_id}")
        return interaction_id

    async def create_download_record(
        self,
        user_id: int,
        youtube_url: str,
        selected_quality: str,
        interaction_id: Optional[int] = None,
    ) -> Optional[int]:
        """Creates a download record."""
        now = self._now_iso()
        download_id = None
        db = await self._get_connection()
        cursor = await db.execute("""
            INSERT INTO downloads (interaction_id, user_id, youtube_url, selected_quality, status, status_timestamp)
            VALUES (?, ?, ?, ?, 'requested', ?)
        """, (interaction_id, user_id, youtube_url, selected_quality, now))
        await db.commit()
        download_id = cursor.lastrowid
        logger.info(f"Created download record (ID: {download_id}): User={user_id}, URL={youtube_url}, Quality={selected_quality}")
        return download_id

    async def update_download_status(
        self,
        download_id: int,
        status: str,
        error_message: Optional[str] = None,
        file_size: Optional[int] = None
    ) -> None:
        """Updates download status."""
        now = self._now_iso()
        db = await self._get_connection()
        await db.execute("""
            UPDATE downloads
            SET status = ?, status_timestamp = ?, error_message = ?, final_file_size = ?
            WHERE download_id = ?
        """, (status, now, error_message, file_size, download_id))
        await db.commit()
        logger.info(f"Updated download record (ID: {download_id}) status to '{status}'" + (f" Error: {error_message}" if error_message else ""))

    async def set_download_title(self, download_id: int, video_title: str) -> None:
        """Sets download title."""
        db = await self._get_connection()
        await db.execute("""
            UPDATE downloads SET video_title = ? WHERE download_id = ?
        """, (video_title, download_id))
        await db.commit()
        logger.debug(f"Set title for download record (ID: {download_id}): '{video_title}'")

    async def get_total_user_count(self) -> int:
        db = await self._get_connection()
        cursor = await db.execute("SELECT COUNT(user_id) FROM users")
        result = await cursor.fetchone()
        return result[0] if result else 0

    async def get_users_count(self, since_iso_timestamp: str) -> int:
        db = await self._get_connection()
        cursor = await db.execute("SELECT COUNT(user_id) FROM users WHERE last_seen >= ?", (since_iso_timestamp,))
        result = await cursor.fetchone()
        return result[0] if result else 0

    async def get_interaction_count_by_type(self, since_iso_timestamp: Optional[str] = None) -> Dict[str, int]:
        query = "SELECT interaction_type, COUNT(*) as count FROM interactions"
        params: List[Any] = []
        if since_iso_timestamp:
            query += " WHERE timestamp >= ?"
            params.append(since_iso_timestamp)
        query += " GROUP BY interaction_type"
        counts = {}
        db = await self._get_connection()
        async with db.execute(query, params) as cursor: # type: ignore[union-attr] # aiosqlite.Connection.execute returns a Cursor
            async for row in cursor:
                counts[row['interaction_type']] = row['count']
        return counts

    async def get_download_status_counts(self) -> Dict[str, int]:
        query = "SELECT status, COUNT(*) as count FROM downloads GROUP BY status"
        counts = {}
        db = await self._get_connection()
        async with db.execute(query) as cursor: # type: ignore[union-attr]
            async for row in cursor:
                counts[row['status']] = row['count']
        return counts

    async def get_downloads_by_quality_summary(self) -> Dict[str, int]:
        query = "SELECT selected_quality, COUNT(*) as count FROM downloads WHERE status = 'completed' GROUP BY selected_quality"
        counts = {}
        db = await self._get_connection()
        async with db.execute(query) as cursor: # type: ignore[union-attr]
            async for row in cursor:
                counts[row['selected_quality']] = row['count']
        return counts

    async def get_top_requested_urls(self, limit: int = 5) -> List[Tuple[str, int]]:
        query = """
            SELECT youtube_url, COUNT(*) as count
            FROM downloads
            GROUP BY youtube_url
            ORDER BY count DESC
            LIMIT ?
        """
        urls = []
        db = await self._get_connection()
        async with db.execute(query, (limit,)) as cursor: # type: ignore[union-attr]
            async for row in cursor:
                urls.append((row['youtube_url'], row['count']))
        return urls
