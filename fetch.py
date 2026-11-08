"""Downloads talks and articles by the Church's senior leaders into prophets.db.

Sources: General Conference, BYU Speeches, Church broadcasts and devotionals, the Liahona, Ensign,
New Era and For the Strength of Youth magazines, and the standard works (verse by verse).

Usage: uv run fetch.py [speaker-slug ...]   (no slugs = everyone and every source; rerunning skips what's saved)
"""
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

DB = Path(os.environ.get("PROPHETS_DB") or Path(__file__).with_name("prophets.db"))  # hosts point this at a disk
LOCK = DB.with_suffix(".updating")  # locked (not just present) while an update runs; see hold_lock
CHECKED = DB.with_suffix(".checked")  # touched only when a full run finishes cleanly
CHURCH = "https://www.churchofjesuschrist.org"
API = f"{CHURCH}/study/api/v3/language-pages/type"
BYU = "https://speeches.byu.edu"

# Roster as of March 2026 (Church News). Update when callings change.
SPEAKERS = {
    "dallin-h-oaks": "Dallin H. Oaks",
    "henry-b-eyring": "Henry B. Eyring",
    "d-todd-christofferson": "D. Todd Christofferson",
    "dieter-f-uchtdorf": "Dieter F. Uchtdorf",
    "david-a-bednar": "David A. Bednar",
    "quentin-l-cook": "Quentin L. Cook",
    "neil-l-andersen": "Neil L. Andersen",
    "ronald-a-rasband": "Ronald A. Rasband",
    "gary-e-stevenson": "Gary E. Stevenson",
    "dale-g-renlund": "Dale G. Renlund",
    "gerrit-w-gong": "Gerrit W. Gong",
    "ulisses-soares": "Ulisses Soares",
    "patrick-kearon": "Patrick Kearon",
    "gerald-causse": "Gérald Caussé",
    "clark-g-gilbert": "Clark G. Gilbert",
    # Died since October 2021.
    "russell-m-nelson": "Russell M. Nelson",
    "jeffrey-r-holland": "Jeffrey R. Holland",
    "m-russell-ballard": "M. Russell Ballard",
    # General officers: the Relief Society, Young Women and Primary general presidencies (Church pages, Oct 2026).
    "camille-n-johnson": "Camille N. Johnson",
    "j-anette-dennis": "J. Anette Dennis",
    "kristin-m-yee": "Kristin M. Yee",
    "emily-belle-freeman": "Emily Belle Freeman",
    "tamara-w-runia": "Tamara W. Runia",
    "andrea-munoz-spannaus": "Andrea Muñoz Spannaus",
    "rosemary-k-chibota": "Rosemary K. Chibota",
    "nina-m-garfield": "Nina M. Garfield",
    "theresa-a-collins": "Theresa A. Collins",
}

# Shown by list_speakers so a client knows who's who. Update with SPEAKERS when callings change.
TWELVE = "Quorum of the Twelve Apostles"
CALLINGS = {
    "dallin-h-oaks": "President of the Church",
    "henry-b-eyring": "First Counselor in the First Presidency",
    "d-todd-christofferson": "Second Counselor in the First Presidency",
    "dieter-f-uchtdorf": "Acting President of the Quorum of the Twelve Apostles",
    "david-a-bednar": TWELVE,
    "quentin-l-cook": TWELVE,
    "neil-l-andersen": TWELVE,
    "ronald-a-rasband": TWELVE,
    "gary-e-stevenson": TWELVE,
    "dale-g-renlund": TWELVE,
    "gerrit-w-gong": TWELVE,
    "ulisses-soares": TWELVE,
    "patrick-kearon": TWELVE,
    "gerald-causse": TWELVE,
    "clark-g-gilbert": TWELVE,
    "russell-m-nelson": "17th President of the Church (died 2025)",
    "jeffrey-r-holland": "President of the Quorum of the Twelve Apostles (died 2025)",
    "m-russell-ballard": "Acting President of the Quorum of the Twelve Apostles (died 2023)",
    "camille-n-johnson": "Relief Society General President",
    "j-anette-dennis": "First Counselor in the Relief Society General Presidency",
    "kristin-m-yee": "Second Counselor in the Relief Society General Presidency",
    "emily-belle-freeman": "Young Women General President",
    "tamara-w-runia": "First Counselor in the Young Women General Presidency",
    "andrea-munoz-spannaus": "Second Counselor in the Young Women General Presidency",
    "rosemary-k-chibota": "Primary General President",
    "nina-m-garfield": "First Counselor in the Primary General Presidency",
    "theresa-a-collins": "Second Counselor in the Primary General Presidency",
}

# Counselors read these as procedure; they're lists of names, not teaching.
SKIP_TITLES = re.compile(r"sustaining of|auditing department|statistical report|solemn assembly|\bexcerpts\b", re.I)

