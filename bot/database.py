import aiosqlite
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from bot.config import DATABASE_FILE

logger = logging.getLogger(__name__)

async def get_db() -> aiosqlite.Connection:
    """Gets a database connection."""
    db = await aiosqlite.connect(DATABASE_FILE)
    # Use Row factory for dict-like access
    db.row_factory = aiosqlite.Row
    # Enable WAL mode for better concurrency (optional but recommended)
    try:
        await db.execute("PRAGMA journal_mode=WAL;")
    except Exception as e:
        logger.warning(f"Could not enable WAL mode: {e}")
    return db

async def init_db() -> None:
    """Initializes the database and creates tables if they don't exist."""
    logger.info(f"Initializing database at {DATABASE_FILE}...")
    async with await get_db() as db:
        # Create users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL,
                last_name TEXT,
                last_seen TEXT NOT NULL
            );
        """)
        logger.debug("Checked/Created 'users' table.")

        # Create interactions table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER, -- Can be null for some interactions initially
                interaction_type TEXT NOT NULL CHECK(interaction_type IN ('command', 'url_message', 'reply_message', 'callback_query', 'status_update')),
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );
        """)
        logger.debug("Checked/Created 'interactions' table.")

        # Create downloads table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                download_id INTEGER PRIMARY KEY AUTOINCREMENT,
                interaction_id INTEGER, -- Link to initiating interaction (can be null if started differently)
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
        await db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_user_id ON downloads (user_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads (status);")
        logger.debug("Checked/Created 'downloads' table and indexes.")

        await db.commit()
    logger.info("Database initialization complete.")

def _now_iso() -> str:
    """Returns the current time in UTC ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

# --- User Operations ---

async def upsert_user(user_id: int, username: Optional[str], first_name: str, last_name: Optional[str]) -> None:
    """Adds a new user or updates the last_seen timestamp and names for an existing user."""
    now = _now_iso()
    async with await get_db() as db:
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

# --- Interaction Operations ---

async def log_interaction(
    user_id: int,
    chat_id: int,
    interaction_type: str,
    content: str,
    message_id: Optional[int] = None
) -> Optional[int]:
    """Logs an interaction and returns the interaction_id."""
    now = _now_iso()
    interaction_id = None
    async with await get_db() as db:
        cursor = await db.execute("""
            INSERT INTO interactions (user_id, chat_id, message_id, interaction_type, content, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, chat_id, message_id, interaction_type, content, now))
        await db.commit()
        interaction_id = cursor.lastrowid
    logger.debug(f"Logged interaction (ID: {interaction_id}): User={user_id}, Type={interaction_type}, Chat={chat_id}")
    return interaction_id

# --- Download Operations ---

async def create_download_record(
    user_id: int,
    youtube_url: str,
    selected_quality: str,
    interaction_id: Optional[int] = None,
) -> Optional[int]:
    """Creates a new download record with 'requested' status."""
    now = _now_iso()
    download_id = None
    async with await get_db() as db:
        cursor = await db.execute("""
            INSERT INTO downloads (interaction_id, user_id, youtube_url, selected_quality, status, status_timestamp)
            VALUES (?, ?, ?, ?, 'requested', ?)
        """, (interaction_id, user_id, youtube_url, selected_quality, now))
        await db.commit()
        download_id = cursor.lastrowid
    logger.info(f"Created download record (ID: {download_id}): User={user_id}, URL={youtube_url}, Quality={selected_quality}")
    return download_id

async def update_download_status(download_id: int, status: str, error_message: Optional[str] = None, file_size: Optional[int] = None) -> None:
    """Updates the status, timestamp, and optionally error message/file size of a download record."""
    now = _now_iso()
    async with await get_db() as db:
        await db.execute("""
            UPDATE downloads
            SET status = ?, status_timestamp = ?, error_message = ?, final_file_size = ?
            WHERE download_id = ?
        """, (status, now, error_message, file_size, download_id))
        await db.commit()
    logger.info(f"Updated download record (ID: {download_id}) status to '{status}'" + (f" Error: {error_message}" if error_message else ""))

async def set_download_title(download_id: int, video_title: str) -> None:
    """Sets the video title for a download record (usually after fetching info)."""
    async with await get_db() as db:
        await db.execute("""
            UPDATE downloads SET video_title = ? WHERE download_id = ?
        """, (video_title, download_id))
        await db.commit()
    logger.debug(f"Set title for download record (ID: {download_id}): '{video_title}'")


# --- Statistics Queries ---

async def get_total_user_count() -> int:
    """Gets the total number of unique users."""
    async with await get_db() as db:
        cursor = await db.execute("SELECT COUNT(user_id) FROM users")
        result = await cursor.fetchone()
        return result[0] if result else 0

async def get_users_count(since_iso_timestamp: str) -> int:
    """Gets the number of users seen since a specific timestamp."""
    async with await get_db() as db:
        cursor = await db.execute("SELECT COUNT(user_id) FROM users WHERE last_seen >= ?", (since_iso_timestamp,))
        result = await cursor.fetchone()
        return result[0] if result else 0

async def get_interaction_count_by_type(since_iso_timestamp: Optional[str] = None) -> Dict[str, int]:
    """Gets the count of interactions by type, optionally filtered by timestamp."""
    query = "SELECT interaction_type, COUNT(*) as count FROM interactions"
    params: List[Any] = []
    if since_iso_timestamp:
        query += " WHERE timestamp >= ?"
        params.append(since_iso_timestamp)
    query += " GROUP BY interaction_type"

    counts = {}
    async with await get_db() as db:
        async with db.execute(query, params) as cursor:
            async for row in cursor:
                counts[row['interaction_type']] = row['count']
    return counts

async def get_download_status_counts() -> Dict[str, int]:
    """Gets the count of downloads by their current status."""
    query = "SELECT status, COUNT(*) as count FROM downloads GROUP BY status"
    counts = {}
    async with await get_db() as db:
        async with db.execute(query) as cursor:
            async for row in cursor:
                counts[row['status']] = row['count']
    return counts

async def get_downloads_by_quality_summary() -> Dict[str, int]:
    """Gets the count of completed downloads grouped by quality."""
    query = "SELECT selected_quality, COUNT(*) as count FROM downloads WHERE status = 'completed' GROUP BY selected_quality"
    counts = {}
    async with await get_db() as db:
        async with db.execute(query) as cursor:
            async for row in cursor:
                counts[row['selected_quality']] = row['count']
    return counts

async def get_top_requested_urls(limit: int = 5) -> List[Tuple[str, int]]:
    """Gets the most frequently requested YouTube URLs."""
    query = """
        SELECT youtube_url, COUNT(*) as count
        FROM downloads
        GROUP BY youtube_url
        ORDER BY count DESC
        LIMIT ?
    """
    urls = []
    async with await get_db() as db:
        async with db.execute(query, (limit,)) as cursor:
            async for row in cursor:
                urls.append((row['youtube_url'], row['count']))
    return urls
