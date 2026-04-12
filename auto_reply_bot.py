"""
auto_reply_bot.py — Arkiveit's mention monitor and auto-reply engine.

Polls for @arkiveit mentions every 60 seconds.
When someone tags @arkiveit in a reply to a prediction tweet:
  1. Fetches the original prediction tweet
  2. Extracts the prediction with Grok
  3. Saves it to the database
  4. Replies publicly confirming it's been archived

Deploy on Railway as a worker process (see Procfile).
Set DRY_RUN = True during testing to log replies without posting.
"""

import os
import time
import logging
from datetime import datetime, timezone
import tweepy
from dotenv import load_dotenv
from core_extraction import extract_prediction, compose_reply
from database import save_prediction

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_USER_ID   = "1435373554422276099"
POLL_INTERVAL = 60          # seconds between mention checks
DRY_RUN       = False       # set True for testing — logs replies but doesn't post
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://xarkive.com")

# Accept tier 1, 2, or 3 from mentions (human deliberately tagged us)
MIN_TIER_FOR_REPLY = 3

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("arkiveit")

# ---------------------------------------------------------------------------
# X clients
# ---------------------------------------------------------------------------

# Read client — bearer token only (for fetching mentions and tweets)
READ_CLIENT = tweepy.Client(
    bearer_token=os.getenv("X_BEARER_TOKEN"),
    wait_on_rate_limit=True,
)

# Write client — OAuth 1.0a (for posting replies)
WRITE_CLIENT = tweepy.Client(
    consumer_key=os.getenv("X_API_KEY"),
    consumer_secret=os.getenv("X_API_SECRET"),
    access_token=os.getenv("X_ACCESS_TOKEN"),
    access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
    wait_on_rate_limit=True,
)

# ---------------------------------------------------------------------------
# State management — tracks last processed mention ID
# ---------------------------------------------------------------------------

STATE_FILE = "bot_state.json"

def load_state() -> dict:
    import json
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        # Fall back to environment variable if no state file exists
        return {"last_mention_id": os.getenv("LAST_MENTION_ID")}

def save_state(state: dict):
    import json
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def get_parent_tweet(mention) -> dict | None:
    """
    Fetch the tweet that the user was replying to when they tagged @arkiveit.
    This is the tweet that (hopefully) contains the prediction.
    Returns None if the mention wasn't a reply.
    """
    if not mention.referenced_tweets:
        return None

    parent_id = None
    for ref in mention.referenced_tweets:
        if ref.type == "replied_to":
            parent_id = ref.id
            break

    if not parent_id:
        return None

    try:
        result = READ_CLIENT.get_tweet(
            parent_id,
            tweet_fields=["author_id", "created_at", "text"],
            expansions=["author_id"],
            user_fields=["username"],
        )
        if not result.data:
            return None

        # Resolve username from expansions
        author_username = None
        if result.includes and "users" in result.includes:
            for user in result.includes["users"]:
                if str(user.id) == str(result.data.author_id):
                    author_username = user.username
                    break

        return {
            "tweet_id": str(result.data.id),
            "text": result.data.text,
            "author_id": str(result.data.author_id),
            "author_username": author_username or "unknown",
            "created_at": str(result.data.created_at),
            "source_url": f"https://x.com/{author_username}/status/{result.data.id}",
        }

    except Exception as e:
        log.warning(f"Could not fetch parent tweet {parent_id}: {e}")
        return None


def post_reply(text: str, in_reply_to_id: str) -> str | None:
    """
    Post a reply tweet. Returns tweet ID on success, None on failure.
    Honours DRY_RUN mode.
    """
    if DRY_RUN:
        log.info(f"[DRY RUN] Would reply to {in_reply_to_id}:\n{text}")
        return "dry_run"

    try:
        response = WRITE_CLIENT.create_tweet(
            text=text,
            in_reply_to_tweet_id=in_reply_to_id,
        )
        return str(response.data["id"])
    except tweepy.Forbidden as e:
        log.error(f"403 Forbidden — check write permissions on X app: {e}")
    except tweepy.Unauthorized as e:
        log.error(f"401 Unauthorized — check Access Token and Secret: {e}")
    except Exception as e:
        log.error(f"Failed to post reply: {e}")
    return None


