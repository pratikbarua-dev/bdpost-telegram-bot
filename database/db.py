import sqlite3
import datetime
import logging
from typing import Optional, List, Dict, Set, Tuple

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

            # Core shipments table (represents 1 physical parcel)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shipments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    primary_tracking_number TEXT UNIQUE NOT NULL,
                    current_status TEXT,
                    current_location TEXT,
                    origin_country TEXT,
                    dest_country TEXT,
                    local_tracking_number TEXT,
                    cainiao_enabled INTEGER NOT NULL DEFAULT 1,
                    bdpost_enabled INTEGER NOT NULL DEFAULT 1,
                    handover_detected INTEGER NOT NULL DEFAULT 0,
                    handover_at TEXT,
                    handover_event_hash TEXT,
                    is_delivered INTEGER NOT NULL DEFAULT 0,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # Linked tracking numbers in the chain (e.g. AP -> CNG -> UG)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shipment_tracking_numbers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shipment_id INTEGER NOT NULL,
                    tracking_number TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'unknown',
                    type TEXT NOT NULL DEFAULT 'linked',
                    discovered_from TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(shipment_id, tracking_number),
                    FOREIGN KEY(shipment_id) REFERENCES shipments(id) ON DELETE CASCADE
                );
            """)

            # User subscriptions to shipments
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shipment_subscribers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shipment_id INTEGER NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    label TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(shipment_id, telegram_id),
                    FOREIGN KEY(shipment_id) REFERENCES shipments(id) ON DELETE CASCADE
                );
            """)

            # Legacy / Direct trackings table for compatibility
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trackings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    tracking_number TEXT NOT NULL,
                    label TEXT,
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
                ("label", "TEXT"),
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

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stn_number ON shipment_tracking_numbers(tracking_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stn_shipment ON shipment_tracking_numbers(shipment_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subs_user ON shipment_subscribers(telegram_id, active);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subs_shipment ON shipment_subscribers(shipment_id, active);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_tracking ON events(tracking_number);")

            # Auto-migrate any existing legacy trackings into shipments
            self._sync_legacy_trackings(cursor)

            conn.commit()
            logger.info("Database initialized & migrated successfully at %s", self.db_path)

    def _migrate_table(self, cursor: sqlite3.Cursor, table_name: str, columns: List[tuple]) -> None:
        cursor.execute(f"PRAGMA table_info({table_name});")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing_cols:
                logger.info("Migrating table %s: adding column %s", table_name, col_name)
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def};")

    def _sync_legacy_trackings(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("SELECT * FROM trackings WHERE active = 1")
        rows = cursor.fetchall()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for r in rows:
            num = r["tracking_number"]
            user_id = r["telegram_id"]
            label = r["label"]

            cursor.execute("SELECT id FROM shipments WHERE primary_tracking_number = ?", (num,))
            existing = cursor.fetchone()
            if existing:
                shipment_id = existing["id"]
            else:
                cursor.execute("""
                    INSERT INTO shipments (
                        primary_tracking_number, cainiao_enabled, bdpost_enabled,
                        handover_detected, handover_at, handover_event_hash,
                        last_checked_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    num, r["cainiao_enabled"], r["bdpost_enabled"],
                    r["handover_detected"], r["handover_at"], r["handover_event_hash"],
                    r["last_checked_at"], r["created_at"], now
                ))
                shipment_id = cursor.lastrowid

                cursor.execute("""
                    INSERT OR IGNORE INTO shipment_tracking_numbers (
                        shipment_id, tracking_number, source, type, created_at
                    ) VALUES (?, ?, 'original', 'original', ?)
                """, (shipment_id, num, now))

            cursor.execute("""
                INSERT OR IGNORE INTO shipment_subscribers (
                    shipment_id, telegram_id, label, active, created_at
                ) VALUES (?, ?, ?, 1, ?)
            """, (shipment_id, user_id, label, now))

    def get_or_create_user(self, telegram_id: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO users (telegram_id, created_at)
                VALUES (?, ?)
            """, (telegram_id, now))
            conn.commit()

    # -----------------------------------------------------------------
    # Shipment & Tracking Chain Management
    # -----------------------------------------------------------------
    def get_or_create_shipment(
        self,
        tracking_number: str,
        telegram_id: Optional[int] = None,
        label: Optional[str] = None
    ) -> int:
        """
        Finds existing shipment containing tracking_number (either primary or linked).
        If not found, creates a new shipment.
        If telegram_id provided, subscribes user to this shipment.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cleaned_num = tracking_number.strip().upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Check if number exists in shipment_tracking_numbers
            cursor.execute("""
                SELECT shipment_id FROM shipment_tracking_numbers
                WHERE tracking_number = ?
                LIMIT 1
            """, (cleaned_num,))
            row = cursor.fetchone()

            if row:
                shipment_id = row["shipment_id"]
            else:
                # 2. Check if number is primary in shipments
                cursor.execute("""
                    SELECT id FROM shipments
                    WHERE primary_tracking_number = ?
                    LIMIT 1
                """, (cleaned_num,))
                srow = cursor.fetchone()

                if srow:
                    shipment_id = srow["id"]
                else:
                    # 3. Create new shipment
                    cursor.execute("""
                        INSERT INTO shipments (
                            primary_tracking_number, created_at, updated_at
                        ) VALUES (?, ?, ?)
                    """, (cleaned_num, now, now))
                    shipment_id = cursor.lastrowid

                # Register as original number in chain
                cursor.execute("""
                    INSERT OR IGNORE INTO shipment_tracking_numbers (
                        shipment_id, tracking_number, source, type, created_at
                    ) VALUES (?, ?, 'original', 'original', ?)
                """, (shipment_id, cleaned_num, now))

            # 4. Subscribe user if telegram_id provided
            if telegram_id is not None:
                cursor.execute("""
                    INSERT OR IGNORE INTO users (telegram_id, created_at)
                    VALUES (?, ?)
                """, (telegram_id, now))

                cursor.execute("""
                    INSERT INTO shipment_subscribers (
                        shipment_id, telegram_id, label, active, created_at
                    ) VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(shipment_id, telegram_id) DO UPDATE SET
                        active = 1,
                        label = COALESCE(excluded.label, shipment_subscribers.label)
                """, (shipment_id, telegram_id, label, now))

                # Also sync legacy trackings table
                cursor.execute("""
                    INSERT INTO trackings (
                        telegram_id, tracking_number, label, active, created_at
                    ) VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(telegram_id, tracking_number) DO UPDATE SET
                        active = 1,
                        label = COALESCE(excluded.label, trackings.label)
                """, (telegram_id, cleaned_num, label, now))

            conn.commit()
            return shipment_id

    def link_tracking_number(
        self,
        shipment_id: int,
        tracking_number: str,
        source: str = "cainiao",
        num_type: str = "linked",
        discovered_from: Optional[str] = None
    ) -> bool:
        """
        Links a discovered tracking number to an existing shipment.
        If the discovered number belongs to another shipment record, merges them.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cleaned_num = tracking_number.strip().upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check if this number already belongs to another shipment
            cursor.execute("""
                SELECT shipment_id FROM shipment_tracking_numbers
                WHERE tracking_number = ?
            """, (cleaned_num,))
            existing = cursor.fetchone()

            if existing:
                other_id = existing["shipment_id"]
                if other_id != shipment_id:
                    logger.info("Merging shipment %d into shipment %d due to linked number %s", other_id, shipment_id, cleaned_num)
                    # Move tracking numbers to target shipment
                    cursor.execute("UPDATE shipment_tracking_numbers SET shipment_id = ? WHERE shipment_id = ?", (shipment_id, other_id))
                    # Move subscribers to target shipment
                    cursor.execute("""
                        INSERT OR IGNORE INTO shipment_subscribers (shipment_id, telegram_id, label, active, created_at)
                        SELECT ?, telegram_id, label, active, created_at FROM shipment_subscribers WHERE shipment_id = ?
                    """, (shipment_id, other_id))
                    cursor.execute("DELETE FROM shipment_subscribers WHERE shipment_id = ?", (other_id,))
                    cursor.execute("DELETE FROM shipments WHERE id = ?", (other_id,))
                return False

            cursor.execute("""
                INSERT OR IGNORE INTO shipment_tracking_numbers (
                    shipment_id, tracking_number, source, type, discovered_from, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (shipment_id, cleaned_num, source, num_type, discovered_from, now))

            if num_type == "local" or source == "bdpost":
                cursor.execute("""
                    UPDATE shipments
                    SET local_tracking_number = ?, updated_at = ?
                    WHERE id = ? AND (local_tracking_number IS NULL OR local_tracking_number = '')
                """, (cleaned_num, now, shipment_id))

            conn.commit()
            return cursor.rowcount > 0

    def get_shipment(self, shipment_id: int) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
            row = cursor.fetchone()
            if not row:
                return None
            shipment = dict(row)
            cursor.execute("""
                SELECT tracking_number, source, type, discovered_from, is_active
                FROM shipment_tracking_numbers
                WHERE shipment_id = ?
                ORDER BY id ASC
            """, (shipment_id,))
            shipment["tracking_chain"] = [dict(r) for r in cursor.fetchall()]
            return shipment

    def get_shipment_by_tracking_number(self, tracking_number: str) -> Optional[Dict]:
        cleaned_num = tracking_number.strip().upper()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT shipment_id FROM shipment_tracking_numbers
                WHERE tracking_number = ?
                LIMIT 1
            """, (cleaned_num,))
            row = cursor.fetchone()
            if row:
                return self.get_shipment(row["shipment_id"])

            cursor.execute("SELECT id FROM shipments WHERE primary_tracking_number = ? LIMIT 1", (cleaned_num,))
            srow = cursor.fetchone()
            if srow:
                return self.get_shipment(srow["id"])

            return None

    def get_tracking_chain_numbers(self, shipment_id: int) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tracking_number
                FROM shipment_tracking_numbers
                WHERE shipment_id = ? AND is_active = 1
                ORDER BY id ASC
            """, (shipment_id,))
            return [row["tracking_number"] for row in cursor.fetchall()]

    def update_shipment_status(
        self,
        shipment_id: int,
        status: Optional[str] = None,
        location: Optional[str] = None,
        cainiao_enabled: Optional[int] = None,
        bdpost_enabled: Optional[int] = None,
        handover_detected: Optional[int] = None,
        handover_event_hash: Optional[str] = None,
        is_delivered: Optional[int] = None,
        local_tracking_number: Optional[str] = None
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = ["updated_at = ?"]
            params = [now]

            if status is not None:
                updates.append("current_status = ?")
                params.append(status)
            if location is not None:
                updates.append("current_location = ?")
                params.append(location)
            if cainiao_enabled is not None:
                updates.append("cainiao_enabled = ?")
                params.append(cainiao_enabled)
            if bdpost_enabled is not None:
                updates.append("bdpost_enabled = ?")
                params.append(bdpost_enabled)
            if handover_detected is not None:
                updates.append("handover_detected = ?")
                params.append(handover_detected)
                if handover_detected and handover_event_hash:
                    updates.append("handover_at = ?")
                    params.append(now)
                    updates.append("handover_event_hash = ?")
                    params.append(handover_event_hash)
            if is_delivered is not None:
                updates.append("is_delivered = ?")
                params.append(is_delivered)
            if local_tracking_number is not None:
                updates.append("local_tracking_number = ?")
                params.append(local_tracking_number)

            params.append(shipment_id)
            cursor.execute(f"UPDATE shipments SET {', '.join(updates)} WHERE id = ?", tuple(params))
            conn.commit()

    def get_shipment_subscribers(self, shipment_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT telegram_id, label
                FROM shipment_subscribers
                WHERE shipment_id = ? AND active = 1
            """, (shipment_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_user_active_shipments(self, telegram_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.*, sub.label
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.telegram_id = ? AND sub.active = 1
                ORDER BY s.updated_at DESC
            """, (telegram_id,))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                shipment = dict(r)
                cursor.execute("""
                    SELECT tracking_number, source, type, discovered_from
                    FROM shipment_tracking_numbers
                    WHERE shipment_id = ?
                    ORDER BY id ASC
                """, (shipment["id"],))
                shipment["tracking_chain"] = [dict(tr) for tr in cursor.fetchall()]
                result.append(shipment)
            return result

    def get_all_active_shipments(self) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT s.*
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.active = 1 AND s.is_delivered = 0
            """)
            rows = cursor.fetchall()
            result = []
            for r in rows:
                shipment = dict(r)
                cursor.execute("""
                    SELECT tracking_number, source, type, discovered_from, is_active
                    FROM shipment_tracking_numbers
                    WHERE shipment_id = ? AND is_active = 1
                    ORDER BY id ASC
                """, (shipment["id"],))
                shipment["tracking_chain"] = [dict(tr) for tr in cursor.fetchall()]
                result.append(shipment)
            return result

    def stop_shipment_tracking(self, telegram_id: int, tracking_number: str) -> bool:
        cleaned_num = tracking_number.strip().upper()
        shipment = self.get_shipment_by_tracking_number(cleaned_num)
        if not shipment:
            return self.stop_tracking(telegram_id, cleaned_num)

        shipment_id = shipment["id"]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shipment_subscribers
                SET active = 0
                WHERE shipment_id = ? AND telegram_id = ? AND active = 1
            """, (shipment_id, telegram_id))
            sub_count = cursor.rowcount

            # Also stop legacy trackings for all numbers in chain
            for num in self.get_tracking_chain_numbers(shipment_id):
                cursor.execute("""
                    UPDATE trackings
                    SET active = 0
                    WHERE telegram_id = ? AND tracking_number = ?
                """, (telegram_id, num))

            conn.commit()
            return sub_count > 0

    def stop_all_user_shipments(self, telegram_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shipment_subscribers
                SET active = 0
                WHERE telegram_id = ? AND active = 1
            """, (telegram_id,))
            count = cursor.rowcount
            cursor.execute("""
                UPDATE trackings
                SET active = 0
                WHERE telegram_id = ? AND active = 1
            """, (telegram_id,))
            conn.commit()
            return count

    def deactivate_shipment_on_delivery(self, shipment_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shipments
                SET is_delivered = 1, cainiao_enabled = 0, bdpost_enabled = 0
                WHERE id = ?
            """, (shipment_id,))
            cursor.execute("""
                UPDATE shipment_subscribers
                SET active = 0
                WHERE shipment_id = ?
            """, (shipment_id,))
            count = cursor.rowcount
            for num in self.get_tracking_chain_numbers(shipment_id):
                cursor.execute("UPDATE trackings SET active = 0 WHERE tracking_number = ?", (num,))
            conn.commit()
            return count

    def set_handover_detected(self, tracking_number: str, handover_event_hash: str) -> None:
        cleaned_num = tracking_number.strip().upper()
        shipment = self.get_shipment_by_tracking_number(cleaned_num)
        if shipment:
            self.update_shipment_status(
                shipment["id"],
                cainiao_enabled=0,
                bdpost_enabled=1,
                handover_detected=1,
                handover_event_hash=handover_event_hash
            )

    def set_shipment_label(self, telegram_id: int, tracking_number: str, label: Optional[str]) -> bool:
        cleaned_num = tracking_number.strip().upper()
        shipment = self.get_shipment_by_tracking_number(cleaned_num)
        if not shipment:
            return self.set_parcel_label(telegram_id, cleaned_num, label)

        shipment_id = shipment["id"]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shipment_subscribers
                SET label = ?
                WHERE shipment_id = ? AND telegram_id = ? AND active = 1
            """, (label.strip() if label else None, shipment_id, telegram_id))
            # Also sync legacy trackings
            cursor.execute("""
                UPDATE trackings
                SET label = ?
                WHERE telegram_id = ? AND tracking_number = ?
            """, (label.strip() if label else None, telegram_id, cleaned_num))
            conn.commit()
            return cursor.rowcount > 0

    # -----------------------------------------------------------------
    # Backward Compatibility Helpers
    # -----------------------------------------------------------------
    def add_or_reactivate_tracking(
        self,
        telegram_id: int,
        tracking_number: str,
        cainiao_enabled: int = 0,
        bdpost_enabled: int = 1,
        handover_detected: int = 0
    ) -> None:
        self.get_or_create_shipment(tracking_number, telegram_id=telegram_id)

    def stop_tracking(self, telegram_id: int, tracking_number: str) -> bool:
        return self.stop_shipment_tracking(telegram_id, tracking_number)

    def stop_all_trackings(self, telegram_id: int) -> int:
        return self.stop_all_user_shipments(telegram_id)

    def deactivate_tracking_number(self, tracking_number: str) -> int:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        if shipment:
            return self.deactivate_shipment_on_delivery(shipment["id"])
        return 0

    def set_parcel_label(self, telegram_id: int, tracking_number: str, label: Optional[str]) -> bool:
        return self.set_shipment_label(telegram_id, tracking_number, label)

    def get_parcel_label(self, telegram_id: int, tracking_number: str) -> Optional[str]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        if shipment:
            subscribers = self.get_shipment_subscribers(shipment["id"])
            for sub in subscribers:
                if sub["telegram_id"] == telegram_id:
                    return sub["label"]
        return None

    def get_user_active_trackings(self, telegram_id: int) -> List[Dict]:
        shipments = self.get_user_active_shipments(telegram_id)
        result = []
        for s in shipments:
            result.append({
                "tracking_number": s["primary_tracking_number"],
                "label": s.get("label"),
                "cainiao_enabled": s["cainiao_enabled"],
                "bdpost_enabled": s["bdpost_enabled"],
                "handover_detected": s["handover_detected"],
                "local_tracking_number": s.get("local_tracking_number"),
                "tracking_chain": s.get("tracking_chain", []),
                "created_at": s["created_at"],
                "last_checked_at": s["last_checked_at"]
            })
        return result

    def get_subscribers_with_labels_for_tracking(self, tracking_number: str) -> List[Dict]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        if shipment:
            return self.get_shipment_subscribers(shipment["id"])
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_id, label FROM trackings WHERE tracking_number = ? AND active = 1", (tracking_number,))
            return [dict(r) for r in cursor.fetchall()]

    def get_all_active_tracking_numbers(self) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT primary_tracking_number as tracking_number
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.active = 1 AND s.is_delivered = 0
            """)
            return [row["tracking_number"] for row in cursor.fetchall()]

    def get_active_trackings_with_providers(self) -> List[Dict]:
        shipments = self.get_all_active_shipments()
        result = []
        for s in shipments:
            result.append({
                "shipment_id": s["id"],
                "tracking_number": s["primary_tracking_number"],
                "local_tracking_number": s.get("local_tracking_number"),
                "tracking_chain": s.get("tracking_chain", []),
                "cainiao_enabled": s["cainiao_enabled"],
                "bdpost_enabled": s["bdpost_enabled"],
                "handover_detected": s["handover_detected"],
                "handover_at": s["handover_at"],
                "handover_event_hash": s["handover_event_hash"]
            })
        return result

    def get_subscribers_for_tracking(self, tracking_number: str) -> List[int]:
        subs = self.get_subscribers_with_labels_for_tracking(tracking_number)
        return [s["telegram_id"] for s in subs]

    def update_last_checked(self, tracking_number: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE shipments SET last_checked_at = ?, updated_at = ? WHERE primary_tracking_number = ?", (now, now, tracking_number))
            cursor.execute("UPDATE trackings SET last_checked_at = ? WHERE tracking_number = ?", (now, tracking_number))
            conn.commit()

    def get_known_event_hashes(self, tracking_number: str) -> Set[str]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        all_numbers = [tracking_number]
        if shipment:
            all_numbers.extend([item["tracking_number"] for item in shipment.get("tracking_chain", [])])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(all_numbers))
            cursor.execute(f"SELECT event_hash FROM events WHERE tracking_number IN ({placeholders})", tuple(all_numbers))
            return {row["event_hash"] for row in cursor.fetchall()}

    def save_events(self, tracking_number: str, events: List[Dict]) -> List[Dict]:
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
                        event.get("tracking_number", tracking_number),
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
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        all_numbers = [tracking_number]
        if shipment:
            all_numbers.extend([item["tracking_number"] for item in shipment.get("tracking_chain", [])])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(all_numbers))
            cursor.execute(f"""
                SELECT *
                FROM events
                WHERE tracking_number IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
            """, tuple(all_numbers))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None


