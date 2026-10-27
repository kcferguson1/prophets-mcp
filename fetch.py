"""Downloads talks and articles by the Church's senior leaders into prophets.db.

Sources: General Conference, BYU Speeches, Church broadcasts and devotionals, and the Liahona, Ensign,
New Era and For the Strength of Youth magazines.

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
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

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
MAGAZINE_ROOTS = ("/magazines/liahona", "/magazines/for-the-strength-of-youth", "/magazines/ensign-19712020")
BROADCASTS_ROOT = "/videos-and-images/broadcasts-and-devotionals"
# Magazine columns whose table-of-contents byline is a label, not a name, though our speakers write them.
HIDDEN_AUTHOR_LABELS = ("Covenant Women", "Answers from an Apostle", "First Presidency Message")
MIN_WORDS = 100  # shorter pages are video-only stubs, posters or quote cards

SKIP_P_CLASSES = {"author-name", "author-role", "reference", "series-title", "subtitle", "title-number"}
SKIP_P_IDS = ("note", "figure")  # footnotes and image captions
# Labels, not teaching: "From a devotional address, '…,' delivered at BYU on April 10, 2018." says where a reprint came
# from, and "CES Devotional for Young Adults • May 4, 2014 • San Diego, California" heads a BYU Speeches transcript.
SOURCE_NOTE = re.compile(
    r"^(?:Adapted |Excerpted |Taken )?from (?:a|an) .*\b(?:address|devotional|talk|fireside|speech|remarks|commencement|broadcast)", re.I
)


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


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: list[tuple[str | None, str]] = []
        self.current: tuple[str | None, list[str]] | None = None
        self.in_sup = 0
        self.in_note = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "li" and (a.get("id") or "").startswith("note"):
            self.in_note = True  # newer talks put footnote paragraphs, with random ids, inside <li id="note5">
        elif tag == "p" and not self.in_note and not SKIP_P_CLASSES & set((a.get("class") or "").split()) and not (a.get("id") or "").startswith(SKIP_P_IDS):
            self.current = (a.get("id"), [])
        elif tag == "sup":  # footnote markers
            self.in_sup += 1

    def handle_endtag(self, tag):
        if tag == "li":
            self.in_note = False
        elif tag == "sup" and self.in_sup:
            self.in_sup -= 1
        elif tag == "p" and self.current:
            text = " ".join("".join(self.current[1]).split())
            if text and not is_source_note(text):
                self.found.append((self.current[0], text))
            self.current = None

    def handle_data(self, data):
        if self.current and not self.in_sup:
            self.current[1].append(data)


def paragraphs(body: str) -> list[tuple[str | None, str]]:
    """(paragraph id, text) for each <p> in a talk body, minus the byline, footnotes and captions."""
    parser = _Paragraphs()
    parser.feed(body)
    return parser.found


def text_of(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())  # split() also folds non-breaking spaces


HONORIFICS = re.compile(r"\b(?:By|With|President|Elder|Sister|Brother|Bishop)\s+|\s+of the [A-Z][\w ]*?(?= and |,|$)")  # titles, "of the Quorum…"


def credits(data: dict) -> tuple[list[str], str] | None:
    """(our speakers on a Gospel Library page, the name to show for it), or None if none of ours spoke.

    A joint talk or panel shows everyone ("Russell M. Nelson and Wendy W. Nelson"), because its text isn't marked by
    speaker and no quote should be pinned on one person. Bylines decide when there are any: the page data often names
    only the first speaker, and sometimes the wrong person.
    """
    found = (text_of(b) for b in re.findall(r'class="author-name"[^>]*>(.*?)</p>', data["content"]["body"], re.S))
    bylines = list(dict.fromkeys(b for b in found if b))  # some pages repeat one byline
    try:
        who = json.loads(data["meta"]["structuredData"])["mainEntity"]["author"]
    except (KeyError, TypeError, ValueError):
        who = []
    people = [p for p in (who if isinstance(who, list) else [who]) if isinstance(p, dict)]
    if bylines:
        shown = " and ".join(HONORIFICS.sub("", b).strip() for b in bylines)
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
            yield "General Conference", title, path[:7].replace("/", "-"), url, paragraphs(data["content"]["body"])


def byu(slug: str, done: set[str]):
    listing = get(f"{BYU}/speakers/{slug}/")
    for talk in sorted(set(re.findall(rf'href="{BYU}/talks/{slug}/([^/"?]+)/', listing))):
        url = f"{BYU}/talks/{slug}/{talk}/"
        if url in done:
            continue
        hits = json.loads(get(f"{BYU}/wp-json/wp/v2/speech?slug={talk}&_fields=date,link,title,content"))
        hit = next((h for h in hits if h["link"] == url), None)
        if not hit:
            print(f"  ! no API record for {url}", file=sys.stderr)
            continue
        title = html.unescape(html.unescape(hit["title"]["rendered"]))  # some titles are escaped twice ("D&amp;amp;C")
        yield "BYU Speeches", title, hit["date"][:10], url, paragraphs(hit["content"]["rendered"])


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
    """(our speakers, name shown, source, title, date, url, paragraphs) for a page by one of ours, or None."""
    data = data or page(uri)
    if not data:
        return None
    try:
        body, title = data["content"]["body"], data["meta"]["title"]
        who = credits(data)
    except (KeyError, TypeError, ValueError, AttributeError) as e:  # one odd page shouldn't stop the whole source
        print(f"  ! skipped an unreadable page: {uri} ({e!r})", file=sys.stderr)
        return None
    paras = paragraphs(body)
    if not who or sum(len(t.split()) for _, t in paras) < MIN_WORDS or SKIP_TITLES.search(title):
        return None
    if re.search(r'class="title-number"[^>]*>[^<]*Session', body):
        return None  # an excerpt of a conference talk, which we already have in full
    when = re.search(r"/(\d{4})/(\d{2})", uri)
    date = "-".join(when.groups()) if when else ""
    return *who, label, title, date, f"{CHURCH}/study{uri}?lang=eng", paras


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


def save(con, slug, src, title, date, url, paras, shown=None):
    """Store a talk under one of our speakers; shown names everyone on a joint talk."""
    shown = shown or SPEAKERS[slug]
    con.executemany(
        "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
        [(title, text, slug, shown, src, date, url, anchor) for anchor, text in paras],
    )
    print(f"  {date}  {shown}: {title}  ({len(paras)} paragraphs)")


def save_record(con, hit):
    """Save a record() result under each of our speakers on it, skipping magazine reprints of their conference talks."""
    slugs, shown, src, title, date, url, paras = hit
    for slug in slugs:
        if not reprint(con, slug, src, title, date):
            save(con, slug, src, title, date, url, paras, shown)


def main():
    slugs = sys.argv[1:] or list(SPEAKERS)
    if unknown := [s for s in slugs if s not in SPEAKERS]:
        sys.exit(f"Unknown speaker(s): {', '.join(unknown)}. Choose from: {', '.join(SPEAKERS)}")
    lock = hold_lock()  # held until this process exits
    if lock is None:
        sys.exit("Another update is already running. Try again when it finishes.")
    con = connect()
    done = {url for (url,) in con.execute("SELECT DISTINCT url FROM passages")}
    failed = False
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
    if not sys.argv[1:]:
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
        if not failed:
            CHECKED.touch()  # the monthly update waits another month; a cut-off or failed run never gets here, so it retries


if __name__ == "__main__":
    main()
