"""MCP server over prophets.db: search Church leaders' own words, every passage with its source.

Usage: uv run server.py --speaker dallin-h-oaks   (leave out --speaker for one server covering everyone)
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from fetch import CALLINGS, CHECKED, DB, SPEAKERS, connect, hold_lock

MAX_PER_TALK = 2  # so one long talk can't fill every result slot
MIN_WORDS = 8  # shorter paragraphs (headings, dates, "I am with you.") outrank real matches because BM25 favors short text
FILLER = set(
    "a about am an and are as at be but by can could did do does for from has have he her his how i if in into is it its "
    "me my not of on or our she should so than that the their them then there these they this to was we were what when "
    "where which who why will with would you your".split()
)
HOUR = 3600
UPDATE_EVERY = 7 * 24 * HOUR
CITE = "Quote passages in the speaker's own words and cite each one with its Source link, title and date."


def search_passages(con: sqlite3.Connection, query: str, speaker: str | None, limit: int = 8) -> str:
    terms = re.findall(r"\w+", query)
    if not terms:
        return "Give a few words to search for."
    terms = [t for t in terms if t.lower() not in FILLER] or terms  # all filler ("how do I")? search it as typed
    # Quote each word so FTS5 never reads the user's text as query syntax.
    match = " OR ".join(f'"{t}"' for t in terms)
    rows = con.execute(
        """SELECT name, title, source, date, url, anchor, text FROM passages
           WHERE passages MATCH ? AND (? IS NULL OR speaker = ?)
           ORDER BY bm25(passages, 1.0, 1.0) LIMIT ?""",  # heavier title weight let any paragraph of a matching talk win
        (match, speaker, speaker, limit * 20),
    ).fetchall()
    per_talk: dict[str, int] = {}
    shown: set[str] = set()  # the same paragraph can be saved twice (a joint talk, a reprint under a new title); show it once
    out = []
    for name, title, source, date, url, anchor, text in rows:
        if per_talk.get(url, 0) >= MAX_PER_TALK or len(text.split()) < MIN_WORDS or text in shown:
            continue
        shown.add(text)
        per_talk[url] = per_talk.get(url, 0) + 1
        link = f"{url}&id={anchor}#{anchor}" if anchor else url  # conference links jump to the paragraph
        out.append(f'## {len(out) + 1}. {name}, "{title}"\n{source}, {date}\nSource: {link}\n\n{text}')
        if len(out) == limit:
            break
    return "\n\n---\n\n".join(out) or f'Nothing matched "{query}". Try other words, or call list_talks.'


def list_sources(con: sqlite3.Connection, speaker: str | None) -> str:
    rows = con.execute(
        """SELECT DISTINCT name, date, source, title, url FROM passages
           WHERE ? IS NULL OR speaker = ? ORDER BY name, date DESC""",
        (speaker, speaker),
    )
    return "\n".join(f"- {name}, {date}, {source}: {title} ({url})" for name, date, source, title, url in rows)


def recent_additions(con: sqlite3.Connection, speaker: str | None, days: int = 30) -> str:
    lock = hold_lock()
    if lock:
        lock.close()
    if lock is None:
        status = "An update is running now."
    elif CHECKED.exists():
        status = f"Last full update finished {time.strftime('%Y-%m-%d', time.localtime(CHECKED.stat().st_mtime))}; updates run weekly."
    else:
        status = "No full update has finished yet."
    rows = con.execute(
        """SELECT DISTINCT date(at), name, date, source, title, url FROM added
           WHERE at >= datetime('now', ?) AND (? IS NULL OR speaker = ?) ORDER BY 1 DESC, 3 DESC""",
        (f"-{days} days", speaker, speaker),
    ).fetchall()
    if not rows:
        return f"{status}\nNothing added in the last {days} days."
    lines = [f"- added {added}: {name}, {date}, {source}: {title} ({url})" for added, name, date, source, title, url in rows]
    return f"{status}\n{len(rows)} added in the last {days} days, newest first:\n" + "\n".join(lines)


def keep_updated():
    """Check at startup and then once a day, so a client left open for weeks still gets new talks."""
    while True:
        update_if_stale()
        time.sleep(24 * HOUR)


def update_if_stale():
    """Fetch new talks in the background when there's no finished full check from the last week (or none at all)."""
    if CHECKED.exists() and time.time() - CHECKED.stat().st_mtime < UPDATE_EVERY:
        return
    lock = hold_lock()
    if lock is None:
        return  # an update is already running
    # fetch.py takes the lock for itself; if several starting servers each launch one, all but one exit at once.
    lock.close()
    # Own session and log file: stdin/stdout belong to the MCP client, and the update should outlive this server.
    # Appended, so a later server can't wipe the log of the update that's running.
    log = open(DB.with_name("prophets-update.log"), "a")
    subprocess.Popen(
        [sys.executable, "-u", str(Path(__file__).with_name("fetch.py"))],  # -u: unbuffered, so the log shows each talk as it's saved
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--speaker", help="e.g. dallin-h-oaks; leave out to cover everyone")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP on $PORT (default 8000) instead of stdio")
    args = parser.parse_args()
    speaker = args.speaker
    if speaker and speaker not in SPEAKERS:
        sys.exit(f"Unknown speaker '{speaker}'. Choose from: {', '.join(SPEAKERS)}")
    threading.Thread(target=keep_updated, daemon=True).start()  # daemon: never keeps the server alive after the client quits
    con = connect()  # creates an empty index on first run; the update fills it while the server answers

    if speaker:
        name = SPEAKERS[speaker]
        mcp = MCPServer(name, instructions=f"Searches the General Conference talks, devotionals, magazine articles and BYU speeches of {name}, {CALLINGS[speaker]}. {CITE}")

        @mcp.tool(description=f"Search {name}'s General Conference talks, devotionals, magazine articles and BYU speeches. Returns passages in the speaker's own words, each with title, date and source link. {CITE}")
        def search(query: str, limit: int = 8) -> str:
            return search_passages(con, query, speaker, max(1, min(limit, 20)))

        @mcp.tool(description=f"List every talk and speech in {name}'s collection, newest first.")
        def list_talks() -> str:
            return list_sources(con, speaker)

        @mcp.tool(description=f"Show which of {name}'s talks and articles the weekly update added in the last `days` days, and when the last update ran.")
        def whats_new(days: int = 30) -> str:
            return recent_additions(con, speaker, max(1, min(days, 365)))

    else:
        mcp = MCPServer("The Prophets", instructions=f"Searches talks by the First Presidency, the Quorum of the Twelve Apostles, apostles who died since 2021, and the Relief Society, Young Women and Primary general presidencies. {CITE}")

        @mcp.tool(description=f"Search talks by the First Presidency, the Twelve, apostles who died since 2021, and the Relief Society, Young Women and Primary general presidencies. Optionally limit to one speaker slug from list_speakers. {CITE}")
        def search(query: str, speaker: str | None = None, limit: int = 8) -> str:
            return search_passages(con, query, speaker, max(1, min(limit, 20)))

        @mcp.tool(description="List every speaker with their calling, the slug to pass to search, and how many talks and articles each has.")
        def list_speakers() -> str:
            counts = dict(con.execute("SELECT speaker, COUNT(DISTINCT url) FROM passages GROUP BY speaker"))
            return "\n".join(
                f"- {name}, {CALLINGS[slug]} (slug: {slug}): " + (f"{counts[slug]} talks and articles" if counts.get(slug) else "no talks yet")
                for slug, name in SPEAKERS.items()
            )

        @mcp.tool(description="List every talk and speech for one speaker slug, newest first.")
        def list_talks(speaker: str) -> str:
            return list_sources(con, speaker) or f"No talks for '{speaker}'. Call list_speakers."

        @mcp.tool(description="Show which talks and articles the weekly update added in the last `days` days, and when the last update ran. Optionally limit to one speaker slug.")
        def whats_new(days: int = 30, speaker: str | None = None) -> str:
            return recent_additions(con, speaker, max(1, min(days, 365)))

    if args.http:
        # Stateless: any request can land on a freshly restarted machine without losing a session.
        mcp.run("streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), stateless_http=True)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