def process_mention(mention) -> bool:
    """
    Handle a single @arkiveit mention.
    Returns True if we successfully archived and replied, False otherwise.
    """
    log.info(f"Processing mention {mention.id}: {mention.text[:80]}")

    # Don't reply to our own tweets
    if str(getattr(mention, "author_id", "")) == str(BOT_USER_ID):
        log.info("Skipping — mention is from the bot itself")
        return False

    # Get the original prediction tweet
    parent = get_parent_tweet(mention)
    if not parent:
        log.info(f"Mention {mention.id} is not a reply to another tweet — skipping")
        return False
    log.info(f"Parent tweet by @{parent['author_username']}: {parent['text'][:80]}")

    # Extract prediction from the parent tweet
    result = extract_prediction(parent["text"], f"Mentioned by user: {mention.text}")

    if not result.is_prediction or result.tier > MIN_TIER_FOR_REPLY:
        log.info(f"No valid prediction found (tier={result.tier}, is_pred={result.is_prediction}). Reason: {result.reasoning}")
        # Inform the user we couldn't find a verifiable prediction
        not_found_reply = (
            f"🔍 I checked that tweet but couldn't find a specific, verifiable prediction to track. "
            f"I need a clear claim with a measurable outcome and timeframe. "
            f"(e.g. 'SPX hits 5000 by June 2025')"
        )
        post_reply(not_found_reply, str(mention.id))
        return False

    # Build and save the prediction record
    prediction_data = {
        "post_id": parent["tweet_id"],
        "username": parent["author_username"],
        "claim_text": result.claim_text,
        "normalized": result.normalized.model_dump(),
        "tier": result.tier,
        "verifiability_score": result.verifiability_score,
        "implied_confidence": result.implied_confidence,
        "timestamp": parent["created_at"],
        "source_url": parent["source_url"],
        "source": "mention",
        "status": "pending",
        "archived_by_mention_id": str(mention.id),
    }

    saved = save_prediction(prediction_data)
    action = "Saved new" if saved else "Already tracked"
    log.info(f"{action} prediction: {result.claim_text[:60]}")

    # Compose and post the public reply
    reply_text = compose_reply(result, parent["author_username"], DASHBOARD_URL)
    reply_id = post_reply(reply_text, str(mention.id))

    if reply_id:
        log.info(f"✅ Reply posted: {reply_id}")
        return True
    else:
        log.warning("Reply failed to post")
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run():
    log.info("=" * 60)
    log.info(f"Arkiveit bot starting | DRY_RUN={DRY_RUN}")
    log.info(f"Dashboard: {DASHBOARD_URL}")
    log.info("=" * 60)

    state = load_state()

    while True:
        try:
            log.info("Checking for new mentions...")

            kwargs = dict(
                id=BOT_USER_ID,
                tweet_fields=["created_at", "text", "referenced_tweets", "author_id"],
                expansions=["referenced_tweets.id"],
                max_results=10,
            )
            if state.get("last_mention_id"):
                kwargs["since_id"] = state["last_mention_id"]

            response = READ_CLIENT.get_users_mentions(**kwargs)

            if response.data:
                log.info(f"Found {len(response.data)} new mention(s)")
                # Process oldest first for chronological replies
                for mention in reversed(response.data):
                    process_mention(mention)
                    time.sleep(3)  # brief pause between replies

                # Advance the cursor
                state["last_mention_id"] = str(response.data[0].id)
                save_state(state)
            else:
                log.info("No new mentions")

        except tweepy.TooManyRequests:
            log.warning("Rate limited — waiting 15 minutes")
            time.sleep(900)
        except tweepy.TwitterServerError as e:
            log.warning(f"X server error — waiting 60s: {e}")
            time.sleep(60)
        except KeyboardInterrupt:
            log.info("Shutting down")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(30)

        log.info(f"Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
