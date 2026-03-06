-- Migration 019: Sales CRM + Upsell Engine
-- Tables: crm_contacts, crm_opportunities, crm_activities,
--         upsell_products, upsell_recommendations, sales_outcomes

CREATE TABLE IF NOT EXISTS crm_contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       VARCHAR(100),
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255),
    phone           VARCHAR(50),
    company         VARCHAR(200),
    segment         VARCHAR(50),
    investec_client BOOLEAN DEFAULT FALSE,
    referral_source VARCHAR(100),
    referred_by     VARCHAR(200),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_crm_contacts_client_id ON crm_contacts(client_id);
CREATE INDEX IF NOT EXISTS idx_crm_contacts_investec ON crm_contacts(investec_client) WHERE investec_client = TRUE;

CREATE TABLE IF NOT EXISTS crm_opportunities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id      UUID REFERENCES crm_contacts(id) ON DELETE CASCADE,
    client_id       VARCHAR(100),
    title           VARCHAR(200) NOT NULL,
    stage           VARCHAR(50) DEFAULT 'lead',
    value_rand      NUMERIC(12,2),
    product         VARCHAR(100),
    urgency         VARCHAR(50),
    investec_flag   BOOLEAN DEFAULT FALSE,
    segment         VARCHAR(50),
    referral_source VARCHAR(100),
    notes           TEXT,
    closed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_crm_opps_contact ON crm_opportunities(contact_id);
CREATE INDEX IF NOT EXISTS idx_crm_opps_stage ON crm_opportunities(stage);
CREATE INDEX IF NOT EXISTS idx_crm_opps_client ON crm_opportunities(client_id);

CREATE TABLE IF NOT EXISTS crm_activities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID REFERENCES crm_opportunities(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES crm_contacts(id) ON DELETE SET NULL,
    activity_type   VARCHAR(50) NOT NULL,
    subject         VARCHAR(200),
    notes           TEXT,
    outcome         VARCHAR(100),
    scheduled_at    TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_by      VARCHAR(100) DEFAULT 'system',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_crm_activities_opp ON crm_activities(opportunity_id);

CREATE TABLE IF NOT EXISTS upsell_products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(200) NOT NULL,
    category            VARCHAR(100),
    price_rand          NUMERIC(12,2),
    description         TEXT,
    diagnostic_triggers TEXT[],
    applicable_segments TEXT[],
    warranty_risk       VARCHAR(50) DEFAULT 'low',
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS upsell_recommendations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       VARCHAR(100) NOT NULL,
    product_id      UUID REFERENCES upsell_products(id) ON DELETE SET NULL,
    product_name    VARCHAR(200),
    trigger_field   VARCHAR(200),
    trigger_value   TEXT,
    roi_description TEXT,
    rand_value      NUMERIC(12,2),
    status          VARCHAR(50) DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_upsell_recs_client ON upsell_recommendations(client_id);
CREATE INDEX IF NOT EXISTS idx_upsell_recs_status ON upsell_recommendations(status);

CREATE TABLE IF NOT EXISTS sales_outcomes (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id    UUID REFERENCES crm_opportunities(id) ON DELETE SET NULL,
    recommendation_id UUID REFERENCES upsell_recommendations(id) ON DELETE SET NULL,
    client_id         VARCHAR(100),
    segment           VARCHAR(50),
    product           VARCHAR(100),
    outcome           VARCHAR(50),
    loss_reason       VARCHAR(200),
    revenue_rand      NUMERIC(12,2),
    notes             TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sales_outcomes_client ON sales_outcomes(client_id);

-- Seed upsell products (idempotent)
INSERT INTO upsell_products (name, category, price_rand, description, diagnostic_triggers, applicable_segments, warranty_risk)
SELECT * FROM (VALUES
  ('Screen Protector',         'hardware',     450,  'Tempered glass screen protector — near-zero failure rate',              ARRAY[]::TEXT[], ARRAY['individual','family','sme','medical_practice'], 'low'),
  ('Laptop Cover / Shell',     'hardware',     650,  'Hard-shell protective cover — near-zero failure rate',                  ARRAY[]::TEXT[], ARRAY['individual','family','sme','medical_practice'], 'low'),
  ('Laptop Bag / Sleeve',      'hardware',     850,  'Quality laptop bag — no failure risk',                                  ARRAY[]::TEXT[], ARRAY['individual','family','sme','medical_practice'], 'low'),
  ('Keyboard Replacement',     'hardware',    3500,  'MacBook keyboard replacement — low failure rate',                       ARRAY['keyboard_issues']::TEXT[], ARRAY['individual','sme','medical_practice'], 'low'),
  ('Trackpad Replacement',     'hardware',    2800,  'MacBook trackpad replacement — low failure rate',                       ARRAY['trackpad_issues']::TEXT[], ARRAY['individual','sme','medical_practice'], 'low'),
  ('MagSafe Port Repair',      'hardware',    2200,  'MagSafe port cleaning or replacement',                                  ARRAY['charging_issues']::TEXT[], ARRAY['individual','sme','medical_practice'], 'moderate'),
  ('Storage Upgrade (SSD)',    'hardware',    4500,  'SSD upgrade — when SMART warnings or <20% free space',                  ARRAY['storage_free_pct','smart_status']::TEXT[], ARRAY['individual','sme','medical_practice'], 'low'),
  ('RAM Upgrade (Intel only)', 'hardware',    3200,  'RAM upgrade for Intel Macs only — M-series RAM is soldered',            ARRAY['swap_used_gb','ram_pressure_high']::TEXT[], ARRAY['individual','sme','medical_practice'], 'low'),
  ('AppleCare+ / Extended Warranty', 'service', 5500,'Extended coverage: keyboards, trackpads, screens, logic board. NEVER batteries.', ARRAY[]::TEXT[], ARRAY['individual','family','sme','medical_practice'], 'never'),
  ('CyberShield Subscription', 'subscription', 1499, 'Monthly network security monitoring — R 1,499/month',                  ARRAY['firewall_disabled','open_ports']::TEXT[], ARRAY['sme','medical_practice'], 'low'),
  ('SLA Support Contract',     'subscription', 2999, 'Monthly SLA — priority support, quarterly health checks',              ARRAY[]::TEXT[], ARRAY['sme','medical_practice'], 'low'),
  ('Health Check Assessment',  'service',     2500,  'Full IT health check and CyberPulse report',                           ARRAY[]::TEXT[], ARRAY['individual','family','sme','medical_practice'], 'low')
) AS v(name, category, price_rand, description, diagnostic_triggers, applicable_segments, warranty_risk)
WHERE NOT EXISTS (SELECT 1 FROM upsell_products WHERE upsell_products.name = v.name);
