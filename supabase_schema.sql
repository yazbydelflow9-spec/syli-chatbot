-- SYLI STUDY MALAYSIA — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query

-- ============================================================
-- 1. CLIENTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS clients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone TEXT UNIQUE NOT NULL,          -- WhatsApp phone number (e.g. "224XXXXXXXXX")
  name TEXT,
  stage TEXT DEFAULT 'lead' CHECK (stage IN (
    'lead',           -- First contact, unknown
    'interested',     -- Engaged, asking questions
    'qualified',      -- Gave us their info (level, programme)
    'docs_submitted', -- Documents received by our team
    'payment_pending',-- Waiting for commission payment
    'visa_pending',   -- Visa submitted, waiting EMGS
    'visa_approved',  -- Visa obtained
    'arrived'         -- Student arrived in KL
  )),
  language TEXT DEFAULT 'fr' CHECK (language IN ('fr', 'en')),
  bac_level TEXT,                      -- terminal, bac, bac+1, bac+2, bac+3
  desired_programme TEXT,              -- IT, Business, Engineering, Aviation, etc.
  country TEXT DEFAULT 'Guinée',
  email TEXT,
  notes TEXT,                          -- Internal team notes
  guide_sent BOOLEAN DEFAULT FALSE,    -- Whether PDF guide was sent
  is_bot_paused BOOLEAN DEFAULT FALSE, -- Manual override: pause bot for this client
  is_archived BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_contact TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 2. MESSAGES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 3. BOT CONFIG TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS bot_config (
  id INTEGER PRIMARY KEY DEFAULT 1,
  is_active BOOLEAN DEFAULT TRUE,      -- Global bot on/off switch
  model TEXT DEFAULT 'anthropic/claude-haiku-4-5-20251001',
  max_history_messages INTEGER DEFAULT 20,
  auto_send_guide BOOLEAN DEFAULT TRUE, -- Auto-send guide when client asks
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO bot_config (id, is_active) VALUES (1, TRUE)
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 4. INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_messages_client_id ON messages(client_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone);
CREATE INDEX IF NOT EXISTS idx_clients_stage ON clients(stage);
CREATE INDEX IF NOT EXISTS idx_clients_last_contact ON clients(last_contact DESC);

-- ============================================================
-- 5. AUTO-UPDATE updated_at TRIGGER
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER clients_updated_at
  BEFORE UPDATE ON clients
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- 6. ENABLE ROW LEVEL SECURITY (optional, for dashboard)
-- ============================================================
-- ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
