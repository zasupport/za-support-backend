-- Migration 017: CyberShield billing records
-- Tracks monthly invoices per enrolled practice

CREATE TABLE IF NOT EXISTS cybershield_billing (
    id           SERIAL PRIMARY KEY,
    client_id    VARCHAR(100) NOT NULL,
    month_label  VARCHAR(20)  NOT NULL,                    -- e.g. "March 2026"
    amount       NUMERIC(10,2) NOT NULL DEFAULT 1499.00,
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending',  -- pending|sent|paid|overdue
    invoice_ref  VARCHAR(50),                               -- optional invoice number
    due_date     DATE,
    paid_at      TIMESTAMPTZ,
    notes        TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, month_label)
);

CREATE INDEX IF NOT EXISTS idx_cybershield_billing_client  ON cybershield_billing (client_id);
CREATE INDEX IF NOT EXISTS idx_cybershield_billing_status  ON cybershield_billing (status);
CREATE INDEX IF NOT EXISTS idx_cybershield_billing_due     ON cybershield_billing (due_date);
