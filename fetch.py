"""Downloads General Conference talks and BYU speeches by the First Presidency and the Twelve into prophets.db.

Usage: uv run fetch.py [speaker-slug ...]   (no slugs = everyone; rerunning skips talks already saved)
"""
import html
import json
import re
import sqlite3
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DB = Path(__file__).with_name("prophets.db")
CHURCH = "https://www.churchofjesuschrist.org"
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
}

# Counselors read these as procedure; they're lists of names, not teaching.
SKIP_TITLES = re.compile(r"sustaining of|auditing department|statistical report", re.I)


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) the-prophets-mcp"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    time.sleep(0.3)  # be polite to both sites
    return body


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: list[tuple[str | None, str]] = []
        self.current: tuple[str | None, list[str]] | None = None
        self.in_sup = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "p" and not {"author-name", "author-role"} & set((a.get("class") or "").split()):
            self.current = (a.get("id"), [])
        elif tag == "sup":  # footnote markers
            self.in_sup += 1

    def handle_endtag(self, tag):
        if tag == "sup" and self.in_sup:
            self.in_sup -= 1
        elif tag == "p" and self.current:
            text = " ".join("".join(self.current[1]).split())
            if text:
                self.found.append((self.current[0], text))
            self.current = None

    def handle_data(self, data):
        if self.current and not self.in_sup:
            self.current[1].append(data)


def paragraphs(body: str) -> list[tuple[str | None, str]]:
    """(paragraph id, text) for each <p> in a talk body, minus the byline."""
    parser = _Paragraphs()
    parser.feed(body)
    return parser.found


def connect(path=DB) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False)
    # FTS5 is SQLite's full-text search; it ranks matches with BM25. Porter stemming makes "repenting" find "repentance".
    con.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
            title, text, speaker UNINDEXED, name UNINDEXED, source UNINDEXED, date UNINDEXED, url UNINDEXED, anchor UNINDEXED,
            tokenize='porter unicode61 remove_diacritics 2')"""
    )
    return con


def conference(slug: str, done: set[str]):
    page = get(f"{CHURCH}/study/general-conference/speakers/{slug}?lang=eng")
    for path in sorted(set(re.findall(r'href="/study/general-conference/(\d{4}/\d{2}/[^"?]+)"', page))):
        url = f"{CHURCH}/study/general-conference/{path}?lang=eng"
        if url in done:
            continue
        data = json.loads(get(f"{CHURCH}/study/api/v3/language-pages/type/content?lang=eng&uri=/general-conference/{path}"))
        title = data["meta"]["title"]
        if not SKIP_TITLES.search(title):
            yield "General Conference", title, path[:7].replace("/", "-"), url, paragraphs(data["content"]["body"])


def byu(slug: str, done: set[str]):
    page = get(f"{BYU}/speakers/{slug}/")
    for talk in sorted(set(re.findall(rf'href="{BYU}/talks/{slug}/([^/"?]+)/', page))):
        url = f"{BYU}/talks/{slug}/{talk}/"
        if url in done:
            continue
        hits = json.loads(get(f"{BYU}/wp-json/wp/v2/speech?slug={talk}&_fields=date,link,title,content"))
        hit = next((h for h in hits if h["link"] == url), None)
        if not hit:
            print(f"  ! no API record for {url}", file=sys.stderr)
            continue
        yield "BYU Speeches", html.unescape(hit["title"]["rendered"]), hit["date"][:10], url, paragraphs(hit["content"]["rendered"])


def main():
    slugs = sys.argv[1:] or list(SPEAKERS)
    if unknown := [s for s in slugs if s not in SPEAKERS]:
        sys.exit(f"Unknown speaker(s): {', '.join(unknown)}. Choose from: {', '.join(SPEAKERS)}")
    con = connect()
    done = {url for (url,) in con.execute("SELECT DISTINCT url FROM passages")}
    for slug in slugs:
        print(SPEAKERS[slug])
        for source in (conference, byu):
            try:
                for src, title, date, url, paras in source(slug, done):
                    con.executemany(
                        "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
                        [(title, text, slug, SPEAKERS[slug], src, date, url, anchor) for anchor, text in paras],
                    )
                    con.commit()
                    print(f"  {date}  {title}  ({len(paras)} paragraphs)")
            except Exception as e:  # network or page-layout error; rerunning resumes where it stopped
                print(f"  ! {source.__name__} stopped: {e}", file=sys.stderr)
        talks = con.execute("SELECT source, COUNT(DISTINCT url) FROM passages WHERE speaker = ? GROUP BY source", (slug,))
        print("  total:", ", ".join(f"{n} {src}" for src, n in talks) or "nothing")


if __name__ == "__main__":
    main()