MAGAZINES = {"liahona": "Liahona", "ensign": "Ensign", "new-era": "New Era", "ftsoy": "For the Strength of Youth"}
VOLUMES = {
    "ot": "Old Testament", "nt": "New Testament", "bofm": "Book of Mormon",
    "dc-testament": "Doctrine and Covenants", "pgp": "Pearl of Great Price",
}
MAGAZINE_ROOTS = ("/magazines/liahona", "/magazines/for-the-strength-of-youth", "/magazines/ensign-19712020")
BROADCASTS_ROOT = "/videos-and-images/broadcasts-and-devotionals"
# Magazine columns whose table-of-contents byline is a label, not a name, though our speakers write them.
HIDDEN_AUTHOR_LABELS = ("Covenant Women", "Answers from an Apostle", "First Presidency Message")
MIN_WORDS = 100  # shorter pages are video-only stubs, posters or quote cards
# The database's PRAGMA user_version once every saved talk has footnotes and citations; older ones are re-read once.
VERSION = 2

SKIP_P_CLASSES = {"author-name", "author-role", "reference", "series-title", "subtitle", "title-number"}
SKIP_P_IDS = ("note", "figure")  # footnotes and image captions
# Labels, not teaching: "From a devotional address, '…,' delivered at BYU on April 10, 2018." says where a reprint came
# from, and "CES Devotional for Young Adults • May 4, 2014 • San Diego, California" heads a BYU Speeches transcript.
SOURCE_NOTE = re.compile(
    r"^(?:Adapted |Excerpted |Taken )?from (?:a|an) .*\b(?:address|devotional|talk|fireside|speech|remarks|commencement|broadcast)", re.I
)


# Short or plural names people type that differ from the chapter titles the verses are stored under.
BOOK_ALIASES = {"d&c": "doctrine and covenants", "dc": "doctrine and covenants", "psalms": "psalm",
                "od": "official declaration", "js h": "joseph smith history", "jsh": "joseph smith history",
                "js m": "joseph smith matthew"}


def book_key(name: str) -> str:
    key = " ".join(re.sub(r"[^\w&]+", " ", name.lower()).split())  # "Joseph Smith—History" -> "joseph smith history"
    return BOOK_ALIASES.get(key, key)


def is_source_note(text: str) -> bool:
    words = len(text.split())
    return (words < 60 and bool(SOURCE_NOTE.match(text))) or (words < 30 and " • " in text)


def hold_lock():
    """Take the update lock and return its open file, or None if another update holds it.

    It's an operating-system lock on the file, so it's freed the moment the holder exits, even after a crash.
    Keep the returned file open for as long as the update runs.
    """
    f = open(LOCK, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) the-prophets-mcp"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode()
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 2:
                raise  # a real answer like 404 won't change; a server error (5xx) may pass, so it's retried
            time.sleep(10 * (attempt + 1))
        except OSError:  # timeouts and dropped connections
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
    time.sleep(0.3)  # be polite to both sites
    return body


def page(uri: str) -> dict | None:
    """A Gospel Library page's data; None if it's gone (404) or has no text. Other errors stop the run, to retry later."""
    try:
        data = api("content", uri)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return None
        raise
    if not isinstance(data.get("content"), dict) or not isinstance(data["content"].get("body"), str):
        print(f"  ! skipped a page with no text: {uri}", file=sys.stderr)
        return None
    return data


def api(kind: str, uri: str) -> dict:
    """The Church's Gospel Library API: kind "content" for a page, "dynamic" for a collection listing."""
    return json.loads(get(f"{API}/{kind}?lang=eng&uri={uri}"))


NOTE_ID = re.compile(r"note-?(\d+)(?:_p\d+)?")  # <li id="note3">, older <p id="note3_p1">, BYU's <p id="note-3">
NOTE_REF = re.compile(r"#note-?(\d+)$")  # a footnote marker's link


