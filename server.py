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
import unicodedata
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from fetch import BYU, CALLINGS, CHECKED, CHURCH, DB, MAGAZINES, SPEAKERS, VOLUMES, connect, hold_lock

MAX_PER_TALK = 2  # so one long talk can't fill every result slot
MIN_WORDS = 8  # shorter paragraphs (headings, dates, "I am with you.") outrank real matches because BM25 favors short text
FILLER = set(
    "a about am an and are as at be but by can could did do does for from has have he her his how i if in into is it its "
    "me my not of on or our she should so than that the their them then there these they this to was we were what when "
    "where which who why will with would you your".split()
)
SOURCES = ("General Conference", "BYU Speeches", "Church broadcast", *MAGAZINES.values())  # the names fetch.py stores
SOURCE_NAMES = {s.lower(): s for s in SOURCES}
FILTERS = (
    'Put a phrase in double quotes to match those exact words in order ("faith in Jesus Christ"). '
    "Optional filters: from_date and to_date (inclusive; 2015, 2015-04 or 2015-04-12) and sources, a list of: "
    + ", ".join(SOURCES) + "."
)
WORDS_PER_CALL = 5000  # per get_talk call: nearly every conference talk and most BYU speeches fit whole
HOUR = 3600
UPDATE_EVERY = 7 * 24 * HOUR
CITE = "Quote passages in the speaker's own words and cite each one with its Source link, title and date."
QUOTE_VERSES = "Quote verses exactly as returned and cite each with its reference and Source link."
NO_SCRIPTURES = "The scriptures haven't been downloaded yet. They arrive with the next full update (uv run fetch.py)."
# Short or plural names people type that differ from the chapter titles the verses are stored under.
BOOK_ALIASES = {"d&c": "doctrine and covenants", "dc": "doctrine and covenants", "psalms": "psalm",
                "od": "official declaration", "js h": "joseph smith history", "js m": "joseph smith matthew"}


def match_query(query: str) -> str:
    """An FTS5 query matching any meaningful word, or "" when there are no words."""
    terms = re.findall(r"\w+", query)
    terms = [t for t in terms if t.lower() not in FILLER] or terms  # all filler ("how do I")? search it as typed
    # Quote each word so FTS5 never reads the user's text as query syntax.
    return " OR ".join(f'"{t}"' for t in terms)


def talk_id(link: str) -> str:
    """A talk's lasting name from its source link: general-conference/2025/04/47oaks, byu/<speaker>/<talk>."""
    link = link.strip().split("#")[0].split("?")[0].strip("/")  # an anchor or query on a link or a pasted ID
    if "speeches.byu.edu/talks/" in link:
        return "byu/" + link.split("/talks/", 1)[1]
    if "/study/" in link:
        return link.split("/study/", 1)[1]
    return link  # already an ID


def talk_link(tid: str) -> str:
    """The stored source link for a talk ID (the reverse of talk_id)."""
    if tid.startswith("byu/"):
        return f"{BYU}/talks/{tid[4:]}/"
    return f"{CHURCH}/study/{tid}?lang=eng"


def talk_text(con: sqlite3.Connection, talk: str, start: int | None = None, end: int | None = None, speaker: str | None = None) -> str:
    """A talk's paragraphs, numbered as in search; speaker limits a one-speaker server to its own talks."""
    tid = talk_id(talk)
    url = talk_link(tid)
    rows = con.execute(
        "SELECT rowid, speaker, name, title, source, date, text FROM passages WHERE url = ? ORDER BY rowid", (url,)
    ).fetchall()
    if not rows:
        return f"No talk with the ID {tid}. Use a Talk ID from search, list_talks or whats_new."
    if speaker and speaker not in {r[1] for r in rows}:
        return f"{tid} isn't one of {SPEAKERS[speaker]}'s talks. Use a Talk ID from this server's search or list_talks."
    copy = speaker or rows[0][1]  # a joint talk is stored once per speaker; read one copy
    numbers = paragraph_numbers(con, {url})
    paras = {numbers[r[0]]: r for r in rows if r[1] == copy}
    total = len(paras)
    first = 1 if start is None else start
    last = total if end is None else min(end, total)
    if not 1 <= first <= last:
        return f"This talk has {total} paragraphs: ask for ¶1 to ¶{total}."
    asked_end = f", end={last}" if end is not None else ""
    lines, words = [], 0
    for n in range(first, last + 1):
        text = paras[n][6]
        if lines and words + len(text.split()) > WORDS_PER_CALL:
            last, more = n - 1, f"\n\nContinued: call get_talk again with start={n}{asked_end}."
            break
        lines.append(f"¶{n} {text}")
        words += len(text.split())
    else:
        more = ""
    _, _, name, title, source, date, _ = paras[1]
    shown = "" if (first, last) == (1, total) else f", showing ¶{first}–¶{last}"
    header = (
        f'# "{title}"\n{name} · {source}, {date}\nSource: {url}\n'
        f"Talk ID: {tid} · {total} paragraphs{shown}\n¶ numbers count this talk's own paragraphs, not the website's."
    )
    return header + "\n\n" + "\n".join(lines) + more


