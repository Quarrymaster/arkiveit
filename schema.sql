-- schema.sql
-- Run this in your Supabase SQL editor to create the predictions table

CREATE TABLE IF NOT EXISTS predictions (
    id              BIGSERIAL PRIMARY KEY,
    post_id         TEXT UNIQUE NOT NULL,
    username        TEXT NOT NULL,
    claim_text      TEXT NOT NULL,
    normalized      JSONB DEFAULT '{}',
    tier            INTEGER CHECK (tier BETWEEN 1 AND 4),
    verifiability_score FLOAT DEFAULT 0.0,
    implied_confidence  TEXT,
    timestamp       TEXT,
    archived_at     TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT DEFAULT 'pending'
                        CHECK (status IN ('pending','correct','wrong','unverifiable')),
    outcome_notes   TEXT DEFAULT '',
    source_url      TEXT DEFAULT '',
    resolved_at     TIMESTAMPTZ
);

-- Index for fast leaderboard queries
CREATE INDEX IF NOT EXISTS idx_predictions_username ON predictions (username);
CREATE INDEX IF NOT EXISTS idx_predictions_status   ON predictions (status);
CREATE INDEX IF NOT EXISTS idx_predictions_tier     ON predictions (tier);

-- Useful view: accuracy leaderboard
CREATE OR REPLACE VIEW leaderboard AS
SELECT
    username,
    COUNT(*)                                                        AS total_predictions,
    COUNT(*) FILTER (WHERE status IN ('correct','wrong'))           AS verified_count,
    COUNT(*) FILTER (WHERE status = 'correct')                      AS correct_count,
    ROUND(
        COUNT(*) FILTER (WHERE status = 'correct')::NUMERIC
        / NULLIF(COUNT(*) FILTER (WHERE status IN ('correct','wrong')), 0) * 100,
        1
    )                                                               AS accuracy_pct,
    MAX(timestamp)                                                  AS last_prediction
FROM predictions
GROUP BY username
ORDER BY verified_count DESC, accuracy_pct DESC;