class Reading(NamedTuple):
    """One reading of a talk page. ¶ numbers count paras from 1, as the passages table stores them."""
    paras: list[tuple[str | None, str]]  # (paragraph id, text)
    notes: list[tuple[int, int, str]] = []  # (¶, footnote number, text)
    links: list[tuple[int, int | None, str]] = []  # (¶, footnote number or None for the paragraph itself, scripture link)
    html: str = ""


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: list[tuple[str | None, str, list[int], list[str]]] = []  # (id, text, footnote numbers, scripture links)
        self.current: tuple[str | None, list[str], list[int], list[str]] | None = None
        self.in_sup = 0
        self.sup: list[str] = []  # the open <sup>'s text: a bare number there is a footnote marker (BYU's API text)
        self.note: tuple[int | None, str, list[str], list[str]] | None = None  # (number, closing tag, text, scripture links)
        self.notes: dict[int, tuple[str, list[str]]] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        pid = a.get("id") or ""
        if tag in ("li", "p") and pid.startswith("note") and not self.note:
            # Newer talks put footnote paragraphs, with random ids, inside <li id="note5">. "note_title1" has no number.
            number = NOTE_ID.fullmatch(pid)
            self.note = (int(number[1]) if number else None, tag, [], [])
        elif tag == "p" and not self.note and not SKIP_P_CLASSES & set((a.get("class") or "").split()) and not pid.startswith(SKIP_P_IDS):
            self.current = (a.get("id"), [], [], [])
        elif tag == "sup":  # footnote markers
            self.in_sup += 1
            self.sup = []
        elif tag == "a":
            href = a.get("href") or ""
            marker = NOTE_REF.search(href)
            if marker and self.current:
                self.current[2].append(int(marker[1]))
            elif "/scriptures/" in href and (self.note or self.current):
                (self.note or self.current)[3].append(href)

    def handle_endtag(self, tag):
        if self.note and tag == self.note[1]:
            number, _, text, links = self.note
            if number is not None:
                self.notes[number] = (" ".join("".join(text).split()), links)
            self.note = None
        elif tag == "sup" and self.in_sup:
            self.in_sup -= 1
            if self.current and "".join(self.sup).strip().isdigit():
                self.current[2].append(int("".join(self.sup)))
        elif tag == "p" and self.current:
            text = " ".join("".join(self.current[1]).split())
            if text and not is_source_note(text):
                self.found.append((self.current[0], text, self.current[2], self.current[3]))
            self.current = None

    def handle_data(self, data):
        if self.note:
            self.note[2].append(data)
        elif self.in_sup:
            self.sup.append(data)
        elif self.current:
            self.current[1].append(data)


def read_talk(body: str, notes: str = "") -> Reading:
    """A talk's paragraphs (minus the byline, footnotes and captions), the footnotes their markers point to, and every
    scripture link in them. notes is a notes panel kept apart from the text (BYU's public page)."""
    parser = _Paragraphs()
    parser.feed(body + notes)
    owner: dict[int, int] = {}  # footnote number -> its marker's ¶; a marker in a caption or byline has none
    for n, (_, _, markers, _) in enumerate(parser.found, 1):
        for m in markers:
            owner.setdefault(m, n)
    mine = sorted((owner[m], m, text, links) for m, (text, links) in parser.notes.items() if m in owner)
    return Reading(
        [(pid, text) for pid, text, _, _ in parser.found],
        [(n, m, re.sub(rf"^{m}\.\s*", "", text)) for n, m, text, _ in mine if text],  # BYU notes start "3. "
        [(n, None, href) for n, (*_, links) in enumerate(parser.found, 1) for href in links]
        + [(n, m, href) for n, m, _, links in mine for href in links],
        body + notes,
    )


def paragraphs(body: str) -> list[tuple[str | None, str]]:
    """(paragraph id, text) for each <p> in a talk body, minus the byline, footnotes and captions."""
    return read_talk(body).paras


SCRIPTURE_LINK = re.compile(r"/scriptures/(ot|nt|bofm|dc-testament|pgp)/([a-z0-9-]+)/(\d+)(?:\.([\d,\-–]+))?")


def verse_numbers(spec: str) -> list[int]:
    """Verse numbers in "p10-p13,p15", "10-13, 15" or "16, 28" (the p is sometimes missing after a comma)."""
    return [v for a, b in re.findall(r"p?(\d+)(?:\s*[-–]\s*p?(\d+))?", spec) for v in range(int(a), min(int(b or a), int(a) + 200) + 1)]


def cited(href: str) -> tuple[str, list[int]] | None:
    """(chapter link as the verses table stores it, verse numbers or [] for a whole chapter) for a link into the
    standard works, or None (Bible Dictionary, JST and other links). Church links put the verses in the id
    ("?id=p10-p13%2Cp15"), not the #fragment, which is only the first; BYU links put them after a dot ("/dc/84.43-45")."""
    href = urllib.parse.unquote(href)
    m = SCRIPTURE_LINK.search(href)
    if not m:
        return None
    spec = m[4] or next(iter(re.findall(r"[?&]id=([^&#]*)", href)), "")
    if not re.fullmatch(r"[p\d,\-–\s]*", spec):
        spec = ""  # an id that isn't verses: the chapter
    return f"{CHURCH}/study/scriptures/{m[1]}/{m[2]}/{int(m[3])}?lang=eng", verse_numbers(spec)


# A typed reference sits in parentheses or brackets: "(see D&C 76:69; 107:19)", "[Abraham 3:22–25]".
WRITTEN_GROUP = re.compile(r"[(\[]([^()\[\]]*\d+:\d+[^()\[\]]*)[)\]]")
WRITTEN_REF = re.compile(r"(?:(?:see|also|cf\.?)\s+)*(.*?)\s*(\d+):(\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)", re.I)


