"""
ingest_watchlist.py — Polls expert accounts for predictions.

Runs on a schedule (cron or Railway cron job).
Tracks the last-seen tweet ID per user so it never re-processes old tweets.
"""

import os
import json
import time
import tweepy
from dotenv import load_dotenv
from core_extraction import extract_prediction
from database import save_prediction
from watchlist import WATCHLIST

load_dotenv()

X_CLIENT = tweepy.Client(
    bearer_token=os.getenv("X_BEARER_TOKEN"),
    wait_on_rate_limit=True,
)

# State file tracks the most recent tweet ID seen per account
# so we only fetch NEW tweets on each run
STATE_FILE = "watchlist_state.json"

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://xarkive.com")

# Only save predictions of tier 1 or 2 from the watchlist
# (mentions can accept tier 3 since a human deliberately tagged us)
MIN_TIER = 2
MIN_VERIFIABILITY = 0.5


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def resolve_user_id(username: str):
    """Fetch and cache the numeric user ID for a username."""
    try:
        resp = X_CLIENT.get_user(username=username, user_fields=["id"])
        if resp.data:
            return str(resp.data.id)
    except Exception as e:
        print(f"   ⚠️  Could not resolve @{username}: {e}")
    return None


def ingest_watchlist():
    print("🔄 Starting watchlist ingestion...")
    state = load_state()
    total_saved = 0
    total_checked = 0

    for username in WATCHLIST:
        if username.lower() == 'arkiveit':
            continue
        print(f"\n📡 Checking @{username}...")

        # Resolve user ID (cached in state to save API calls)
        user_id = state.get(f"_uid_{username}") or resolve_user_id(username)
        if not user_id:
            continue
        state[f"_uid_{username}"] = user_id

        since_id = state.get(f"_since_{username}")

        try:
            kwargs = dict(
                id=user_id,
                max_results=20,  # max per call on Basic tier
                tweet_fields=["created_at", "text", "public_metrics"],
                exclude=["retweets", "replies"],  # only original tweets
            )
            if since_id:
                kwargs["since_id"] = since_id

            response = X_CLIENT.get_users_tweets(**kwargs)

            if not response.data:
                print(f"   No new tweets.")
                continue

            print(f"   Found {len(response.data)} new tweet(s)")

            # Track the newest tweet ID for next run
            newest_id = str(response.data[0].id)

            for tweet in response.data:
                total_checked += 1
                result = extract_prediction(tweet.text, "")

                print(f"   Tweet {tweet.id}: tier={result.tier}, is_pred={result.is_prediction}, score={result.verifiability_score:.2f}")

                if (
                    result.is_prediction
                    and result.tier <= MIN_TIER
                    and result.verifiability_score >= MIN_VERIFIABILITY
                ):
                    prediction_data = {
                        "post_id": str(tweet.id),
                        "username": username,
                        "claim_text": result.claim_text,
                        "normalized": result.normalized.model_dump(),
                        "tier": result.tier,
                        "verifiability_score": result.verifiability_score,
                        "implied_confidence": result.implied_confidence,
                        "timestamp": str(tweet.created_at),
                        "source_url": f"https://x.com/{username}/status/{tweet.id}",
                        "source": "watchlist",
                        "status": "pending",
                    }
                    saved = save_prediction(prediction_data)
                    if saved:
                        total_saved += 1
                        print(f"   ✅ Saved: {result.claim_text[:60]}...")

                # Small delay between extraction calls to avoid hammering the LLM
                time.sleep(0.5)

            # Update since_id so next run starts from here
            state[f"_since_{username}"] = newest_id

        except tweepy.TooManyRequests:
            print(f"   ⏸️  Rate limited. Waiting 15 minutes...")
            time.sleep(900)
        except tweepy.TwitterServerError as e:
            print(f"   ⚠️  X server error for @{username}: {e}")
        except Exception as e:
            print(f"   ❌ Error for @{username}: {e}")

        # Polite delay between users
        time.sleep(2)

    save_state(state)
    print(f"\n✅ Ingestion complete. Checked {total_checked} tweets. Saved {total_saved} new predictions.")
    return total_saved


if __name__ == "__main__":
    ingest_watchlist()
