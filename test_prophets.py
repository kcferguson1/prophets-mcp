"""Self-check for the parser, author matching and search. Run: uv run test_prophets.py"""
import json

from fetch import author, connect, magazine_articles, paragraphs, reprint
from server import search_passages

body = '<p class="author-name" id="a">By President X</p><p id="p_1">Faith in Jesus<sup class="marker">1</sup> Christ &amp; hope.</p><p id="p_2"> </p><p id="note_title1">Notes</p><p id="note1_p1">See Mosiah 3:19.</p><p id="figure1_p1">Photo caption</p>'
assert paragraphs(body) == [("p_1", "Faith in Jesus Christ & hope.")], paragraphs(body)

# Author: the structured-data leader link wins; otherwise the byline, with its non-breaking spaces.
page = lambda sd, byline: {"meta": {"structuredData": json.dumps(sd)}, "content": {"body": f'<p class="author-name">{byline}</p>'}}
assert author(page({"mainEntity": {"author": {"url": "/church/leader/camille-n-johnson"}}}, "")) == "camille-n-johnson"
assert author(page({}, "By President Emily\xa0Belle Freeman")) == "emily-belle-freeman"
assert author(page({"mainEntity": {"author": {"url": "/church/leader/someone-else"}}}, "By Sister Someone")) is None

toc = (
    '<li data-content-type="article"><a href="/study/ftsoy/2024/12/12-the-christ-child"><p class="primaryMeta">President Emily Belle Freeman</p></a></li>'
    '<li><a class="list-tile" href="/study/liahona/2025/01/05-all-are-needed"><p class="primaryMeta">Covenant Women</p></a></li>'
    '<li data-content-type="general-conference-talk"><a href="/study/liahona/2025/05/14johnson"><p class="primaryMeta">Camille N. Johnson</p></a></li>'
    '<li><a href="/study/ensign/2015/05/saturday-morning-session/x"><p class="primaryMeta">Dallin H. Oaks</p></a></li>'
    '<li><a href="/study/ftsoy/2024/04/09-healing"><p class="primaryMeta">Youth Voices</p></a></li>'
)
assert list(magazine_articles(toc)) == ["/ftsoy/2024/12/12-the-christ-child", "/liahona/2025/01/05-all-are-needed"], list(magazine_articles(toc))

con = connect(":memory:")
oaks = ("dallin-h-oaks", "Dallin H. Oaks", "General Conference", "2025-10", "https://x/a?lang=eng")
con.executemany(
    "INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)",
    [
        ("Talk A", "Repentance brings joy.", *oaks, "p_1"),
        ("Talk A", "Joy comes through repentance.", *oaks, "p_2"),
        ("Talk A", "Repentance is a daily joy.", *oaks, "p_3"),
        ("Talk B", "Repentance and joy.", "henry-b-eyring", "Henry B. Eyring", "BYU Speeches", "1990-01-01", "https://y/b/", None),
    ],
)
out = search_passages(con, 'repenting "joy" OR -', "dallin-h-oaks")
assert "Source: https://x/a?lang=eng&id=p_1#p_1" in out, out
assert out.count("## ") == 2, out  # at most two passages per talk
assert "Eyring" not in out, out  # speaker filter
assert "Source: https://y/b/\n" in search_passages(con, "joy", "henry-b-eyring")  # no anchor, plain link
assert "Nothing matched" in search_passages(con, "zzz", None)

# A magazine's reprint of a conference talk is skipped; a broadcast with the same title, or a much later article, is not.
assert reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Church broadcast", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2027-01")
print("ok")