def written_citations(con, paras) -> list[tuple[int, str, int | None, None]]:
    """(¶, chapter link, verse, None) for references typed into the text, for BYU speeches with no links. A part with no
    book of its own ("107:19") takes the one before it in the same parentheses. Not every verse found exists."""
    chapters = {(book_key(b), int(c)): u for b, c, u in con.execute("SELECT DISTINCT book, chapter, url FROM verses")}
    names = {k for k, _ in chapters}
    found = []
    for n, (_, text) in enumerate(paras, 1):
        for group in WRITTEN_GROUP.findall(text):
            book = None
            for part in re.split(r";|,(?=\s*\d+:)", group):  # "D&C 6:34, 78:17–18" is two references
                ref = WRITTEN_REF.match(part.strip())
                if not ref:
                    continue
                if ref[1]:  # a book name, or an abbreviation that starts exactly one ("Hel.", "2 Ne."); "JD" starts none
                    key = book_key(ref[1])
                    starts = [k for k in names if k.startswith(key)]
                    book = key if key in names else starts[0] if len(starts) == 1 else None
                if url := chapters.get((book, int(ref[2]))):
                    found += [(n, url, v, None) for v in verse_numbers(ref[3])]
    return found


def citations(con, source: str, talk: Reading) -> list[tuple[int, str, int | None, int | None]]:
    """(¶, chapter link, verse or None for a whole chapter, footnote number or None) for each verse a talk cites, once
    each, checked against the verses table. BYU speeches with no links are read for typed references instead."""
    found = [(n, hit[0], v, note) for n, note, href in talk.links if (hit := cited(href)) for v in hit[1] or [None]]
    if not talk.links and source == "BYU Speeches":
        found = written_citations(con, talk.paras)
    chapters = list({c for _, c, _, _ in found})
    real = set(con.execute(f"SELECT url, CAST(verse AS INTEGER) FROM verses WHERE url IN ({','.join('?' * len(chapters))})", chapters)) if chapters else set()
    whole = {u for u, _ in real}
    return list(dict.fromkeys(r for r in found if (r[1], r[2]) in real or (r[2] is None and r[1] in whole)))


def text_of(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())  # split() also folds non-breaking spaces


HONORIFICS = re.compile(r"\b(?:By:?|With|President|Elder|Sister|Brother|Bishop)\s+|\s+of the [A-Z][\w ]*?(?= and |,|$)")  # titles, "of the Quorum…"


def credits(data: dict) -> tuple[list[str], str] | None:
    """(our speakers on a Gospel Library page, the name to show for it), or None if none of ours spoke.

    A joint talk or panel shows everyone ("Russell M. Nelson and Wendy W. Nelson"), because its text isn't marked by
    speaker and no quote should be pinned on one person. Bylines decide when there are any: the page data often names
    only the first speaker, and sometimes the wrong person.
    """
    def name_of(byline):  # newer bylines put the name in a "dominant" span and the calling after it
        lead = re.search(r'class="dominant"[^>]*>(.*?)</span>', byline, re.S)
        return text_of(lead[1] if lead else byline).rstrip(",")

    found = (name_of(b) for b in re.findall(r'class="author-name"[^>]*>(.*?)</p>', data["content"]["body"], re.S))
    bylines = list(dict.fromkeys(b for b in found if b))  # some pages repeat one byline
    try:
        who = json.loads(data["meta"]["structuredData"])["mainEntity"]["author"]
    except (KeyError, TypeError, ValueError):
        who = []
    people = [p for p in (who if isinstance(who, list) else [who]) if isinstance(p, dict)]
    if bylines:
        names = [HONORIFICS.sub("", b).strip() for b in bylines]
        shown = " and ".join(filter(None, [", ".join(names[:-1]), names[-1]]))  # "A, B and C"
        ours = [s for s, name in SPEAKERS.items() if name in shown]
    else:
        shown = " and ".join(p["name"] for p in people if p.get("name"))
        ours = [s for s in (str(p.get("url", "")).rsplit("/", 1)[-1] for p in people) if s in SPEAKERS]
    if not ours:
        return None
    joint = len(bylines) > 1 or len(people) > 1 or re.search(r",|\band\b|&", shown)
    return ours, shown if joint else SPEAKERS[ours[0]]


