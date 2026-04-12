"""
mention_monitor.py — Legacy entry point.
The full bot logic now lives in auto_reply_bot.py.
This file is kept for backwards compatibility.
Run auto_reply_bot.py directly instead.
"""

from auto_reply_bot import run

if __name__ == "__main__":
    run()
