#!/usr/bin/env python3
"""
harvest.py — Extract all Hermes sessions for a given date and produce a digest.

Queries state.db, extracts session metadata + messages, and outputs a structured
JSON digest that serves as input for the journal generation phase.

Usage:
    python scripts/harvest.py --date 2026-05-04 [--db PATH] [--output PATH]
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


DEFAULT_DB = os.path.expanduser("~/.hermes/state.db")


def parse_args():
    parser = argparse.ArgumentParser(description="Harvest Hermes sessions for a date")
    parser.add_argument("--date", required=True, help="Date in YYYY-MM-DD format")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to state.db")
    parser.add_argument("--output", default=None, help="Output JSON path (default: stdout)")
    parser.add_argument("--max-content-chars", type=int, default=8000,
                        help="Max chars of message content per message (default: 8000)")
    return parser.parse_args()


# Pacific timezone (agent runs in US-East but user is Pacific)
PST = timezone(timedelta(hours=-7))


def get_day_bounds(date_str):
    """Return Unix timestamps for start/end of the given date in Pacific Time."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=PST)
    start_ts = dt.timestamp()
    end_ts = (dt + timedelta(days=1)).timestamp()
    return start_ts, end_ts


def harvest(db_path, start_ts, end_ts, max_content_chars=8000):
    """Query sessions and messages for the given time range."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Fetch sessions (exclude cron — those are pipeline internals, not user activity)
    cursor.execute("""
        SELECT id, source, title, started_at, ended_at, message_count, 
               tool_call_count, model, api_call_count, estimated_cost_usd
        FROM sessions
        WHERE started_at >= ? AND started_at < ?
          AND source != 'cron'
        ORDER BY started_at
    """, (start_ts, end_ts))
    
    sessions = []
    for row in cursor.fetchall():
        session_id = row["id"]
        
        # Fetch user+assistant messages (skip tool results for brevity)
        cursor.execute("""
            SELECT role, content, tool_name, tool_calls
            FROM messages
            WHERE session_id = ?
              AND role IN ('user', 'assistant')
            ORDER BY timestamp
            LIMIT 100
        """, (session_id,))
        
        messages = []
        for msg in cursor.fetchall():
            content = msg["content"] or ""
            if len(content) > max_content_chars:
                content = content[:max_content_chars] + "\n... [truncated]"
            
            entry = {
                "role": msg["role"],
                "content": content.strip(),
            }
            if msg["tool_name"]:
                entry["tool_name"] = msg["tool_name"]
            if msg["tool_calls"]:
                try:
                    entry["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    entry["tool_calls_raw"] = msg["tool_calls"][:500]
            
            messages.append(entry)
        
        # Extract unique tool names used
        cursor.execute("""
            SELECT DISTINCT tool_name FROM messages
            WHERE session_id = ? AND tool_name IS NOT NULL AND tool_name != ''
        """, (session_id,))
        tools_used = [r["tool_name"] for r in cursor.fetchall()]
        
        sessions.append({
            "id": session_id,
            "source": row["source"],
            "title": row["title"][:200] if row["title"] else None,
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "started_at_iso": datetime.fromtimestamp(row["started_at"]).isoformat(),
            "message_count": row["message_count"],
            "tool_call_count": row["tool_call_count"],
            "api_call_count": row["api_call_count"],
            "model": row["model"],
            "estimated_cost_usd": row["estimated_cost_usd"],
            "tools_used": tools_used,
            "messages": messages,
        })

    conn.close()
    return sessions


def build_digest(date_str, sessions):
    """Build the final digest structure."""
    total_messages = sum(s["message_count"] for s in sessions)
    total_tool_calls = sum(s["tool_call_count"] for s in sessions)
    total_cost = sum(s["estimated_cost_usd"] or 0 for s in sessions)
    
    # Aggregate tools used across all sessions
    all_tools = set()
    for s in sessions:
        all_tools.update(s["tools_used"])
    
    digest = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "session_count": len(sessions),
            "total_messages": total_messages,
            "total_tool_calls": total_tool_calls,
            "total_estimated_cost_usd": round(total_cost, 4),
            "tools_used": sorted(all_tools),
        },
        "sessions": sessions,
    }
    
    return digest


def main():
    args = parse_args()
    
    if not os.path.exists(args.db):
        print(f"Error: DB not found at {args.db}", file=sys.stderr)
        sys.exit(1)
    
    start_ts, end_ts = get_day_bounds(args.date)
    
    sessions = harvest(args.db, start_ts, end_ts, args.max_content_chars)
    
    if not sessions:
        print(f"No sessions found for {args.date}", file=sys.stderr)
        digest = build_digest(args.date, [])
    else:
        digest = build_digest(args.date, sessions)
    
    output_json = json.dumps(digest, indent=2, default=str)
    
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json)
        print(f"Digest written to {output_path} ({len(sessions)} sessions, {len(output_json)} bytes)", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