def connect(path=DB) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False)
    # FTS5 is SQLite's full-text search; it ranks matches with BM25. Porter stemming makes "repenting" find "repentance".
    con.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
            title, text, speaker UNINDEXED, name UNINDEXED, source UNINDEXED, date UNINDEXED, url UNINDEXED, anchor UNINDEXED,
            tokenize='porter unicode61 remove_diacritics 2')"""
    )
    # Gospel Library pages, events and issues already checked, whether or not they were by one of ours.
    con.execute("CREATE TABLE IF NOT EXISTS seen (uri TEXT PRIMARY KEY)")
    # One row per talk saved by an update, so whats_new can show what arrived and when (UTC). Starts empty on an existing index.
    con.execute(
        """CREATE TABLE IF NOT EXISTS added (
            url TEXT, speaker TEXT, name TEXT, source TEXT, date TEXT, title TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP)"""
    )
    # The standard works, one row per verse; ref ("Moroni 10:4") is indexed so naming a book finds its verses too.
    con.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS verses USING fts5(
            ref, text, volume UNINDEXED, book UNINDEXED, chapter UNINDEXED, verse UNINDEXED, url UNINDEXED, anchor UNINDEXED,
            tokenize='porter unicode61 remove_diacritics 2')"""
    )
    # Keyed by talk link and ¶ number (passages' own order), not row ids, so a joint talk's copies share them.
    con.execute("CREATE TABLE IF NOT EXISTS footnotes (url TEXT, para INTEGER, note INTEGER, text TEXT)")
    # One row per cited verse; a whole-chapter citation has no verse. note is the footnote number, or empty for the text.
    con.execute("CREATE TABLE IF NOT EXISTS citations (url TEXT, para INTEGER, chapter TEXT, verse INTEGER, note INTEGER)")
    con.execute("CREATE INDEX IF NOT EXISTS footnotes_url ON footnotes (url, para)")
    con.execute("CREATE INDEX IF NOT EXISTS citations_url ON citations (url)")
    # Each talk page as read, zlib-compressed, so a new reader can re-read pages without downloading them (docs/adr/0001).
    con.execute("CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, html BLOB)")
    # Talks saved by the current reader, with footnotes and citations. Lets the one-time re-read resume where it stopped.
    con.execute("CREATE TABLE IF NOT EXISTS reread (url TEXT PRIMARY KEY)")
    return con


def conference(slug: str, done: set[str]):
    listing = get(f"{CHURCH}/study/general-conference/speakers/{slug}?lang=eng")
    for path in sorted(set(re.findall(r'href="/study/general-conference/(\d{4}/\d{2}/[^"?]+)"', listing))):
        url = f"{CHURCH}/study/general-conference/{path}?lang=eng"
        if url in done:
            continue
        data = page(f"/general-conference/{path}")
        title = (data or {}).get("meta", {}).get("title", "")
        if data and title and not SKIP_TITLES.search(title):
            yield "General Conference", title, path[:7].replace("/", "-"), url, read_talk(data["content"]["body"])


def speech(url: str) -> dict | None:
    """The BYU Speeches API record for a speech link, or None if it has none."""
    slug = url.rstrip("/").rsplit("/", 1)[1]
    hits = json.loads(get(f"{BYU}/wp-json/wp/v2/speech?slug={slug}&_fields=date,link,title,content"))
    return next((h for h in hits if h["link"] == url), None)


def byu_talk(url: str, text: str) -> Reading:
    """A BYU speech read with its footnotes. The API text has only bare markers (<sup>2</sup>), so a speech that has
    them costs one more request: the notes are in a hidden panel on the public page. A panel that's missing (a layout
    change) is logged and skipped; a request error stops the run, to retry later."""
    if "<sup" not in text:
        return read_talk(text)  # before 2010, speeches have no footnotes
    try:
        panel = re.search(r'<div[^>]*id="?is-notes-body"?[^>]*>(.*?)</div>', get(url), re.S)
    except urllib.error.HTTPError as e:
        if e.code not in (404, 410):
            raise
        panel = None
    if not panel:
        print(f"  ! no footnotes panel on {url}; saved without footnotes", file=sys.stderr)
    return read_talk(text, panel[1] if panel else "")


def byu(slug: str, done: set[str]):
    listing = get(f"{BYU}/speakers/{slug}/")
    for talk in sorted(set(re.findall(rf'href="{BYU}/talks/{slug}/([^/"?]+)/', listing))):
        url = f"{BYU}/talks/{slug}/{talk}/"
        if url in done:
            continue
        hit = speech(url)
        if not hit:
            print(f"  ! no API record for {url}", file=sys.stderr)
            continue
        title = html.unescape(html.unescape(hit["title"]["rendered"]))  # some titles are escaped twice ("D&amp;amp;C")
        yield "BYU Speeches", title, hit["date"][:10], url, byu_talk(url, hit["content"]["rendered"])


def walk(uri: str, top: bool = True):
    """Every item uri under a Gospel Library collection, following sub-collections.

    A missing sub-collection is skipped. A missing top collection stops the run: it means the Church moved the
    listing, and finishing "successfully" would hide that no new talks can be found.
    """
    try:
        listing = api("dynamic", uri)["collection"]
    except urllib.error.HTTPError as e:
        if e.code == 404 and not top:
            return
        raise
    for section in listing.get("sections", []):
        for entry in section.get("entries", []):
            if entry.get("type") == "collection":
                yield from walk(entry["uri"], top=False)
            else:
                yield entry["uri"]


