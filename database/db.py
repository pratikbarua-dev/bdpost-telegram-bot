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
                    cainiao_enabled INTEGER NOT NULL DEFAULT 0,
                    bdpost_enabled INTEGER NOT NULL DEFAULT 1,
                    handover_detected INTEGER NOT NULL DEFAULT 0,
                    handover_at TEXT,
                    handover_event_hash TEXT,
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
                    description TEXT,
                    source TEXT DEFAULT 'bdpost',
                    action_code TEXT,
                    timezone TEXT,
                    event_hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # Migrations for existing databases
            self._migrate_table(cursor, "trackings", [
                ("cainiao_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("bdpost_enabled", "INTEGER NOT NULL DEFAULT 1"),
                ("handover_detected", "INTEGER NOT NULL DEFAULT 0"),
                ("handover_at", "TEXT"),
                ("handover_event_hash", "TEXT"),
            ])
            self._migrate_table(cursor, "events", [
                ("description", "TEXT"),
                ("source", "TEXT DEFAULT 'bdpost'"),
                ("action_code", "TEXT"),
                ("timezone", "TEXT"),
            ])

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trackings_active 
                ON trackings (active, tracking_number);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_tracking 
                ON events (tracking_number);
            """)
            conn.commit()
            logger.info("Database initialized & migrated successfully at %s", self.db_path)

    def _migrate_table(self, cursor: sqlite3.Cursor, table_name: str, columns: List[tuple]) -> None:
        cursor.execute(f"PRAGMA table_info({table_name});")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing_cols:
                logger.info("Migrating table %s: adding column %s", table_name, col_name)
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def};")

    def get_or_create_user(self, telegram_id: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO users (telegram_id, created_at)
                VALUES (?, ?)
            """, (telegram_id, now))
            conn.commit()

    def add_or_reactivate_tracking(
        self,
        telegram_id: int,
        tracking_number: str,
        cainiao_enabled: int = 0,
        bdpost_enabled: int = 1,
        handover_detected: int = 0
    ) -> None:
        self.get_or_create_user(telegram_id)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trackings (
                    telegram_id, tracking_number, active,
                    cainiao_enabled, bdpost_enabled, handover_detected, created_at
                )
                VALUES (?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(telegram_id, tracking_number) DO UPDATE SET
                    active = 1,
                    cainiao_enabled = excluded.cainiao_enabled,
                    bdpost_enabled = excluded.bdpost_enabled,
                    handover_detected = excluded.handover_detected
            """, (telegram_id, tracking_number, cainiao_enabled, bdpost_enabled, handover_detected, now))
            conn.commit()

    def set_handover_detected(self, tracking_number: str, handover_event_hash: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trackings
                SET handover_detected = 1,
                    cainiao_enabled = 0,
                    bdpost_enabled = 1,
                    handover_at = ?,
                    handover_event_hash = ?
                WHERE tracking_number = ?
            """, (now, handover_event_hash, tracking_number))
            conn.commit()

    def get_tracking_config(self, tracking_number: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cainiao_enabled, bdpost_enabled, handover_detected, handover_at, handover_event_hash
                FROM trackings
                WHERE tracking_number = ? AND active = 1
                LIMIT 1
            """, (tracking_number,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

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
                SELECT tracking_number, cainiao_enabled, bdpost_enabled, handover_detected, created_at, last_checked_at
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

    def get_active_trackings_with_providers(self) -> List[Dict]:
        """
        Returns unique active tracking configurations across all users.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tracking_number,
                       MAX(cainiao_enabled) as cainiao_enabled,
                       MAX(bdpost_enabled) as bdpost_enabled,
                       MAX(handover_detected) as handover_detected,
                       MAX(handover_at) as handover_at,
                       MAX(handover_event_hash) as handover_event_hash
                FROM trackings
                WHERE active = 1
                GROUP BY tracking_number
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

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
                            destination_country, location, status, description,
                            source, action_code, timezone, event_hash, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        tracking_number,
                        event.get("event_date", ""),
                        event.get("origin_country", ""),
                        event.get("destination_country", ""),
                        event.get("location", ""),
                        event.get("status", ""),
                        event.get("description", ""),
                        event.get("source", "bdpost"),
                        event.get("action_code", ""),
                        event.get("timezone", ""),
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

