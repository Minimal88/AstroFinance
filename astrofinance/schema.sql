-- Local mirror of the Google Sheet. Fully derivable from it: `pull --rebuild`
-- is always safe, and nothing here is written without writing the Sheet first.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cardholders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cardholder_id INTEGER NOT NULL REFERENCES cardholders(id),
    card_type TEXT NOT NULL,
    last_digits TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (card_type, last_digits)
);

-- id is the Sheet's PaymentID, so an id seen in AppSheet is the same id shown
-- in the web UI.
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    payment_date TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT NOT NULL UNIQUE,
    txn_date TEXT NOT NULL,
    description TEXT,
    currency TEXT NOT NULL,
    amount REAL NOT NULL,
    merchant TEXT,
    location TEXT,
    card_id INTEGER NOT NULL REFERENCES cards(id),
    cardholder_id INTEGER NOT NULL REFERENCES cardholders(id),
    authorization TEXT,
    category TEXT,
    gmail_message_id TEXT,
    gmail_permalink TEXT,
    payment_id TEXT REFERENCES payments(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_transactions_date       ON transactions(txn_date);
CREATE INDEX IF NOT EXISTS idx_transactions_cardholder ON transactions(cardholder_id);
CREATE INDEX IF NOT EXISTS idx_transactions_card       ON transactions(card_id);
CREATE INDEX IF NOT EXISTS idx_transactions_payment    ON transactions(payment_id);