def record(uri: str, label: str, data: dict | None = None):
    """(our speakers, name shown, source, title, date, url, Reading) for a page by one of ours, or None."""
    data = data or page(uri)
    if not data:
        return None
    try:
        body, title = data["content"]["body"], data["meta"]["title"]
        who = credits(data)
    except (KeyError, TypeError, ValueError, AttributeError) as e:  # one odd page shouldn't stop the whole source
        print(f"  ! skipped an unreadable page: {uri} ({e!r})", file=sys.stderr)
        return None
    talk = read_talk(body)
    if not who or sum(len(t.split()) for _, t in talk.paras) < MIN_WORDS or SKIP_TITLES.search(title):
        return None
    if re.search(r'class="title-number"[^>]*>[^<]*Session', body):
        return None  # an excerpt of a conference talk, which we already have in full
    when = re.search(r"/(\d{4})/(\d{2})", uri)
    date = "-".join(when.groups()) if when else ""
    return *who, label, title, date, f"{CHURCH}/study{uri}?lang=eng", talk


def recent(uri: str) -> bool:
    """True for a page dated in the last two months. Its listing or text may still change (a devotional posted as
    video gets its transcript later; digital-only articles join an issue late), so it's checked again next run."""
    when = re.search(r"/(\d{4})/(\d{2})", uri)
    return bool(when) and f"{when[1]}/{when[2]}" >= time.strftime("%Y/%m", time.localtime(time.time() - 62 * 86400))


def conference_tocs(seen: set[str]):
    """Every General Conference table of contents, the official list of who spoke; catches talks a speaker page misses.
    Yields (uri to mark seen, record or None)."""
    for year in range(1971, int(time.strftime("%Y")) + 1):
        for month in ("04", "10"):
            toc = f"/general-conference/{year}/{month}"
            if toc in seen:
                continue
            data = page(toc)
            if not data:
                continue  # a conference not held yet
            for uri, inner in re.findall(r'<a href="/study(/general-conference/\d{4}/\d{2}/[^"?#]+)[^>]*>(.*?)</a>', data["content"]["body"], re.S):
                byline = text_of(" ".join(re.findall(r'class="primaryMeta"[^>]*>(.*?)</p>', inner, re.S)))
                if uri not in seen and any(name in byline for name in SPEAKERS.values()):
                    yield uri, record(uri, "General Conference")
            yield toc, None


def broadcasts(seen: set[str]):
    """Devotionals and other broadcasts. Yields (uri to mark seen, record or None)."""
    for event in walk(BROADCASTS_ROOT):
        if not event.startswith("/broadcasts/") or event in seen:
            continue
        data = page(event)
        if not data:
            yield event, None  # single-talk events that only redirect on the website
            continue
        talks = sorted({t for t in re.findall(r'href="/study(/broadcasts/[^"?#]+)', data["content"]["body"]) if t.startswith(event + "/")})
        for talk in talks:
            if talk not in seen:
                yield talk, record(talk, "Church broadcast")
        yield event, None if talks else record(event, "Church broadcast", data)


def magazine_articles(body: str):
    """Article uris in an issue's table of contents that may be by one of ours."""
    for attrs, uri, inner in re.findall(r'<li([^>]*)>\s*<a [^>]*?href="/study([^"?#]+)[^>]*>(.*?)</a>', body, re.S):
        if "general-conference" in attrs or "-session/" in uri or "local-pages" in uri:
            continue  # conference reprints and local news
        byline = text_of(" ".join(re.findall(r'class="primaryMeta"[^>]*>(.*?)</p>', inner, re.S)))
        leaders = re.findall(r'data-uri="/church/leader/([^"]+)"', inner)
        if any(s in SPEAKERS for s in leaders) or any(n in byline for n in SPEAKERS.values()) or any(l in byline for l in HIDDEN_AUTHOR_LABELS):
            yield uri


def magazines(seen: set[str]):
    """Liahona (2021 on), Ensign, New Era and For the Strength of Youth. Yields (uri to mark seen, record or None)."""
    for root in MAGAZINE_ROOTS:
        for issue in walk(root):
            m = re.match(r"/(liahona|ensign|new-era|ftsoy)/(\d{4})/(\d{2})", issue)
            # Before 2021 the Liahona was an international edition that reprinted the Ensign and New Era.
            if not m or issue in seen or (m[1] == "liahona" and int(m[2]) < 2021):
                continue
            data = page(issue)
            if not data:
                continue
            for uri in magazine_articles(data["content"]["body"]):
                if uri not in seen:
                    yield uri, record(uri, MAGAZINES[m[1]])
            yield issue, None


