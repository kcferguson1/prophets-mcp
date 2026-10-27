"""MCP server over prophets.db: search the First Presidency's and the Twelve's own words, every passage with its source.

Usage: uv run server.py --speaker dallin-h-oaks   (leave out --speaker for one server covering everyone)
"""
import argparse
import re
import sqlite3
import sys

from mcp.server.mcpserver import MCPServer

from fetch import DB

MAX_PER_TALK = 2  # so one long talk can't fill every result slot
CITE = "Quote passages in the speaker's own words and cite each one with its Source link, title and date."


def search_passages(con: sqlite3.Connection, query: str, speaker: str | None, limit: int = 8) -> str:
    terms = re.findall(r"\w+", query)
    if not terms:
        return "Give a few words to search for."
    # Quote each word so FTS5 never reads the user's text as query syntax.
    match = " OR ".join(f'"{t}"' for t in terms)
    rows = con.execute(
        """SELECT name, title, source, date, url, anchor, text FROM passages
           WHERE passages MATCH ? AND (? IS NULL OR speaker = ?)
           ORDER BY bm25(passages, 3.0, 1.0) LIMIT ?""",
        (match, speaker, speaker, limit * 10),
    ).fetchall()
    per_talk: dict[str, int] = {}
    out = []
    for name, title, source, date, url, anchor, text in rows:
        if per_talk.get(url, 0) >= MAX_PER_TALK:
            continue
        per_talk[url] = per_talk.get(url, 0) + 1
        link = f"{url}&id={anchor}#{anchor}" if anchor else url  # conference links jump to the paragraph
        out.append(f'## {len(out) + 1}. {name}, "{title}"\n{source}, {date}\nSource: {link}\n\n{text}')
        if len(out) == limit:
            break
    return "\n\n---\n\n".join(out) or f'Nothing matched "{query}". Try other words, or call list_sources.'


def list_sources(con: sqlite3.Connection, speaker: str | None) -> str:
    rows = con.execute(
        """SELECT DISTINCT name, date, source, title, url FROM passages
           WHERE ? IS NULL OR speaker = ? ORDER BY name, date DESC""",
        (speaker, speaker),
    )
    return "\n".join(f"- {name}, {date}, {source}: {title} ({url})" for name, date, source, title, url in rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--speaker", help="e.g. dallin-h-oaks; leave out to cover everyone")
    speaker = parser.parse_args().speaker
    if not DB.exists():
        sys.exit("prophets.db not found. Run `uv run fetch.py` first.")
    con = sqlite3.connect(DB, check_same_thread=False)

    if speaker:
        row = con.execute("SELECT name FROM passages WHERE speaker = ? LIMIT 1", (speaker,)).fetchone()
        if not row:
            sys.exit(f"No talks for '{speaker}' in prophets.db. Run `uv run fetch.py {speaker}`.")
        name = row[0]
        mcp = MCPServer(name, instructions=f"Searches {name}'s General Conference talks and BYU speeches. {CITE}")

        @mcp.tool(description=f"Search {name}'s General Conference talks and BYU speeches. Returns passages in his own words, each with title, date and source link. {CITE}")
        def search(query: str, limit: int = 8) -> str:
            return search_passages(con, query, speaker, max(1, min(limit, 20)))

        @mcp.tool(description=f"List every talk and speech in {name}'s collection, newest first.")
        def list_talks() -> str:
            return list_sources(con, speaker)

    else:
        mcp = MCPServer("The Prophets", instructions=f"Searches talks by the First Presidency and the Quorum of the Twelve Apostles, plus apostles who died since 2021. {CITE}")

        @mcp.tool(description=f"Search talks by the First Presidency, the Twelve, and apostles who died since 2021. Optionally limit to one speaker slug from list_speakers. {CITE}")
        def search(query: str, speaker: str | None = None, limit: int = 8) -> str:
            return search_passages(con, query, speaker, max(1, min(limit, 20)))

        @mcp.tool(description="List the speakers (with the slug to pass to search) and how many talks each has.")
        def list_speakers() -> str:
            rows = con.execute("SELECT speaker, name, COUNT(DISTINCT url) FROM passages GROUP BY speaker ORDER BY name")
            return "\n".join(f"- {name} (slug: {slug}): {n} talks" for slug, name, n in rows)

        @mcp.tool(description="List every talk and speech for one speaker slug, newest first.")
        def list_talks(speaker: str) -> str:
            return list_sources(con, speaker) or f"No talks for '{speaker}'. Call list_speakers."

    mcp.run()


if __name__ == "__main__":
    main()
