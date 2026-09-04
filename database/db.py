import os
import re
import sqlite3
import datetime
import logging
from typing import Optional, List, Dict, Set, Tuple, Any

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class Database:
    def __init__(self, db_path: str = "bdpost.db", db_url: Optional[str] = None):
        if db_url and (db_url.startswith("postgres://") or db_url.startswith("postgresql://")):
            if not HAS_PSYCOPG2:
                logger.warning("psycopg2 not installed. Falling back to SQLite.")
                self.is_postgres = False
                self.db_path = db_path
            else:
                self.is_postgres = True
                # Fix uri scheme if postgres://
                if db_url.startswith("postgres://"):
                    db_url = db_url.replace("postgres://", "postgresql://", 1)
                self.db_url = db_url
        else:
            self.is_postgres = False
            self.db_path = db_path

        self.init_db()

    def _get_connection(self):
        if self.is_postgres:
            conn = psycopg2.connect(self.db_url, cursor_factory=psycopg2.extras.RealDictCursor)
            conn.autocommit = False
            return conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    def _prep_sql(self, sql: str) -> str:
        if not self.is_postgres:
            return sql

        # Convert SQLite dialect to PostgreSQL dialect
        res = sql.replace("?", "%s")
        res = res.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        res = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", res, flags=re.IGNORECASE)
        # If INSERT OR IGNORE was used without ON CONFLICT clause, append ON CONFLICT DO NOTHING
        if "INSERT OR IGNORE INTO" in sql.upper() and "ON CONFLICT" not in res.upper():
            res = res.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING;"

        return res

    def init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. users
            cursor.execute(self._prep_sql("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username TEXT,
                    full_name TEXT,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
            """))

            # 2. shipments
            cursor.execute(self._prep_sql("""
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
            """))

            # 3. shipment_tracking_numbers
            cursor.execute(self._prep_sql("""
                CREATE TABLE IF NOT EXISTS shipment_tracking_numbers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shipment_id INTEGER NOT NULL,
                    tracking_number TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'unknown',
                    type TEXT NOT NULL DEFAULT 'linked',
                    discovered_from TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(shipment_id, tracking_number)
                );
            """))

            # 4. shipment_subscribers
            cursor.execute(self._prep_sql("""
                CREATE TABLE IF NOT EXISTS shipment_subscribers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shipment_id INTEGER NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    label TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(shipment_id, telegram_id)
                );
            """))

            # 5. legacy trackings table
            cursor.execute(self._prep_sql("""
                CREATE TABLE IF NOT EXISTS trackings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id BIGINT NOT NULL,
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
            """))

            # 6. events table
            cursor.execute(self._prep_sql("""
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
            """))

            # 7. notification_queue table (Transactional Outbox Pattern)
            cursor.execute(self._prep_sql("""
                CREATE TABLE IF NOT EXISTS notification_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id BIGINT NOT NULL,
                    shipment_id INTEGER NOT NULL,
                    event_id INTEGER,
                    message_type TEXT NOT NULL DEFAULT 'STATUS_UPDATE',
                    payload_html TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                );
            """))

            # 8. post_offices table
            cursor.execute(self._prep_sql("""
                CREATE TABLE IF NOT EXISTS post_offices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_office TEXT NOT NULL,
                    post_code TEXT NOT NULL,
                    thana TEXT,
                    district TEXT NOT NULL,
                    division TEXT NOT NULL,
                    phone TEXT,
                    source TEXT,
                    UNIQUE(post_office, post_code, district)
                );
            """))

            # 9. postal_officials table
            cursor.execute(self._prep_sql("""
                CREATE TABLE IF NOT EXISTS postal_officials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portal TEXT NOT NULL,
                    name TEXT NOT NULL,
                    designation TEXT NOT NULL,
                    office TEXT,
                    email TEXT,
                    phone_office TEXT,
                    mobile TEXT,
                    fax TEXT,
                    UNIQUE(portal, name, designation)
                );
            """))

            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_stn_number ON shipment_tracking_numbers(tracking_number);"))
            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_stn_shipment ON shipment_tracking_numbers(shipment_id);"))
            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_subs_user ON shipment_subscribers(telegram_id, active);"))
            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_subs_shipment ON shipment_subscribers(shipment_id, active);"))
            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_events_tracking ON events(tracking_number);"))
            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_notif_queue_pending ON notification_queue(status, next_retry_at);"))
            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_po_code ON post_offices(post_code);"))
            cursor.execute(self._prep_sql("CREATE INDEX IF NOT EXISTS idx_po_district ON post_offices(district);"))

            # Automatic Schema Migrations for Users, Shipments & Subscribers tables
            for col, col_def in [("username", "TEXT"), ("full_name", "TEXT"), ("is_banned", "INTEGER DEFAULT 0"), ("updated_at", "TEXT")]:
                try:
                    cursor.execute(self._prep_sql(f"ALTER TABLE users ADD COLUMN {col} {col_def};"))
                except Exception:
                    pass

            for col, col_def in [("carrier_code", "TEXT DEFAULT 'cainiao'"), ("priority", "TEXT DEFAULT 'HOT'"), ("delivered_at", "TEXT"), ("last_status", "TEXT")]:
                try:
                    cursor.execute(self._prep_sql(f"ALTER TABLE shipments ADD COLUMN {col} {col_def};"))
                except Exception:
                    pass

            for col, col_def in [("notifications_enabled", "INTEGER DEFAULT 1"), ("updated_at", "TEXT")]:
                try:
                    cursor.execute(self._prep_sql(f"ALTER TABLE shipment_subscribers ADD COLUMN {col} {col_def};"))
                except Exception:
                    pass

            conn.commit()
            backend_type = f"PostgreSQL ({self.db_url.split('@')[-1]})" if self.is_postgres else f"SQLite ({self.db_path})"
            logger.info("Database initialized successfully using %s", backend_type)

        # Seed post offices and officials directory if empty
        self.seed_post_office_directory_if_needed()

    def seed_post_office_directory_if_needed(self) -> None:
        try:
            from bdpost.post_office_data import get_cleaned_post_offices_data, get_cleaned_officials_data
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(self._prep_sql("SELECT COUNT(*) as cnt FROM post_offices;"))
                row = cursor.fetchone()
                if row and row["cnt"] == 0:
                    offices = get_cleaned_post_offices_data()
                    logger.info("Seeding %d post offices into database...", len(offices))
                    for o in offices:
                        cursor.execute(self._prep_sql("""
                            INSERT INTO post_offices (post_office, post_code, thana, district, division, phone, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(post_office, post_code, district) DO UPDATE SET
                                phone = COALESCE(excluded.phone, post_offices.phone),
                                source = COALESCE(excluded.source, post_offices.source);
                        """), (o["post_office"], o["post_code"], o["thana"], o["district"], o["division"], o["phone"], o["source"]))
                    conn.commit()

                cursor.execute(self._prep_sql("SELECT COUNT(*) as cnt FROM postal_officials;"))
                orow = cursor.fetchone()
                if orow and orow["cnt"] == 0:
                    officials = get_cleaned_officials_data()
                    logger.info("Seeding %d postal officials into database...", len(officials))
                    for off in officials:
                        cursor.execute(self._prep_sql("""
                            INSERT INTO postal_officials (portal, name, designation, office, email, phone_office, mobile, fax)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(portal, name, designation) DO UPDATE SET
                                mobile = COALESCE(excluded.mobile, postal_officials.mobile),
                                phone_office = COALESCE(excluded.phone_office, postal_officials.phone_office);
                        """), (off["portal"], off["name"], off["designation"], off["office"], off["email"], off["phone_office"], off["mobile"], off["fax"]))
                    conn.commit()
        except Exception as e:
            logger.warning("Directory seeding notice: %s", e)

    def get_or_create_user(self, telegram_id: int, username: Optional[str] = None, full_name: Optional[str] = None) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                INSERT INTO users (telegram_id, username, full_name, is_banned, created_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    full_name = COALESCE(excluded.full_name, users.full_name)
            """), (telegram_id, username, full_name, now))
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
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cleaned_num = tracking_number.strip().upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Check if number exists in shipment_tracking_numbers
            cursor.execute(self._prep_sql("""
                SELECT shipment_id FROM shipment_tracking_numbers
                WHERE tracking_number = ?
                LIMIT 1
            """), (cleaned_num,))
            row = cursor.fetchone()

            if row:
                shipment_id = row["shipment_id"]
            else:
                # 2. Check if number is primary in shipments
                cursor.execute(self._prep_sql("""
                    SELECT id FROM shipments
                    WHERE primary_tracking_number = ?
                    LIMIT 1
                """), (cleaned_num,))
                srow = cursor.fetchone()

                if srow:
                    shipment_id = srow["id"]
                else:
                    # 3. Create new shipment
                    if self.is_postgres:
                        cursor.execute("""
                            INSERT INTO shipments (
                                primary_tracking_number, created_at, updated_at
                            ) VALUES (%s, %s, %s) RETURNING id;
                        """, (cleaned_num, now, now))
                        shipment_id = cursor.fetchone()["id"]
                    else:
                        cursor.execute("""
                            INSERT INTO shipments (
                                primary_tracking_number, created_at, updated_at
                            ) VALUES (?, ?, ?)
                        """, (cleaned_num, now, now))
                        shipment_id = cursor.lastrowid

                # Register as original number in chain
                cursor.execute(self._prep_sql("""
                    INSERT OR IGNORE INTO shipment_tracking_numbers (
                        shipment_id, tracking_number, source, type, created_at
                    ) VALUES (?, ?, 'original', 'original', ?)
                """), (shipment_id, cleaned_num, now))

            # 4. Subscribe user if telegram_id provided
            if telegram_id is not None:
                cursor.execute(self._prep_sql("""
                    INSERT OR IGNORE INTO users (telegram_id, created_at)
                    VALUES (?, ?)
                """), (telegram_id, now))

                cursor.execute(self._prep_sql("""
                    INSERT INTO shipment_subscribers (
                        shipment_id, telegram_id, label, active, created_at
                    ) VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(shipment_id, telegram_id) DO UPDATE SET
                        active = 1,
                        label = COALESCE(excluded.label, shipment_subscribers.label)
                """), (shipment_id, telegram_id, label, now))

                cursor.execute(self._prep_sql("""
                    INSERT INTO trackings (
                        telegram_id, tracking_number, label, active, created_at
                    ) VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(telegram_id, tracking_number) DO UPDATE SET
                        active = 1,
                        label = COALESCE(excluded.label, trackings.label)
                """), (telegram_id, cleaned_num, label, now))

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
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cleaned_num = tracking_number.strip().upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(self._prep_sql("""
                SELECT shipment_id FROM shipment_tracking_numbers
                WHERE tracking_number = ?
            """), (cleaned_num,))
            existing = cursor.fetchone()

            if existing:
                other_id = existing["shipment_id"]
                if other_id != shipment_id:
                    logger.info("Merging shipment %d into shipment %d due to linked number %s", other_id, shipment_id, cleaned_num)
                    cursor.execute(self._prep_sql("UPDATE shipment_tracking_numbers SET shipment_id = ? WHERE shipment_id = ?"), (shipment_id, other_id))
                    cursor.execute(self._prep_sql("""
                        INSERT OR IGNORE INTO shipment_subscribers (shipment_id, telegram_id, label, active, created_at)
                        SELECT ?, telegram_id, label, active, created_at FROM shipment_subscribers WHERE shipment_id = ?
                    """), (shipment_id, other_id))
                    cursor.execute(self._prep_sql("DELETE FROM shipment_subscribers WHERE shipment_id = ?"), (other_id,))
                    cursor.execute(self._prep_sql("DELETE FROM shipments WHERE id = ?"), (other_id,))
                return False

            cursor.execute(self._prep_sql("""
                INSERT OR IGNORE INTO shipment_tracking_numbers (
                    shipment_id, tracking_number, source, type, discovered_from, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """), (shipment_id, cleaned_num, source, num_type, discovered_from, now))

            if num_type == "local" or source == "bdpost":
                cursor.execute(self._prep_sql("""
                    UPDATE shipments
                    SET local_tracking_number = ?, updated_at = ?
                    WHERE id = ? AND (local_tracking_number IS NULL OR local_tracking_number = '')
                """), (cleaned_num, now, shipment_id))

            conn.commit()
            return cursor.rowcount > 0

    def get_shipment(self, shipment_id: int) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("SELECT * FROM shipments WHERE id = ?"), (shipment_id,))
            row = cursor.fetchone()
            if not row:
                return None
            shipment = dict(row)
            cursor.execute(self._prep_sql("""
                SELECT tracking_number, source, type, discovered_from, is_active
                FROM shipment_tracking_numbers
                WHERE shipment_id = ?
                ORDER BY id ASC
            """), (shipment_id,))
            shipment["tracking_chain"] = [dict(r) for r in cursor.fetchall()]
            return shipment

    def get_shipment_by_tracking_number(self, tracking_number: str) -> Optional[Dict]:
        cleaned_num = tracking_number.strip().upper()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT shipment_id FROM shipment_tracking_numbers
                WHERE tracking_number = ?
                LIMIT 1
            """), (cleaned_num,))
            row = cursor.fetchone()
            if row:
                return self.get_shipment(row["shipment_id"])

            cursor.execute(self._prep_sql("SELECT id FROM shipments WHERE primary_tracking_number = ? LIMIT 1"), (cleaned_num,))
            srow = cursor.fetchone()
            if srow:
                return self.get_shipment(srow["id"])

            return None

    def get_tracking_chain_numbers(self, shipment_id: int) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT tracking_number
                FROM shipment_tracking_numbers
                WHERE shipment_id = ? AND is_active = 1
                ORDER BY id ASC
            """), (shipment_id,))
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
            cursor.execute(self._prep_sql(f"UPDATE shipments SET {', '.join(updates)} WHERE id = ?"), tuple(params))
            conn.commit()

    def get_shipment_subscribers(self, shipment_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT telegram_id, label
                FROM shipment_subscribers
                WHERE shipment_id = ? AND active = 1
            """), (shipment_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_user_active_shipments(self, telegram_id: int) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT s.*, sub.label
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.telegram_id = ? AND sub.active = 1
                ORDER BY s.updated_at DESC
            """), (telegram_id,))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                shipment = dict(r)
                cursor.execute(self._prep_sql("""
                    SELECT tracking_number, source, type, discovered_from
                    FROM shipment_tracking_numbers
                    WHERE shipment_id = ?
                    ORDER BY id ASC
                """), (shipment["id"],))
                shipment["tracking_chain"] = [dict(tr) for tr in cursor.fetchall()]
                result.append(shipment)
            return result

    def get_all_active_shipments(self) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT DISTINCT s.*
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.active = 1 AND s.is_delivered = 0
            """))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                shipment = dict(r)
                cursor.execute(self._prep_sql("""
                    SELECT tracking_number, source, type, discovered_from, is_active
                    FROM shipment_tracking_numbers
                    WHERE shipment_id = ? AND is_active = 1
                    ORDER BY id ASC
                """), (shipment["id"],))
                shipment["tracking_chain"] = [dict(tr) for tr in cursor.fetchall()]
                result.append(shipment)
            return result

    def has_events_for_shipment(self, shipment_id: int) -> bool:
        chain_numbers = self.get_tracking_chain_numbers(shipment_id)
        if not chain_numbers:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(chain_numbers))
            cursor.execute(self._prep_sql(f"SELECT 1 FROM events WHERE tracking_number IN ({placeholders}) LIMIT 1"), tuple(chain_numbers))
            return cursor.fetchone() is not None

    def get_stale_unscanned_shipments(self, days: int = 10) -> List[Dict]:
        now = datetime.datetime.now(datetime.timezone.utc)
        active_shipments = self.get_all_active_shipments()
        stale = []
        for s in active_shipments:
            created_at_str = s.get("created_at", "")
            try:
                created_dt = datetime.datetime.fromisoformat(created_at_str)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                if (now - created_dt).total_seconds() >= days * 86400:
                    if not self.has_events_for_shipment(s["id"]):
                        stale.append(s)
            except Exception as e:
                logger.debug("Error checking age of shipment %s: %s", s.get("primary_tracking_number"), e)

        return stale

    def expire_stale_shipment(self, shipment_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE shipments
                SET cainiao_enabled = 0, bdpost_enabled = 0
                WHERE id = ?
            """), (shipment_id,))
            cursor.execute(self._prep_sql("""
                UPDATE shipment_subscribers
                SET active = 0
                WHERE shipment_id = ?
            """), (shipment_id,))
            count = cursor.rowcount
            for num in self.get_tracking_chain_numbers(shipment_id):
                cursor.execute(self._prep_sql("UPDATE trackings SET active = 0 WHERE tracking_number = ?"), (num,))
            conn.commit()
            return count

    def stop_shipment_tracking(self, telegram_id: int, tracking_number: str) -> bool:
        cleaned_num = tracking_number.strip().upper()
        shipment = self.get_shipment_by_tracking_number(cleaned_num)
        if not shipment:
            return self.stop_tracking(telegram_id, cleaned_num)

        shipment_id = shipment["id"]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE shipment_subscribers
                SET active = 0
                WHERE shipment_id = ? AND telegram_id = ? AND active = 1
            """), (shipment_id, telegram_id))
            sub_count = cursor.rowcount

            for num in self.get_tracking_chain_numbers(shipment_id):
                cursor.execute(self._prep_sql("""
                    UPDATE trackings
                    SET active = 0
                    WHERE telegram_id = ? AND tracking_number = ?
                """), (telegram_id, num))

            conn.commit()
            return sub_count > 0

    def stop_all_user_shipments(self, telegram_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE shipment_subscribers
                SET active = 0
                WHERE telegram_id = ? AND active = 1
            """), (telegram_id,))
            count = cursor.rowcount
            cursor.execute(self._prep_sql("""
                UPDATE trackings
                SET active = 0
                WHERE telegram_id = ? AND active = 1
            """), (telegram_id,))
            conn.commit()
            return count

    def deactivate_shipment_on_delivery(self, shipment_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE shipments
                SET is_delivered = 1, cainiao_enabled = 0, bdpost_enabled = 0
                WHERE id = ?
            """), (shipment_id,))
            cursor.execute(self._prep_sql("""
                UPDATE shipment_subscribers
                SET active = 0
                WHERE shipment_id = ?
            """), (shipment_id,))
            count = cursor.rowcount
            for num in self.get_tracking_chain_numbers(shipment_id):
                cursor.execute(self._prep_sql("UPDATE trackings SET active = 0 WHERE tracking_number = ?"), (num,))
            conn.commit()
            return count

    def set_shipment_label(self, telegram_id: int, tracking_number: str, label: Optional[str]) -> bool:
        cleaned_num = tracking_number.strip().upper()
        shipment = self.get_shipment_by_tracking_number(cleaned_num)
        if not shipment:
            return self.set_parcel_label(telegram_id, cleaned_num, label)

        shipment_id = shipment["id"]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE shipment_subscribers
                SET label = ?
                WHERE shipment_id = ? AND telegram_id = ? AND active = 1
            """), (label.strip() if label else None, shipment_id, telegram_id))
            cursor.execute(self._prep_sql("""
                UPDATE trackings
                SET label = ?
                WHERE telegram_id = ? AND tracking_number = ?
            """), (label.strip() if label else None, telegram_id, cleaned_num))
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
            cursor.execute(self._prep_sql("SELECT telegram_id, label FROM trackings WHERE tracking_number = ? AND active = 1"), (tracking_number,))
            return [dict(r) for r in cursor.fetchall()]

    def get_all_active_tracking_numbers(self) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT DISTINCT primary_tracking_number as tracking_number
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.active = 1 AND s.is_delivered = 0
            """))
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
            cursor.execute(self._prep_sql("UPDATE shipments SET last_checked_at = ?, updated_at = ? WHERE primary_tracking_number = ?"), (now, now, tracking_number))
            cursor.execute(self._prep_sql("UPDATE trackings SET last_checked_at = ? WHERE tracking_number = ?"), (now, tracking_number))
            conn.commit()

    def get_known_event_hashes(self, tracking_number: str) -> Set[str]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        all_numbers = [tracking_number]
        if shipment:
            all_numbers.extend([item["tracking_number"] for item in shipment.get("tracking_chain", [])])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(all_numbers))
            cursor.execute(self._prep_sql(f"SELECT event_hash FROM events WHERE tracking_number IN ({placeholders})"), tuple(all_numbers))
            return {row["event_hash"] for row in cursor.fetchall()}

    def save_events(self, tracking_number: str, events: List[Dict]) -> List[Dict]:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        known_hashes = self.get_known_event_hashes(tracking_number)
        new_events = []

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Retrieve existing event signatures to deduplicate cross-provider events (e.g. Cainiao vs 17TRACK)
            shipment = self.get_shipment_by_tracking_number(tracking_number)
            all_numbers = [tracking_number]
            if shipment:
                all_numbers.extend([item["tracking_number"] for item in shipment.get("tracking_chain", [])])

            placeholders = ",".join("?" * len(all_numbers))
            cursor.execute(self._prep_sql(f"""
                SELECT event_date, status, description
                FROM events
                WHERE tracking_number IN ({placeholders})
            """), tuple(all_numbers))
            existing_rows = cursor.fetchall()

            existing_signatures = set()
            for r in existing_rows:
                d = str(r["event_date"] or "").strip()[:16]
                st = str(r["status"] or "").strip().lower()
                desc = str(r["description"] or "").strip().lower()
                if d and st:
                    existing_signatures.add((d, st))
                if d and desc:
                    existing_signatures.add((d, desc))

            for event in events:
                event_hash = event["event_hash"]
                evt_date = str(event.get("event_date", "")).strip()[:16]
                evt_status = str(event.get("status", "")).strip().lower()
                evt_desc = str(event.get("description", "")).strip().lower()

                if event_hash in known_hashes:
                    continue

                if evt_date and ((evt_date, evt_status) in existing_signatures or (evt_date, evt_desc) in existing_signatures):
                    continue

                cursor.execute(self._prep_sql("""
                    INSERT OR IGNORE INTO events (
                        tracking_number, event_date, origin_country,
                        destination_country, location, status, description,
                        source, action_code, timezone, event_hash, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (
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
                    if evt_date:
                        existing_signatures.add((evt_date, evt_status))
                        existing_signatures.add((evt_date, evt_desc))
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
            cursor.execute(self._prep_sql(f"""
                SELECT *
                FROM events
                WHERE tracking_number IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
            """), tuple(all_numbers))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    # -----------------------------------------------------------------
    # Admin Control & Oversight Methods
    # -----------------------------------------------------------------
    def get_system_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("SELECT COUNT(*) as total_users FROM users;"))
            total_users = cursor.fetchone()["total_users"]

            cursor.execute(self._prep_sql("SELECT COUNT(*) as total_shipments FROM shipments;"))
            total_shipments = cursor.fetchone()["total_shipments"]

            cursor.execute(self._prep_sql("""
                SELECT COUNT(DISTINCT s.id) as active_shipments
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.active = 1 AND s.is_delivered = 0;
            """))
            active_shipments = cursor.fetchone()["active_shipments"]

            cursor.execute(self._prep_sql("SELECT COUNT(*) as delivered FROM shipments WHERE is_delivered = 1;"))
            delivered = cursor.fetchone()["delivered"]

            cursor.execute(self._prep_sql("SELECT COUNT(*) as handover_count FROM shipments WHERE handover_detected = 1;"))
            handover_count = cursor.fetchone()["handover_count"]

            cursor.execute(self._prep_sql("SELECT COUNT(*) as banned_users FROM users WHERE is_banned = 1;"))
            banned_users = cursor.fetchone()["banned_users"]

            return {
                "total_users": total_users,
                "total_shipments": total_shipments,
                "active_shipments": active_shipments,
                "delivered_shipments": delivered,
                "handover_shipments": handover_count,
                "banned_users": banned_users
            }

    def get_all_users_admin(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT u.telegram_id, u.username, u.full_name, u.is_banned, u.created_at,
                       COUNT(DISTINCT CASE WHEN sub.active = 1 THEN sub.shipment_id END) as active_parcels,
                       COUNT(DISTINCT sub.shipment_id) as total_parcels
                FROM users u
                LEFT JOIN shipment_subscribers sub ON u.telegram_id = sub.telegram_id
                GROUP BY u.telegram_id, u.username, u.full_name, u.is_banned, u.created_at
                ORDER BY u.id DESC
                LIMIT ? OFFSET ?;
            """), (limit, offset))
            return [dict(r) for r in cursor.fetchall()]

    def get_user_admin_profile(self, identifier: str) -> Optional[Dict[str, Any]]:
        cleaned = identifier.strip().lstrip("@")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if cleaned.isdigit():
                cursor.execute(self._prep_sql("SELECT * FROM users WHERE telegram_id = ? LIMIT 1;"), (int(cleaned),))
            else:
                cursor.execute(self._prep_sql("SELECT * FROM users WHERE LOWER(username) = LOWER(?) LIMIT 1;"), (cleaned,))
            row = cursor.fetchone()
            if not row:
                return None
            user_data = dict(row)
            user_data["parcels"] = self.get_user_parcels_admin(user_data["telegram_id"])
            return user_data

    def get_user_parcels_admin(self, telegram_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT s.*, sub.label, sub.active as is_subscribed, sub.created_at as subscribed_at
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.telegram_id = ?
                ORDER BY sub.active DESC, s.updated_at DESC;
            """), (telegram_id,))
            rows = cursor.fetchall()
            parcels = []
            for r in rows:
                p = dict(r)
                p["latest_event"] = self.get_latest_event_for_tracking(p["primary_tracking_number"])
                cursor.execute(self._prep_sql("""
                    SELECT tracking_number, source, type, discovered_from
                    FROM shipment_tracking_numbers
                    WHERE shipment_id = ?
                    ORDER BY id ASC;
                """), (p["id"],))
                p["tracking_chain"] = [dict(tr) for tr in cursor.fetchall()]
                parcels.append(p)
            return parcels

    def get_all_shipments_admin(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT s.*, COUNT(sub.telegram_id) as subscribers_count
                FROM shipments s
                LEFT JOIN shipment_subscribers sub ON s.id = sub.shipment_id AND sub.active = 1
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                LIMIT ? OFFSET ?;
            """), (limit, offset))
            rows = cursor.fetchall()
            shipments = []
            for r in rows:
                s = dict(r)
                cursor.execute(self._prep_sql("""
                    SELECT tracking_number, source, type
                    FROM shipment_tracking_numbers
                    WHERE shipment_id = ?
                    ORDER BY id ASC;
                """), (s["id"],))
                s["tracking_chain"] = [dict(tr) for tr in cursor.fetchall()]
                s["latest_event"] = self.get_latest_event_for_tracking(s["primary_tracking_number"])
                shipments.append(s)
            return shipments

    def set_user_ban_status(self, telegram_id: int, is_banned: bool) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("UPDATE users SET is_banned = ? WHERE telegram_id = ?;"), (1 if is_banned else 0, telegram_id))
            conn.commit()
            return cursor.rowcount > 0

    def is_user_banned(self, telegram_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("SELECT is_banned FROM users WHERE telegram_id = ? LIMIT 1;"), (telegram_id,))
            row = cursor.fetchone()
            return bool(row and row["is_banned"] == 1)

    def admin_delete_shipment(self, shipment_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            chain = self.get_tracking_chain_numbers(shipment_id)
            if chain:
                placeholders = ",".join("?" * len(chain))
                cursor.execute(self._prep_sql(f"DELETE FROM events WHERE tracking_number IN ({placeholders});"), tuple(chain))
                cursor.execute(self._prep_sql(f"DELETE FROM trackings WHERE tracking_number IN ({placeholders});"), tuple(chain))
            cursor.execute(self._prep_sql("DELETE FROM shipment_subscribers WHERE shipment_id = ?;"), (shipment_id,))
            cursor.execute(self._prep_sql("DELETE FROM shipment_tracking_numbers WHERE shipment_id = ?;"), (shipment_id,))
            cursor.execute(self._prep_sql("DELETE FROM shipments WHERE id = ?;"), (shipment_id,))
            conn.commit()
            return cursor.rowcount > 0

    def admin_force_shipment_state(
        self,
        shipment_id: int,
        cainiao_enabled: Optional[int] = None,
        bdpost_enabled: Optional[int] = None,
        handover_detected: Optional[int] = None,
        is_delivered: Optional[int] = None
    ) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = ["updated_at = ?"]
            params = [now]
            if cainiao_enabled is not None:
                updates.append("cainiao_enabled = ?")
                params.append(cainiao_enabled)
            if bdpost_enabled is not None:
                updates.append("bdpost_enabled = ?")
                params.append(bdpost_enabled)
            if handover_detected is not None:
                updates.append("handover_detected = ?")
                params.append(handover_detected)
            if is_delivered is not None:
                updates.append("is_delivered = ?")
                params.append(is_delivered)
                if is_delivered == 1:
                    cursor.execute(self._prep_sql("UPDATE shipment_subscribers SET active = 0 WHERE shipment_id = ?;"), (shipment_id,))
            params.append(shipment_id)
            cursor.execute(self._prep_sql(f"UPDATE shipments SET {', '.join(updates)} WHERE id = ?;"), tuple(params))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_registered_telegram_ids(self) -> List[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("SELECT telegram_id FROM users WHERE is_banned = 0;"))
            return [r["telegram_id"] for r in cursor.fetchall()]

    # -----------------------------------------------------------------
    # Notification Outbox Queue Methods
    # -----------------------------------------------------------------
    def enqueue_notification(
        self,
        telegram_id: int,
        shipment_id: int,
        payload_html: str,
        message_type: str = "STATUS_UPDATE",
        event_id: Optional[int] = None
    ) -> int:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                INSERT INTO notification_queue (
                    telegram_id, shipment_id, event_id, message_type,
                    payload_html, status, retry_count, next_retry_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'PENDING', 0, ?, ?);
            """), (telegram_id, shipment_id, event_id, message_type, payload_html, now, now))
            conn.commit()
            return cursor.lastrowid or 0

    def get_pending_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT nq.*, s.primary_tracking_number
                FROM notification_queue nq
                JOIN shipments s ON nq.shipment_id = s.id
                WHERE nq.status = 'PENDING' AND nq.next_retry_at <= ?
                ORDER BY nq.id ASC
                LIMIT ?;
            """), (now, limit))
            return [dict(r) for r in cursor.fetchall()]

    def mark_notification_sent(self, notification_id: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE notification_queue
                SET status = 'SENT', sent_at = ?
                WHERE id = ?;
            """), (now, notification_id))
            conn.commit()

    def mark_notification_failed(self, notification_id: int, retry_count: int, next_retry_seconds: int = 60) -> None:
        next_dt = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=next_retry_seconds)).isoformat()
        new_status = 'FAILED' if retry_count >= 5 else 'PENDING'
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE notification_queue
                SET status = ?, retry_count = ?, next_retry_at = ?
                WHERE id = ?;
            """), (new_status, retry_count, next_dt, notification_id))
            conn.commit()

    # -----------------------------------------------------------------
    # Priority-Aware Dynamic Scheduler Methods
    # -----------------------------------------------------------------
    def get_shipments_due_for_check(self, batch_size: int = 25) -> List[Dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc)
        hot_threshold = (now - datetime.timedelta(minutes=15)).isoformat()
        warm_threshold = (now - datetime.timedelta(minutes=30)).isoformat()
        cold_threshold = (now - datetime.timedelta(hours=2)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT DISTINCT s.*
                FROM shipments s
                JOIN shipment_subscribers sub ON s.id = sub.shipment_id
                WHERE sub.active = 1 AND s.is_delivered = 0
                  AND (
                    s.last_checked_at IS NULL
                    OR (COALESCE(s.priority, 'HOT') = 'HOT' AND s.last_checked_at <= ?)
                    OR (s.priority = 'WARM' AND s.last_checked_at <= ?)
                    OR (s.priority = 'COLD' AND s.last_checked_at <= ?)
                  )
                ORDER BY s.last_checked_at ASC
                LIMIT ?;
            """), (hot_threshold, warm_threshold, cold_threshold, batch_size))
            rows = cursor.fetchall()
            shipments = []
            for r in rows:
                shipment = dict(r)
                cursor.execute(self._prep_sql("""
                    SELECT tracking_number, source, type, discovered_from, is_active
                    FROM shipment_tracking_numbers
                    WHERE shipment_id = ? AND is_active = 1
                    ORDER BY id ASC;
                """), (shipment["id"],))
                shipment["tracking_chain"] = [dict(tr) for tr in cursor.fetchall()]
                shipments.append(shipment)
            return shipments

    def update_shipment_priority(self, shipment_id: int, priority: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE shipments
                SET priority = ?, updated_at = ?
                WHERE id = ?;
            """), (priority, now, shipment_id))
            conn.commit()

    # -----------------------------------------------------------------
    # Post Office & Officials Directory Operations
    # -----------------------------------------------------------------
    def update_post_office_phone(self, post_code: str, new_phone: str, source: str = "user_verified") -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                UPDATE post_offices
                SET phone = ?, source = ?
                WHERE post_code = ?;
            """), (new_phone, source, post_code.strip()))
            conn.commit()
            return cursor.rowcount > 0

    def get_post_offices_by_query(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        q = f"%{query.strip()}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(self._prep_sql("""
                SELECT * FROM post_offices
                WHERE post_code LIKE ?
                   OR post_office LIKE ?
                   OR thana LIKE ?
                   OR district LIKE ?
                ORDER BY district ASC, post_office ASC
                LIMIT ?;
            """), (q, q, q, q, limit))
            return [dict(r) for r in cursor.fetchall()]

