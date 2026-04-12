"""
dashboard.py — Arkiveit public dashboard
Deployed on Streamlit Cloud at arkiveit.streamlit.app
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_all_predictions
from watchlist import WATCHLIST

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Arkiveit — Expert Prediction Tracker",
    page_icon="📌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .accuracy-high { color: #28a745; font-weight: bold; }
    .accuracy-mid  { color: #fd7e14; font-weight: bold; }
    .accuracy-low  { color: #dc3545; font-weight: bold; }
    .stDataFrame { font-size: 13px; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("📌 Arkiveit")
st.markdown(
    "**AI-powered prediction tracker for X** — Finance · Politics · Geopolitics  \n"
    "We track what experts predict. We score whether they were right."
)
st.divider()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)  # refresh every 60 seconds
def load_data():
    raw = get_all_predictions()
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)

    # Normalise columns
    if "normalized" in df.columns:
        df["category"] = df["normalized"].apply(
            lambda x: (x.get("category") or "—").capitalize() if isinstance(x, dict) else "—"
        )
        df["deadline"] = df["normalized"].apply(
            lambda x: x.get("deadline") or "—" if isinstance(x, dict) else "—"
        )
    else:
        df["category"] = "—"
        df["deadline"] = "—"

    # Ensure status column exists
    if "status" not in df.columns:
        df["status"] = "pending"

    # Ensure source_url exists
    if "source_url" not in df.columns:
        df["source_url"] = df.get("post_id", "").apply(
            lambda x: f"https://x.com/i/web/status/{x}" if x else "#"
        )

    return df

df = load_data()

if df.empty:
    st.info("No predictions tracked yet. Tag @arkiveit in a reply to any prediction tweet to get started.")
    st.stop()

# ---------------------------------------------------------------------------
# Accuracy calculation
# ---------------------------------------------------------------------------

def calc_accuracy(subset: pd.DataFrame) -> dict:
    """Calculate accuracy stats for a subset of predictions."""
    total = len(subset)
    verified = subset[subset["status"].isin(["correct", "wrong"])]
    correct = subset[subset["status"] == "correct"]
    pending = subset[subset["status"] == "pending"]

    acc = None
    if len(verified) > 0:
        acc = round(len(correct) / len(verified) * 100, 1)

    return {
        "total": total,
        "verified": len(verified),
        "correct": len(correct),
        "pending": len(pending),
        "accuracy": acc,
    }

overall = calc_accuracy(df)

# ---------------------------------------------------------------------------
# Top-level metrics
# ---------------------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
c1.metric("Predictions Tracked", overall["total"])
c2.metric("Verified Outcomes", overall["verified"])
c3.metric("Experts Monitored", len(WATCHLIST))
c4.metric(
    "Overall Accuracy",
    f"{overall['accuracy']}%" if overall["accuracy"] is not None else "—",
    help="Only counts predictions with verified outcomes"
)

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["🏆 Leaderboard", "📋 All Predictions", "ℹ️ How It Works"])

# ---- Tab 1: Leaderboard ----
with tab1:
    st.subheader("Expert Accuracy Leaderboard")
    st.caption("Ranked by verified accuracy. Requires at least 1 verified outcome to appear.")

    # Build leaderboard
    rows = []
    for username in df["username"].unique():
        user_df = df[df["username"] == username]
        stats = calc_accuracy(user_df)
        rows.append({
            "Expert": f"@{username}",
            "Predictions": stats["total"],
            "Verified": stats["verified"],
            "Correct": stats["correct"],
            "Accuracy": stats["accuracy"],
            "Pending": stats["pending"],
        })

    lb = pd.DataFrame(rows)

    # Sort: verified experts first (by accuracy), then unverified by prediction count
    verified_lb = lb[lb["Verified"] > 0].sort_values("Accuracy", ascending=False)
    unverified_lb = lb[lb["Verified"] == 0].sort_values("Predictions", ascending=False)
    lb_sorted = pd.concat([verified_lb, unverified_lb], ignore_index=True)

    # Format accuracy column
    lb_sorted["Accuracy"] = lb_sorted["Accuracy"].apply(
        lambda x: f"{x}%" if x is not None else "⏳ Pending"
    )

    st.dataframe(
        lb_sorted,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Expert": st.column_config.TextColumn("Expert", width="medium"),
            "Accuracy": st.column_config.TextColumn("Accuracy", width="small"),
        }
    )

    st.caption(
        "📌 **Methodology:** Accuracy = correct predictions ÷ verified predictions. "
        "Predictions are only marked correct/wrong once the deadline has passed and the outcome is confirmed. "
        "Pending predictions are not counted in the accuracy score."
    )

# ---- Tab 2: All Predictions ----
with tab2:
    st.subheader("All Tracked Predictions")

    # Filters
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        cat_filter = st.selectbox(
            "Category",
            ["All"] + sorted(df["category"].dropna().unique().tolist())
        )
    with col_b:
        status_filter = st.selectbox(
            "Status",
            ["All", "Pending", "Correct", "Wrong", "Unverifiable"]
        )
    with col_c:
        expert_filter = st.selectbox(
            "Expert",
            ["All"] + sorted(df["username"].dropna().unique().tolist())
        )

    filtered = df.copy()
    if cat_filter != "All":
        filtered = filtered[filtered["category"] == cat_filter]
    if status_filter != "All":
        filtered = filtered[filtered["status"] == status_filter.lower()]
    if expert_filter != "All":
        filtered = filtered[filtered["username"] == expert_filter]

    # Display columns
    display_cols = ["username", "claim_text", "category", "deadline", "tier", "status"]
    if "timestamp" in filtered.columns:
        display_cols.insert(0, "timestamp")
    if "source_url" in filtered.columns:
        display_cols.append("source_url")

    # Only show columns that exist
    display_cols = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[display_cols].rename(columns={
            "username": "Expert",
            "claim_text": "Prediction",
            "category": "Category",
            "deadline": "Deadline",
            "tier": "Tier",
            "status": "Status",
            "timestamp": "Posted",
            "source_url": "Source",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Source": st.column_config.LinkColumn("Source", display_text="View Tweet"),
            "Prediction": st.column_config.TextColumn("Prediction", width="large"),
        }
    )

    st.caption(f"Showing {len(filtered)} of {len(df)} predictions")

# ---- Tab 3: How It Works ----
with tab3:
    st.subheader("How Arkiveit Works")
    st.markdown("""
    **Arkiveit automatically tracks and scores expert predictions made on X (Twitter).**

    ### How predictions get tracked
    1. **Watchlist:** We automatically monitor a curated list of high-follower experts in finance, politics, and geopolitics.
    2. **Community tagging:** Anyone can tag **@arkiveit** in a reply to a prediction tweet to have it archived.

    ### How extraction works
    Our AI (Grok-4) reads each tweet and determines whether it contains a specific, verifiable, forward-looking prediction.
    We only track claims that have:
    - A **specific, measurable outcome** (not vague opinions)
    - An **implied or explicit timeframe**
    - A **way to verify** whether it came true

    ### How accuracy is scored
    - Predictions start as **Pending ⏳**
    - When the deadline passes, we check the outcome against public data sources
    - Financial predictions are verified automatically where possible
    - Political/geopolitical predictions are verified manually
    - Only **verified** predictions count toward an expert's accuracy score
    - An expert with 10 predictions but 0 verified outcomes shows no accuracy score yet

    ### Prediction tiers
    | Tier | Description | Example |
    |------|-------------|---------|
    | 1 | Highly specific — number + date | "SPX hits 6,000 by Dec 2025" |
    | 2 | Moderately specific — direction + timeframe | "Fed cuts before June" |
    | 3 | Qualitative but time-bound | "China escalates on Taiwan in 2025" |

    ### How to use Arkiveit
    Reply to any prediction tweet on X and tag **@arkiveit**.
    The bot will archive the prediction and reply publicly confirming it's been tracked.
    """)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("📡 Monitored Experts")
    st.caption(f"Currently tracking {len(WATCHLIST)} accounts")
    for handle in sorted(WATCHLIST):
        st.markdown(f"[@{handle}](https://x.com/{handle})")

    st.divider()
    st.markdown("**Track a prediction:**")
    st.markdown("Reply to any prediction tweet and tag **@arkiveit**")
    st.divider()
    st.caption("Built with Grok-4 + X API v2  \n[xarkive.com](https://xarkive.com)")
