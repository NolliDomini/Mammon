CREATE TABLE IF NOT EXISTS money_orders (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    symbol TEXT,
    side TEXT,
    qty NUMERIC,
    order_type TEXT,
    status TEXT,
    transport TEXT DEFAULT 'timescale',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trade_intents (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    symbol TEXT,
    side TEXT,
    qty NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS broadcast_audit (
    id SERIAL PRIMARY KEY,
    event_type TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