def paragraph_numbers(con: sqlite3.Connection, urls: set[str]) -> dict[int, int]:
    """Each stored paragraph's number in its talk (1, 2, 3… in reading order), keyed by row id."""
    rows = con.execute(
        f"SELECT url, speaker, rowid FROM passages WHERE url IN ({','.join('?' * len(urls))}) ORDER BY rowid", list(urls)
    )
    counts: dict[tuple[str, str], int] = {}
    numbers = {}
    for url, speaker, rowid in rows:  # a joint talk's copies are numbered separately, and identically
        counts[url, speaker] = numbers[rowid] = counts.get((url, speaker), 0) + 1
    return numbers


PHRASE = re.compile(r'["“”]([^"“”]+)["“”]')  # a phrase in straight or curly double quotes


def real_date(d: str) -> bool:
    """2015, 2015-04 or 2015-04-12, and a date that exists."""
    try:
        datetime.strptime(d, {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d"}[len(d)])
        return True
    except (KeyError, ValueError):
        return False


def plain_words(text: str) -> str:
    """Text reduced for exact-phrase comparison: capitals, accents, punctuation and apostrophe style don't count."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))  # José -> Jose, as the index does
    return " ".join(re.findall(r"\w+", text.lower().replace("’", "").replace("'", "")))


def search_passages(
    con: sqlite3.Connection, query: str, speakers: list[str] | None, limit: int = 8, sources: list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None,
) -> str:
    for d in (from_date, to_date):
        if d and not real_date(d):
            return f'Dates look like 2015, 2015-04 or 2015-04-12, not "{d}".'
    if from_date and to_date and from_date[:len(to_date)] > to_date[:len(from_date)]:
        return f"from_date {from_date} is after to_date {to_date}."
    if unknown := [s for s in speakers or [] if s not in SPEAKERS]:
        return f"Unknown speaker: {', '.join(unknown)}. Speakers: {', '.join(SPEAKERS)}."
    if unknown := [s for s in sources or [] if s.lower() not in SOURCE_NAMES]:
        return f"Unknown source: {', '.join(unknown)}. Sources: {', '.join(SOURCES)}."
    phrases = [p for p in PHRASE.findall(query) if re.search(r"\w", p)]
    match = match_query(PHRASE.sub(" ", query))  # the words outside quotes, matched broadly
    # Each phrase is required; FTS5's own phrase match (stemmed) narrows the candidates, the exact check comes below.
    required = " AND ".join(f'"{" ".join(re.findall(r"\w+", p))}"' for p in phrases)
    if required:
        match = f"{required} AND ({match} OR {required})" if match else required
    if not match:
        return "Give a few words to search for."
    exact = [plain_words(p) for p in phrases]
    where, params = ["passages MATCH ?"], [match]
    if speakers:
        where.append(f"speaker IN ({','.join('?' * len(speakers))})")
        params += speakers
    if sources:
        where.append(f"source IN ({','.join('?' * len(sources))})")
        params += [SOURCE_NAMES[s.lower()] for s in sources]
    # Stored dates are 2025-04 or 2025-08-22. Comparing at the shorter of the two lengths keeps both ends inclusive:
    # 2025-10 is inside 2025-10-01..2025-10-31, and 2025-08-22 is inside ..2025. Undated talks never match a date filter.
    for bound, op in ((from_date, ">="), (to_date, "<=")):
        if bound:
            where.append(f"date <> '' AND substr(date, 1, min(length(date), ?)) {op} substr(?, 1, min(length(date), ?))")
            params += [len(bound), bound, len(bound)]
    rows = con.execute(
        f"""SELECT rowid, name, title, source, date, url, anchor, text FROM passages WHERE {' AND '.join(where)}
           ORDER BY bm25(passages, 1.0, 1.0) LIMIT ?""",  # heavier title weight let any paragraph of a matching talk win
        # A quoted phrase reads candidates until enough pass the exact check (-1: no limit), since near
        # matches by word stem can outnumber them; plain searches stop at a fixed pool.
        (*params, -1 if exact else limit * 20),
    )
    per_talk: dict[str, int] = {}
    shown: set[str] = set()  # the same paragraph can be saved twice (a joint talk, a reprint under a new title); show it once
    passages = []
    for row in rows:
        *_, url, _, text = row
        if per_talk.get(url, 0) >= MAX_PER_TALK or len(text.split()) < MIN_WORDS or text in shown:
            continue
        if exact and not all(f" {p} " in f" {plain_words(text)} " for p in exact):
            continue
        shown.add(text)
        per_talk[url] = per_talk.get(url, 0) + 1
        passages.append(row)
        if len(passages) == limit:
            break
    numbers = paragraph_numbers(con, {url for *_, url, _, _ in passages}) if passages else {}
    out = []
    for rowid, name, title, source, date, url, anchor, text in passages:
        link = f"{url}&id={anchor}#{anchor}" if anchor else url  # conference links jump to the paragraph
        out.append(f'## {len(out) + 1}. {name}, "{title}" ¶{numbers[rowid]}\n{source}, {date}\nTalk ID: {talk_id(url)}\nSource: {link}\n\n{text}')
    return "\n\n---\n\n".join(out) or f'Nothing matched "{query}". Try other words, or call list_talks.'


def verse_link(url: str, anchor: str) -> str:
    return f"{url}&id={anchor}#{anchor}"  # jumps to the verse


def search_verses(con: sqlite3.Connection, query: str, volume: str | None, limit: int = 8) -> str:
    if not con.execute("SELECT 1 FROM verses LIMIT 1").fetchone():
        return NO_SCRIPTURES
    match = match_query(query)
    if not match:
        return "Give a few words to search for."
    volume = VOLUMES.get(volume, volume)  # "bofm" or "Book of Mormon"
    rows = con.execute(
        """SELECT ref, text, url, anchor FROM verses WHERE verses MATCH ? AND (? IS NULL OR volume = ?)
           ORDER BY bm25(verses) LIMIT ?""",
        (match, volume, volume, limit),
    ).fetchall()
    out = [f"## {ref}\nSource: {verse_link(url, anchor)}\n\n{text}" for ref, text, url, anchor in rows]
    return "\n\n---\n\n".join(out) or f'No verse matched "{query}". Try other words.'


def book_key(name: str) -> str:
    key = " ".join(re.sub(r"[^\w&]+", " ", name.lower()).split())  # "Joseph Smith—History" -> "joseph smith history"
    return BOOK_ALIASES.get(key, key)


def lookup_verses(con: sqlite3.Connection, reference: str) -> str:
    if not con.execute("SELECT 1 FROM verses LIMIT 1").fetchone():
        return NO_SCRIPTURES
    ref = re.fullmatch(r"\s*(.+?)\s+(\d+)(?::(\d+)(?:\s*[-–]\s*(\d+))?)?\s*", reference)
    if not ref:
        return f'Give a reference like "Moroni 10:4-5", "D&C 121:7" or "Alma 32", not "{reference}".'
    books = {book_key(b): b for (b,) in con.execute("SELECT DISTINCT book FROM verses")}
    book = books.get(book_key(ref[1]))
    if not book:
        return f'No book called "{ref[1]}" in the standard works.'
    chapter = int(ref[2])
    first = int(ref[3] or 1)
    last = int(ref[4] or ref[3] or 10_000)  # no verse given: the whole chapter
    rows = con.execute(
        """SELECT CAST(verse AS INTEGER) AS v, text, url, anchor FROM verses
           WHERE book = ? AND CAST(chapter AS INTEGER) = ? AND v BETWEEN ? AND ? ORDER BY v""",
        (book, chapter, first, last),
    ).fetchall()
    if not rows:
        return f"{book} {chapter} has no verse {first}." if ref[3] else f"{book} has no chapter {chapter}."
    span = f"{rows[0][0]}-{rows[-1][0]}" if len(rows) > 1 else f"{rows[0][0]}"
    lines = "\n".join(f"{v} {text}" for v, text, _, _ in rows)
    return f"## {book} {chapter}:{span}\nSource: {verse_link(rows[0][2], rows[0][3])}\n\n{lines}"


def list_sources(con: sqlite3.Connection, speaker: str | None) -> str:
    rows = con.execute(
        """SELECT DISTINCT name, date, source, title, url FROM passages
           WHERE ? IS NULL OR speaker = ? ORDER BY name, date DESC""",
        (speaker, speaker),
    )
    return "\n".join(f"- {name}, {date}, {source}: {title} · Talk ID: {talk_id(url)} · {url}" for name, date, source, title, url in rows)


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
    lines = [f"- added {added}: {name}, {date}, {source}: {title} · Talk ID: {talk_id(url)} · {url}" for added, name, date, source, title, url in rows]
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
    log.close()  # the update has its own copy


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
    scripture_note = f"It also looks up and searches the standard works (search_scriptures, get_verses). {QUOTE_VERSES}"

    if speaker:
        name = SPEAKERS[speaker]
        mcp = MCPServer(name, instructions=f"Searches the General Conference talks, devotionals, magazine articles and BYU speeches of {name}, {CALLINGS[speaker]}. {CITE} {scripture_note}")

        @mcp.tool(description=f"Search {name}'s General Conference talks, devotionals, magazine articles and BYU speeches. Returns passages in the speaker's own words, each with title, date and source link. {FILTERS} {CITE}")
        def search(query: str, limit: int = 8, from_date: str | None = None, to_date: str | None = None, sources: list[str] | None = None) -> str:
            return search_passages(con, query, [speaker], max(1, min(limit, 20)), sources, from_date, to_date)

        @mcp.tool(description=f"List every talk and speech in {name}'s collection, newest first.")
        def list_talks() -> str:
            return list_sources(con, speaker)

        @mcp.tool(description=f"Show which of {name}'s talks and articles the weekly update added in the last `days` days, and when the last update ran.")
        def whats_new(days: int = 30) -> str:
            return recent_additions(con, speaker, max(1, min(days, 365)))

    else:
        mcp = MCPServer("The Prophets", instructions=f"Searches talks by the First Presidency, the Quorum of the Twelve Apostles, apostles who died since 2021, and the Relief Society, Young Women and Primary general presidencies. {CITE} {scripture_note}")

        @mcp.tool(description=f"Search talks by the First Presidency, the Twelve, apostles who died since 2021, and the Relief Society, Young Women and Primary general presidencies. Optionally limit to speakers: a list of slugs from list_speakers. {FILTERS} {CITE}")
        def search(query: str, speakers: list[str] | None = None, limit: int = 8, from_date: str | None = None, to_date: str | None = None, sources: list[str] | None = None) -> str:
            return search_passages(con, query, speakers, max(1, min(limit, 20)), sources, from_date, to_date)

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

    @mcp.tool(description=f"Read a talk's full text as numbered paragraphs (¶1, ¶2…). Pass a Talk ID from search, list_talks or whats_new, or the talk's Source link. Optionally pass start and end paragraph numbers. Long talks come in parts of about {WORDS_PER_CALL:,} words; follow the note at the end to read on. {CITE}")
    def get_talk(talk: str, start: int | None = None, end: int | None = None) -> str:
        return talk_text(con, talk, start, end, speaker)

    @mcp.tool(description=f"Search the standard works (Old Testament, New Testament, Book of Mormon, Doctrine and Covenants, Pearl of Great Price) for verses about a topic. Optionally limit to one volume: ot, nt, bofm, dc-testament or pgp. {QUOTE_VERSES}")
    def search_scriptures(query: str, volume: str | None = None, limit: int = 8) -> str:
        return search_verses(con, query, volume, max(1, min(limit, 20)))

    @mcp.tool(description=f'Get the exact text of a scripture reference, like "Moroni 10:4-5", "D&C 121:7-8", "1 Nephi 3:7" or "Alma 32" (a whole chapter). {QUOTE_VERSES}')
    def get_verses(reference: str) -> str:
        return lookup_verses(con, reference)

    if args.http:
        # Stateless: any request can land on a freshly restarted machine without losing a session.
        mcp.run("streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), stateless_http=True)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