def scriptures(seen: set[str]):
    """The standard works, chapter by chapter. Yields (chapter uri, verse rows for the verses table, or None if gone)."""
    for vol, volume in VOLUMES.items():
        toc = json.dumps(api("dynamic", f"/scriptures/{vol}")["toc"])
        for uri in sorted(set(re.findall(rf'"(/scriptures/{vol}/[a-z0-9-]+/(\d+))"', toc))):
            uri, chapter = uri[0], int(uri[1])
            if uri in seen:
                continue
            data = page(uri)
            if not data:
                yield uri, None
                continue
            book = re.sub(r"\s+\d+$", "", " ".join(data["meta"]["title"].split()))  # "1\xa0Corinthians 13" -> "1 Corinthians"
            # Verse ids are p1, p2…, unlike chapter headings or "The End"; the id number is the verse number.
            found = [(int(a[1:]), t) for a, t in paragraphs(data["content"]["body"]) if a and re.fullmatch(r"p\d+", a)]
            numbered = [(v, t) for v, t in found if t.startswith(f"{v} ")]
            # Where verses are numbered, unnumbered ids are signatures and notes ("Joseph Smith.", Oliver Cowdery's
            # note after JS—H 1:75). The Official Declarations number nothing, so every paragraph stays.
            verses = [(v, t[len(str(v)) + 1:]) for v, t in numbered] if numbered else found
            url = f"{CHURCH}/study{uri}?lang=eng"
            yield uri, [(f"{book} {chapter}:{v}", t, volume, book, chapter, v, url, f"p{v}") for v, t in verses]


def months(date: str) -> int:
    year, month = date.split("-")[:2]
    return int(year) * 12 + int(month)


def reprint(con, slug, src, title, date) -> bool:
    """A magazine's reprint of a conference talk we already have: same speaker and title, within three months after."""
    if src not in MAGAZINES.values() or not date:
        return False
    rows = con.execute(
        "SELECT DISTINCT date FROM passages WHERE source = 'General Conference' AND speaker = ? AND title = ?", (slug, title)
    )
    return any(0 <= months(date) - months(d) <= 3 for (d,) in rows)


def store(con, url, src, talk: Reading):
    """Save a talk's footnotes, citations and page HTML, replacing any from an earlier reading."""
    con.execute("DELETE FROM footnotes WHERE url = ?", (url,))
    con.execute("DELETE FROM citations WHERE url = ?", (url,))
    con.executemany("INSERT INTO footnotes VALUES (?,?,?,?)", [(url, *note) for note in talk.notes])
    con.executemany("INSERT INTO citations VALUES (?,?,?,?,?)", [(url, *c) for c in citations(con, src, talk)])
    con.execute("INSERT OR REPLACE INTO pages VALUES (?,?)", (url, zlib.compress(talk.html.encode())))
    if con.execute("SELECT 1 FROM verses LIMIT 1").fetchone():  # with no verses to check against, re-read it later
        con.execute("INSERT OR IGNORE INTO reread VALUES (?)", (url,))


def fresh(url: str) -> Reading | None:
    """A saved talk's page read again, or None if it's gone or has no text now."""
    if url.startswith(BYU):
        hit = speech(url)
        return byu_talk(url, hit["content"]["rendered"]) if hit else None
    data = page(url.split("/study", 1)[1].split("?")[0])
    return read_talk(data["content"]["body"]) if data else None


def reread(con) -> bool:
    """Read every talk saved before footnotes and citations were kept again, once (docs/adr/0001), and set the
    database's version when none is left. Each talk's paragraphs are replaced in one transaction, so search sees
    the old ones or the new, never neither. True when every talk is done."""
    if not con.execute("SELECT 1 FROM verses LIMIT 1").fetchone():
        return False  # citations are checked against the verses; the scriptures come first next run
    todo = con.execute("SELECT DISTINCT url, source FROM passages WHERE url NOT IN (SELECT url FROM reread) ORDER BY url").fetchall()
    if todo:
        print(f"Re-reading {len(todo)} saved talks for footnotes and citations (once)")
    errors = 0
    for url, src in todo:
        try:
            talk = fresh(url)
        except Exception as e:  # a request error: left unmarked, so the next update tries it again
            print(f"  ! couldn't re-read {url}: {e}", file=sys.stderr)
            errors += 1
            if errors == 5:
                print("  ! stopped after 5 errors in a row; the next update goes on from here", file=sys.stderr)
                return False
            continue
        errors = 0
        with con:
            if talk and talk.paras:
                copies = con.execute("SELECT DISTINCT title, speaker, name, source, date FROM passages WHERE url = ?", (url,)).fetchall()
                con.execute("DELETE FROM passages WHERE url = ?", (url,))
                con.executemany(
                    "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
                    [(title, text, slug, name, source, date, url, anchor) for title, slug, name, source, date in copies for anchor, text in talk.paras],
                )
                store(con, url, src, talk)
            else:  # removed from the site since it was saved: keep the text we have
                print(f"  ! {url} is gone or empty now; kept its saved text", file=sys.stderr)
                con.execute("INSERT OR IGNORE INTO reread VALUES (?)", (url,))
    left = con.execute("SELECT COUNT(DISTINCT url) FROM passages WHERE url NOT IN (SELECT url FROM reread)").fetchone()[0]
    if not left:
        con.execute(f"PRAGMA user_version = {VERSION}")
    return not left


