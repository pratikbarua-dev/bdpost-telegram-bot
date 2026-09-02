import sqlite3
import datetime
import logging
from typing import Optional, List, Dict, Set

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trackings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    tracking_number TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(telegram_id, tracking_number)
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracking_number TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    origin_country TEXT,
                    destination_country TEXT,
                    location TEXT,
                    status TEXT,
                    event_hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trackings_active 
                ON trackings (active, tracking_number);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_tracking 
                ON events (tracking_number);
            """)
            conn.commit()
            logger.info("Database initialized successfully at %s", self.db_path)

    def get_or_create_user(self, telegram_id: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO users (telegram_id, created_at)
                VALUES (?, ?)
            """, (telegram_id, now))
            conn.commit()

    def add_or_reactivate_tracking(self, telegram_id: int, tracking_number: str) -> None:
        self.get_or_create_user(telegram_id)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trackings (telegram_id, tracking_number, active, created_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(telegram_id, tracking_number) DO UPDATE SET
                    active = 1
            """, (telegram_id, tracking_number, now))
            conn.commit()

    def stop_tracking(self, telegram_id: int, tracking_number: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trackings
                SET active = 0
                WHERE telegram_id = ? AND tracking_number = ? AND active = 1
            """, (telegram_id, tracking_number))
            conn.commit()
            return cursor.rowcount > 0

    def stop_all_trackings(self, telegram_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trackings
                SET active = 0
                WHERE telegram_id = ? AND active = 1
            """, (telegram_id,))
            conn.commit()
            return cursor.rowcount

    def deactivate_tracking_number(self, tracking_number: str) -> int:
        """
        Deactivates all active subscriptions for a tracking number (e.g. once delivered).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trackings
                SET active = 0
                WHERE tracking_number = ? AND active = 1
            """, (tracking_number,))
            conn.commit()
            return cursor.rowcount

    def get_user_active_trackings(self, telegram_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tracking_number, created_at, last_checked_at
                FROM trackings
                WHERE telegram_id = ? AND active = 1
                ORDER BY created_at DESC
            """, (telegram_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_all_active_tracking_numbers(self) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT tracking_number
                FROM trackings
                WHERE active = 1
            """)
            rows = cursor.fetchall()
            return [row["tracking_number"] for row in rows]

    def get_subscribers_for_tracking(self, tracking_number: str) -> List[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT telegram_id
                FROM trackings
                WHERE tracking_number = ? AND active = 1
            """, (tracking_number,))
            rows = cursor.fetchall()
            return [row["telegram_id"] for row in rows]

    def update_last_checked(self, tracking_number: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trackings
                SET last_checked_at = ?
                WHERE tracking_number = ?
            """, (now, tracking_number))
            conn.commit()

    def get_known_event_hashes(self, tracking_number: str) -> Set[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT event_hash
                FROM events
                WHERE tracking_number = ?
            """, (tracking_number,))
            rows = cursor.fetchall()
            return {row["event_hash"] for row in rows}

    def save_events(self, tracking_number: str, events: List[Dict]) -> List[Dict]:
        """
        Saves new events to the database and returns the list of newly inserted events.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        known_hashes = self.get_known_event_hashes(tracking_number)
        new_events = []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for event in events:
                event_hash = event["event_hash"]
                if event_hash not in known_hashes:
                    cursor.execute("""
                        INSERT OR IGNORE INTO events (
                            tracking_number, event_date, origin_country,
                            destination_country, location, status, event_hash, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        tracking_number,
                        event.get("event_date", ""),
                        event.get("origin_country", ""),
                        event.get("destination_country", ""),
                        event.get("location", ""),
                        event.get("status", ""),
                        event_hash,
                        now
                    ))
                    if cursor.rowcount > 0:
                        new_events.append(event)
                        known_hashes.add(event_hash)
            conn.commit()

        return new_events

    def get_latest_event_for_tracking(self, tracking_number: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT *
                FROM events
                WHERE tracking_number = ?
                ORDER BY id DESC
                LIMIT 1
            """, (tracking_number,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
