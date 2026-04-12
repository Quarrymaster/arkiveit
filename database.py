"""
database.py — Arkiveit data layer
Supports two modes:
  1. Supabase (Postgres) — set SUPABASE_DB_URL in .env
  2. JSON fallback      — used automatically if no DB URL is set

To migrate to Supabase:
  1. Create a free project at supabase.com
  2. Run the SQL in schema.sql to create the predictions table
  3. Add SUPABASE_DB_URL to your .env / Railway env vars
  4. That's it — no other code changes needed
"""

import json
import os
import fcntl  # file locking — prevents corruption on concurrent writes
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DATA_FILE = "predictions.json"
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

# ---------------------------------------------------------------------------
# Supabase / Postgres backend
# ---------------------------------------------------------------------------

def _get_db_conn():
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(SUPABASE_DB_URL)


def _save_prediction_db(prediction: dict) -> bool:
    """Insert prediction into Postgres. Returns True if inserted, False if duplicate."""
    import psycopg2
    import psycopg2.extras
    conn = _get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO predictions (
                        post_id, username, claim_text, normalized,
                        tier, verifiability_score, implied_confidence,
                        timestamp, status, source_url
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (post_id) DO NOTHING
                    RETURNING post_id
                    """,
                    (
                        prediction.get("post_id"),
                        prediction.get("username"),
                        prediction.get("claim_text"),
                        psycopg2.extras.Json(prediction.get("normalized", {})),
                        prediction.get("tier"),
                        prediction.get("verifiability_score"),
                        prediction.get("implied_confidence"),
                        prediction.get("timestamp"),
                        prediction.get("status", "pending"),
                        prediction.get("source_url"),
                    ),
                )
                inserted = cur.fetchone() is not None
        return inserted
    finally:
        conn.close()


def _get_all_predictions_db() -> list:
    conn = _get_db_conn()
    try:
        with conn.cursor(cursor_factory=__import__("psycopg2").extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM predictions ORDER BY timestamp DESC")
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# JSON fallback backend (with file locking)
# ---------------------------------------------------------------------------

def _init_json():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump([], f)


def _save_prediction_json(prediction: dict) -> bool:
    """Thread-safe JSON save. Returns True if inserted, False if duplicate."""
    _init_json()
    with open(DATA_FILE, "r+") as f:
        # Exclusive lock — any other process trying to write will wait
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            data = json.load(f)
            post_id = prediction.get("post_id")
            if any(p.get("post_id") == post_id for p in data):
                return False  # duplicate
            prediction.setdefault("status", "pending")
            prediction.setdefault("archived_at", datetime.now(timezone.utc).isoformat())
            data.append(prediction)
            f.seek(0)
            json.dump(data, f, indent=2, default=str)
            f.truncate()
            return True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _get_all_predictions_json() -> list:
    _init_json()
    with open(DATA_FILE, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Public API — call these everywhere, backend is chosen automatically
# ---------------------------------------------------------------------------

def save_prediction(prediction: dict) -> bool:
    """
    Save a prediction. Returns True if saved, False if duplicate.
    Automatically uses Supabase if SUPABASE_DB_URL is set, else JSON.
    """
    try:
        if SUPABASE_DB_URL:
            inserted = _save_prediction_db(prediction)
        else:
            inserted = _save_prediction_json(prediction)

        if inserted:
            claim = prediction.get("claim_text", "")[:60]
            print(f"💾 Saved: {claim}...")
        else:
            print(f"⏭️  Duplicate skipped: {prediction.get('post_id')}")
        return inserted

    except Exception as e:
        print(f"❌ Database error: {e}")
        # Always fall back to JSON if Supabase fails
        if SUPABASE_DB_URL:
            print("⚠️  Falling back to JSON storage")
            return _save_prediction_json(prediction)
        return False


def get_all_predictions() -> list:
    """Retrieve all predictions, newest first."""
    try:
        if SUPABASE_DB_URL:
            return _get_all_predictions_db()
        return _get_all_predictions_json()
    except Exception as e:
        print(f"❌ Database read error: {e}")
        return _get_all_predictions_json()


def get_predictions_by_username(username: str) -> list:
    """Get all predictions for a specific expert."""
    return [p for p in get_all_predictions() if p.get("username") == username]


def update_prediction_status(post_id: str, status: str, outcome_notes: str = "") -> bool:
    """
    Mark a prediction as resolved/correct/wrong.
    status: 'pending' | 'correct' | 'wrong' | 'unverifiable'
    """
    if SUPABASE_DB_URL:
        try:
            conn = _get_db_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE predictions SET status=%s, outcome_notes=%s WHERE post_id=%s",
                        (status, outcome_notes, post_id)
                    )
            conn.close()
            return True
        except Exception as e:
            print(f"❌ Update error: {e}")
            return False
    else:
        # JSON update
        with open(DATA_FILE, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                data = json.load(f)
                for p in data:
                    if p.get("post_id") == post_id:
                        p["status"] = status
                        p["outcome_notes"] = outcome_notes
                        p["resolved_at"] = datetime.now(timezone.utc).isoformat()
                        break
                f.seek(0)
                json.dump(data, f, indent=2, default=str)
                f.truncate()
                return True
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