def save(con, slug, src, title, date, url, talk: Reading, shown=None):
    """Store a talk under one of our speakers; shown names everyone on a joint talk."""
    if not talk.paras:
        return  # audio- or video-only: nothing to search, and leaving it unsaved means a later transcript is picked up
    shown = shown or SPEAKERS[slug]
    con.executemany(
        "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
        [(title, text, slug, shown, src, date, url, anchor) for anchor, text in talk.paras],
    )
    store(con, url, src, talk)  # a joint talk's second speaker replaces the first's rows with the same ones
    con.execute("INSERT INTO added (url, speaker, name, source, date, title) VALUES (?,?,?,?,?,?)", (url, slug, shown, src, date, title))
    print(f"  {date}  {shown}: {title}  ({len(talk.paras)} paragraphs)")


def save_record(con, hit):
    """Save a record() result under each of our speakers on it, skipping magazine reprints of their conference talks."""
    slugs, shown, src, title, date, url, talk = hit
    for slug in slugs:
        if not reprint(con, slug, src, title, date):
            save(con, slug, src, title, date, url, talk, shown)


def main():
    slugs = sys.argv[1:] or list(SPEAKERS)
    if unknown := [s for s in slugs if s not in SPEAKERS]:
        sys.exit(f"Unknown speaker(s): {', '.join(unknown)}. Choose from: {', '.join(SPEAKERS)}")
    lock = hold_lock()  # held until this process exits
    if lock is None:
        sys.exit("Another update is already running. Try again when it finishes.")
    con = connect()
    started = con.execute("SELECT datetime('now')").fetchone()[0]
    print(f"Update started {started} UTC", flush=True)  # the log is appended to, so mark where each run begins
    done = {url for (url,) in con.execute("SELECT DISTINCT url FROM passages")}
    failed = False
    full = not sys.argv[1:]
    if full:  # first, because saving a talk checks its citations against the verses
        print("Scriptures")
        chapters = 0
        try:
            # Scripture text doesn't change, so a saved chapter is never fetched again.
            for uri, rows in scriptures({uri for (uri,) in con.execute("SELECT uri FROM seen")}):
                con.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?,?)", rows or [])
                con.execute("INSERT OR IGNORE INTO seen VALUES (?)", (uri,))
                con.commit()
                chapters += bool(rows)
        except Exception as e:  # network or page-layout error; rerunning resumes where it stopped
            print(f"  ! scriptures stopped: {e}", file=sys.stderr)
            failed = True
        print(f"  {chapters} new chapters")
    for slug in slugs:
        print(SPEAKERS[slug])
        for source in (conference, byu):
            try:
                for hit in source(slug, done):
                    save(con, slug, *hit)
                    con.commit()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    print(f"  no {source.__name__} page yet")  # newer leaders who haven't spoken there; not a failure
                else:
                    print(f"  ! {source.__name__} stopped: {e}", file=sys.stderr)
                    failed = True
            except Exception as e:  # network or page-layout error; rerunning resumes where it stopped
                print(f"  ! {source.__name__} stopped: {e}", file=sys.stderr)
                failed = True
        talks = con.execute("SELECT source, COUNT(DISTINCT url) FROM passages WHERE speaker = ? GROUP BY source", (slug,))
        print("  total:", ", ".join(f"{n} {src}" for src, n in talks) or "nothing")

    # These sources are listed by event or issue, not by speaker, so they run only on a full run.
    if full:
        seen = {uri for (uri,) in con.execute("SELECT uri FROM seen")}
        saved = {url for (url,) in con.execute("SELECT DISTINCT url FROM passages")}  # fresh: includes this run's saves
        seen |= {url.split("/study", 1)[1].split("?")[0] for url in saved if "/study/" in url}
        for source in (conference_tocs, broadcasts, magazines):
            print(source.__name__.capitalize())
            try:
                for uri, hit in source(seen):
                    if hit:
                        save_record(con, hit)
                    if uri:
                        seen.add(uri)  # not again this run, either way
                        if hit or not recent(uri):  # a recent page may still change, so only remember it once saved
                            con.execute("INSERT OR IGNORE INTO seen VALUES (?)", (uri,))
                    con.commit()
            except Exception as e:  # network or page-layout error; rerunning resumes where it stopped
                print(f"  ! {source.__name__} stopped: {e}", file=sys.stderr)
                failed = True
        try:
            failed |= not reread(con)
        except Exception as e:  # a database or page-layout error; rerunning resumes where it stopped
            print(f"  ! re-reading stopped: {e}", file=sys.stderr)
            failed = True
        if not failed:
            CHECKED.touch()  # the weekly update waits another week; a cut-off or failed run never gets here, so it retries
    new = con.execute("SELECT COUNT(DISTINCT url) FROM added WHERE at >= ?", (started,)).fetchone()[0]
    print(f"Update finished: {new} new talks and articles" + (" (stopped early; the next run picks up the rest)" if failed else ""))


if __name__ == "__main__":
    main()
