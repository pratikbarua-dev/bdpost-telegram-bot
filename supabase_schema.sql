-- ==========================================================
-- Bangladesh Post & AliExpress Telegram Bot Schema for Supabase
-- Copy and paste this into Supabase SQL Editor and click Run.
-- ==========================================================

-- 1. Users Table
CREATE TABLE IF NOT EXISTS users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    full_name TEXT,
    is_banned INT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Optional column additions if updating existing tables
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned INT DEFAULT 0;

-- 2. Shipments Table (Core Physical Shipment Entity)
CREATE TABLE IF NOT EXISTS shipments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    primary_tracking_number TEXT UNIQUE NOT NULL,
    current_status TEXT,
    current_location TEXT,
    origin_country TEXT,
    dest_country TEXT,
    local_tracking_number TEXT,
    cainiao_enabled INT NOT NULL DEFAULT 1,
    bdpost_enabled INT NOT NULL DEFAULT 1,
    handover_detected INT NOT NULL DEFAULT 0,
    handover_at TEXT,
    handover_event_hash TEXT,
    is_delivered INT NOT NULL DEFAULT 0,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 3. Shipment Tracking Numbers (Linked Tracking Chains: AP -> CNG -> UG)
CREATE TABLE IF NOT EXISTS shipment_tracking_numbers (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    tracking_number TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'unknown',
    type TEXT NOT NULL DEFAULT 'linked',
    discovered_from TEXT,
    is_active INT NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(shipment_id, tracking_number)
);

-- 4. Shipment Subscribers Table (User Subscriptions & Custom Labels)
CREATE TABLE IF NOT EXISTS shipment_subscribers (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    telegram_id BIGINT NOT NULL,
    label TEXT,
    active INT NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(shipment_id, telegram_id)
);

-- 5. Legacy / Direct Trackings Table
CREATE TABLE IF NOT EXISTS trackings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    tracking_number TEXT NOT NULL,
    label TEXT,
    active INT NOT NULL DEFAULT 1,
    cainiao_enabled INT NOT NULL DEFAULT 0,
    bdpost_enabled INT NOT NULL DEFAULT 1,
    handover_detected INT NOT NULL DEFAULT 0,
    handover_at TEXT,
    handover_event_hash TEXT,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(telegram_id, tracking_number)
);

-- 6. Events Table (Tracking Events with SHA-256 Deduplication)
CREATE TABLE IF NOT EXISTS events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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

-- Indexes for maximum performance
CREATE INDEX IF NOT EXISTS idx_stn_number ON shipment_tracking_numbers(tracking_number);
CREATE INDEX IF NOT EXISTS idx_stn_shipment ON shipment_tracking_numbers(shipment_id);
CREATE INDEX IF NOT EXISTS idx_subs_user ON shipment_subscribers(telegram_id, active);
CREATE INDEX IF NOT EXISTS idx_subs_shipment ON shipment_subscribers(shipment_id, active);
CREATE INDEX IF NOT EXISTS idx_events_tracking ON events(tracking_number);
CREATE INDEX IF NOT EXISTS idx_events_hash ON events(event_hash);
CREATE INDEX IF NOT EXISTS idx_shipments_primary ON shipments(primary_tracking_number);
