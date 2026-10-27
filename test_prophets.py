"""Self-check for the parser and search. Run: uv run test_prophets.py"""
from fetch import connect, paragraphs
from server import search_passages

body = '<p class="author-name" id="a">By President X</p><p id="p_1">Faith in Jesus<sup class="marker">1</sup> Christ &amp; hope.</p><p id="p_2"> </p>'
assert paragraphs(body) == [("p_1", "Faith in Jesus Christ & hope.")], paragraphs(body)

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
print("ok")
