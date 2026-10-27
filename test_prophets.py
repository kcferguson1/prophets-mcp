"""Self-check for the parser, author matching and search. Run: uv run test_prophets.py"""
import json

from fetch import CALLINGS, SPEAKERS, connect, credits, magazine_articles, paragraphs, reprint
from server import search_passages

body = '<p class="author-name" id="a">By President X</p><p id="p_1">Faith in Jesus<sup class="marker">1</sup> Christ &amp; hope.</p><p id="p_2"> </p><p id="note_title1">Notes</p><p id="note1_p1">See Mosiah 3:19.</p><p id="figure1_p1">Photo caption</p>'
assert paragraphs(body) == [("p_1", "Faith in Jesus Christ & hope.")], paragraphs(body)

# Credits: the byline decides when there is one (non-breaking spaces and all); otherwise the page data's leader link.
page = lambda sd, byline: {"meta": {"structuredData": json.dumps(sd)}, "content": {"body": f'<p class="author-name">{byline}</p>'}}
assert credits(page({"mainEntity": {"author": {"url": "/church/leader/camille-n-johnson"}}}, "")) == (["camille-n-johnson"], "Camille N. Johnson")
assert credits(page({}, "By President Emily\xa0Belle Freeman")) == (["emily-belle-freeman"], "Emily Belle Freeman")
assert credits(page({"mainEntity": {"author": {"url": "/church/leader/someone-else"}}}, "By Sister Someone")) is None
# The page data named President Eyring, but the byline shows two other writers: not ours.
assert credits(page({"mainEntity": {"author": {"url": "/church/leader/henry-b-eyring"}}}, "John Hilton III and Anthony Sweat")) is None
# Joint talks go to each of our speakers on them, shown with everyone's names.
joint = "By President Camille N. Johnson, Sister J. Anette Dennis, and Sister Kristin M. Yee"
assert credits(page({"mainEntity": {"author": {"url": "/church/leader/camille-n-johnson"}}}, joint)) == (
    ["camille-n-johnson", "j-anette-dennis", "kristin-m-yee"], "Camille N. Johnson, J. Anette Dennis, and Kristin M. Yee")
assert credits(page({}, "President Russell M. Nelson and Sister Wendy W. Nelson")) == (["russell-m-nelson"], "Russell M. Nelson and Wendy W. Nelson")
twice = {"meta": {"structuredData": "{}"}, "content": {"body": '<p class="author-name">By Elder Neil L. Andersen</p><p class="author-name">By Elder Neil L. Andersen</p>'}}
assert credits(twice) == (["neil-l-andersen"], "Neil L. Andersen")  # a repeated byline is still one speaker

# Footnote paragraphs inside <li id="noteN"> are skipped even with random paragraph ids.
assert paragraphs('<p id="p_a">Our covenant relationship grants access to His power.</p><ol><li id="note5"><p id="p_ef19Q">See Joshua 3:5.</p></li></ol>') == [("p_a", "Our covenant relationship grants access to His power.")]

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
        ("Talk A", "Repentance brings a deep and lasting joy to every one of us.", *oaks, "p_1"),
        ("Talk A", "Joy comes to all of us through sincere and daily repentance.", *oaks, "p_2"),
        ("Talk A", "Repentance is a daily joy we can choose again and again.", *oaks, "p_3"),
        ("Talk A", "Repentance brings joy.", *oaks, "p_4"),  # too short to be a useful passage
        ("Talk C", "I am with you.", *oaks[:4], "https://x/c?lang=eng", "p_1"),
        ("Talk B", "Repentance and joy belong together in the life of a disciple.", "henry-b-eyring", "Henry B. Eyring", "BYU Speeches", "1990-01-01", "https://y/b/", None),
    ],
)
out = search_passages(con, 'repenting "joy" OR -', "dallin-h-oaks")
assert "Source: https://x/a?lang=eng&id=p_2#p_2" in out, out  # conference links jump to the paragraph
assert out.count("## ") == 2, out  # at most two passages per talk
assert "p_4" not in out, out  # short paragraphs are skipped
assert "Eyring" not in out, out  # speaker filter
assert "Source: https://y/b/\n" in search_passages(con, "joy", "henry-b-eyring")  # no anchor, plain link
assert "Nothing matched" in search_passages(con, "zzz", None)
assert "Nothing matched" in search_passages(con, "with you", None)  # filler words alone don't match "I am with you."
assert "we can choose" in search_passages(con, "we can", "dallin-h-oaks")  # all filler: searched as typed

# A joint talk stored under two of our speakers shows each paragraph once, with everyone's names.
both = "Camille N. Johnson and J. Anette Dennis"
for slug in ("camille-n-johnson", "j-anette-dennis"):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Joint", "Ministering together brings the healing power of the Savior to many.", slug, both, "Church broadcast", "2025-02", "https://z/j?lang=eng", "p1"))
joint_out = search_passages(con, "ministering healing", None)
assert joint_out.count("Ministering together") == 1 and both in joint_out, joint_out
assert both in search_passages(con, "ministering healing", "j-anette-dennis")

# A magazine's reprint of a conference talk is skipped; a broadcast with the same title, or a much later article, is not.
assert reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Church broadcast", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2027-01")
assert set(CALLINGS) == set(SPEAKERS), set(CALLINGS) ^ set(SPEAKERS)  # every speaker shows a calling
print("ok")
