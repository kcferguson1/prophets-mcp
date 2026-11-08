"""Self-check for the parser, author matching, search and update safety. Run: uv run test_prophets.py"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import zlib
from contextlib import closing

os.environ["PROPHETS_DB"] = os.path.join(tempfile.mkdtemp(), "prophets.db")  # never touch the real index or lock

import fetch  # noqa: E402
from fetch import CALLINGS, SPEAKERS, connect, credits, hold_lock, magazine_articles, page, paragraphs, recent, record, reprint, walk  # noqa: E402
import server  # noqa: E402
from server import list_sources, lookup_verses, recent_additions, search_passages, search_verses, talk_text  # noqa: E402

# The update lock: one holder at a time, and the operating system frees it when the holder exits, even on a crash.
first = hold_lock()
assert first is not None and hold_lock() is None
first.close()
holder = "import fetch, sys, time; lock = fetch.hold_lock(); print('locked' if lock else 'busy', flush=True); time.sleep(60)"
child = subprocess.Popen([sys.executable, "-c", holder], cwd=os.path.dirname(os.path.abspath(fetch.__file__)), env=os.environ, stdout=subprocess.PIPE, text=True)
assert child.stdout.readline().strip() == "locked"
assert hold_lock() is None, "another process's update must block this one"
child.kill()  # like a crash: no cleanup runs
child.wait()
again = hold_lock()
assert again is not None, "a crashed update must not leave the lock held"
again.close()

# Only "not found" means a page is gone; a server error stops the run so it's retried, instead of skipping the page forever.
def fake_api(error=None, data=None):
    def api(kind, uri):
        if error:
            raise urllib.error.HTTPError(uri, error, "test", None, None)
        return data
    return api

real_api = fetch.api
fetch.api = fake_api(404)
assert page("/gone") is None
assert list(walk("/magazines/x/2020", top=False)) == []  # a missing sub-listing is skipped
try:
    list(walk("/magazines/moved"))
    raise AssertionError("a missing top listing must stop the run")
except urllib.error.HTTPError:
    pass
fetch.api = fake_api(503)
try:
    page("/busy")
    raise AssertionError("a server error must stop the run")
except urllib.error.HTTPError:
    pass
fetch.api = fake_api(data={"meta": {}})
assert page("/odd") is None  # a page with no text is skipped
fetch.api = real_api
assert record("/liahona/2025/01/odd", "Liahona", {"meta": {}, "content": {"body": "<p>x</p>"}}) is None  # no title: skipped, no crash

# Pages from the last two months may still change, so they're checked again; older ones aren't.
assert recent(time.strftime("/broadcasts/x/%Y/%m/talk"))
assert not recent("/ensign/2005/06/peace-in-our-savior")
assert not recent("/broadcasts/x/undated")

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
# Newer bylines: "By:" with a colon, the name in a "dominant" span, the calling after it; three names read "A, B and C".
panel = {"meta": {"structuredData": "{}"}, "content": {"body": "".join(
    f'<p class="author-name">{by}<span class="dominant">President {n},</span> {c} General President</p>'
    for by, n, c in (("<i>By:</i> ", "Rosemary K. Chibota", "Primary"), ("", "Timothy L. Farnes", "Young Men"), ("", "Emily Belle Freeman", "Young Women")))}}
assert credits(panel) == (["emily-belle-freeman", "rosemary-k-chibota"], "Rosemary K. Chibota, Timothy L. Farnes and Emily Belle Freeman"), credits(panel)
# Off the roster, everyone credits the speaker under their leader link's slug, or one made from their name.
hathaway = {"meta": {"title": "Steady", "structuredData": json.dumps({"mainEntity": {"author": {"name": "Kevin J. Hathaway", "url": "/church/leader/kevin-j-hathaway"}}})},
            "content": {"body": '<p class="author-name">By Elder Kevin\xa0J. Hathaway</p><p class="author-role">Of the Seventy</p><p id="p1">' + "Steady faith grows. " * 40 + "</p>"}}
assert credits(hathaway) is None and credits(hathaway, everyone=True) == (["kevin-j-hathaway"], "Kevin J. Hathaway"), credits(hathaway, everyone=True)
assert credits(page({}, "By Elder José A. Teixeira"), everyone=True) == (["jose-a-teixeira"], "José A. Teixeira")

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
out = search_passages(con, 'repenting "joy" OR -', ["dallin-h-oaks"])
assert "Source: https://x/a?lang=eng&id=p_2#p_2" in out, out  # conference links jump to the paragraph
assert out.count("## ") == 2, out  # at most two passages per talk
assert "p_4" not in out, out  # short paragraphs are skipped
assert "Eyring" not in out, out  # speaker filter
assert "Source: https://y/b/\n" in search_passages(con, "joy", ["henry-b-eyring"])  # no anchor, plain link
assert "Nothing matched" in search_passages(con, "zzz", None)
assert "Nothing matched" in search_passages(con, "with you", None)  # filler words alone don't match "I am with you."
assert "we can choose" in search_passages(con, "we can", ["dallin-h-oaks"])  # all filler: searched as typed

# Filters. Several speakers at once; an unknown slug says so and lists the real ones instead of finding nothing.
two = search_passages(con, "repentance joy", ["henry-b-eyring", "dallin-h-oaks"])
assert "Henry B. Eyring" in two and "Dallin H. Oaks" in two, two
assert search_passages(con, "joy", ["dallin-h-oakes"]).startswith("Unknown speaker: dallin-h-oakes. Speakers: dallin-h-oaks, henry-b-eyring,")
# Sources, in any capitalization; an unknown one lists the seven.
byu_only = search_passages(con, "repentance joy", None, sources=["byu speeches"])
assert "BYU Speeches" in byu_only and "General Conference" not in byu_only, byu_only
assert search_passages(con, "joy", None, sources=["Conference"]) == (
    "Unknown source: Conference. Sources: General Conference, BYU Speeches, Church broadcast, Liahona, Ensign, New Era, For the Strength of Youth.")
# Date ranges are inclusive and work on both stored forms (Oaks: 2025-10, Eyring: 1990-01-01).
def speakers_found(**dates):
    found = search_passages(con, "repentance joy", ["dallin-h-oaks", "henry-b-eyring"], **dates)
    return {name for name in ("Oaks", "Eyring") if name in found}
assert speakers_found(from_date="2000") == {"Oaks"}
assert speakers_found(to_date="1990") == {"Eyring"}  # all of 1990, though Eyring's date has a day
assert speakers_found(from_date="1990-01", to_date="1990-01") == {"Eyring"}
assert speakers_found(from_date="2025-10", to_date="2025") == {"Oaks"}
assert speakers_found(from_date="1990-01-01", to_date="2025-10") == {"Oaks", "Eyring"}
assert search_passages(con, "joy", None, from_date="spring 2020") == 'Dates look like 2015, 2015-04 or 2015-04-12, not "spring 2020".'
assert speakers_found(from_date="2025-10-01", to_date="2025-10-31") == {"Oaks"}  # a day-precise range still finds a month-only date
for bad in ("2015-13", "2015-02-31"):
    assert search_passages(con, "joy", None, to_date=bad) == f'Dates look like 2015, 2015-04 or 2015-04-12, not "{bad}".', bad
assert search_passages(con, "joy", None, from_date="2021", to_date="2020") == "from_date 2021 is after to_date 2020."

# A passage names its paragraph (counting the short paragraphs search hides) and its talk ID.
home = "https://www.churchofjesuschrist.org/study/general-conference/2026/04/15gilbert?lang=eng"
for n, text in enumerate(["Brothers and sisters, welcome.", "The prodigal son came to himself in a far country and arose.",
                          "Come home, ye who are weary, for the Father runs to meet every returning child."], 1):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Come Home", text, "clark-g-gilbert", "Clark G. Gilbert", "General Conference", "2026-04", home, f"p{n}"))
passage = search_passages(con, "weary returning child", ["clark-g-gilbert"])
assert passage.startswith('## 1. Clark G. Gilbert, "Come Home" ¶3\nGeneral Conference, 2026-04\nTalk ID: general-conference/2026/04/15gilbert\nSource: '), passage
# Quoted phrases match the same words in the same order, ignoring capitals, punctuation and quote or apostrophe style.
con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("His Hand", "We have seen the Lord’s hand in the lives of His children, day after day.", "patrick-kearon", "Patrick Kearon", "General Conference", "2024-10", "https://www.churchofjesuschrist.org/study/general-conference/2024/10/hand?lang=eng", "p1"))
weary = search_passages(con, '"ye who are weary"', None)
assert "¶3" in weary, weary
assert "¶3" in search_passages(con, "“Ye who are WEARY,”", None)  # curly quotes, capitals, punctuation
assert "His Hand" in search_passages(con, '"the Lord\'s hand"', None)  # straight apostrophe finds a curly one
assert "Nothing matched" in search_passages(con, '"return child"', None)  # stemming would match "returning child"; exact doesn't
assert "Nothing matched" in search_passages(con, '"ye who were weary"', None)
con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Ward", "On Sunday we met Brother José and Sister María at the chapel doors.", "patrick-kearon", "Patrick Kearon", "Liahona", "2024-05", "https://www.churchofjesuschrist.org/study/liahona/2024/05/ward?lang=eng", "p1"))
assert "Ward" in search_passages(con, '"brother jose and sister maria"', None)  # accents don't count either
# Near matches by word stem ("faith servant" for "faithful servant") can't crowd a real exact match out of the results.
con.executemany("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", [("Near", "A faith servant serves.", "dallin-h-oaks", "Dallin H. Oaks", "Ensign", "2001-01", f"https://www.churchofjesuschrist.org/study/ensign/2001/01/near-{n}?lang=eng", "p1") for n in range(300)])
con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Steward", "Well done, thou good and faithful servant: thou hast been faithful over a few things, and the Lord will make thee ruler over many.", "dallin-h-oaks", "Dallin H. Oaks", "Ensign", "2002-02", "https://www.churchofjesuschrist.org/study/ensign/2002/02/steward?lang=eng", "p1"))
assert "Steward" in search_passages(con, '"faithful servant"', None, limit=1)
mixed = search_passages(con, '"ye who are weary" prodigal', None)  # words outside the quotes don't let other paragraphs in
assert "¶3" in mixed and "prodigal son" not in mixed, mixed

# get_talk: a header, then every paragraph numbered in reading order.
assert talk_text(con, "general-conference/2026/04/15gilbert") == """# "Come Home"
Clark G. Gilbert · General Conference, 2026-04
Source: https://www.churchofjesuschrist.org/study/general-conference/2026/04/15gilbert?lang=eng
Talk ID: general-conference/2026/04/15gilbert · 3 paragraphs
¶ numbers count this talk's own paragraphs, not the website's.

¶1 Brothers and sisters, welcome.
¶2 The prodigal son came to himself in a far country and arose.
¶3 Come home, ye who are weary, for the Father runs to meet every returning child.""", talk_text(con, "general-conference/2026/04/15gilbert")
assert talk_text(con, home + "&id=p3#p3") == talk_text(con, "general-conference/2026/04/15gilbert")  # a link from a passage works too
assert talk_text(con, "general-conference/2026/04/15gilbert?lang=eng#p3") == talk_text(con, "general-conference/2026/04/15gilbert")  # an ID with a link's tail
assert "No talk with the ID general-conference/1999/04/nobody" in talk_text(con, "general-conference/1999/04/nobody")
part = talk_text(con, "general-conference/2026/04/15gilbert", start=2, end=3)
assert "Talk ID: general-conference/2026/04/15gilbert · 3 paragraphs, showing ¶2–¶3\n" in part and part.endswith(
    "\n\n¶2 The prodigal son came to himself in a far country and arose.\n¶3 Come home, ye who are weary, for the Father runs to meet every returning child."), part
assert talk_text(con, "general-conference/2026/04/15gilbert", start=3, end=99).endswith("\n\n¶3 Come home, ye who are weary, for the Father runs to meet every returning child.")  # end past the last: up to the last
# A long talk comes in parts of about 5,000 words, split between paragraphs, each saying where to go on.
for n in range(1, 5):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Long Speech", f"part{n} " + "word " * 1999, "clark-g-gilbert", "Clark G. Gilbert", "BYU Speeches", "2024-01-09", "https://speeches.byu.edu/talks/clark-g-gilbert/long-speech/", None))
long = talk_text(con, "byu/clark-g-gilbert/long-speech")
assert "Talk ID: byu/clark-g-gilbert/long-speech · 4 paragraphs, showing ¶1–¶2\n" in long and "¶2 part2 " in long and "part3" not in long, long[:400]
assert long.endswith("\n\nContinued: call get_talk again with start=3."), long[-200:]
rest = talk_text(con, "https://speeches.byu.edu/talks/clark-g-gilbert/long-speech/#p3", start=3)  # a BYU link with an anchor
assert "showing ¶3–¶4\n" in rest and rest.rstrip().endswith("word") and "Continued" not in rest, rest[-200:]
assert talk_text(con, "byu/clark-g-gilbert/long-speech", start=1, end=4).endswith("start=3, end=4.")  # reading on keeps the asked-for end
# A one-speaker server reads only that speaker's talks.
assert talk_text(con, "general-conference/2026/04/15gilbert", speaker="henry-b-eyring") == "general-conference/2026/04/15gilbert isn't one of Henry B. Eyring's talks. Use a Talk ID from this server's search or list_talks."
assert talk_text(con, "general-conference/2026/04/15gilbert", speaker="clark-g-gilbert") == talk_text(con, "general-conference/2026/04/15gilbert")
for start, end in ((4, None), (3, 2), (0, 2)):
    assert talk_text(con, "general-conference/2026/04/15gilbert", start=start, end=end) == "This talk has 3 paragraphs: ask for ¶1 to ¶3.", (start, end)

# A joint talk stored under two of our speakers shows each paragraph once, with everyone's names.
both = "Camille N. Johnson and J. Anette Dennis"
for slug in ("camille-n-johnson", "j-anette-dennis"):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Joint", "Ministering together brings the healing power of the Savior to many.", slug, both, "Church broadcast", "2025-02", "https://z/j?lang=eng", "p1"))
joint_out = search_passages(con, "ministering healing", None)
assert joint_out.count("Ministering together") == 1 and both in joint_out, joint_out
assert both in search_passages(con, "ministering healing", ["j-anette-dennis"])

# A reprint under a new title shows its shared paragraph once; a reprint's source note isn't a passage at all.
for url in ("https://b/holier/", "https://e/holier?lang=eng"):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Holier", "Even in declaring His own divinity, Jesus ministered to the one.", "neil-l-andersen", "Neil L. Andersen", "Ensign", "2019-06", url, None))
assert search_passages(con, "ministered divinity", ["neil-l-andersen"]).count("Even in declaring") == 1
assert paragraphs('<p>CES Devotional for Young Adults • May 4, 2014 • San Diego, California</p>') == []
assert paragraphs('<p>From a devotional address, “A Holier Approach to Ministering,” delivered at Brigham Young University on April 10, 2018.</p>'
                  '<p>From the First Vision, we learn that because of the grace of our Savior we too can be forgiven.</p>') == [
    (None, "From the First Vision, we learn that because of the grace of our Savior we too can be forgiven.")]

# From EVERYONE_FROM on, a conference's table of contents is read for every speaker, once more under its own key even when
# it was read for the roster alone; before then, a speaker off the roster is still skipped.
tocs = {
    "/general-conference/2026/10": {"content": {"body": '<a href="/study/general-conference/2026/10/16hathaway"><p class="primaryMeta">Kevin J. Hathaway</p></a>'
                                                        '<a href="/study/general-conference/2026/10/12oaks"><p class="primaryMeta">Dallin H. Oaks</p></a>'}},
    "/general-conference/2026/10/16hathaway": hathaway,
    "/general-conference/2020/10": {"content": {"body": '<a href="/study/general-conference/2020/10/15someone"><p class="primaryMeta">Some One</p></a>'}},
}
real_page = fetch.page
fetch.page = tocs.get
found = list(fetch.conference_tocs({"/general-conference/2026/10", "/general-conference/2026/10/12oaks"}))
fetch.page = real_page
assert [uri for uri, _ in found] == ["/general-conference/2020/10", "/general-conference/2026/10/16hathaway", "/general-conference/2026/10?everyone"], found
assert found[1][1][:5] == (["kevin-j-hathaway"], "Kevin J. Hathaway", "General Conference", "Steady", "2026-10"), found[1][1][:5]

# A magazine's reprint of a conference talk is skipped; a broadcast with the same title, or a much later article, is not.
assert reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Church broadcast", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2027-01")
assert set(CALLINGS) == set(SPEAKERS), set(CALLINGS) ^ set(SPEAKERS)  # every speaker shows a calling

# whats_new: a saved talk shows once (even when joint), an old addition drops out of the window, and the speaker filter holds.
fetch.save(con, "camille-n-johnson", "Liahona", "New Light", "2026-11", "https://www.churchofjesuschrist.org/study/liahona/2026/11/new-light?lang=eng", fetch.Reading([("p1", "x")]), both)
fetch.save(con, "j-anette-dennis", "Liahona", "New Light", "2026-11", "https://www.churchofjesuschrist.org/study/liahona/2026/11/new-light?lang=eng", fetch.Reading([("p1", "x")]), both)
fetch.save(con, "dallin-h-oaks", "BYU Speeches", "Old News", "2020-01-01", "https://o/n/", fetch.Reading([(None, "x")]))
fetch.save(con, "dallin-h-oaks", "BYU Speeches", "Video Only", "2026-11-01", "https://v/o/", fetch.Reading([]))  # no transcript: not saved
con.execute("UPDATE added SET at = datetime('now', '-60 days') WHERE title = 'Old News'")
new = recent_additions(con, None, 30)
assert new.count("New Light") == 1 and "Old News" not in new and "Video Only" not in new and "1 added" in new, new
assert ": New Light · Talk ID: liahona/2026/11/new-light · https://" in new, new  # every listed talk shows its ID
assert "- Clark G. Gilbert, 2026-04, General Conference: Come Home · Talk ID: general-conference/2026/04/15gilbert · https://" in list_sources(con, "clark-g-gilbert")
# list_talks across speakers: a conference by date and source, in the order its talks were given (their link numbers).
conf = "https://www.churchofjesuschrist.org/study/general-conference/2026/10/"
for n, slug, title in ((510, "dallin-h-oaks", "Closing Remarks"), (12, "henry-b-eyring", "Fear Not"), (51, "gerrit-w-gong", "Holy House")):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", (title, "x", slug, SPEAKERS[slug], "General Conference", "2026-10", f"{conf}{n}x?lang=eng", "p1"))
october = list_sources(con, None, ["general conference"], "2026-10", "2026-10")  # 510 is session 5, talk 10: after 51
assert [line.split(": ", 1)[1].split(" · ")[0] for line in october.split("\n")] == ["Fear Not", "Holy House", "Closing Remarks"], october
assert list_sources(con, "henry-b-eyring", None, "2026-10", "2026-10").count("\n") == 0  # one speaker, one talk
assert list_sources(con, None, None, "2031") == "No talks match those filters."
assert list_sources(con, None, None, "fall 2026") == 'Dates look like 2015, 2015-04 or 2015-04-12, not "fall 2026".'
assert list_sources(con, "nobody", None).startswith("Unknown speaker: nobody. Speakers: dallin-h-oaks,")
server.MAX_LISTED = 2
assert list_sources(con, None, None, "2026-10", "2026-10").endswith("\nShowing the newest 2 of 3 talks. Narrow with from_date/to_date or sources to see the rest.")
server.MAX_LISTED = 250
# A General Conference speaker off the roster: found by slug, named by their own talks, listed after the roster.
con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Steady", "Steady faith grows when we keep our covenants through every season of life.", "kevin-j-hathaway", "Kevin J. Hathaway", "General Conference", "2026-10", f"{conf}16hathaway?lang=eng", "p1"))
assert "Steady faith grows" in search_passages(con, "steady faith covenants", ["kevin-j-hathaway"])
assert list_sources(con, "kevin-j-hathaway").startswith("- Kevin J. Hathaway, 2026-10, General Conference: Steady")
roster_and_others = server.speaker_list(con)
assert roster_and_others.startswith("Leaders whose talks are all collected:\n- Dallin H. Oaks, President of the Church (slug: dallin-h-oaks): "), roster_and_others[:200]
assert roster_and_others.endswith("\n\nOther General Conference speakers since April 2021 (their conference talks only):\n- Kevin J. Hathaway (slug: kevin-j-hathaway): 1 talk"), roster_and_others[-300:]
# Leaders who have died are marked wherever a name shows, so living voices can come first; a joint talk marks only them.
nelson = "https://www.churchofjesuschrist.org/study/general-conference/2024/10/57nelson?lang=eng"
con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Joy", "Joy is a gift for the faithful who strive to live righteously and follow the Savior.", "russell-m-nelson", "Russell M. Nelson and Wendy W. Nelson", "General Conference", "2024-10", nelson, "p1"))
assert '## 1. Russell M. Nelson (died 2025) and Wendy W. Nelson, "Joy" ¶1\n' in search_passages(con, "joy faithful strive", ["russell-m-nelson"])
assert "\nRussell M. Nelson (died 2025) and Wendy W. Nelson · General Conference, 2024-10\n" in talk_text(con, nelson)
assert "- Russell M. Nelson (died 2025) and Wendy W. Nelson, 2024-10" in list_sources(con, "russell-m-nelson")
assert "(died" not in list_sources(con, "henry-b-eyring")
assert "Old News" in recent_additions(con, "dallin-h-oaks", 90)
assert "Nothing added" in recent_additions(con, "henry-b-eyring", 30)
assert "No full update has finished yet." in new  # the test index has never finished a full run

# Scriptures: verses only (no chapter heading or "The End"), numbers from the id, titles with non-breaking spaces cleaned.
chapter = {"meta": {"title": "1\xa0Nephi 3"}, "content": {"body":
    '<p id="study_summary1">Nephi and his brethren return.</p><p class="verse" id="p1">1 And it came to pass.</p>'
    '<p class="verse" id="p7">7 I will go and do the things which the Lord hath commanded.</p><p id="p8">Nephi.</p><p id="closing1">The End</p>'}}
fetch.api = lambda kind, uri: {"toc": {"entries": ["/scriptures/bofm/1-ne/3"]}} if kind == "dynamic" else chapter
url = "https://www.churchofjesuschrist.org/study/scriptures/bofm/1-ne/3?lang=eng"
assert list(fetch.scriptures(set())) == [("/scriptures/bofm/1-ne/3", [
    ("1 Nephi 3:1", "And it came to pass.", "Book of Mormon", "1 Nephi", 3, 1, url, "p1"),
    ("1 Nephi 3:7", "I will go and do the things which the Lord hath commanded.", "Book of Mormon", "1 Nephi", 3, 7, url, "p7")])]
assert list(fetch.scriptures({"/scriptures/bofm/1-ne/3"})) == []  # a saved chapter isn't fetched again
declaration = {"meta": {"title": "Official Declaration 2"}, "content": {"body": '<p id="p1">To Whom It May Concern:</p><p id="p2">We have watched.</p>'}}
fetch.api = lambda kind, uri: {"toc": ["/scriptures/dc-testament/od/2"]} if kind == "dynamic" else declaration
assert [row[0] for _, rows in fetch.scriptures(set()) for row in rows] == ["Official Declaration 2:1", "Official Declaration 2:2"]  # nothing numbered: all kept
fetch.api = real_api

con.execute(f"PRAGMA user_version = {fetch.VERSION}")  # citations built (none cite these verses)
assert "haven't been downloaded" in lookup_verses(con, "Moroni 10:4") and "haven't been downloaded" in search_verses(con, "faith", None)
for ref, text, volume, book, ch, v in [
    ("Moroni 10:3", "Behold, I would exhort you.", "Book of Mormon", "Moroni", 10, 3),
    ("Moroni 10:4", "Ask God with a sincere heart, with real intent, having faith in Christ.", "Book of Mormon", "Moroni", 10, 4),
    ("Moroni 10:5", "By the power of the Holy Ghost ye may know the truth of all things.", "Book of Mormon", "Moroni", 10, 5),
    ("Doctrine and Covenants 121:7", "My son, peace be unto thy soul.", "Doctrine and Covenants", "Doctrine and Covenants", 121, 7),
    ("Psalm 23:1", "The Lord is my shepherd; I shall not want.", "Old Testament", "Psalm", 23, 1),
]:
    con.execute("INSERT INTO verses VALUES (?,?,?,?,?,?,?,?)", (ref, text, volume, book, ch, v, f"https://s/{book}/{ch}?lang=eng", f"p{v}"))
four_five = lookup_verses(con, "moroni 10:4-5")
assert four_five.startswith("## Moroni 10:4-5\nSource: https://s/Moroni/10?lang=eng&id=p4#p4") and "Behold" not in four_five and "5 By the power" in four_five, four_five
whole = lookup_verses(con, "Moroni 10")  # no verse: the whole chapter
assert whole.startswith("## Moroni 10:3-5\n") and all(f"\n{v} " in whole for v in (3, 4, 5)), whole
assert "peace be unto thy soul" in lookup_verses(con, "D&C 121:7")
assert "my shepherd" in lookup_verses(con, "Psalms 23:1")
assert "No book called" in lookup_verses(con, "Hezekiah 1:1")
assert "has no verse 9" in lookup_verses(con, "Moroni 10:9")
assert "Give a reference" in lookup_verses(con, "Moroni")
# Context: verses around the request, within the chapter; the heading names only what was asked, and the asked verses are bold.
assert lookup_verses(con, "Moroni 10:4", context=1) == """## Moroni 10:4 (with 1 verse of context)
Source: https://s/Moroni/10?lang=eng&id=p4#p4

3 Behold, I would exhort you.
**4** Ask God with a sincere heart, with real intent, having faith in Christ.
5 By the power of the Holy Ghost ye may know the truth of all things.

No talks cite these verses.""", lookup_verses(con, "Moroni 10:4", context=1)
edge = lookup_verses(con, "Moroni 10:4-5", context=3)  # the chapter's stored verses run out after 5: no error, nothing invented
assert edge.startswith("## Moroni 10:4-5 (with 3 verses of context)\n") and edge.endswith("\n3 Behold, I would exhort you.\n**4** Ask God with a sincere heart, with real intent, having faith in Christ.\n**5** By the power of the Holy Ghost ye may know the truth of all things.\n\nNo talks cite these verses."), edge
assert "has no verse 9" in lookup_verses(con, "Moroni 10:9", context=10)  # neighbours exist, the asked verse doesn't
assert lookup_verses(con, "Moroni 10", context=2) == lookup_verses(con, "Moroni 10")  # a whole chapter has nothing around it
assert lookup_verses(con, "Moroni 10:4-5", context=-1) == lookup_verses(con, "Moroni 10:4-5")  # negative context means none
assert "## Moroni 10:4\n" in search_verses(con, "sincere intent", None)
assert "No verse matched" in search_verses(con, "sincere intent", "ot")  # volume filter, by short name
assert "Psalm 23:1" in search_verses(con, "shepherd", "Old Testament")

# Footnotes land on the ¶ whose marker points to them; one marked in a caption has no ¶ and is dropped. Scripture links
# are kept with their ¶, and with the footnote number when they sit in a footnote.
church = (
    '<p class="author-name">By Elder X</p><p id="p1">Ask in faith.<a class="note-ref" href="#note1"><sup class="marker" data-value="1"></sup></a></p>'
    '<p id="p2">Read <a class="scripture-ref" href="/study/scriptures/dc-testament/dc/76?lang=eng&amp;id=p58-p59#p58">D&amp;C 76:58–59</a> often.<a class="note-ref" href="#note2"><sup class="marker"></sup></a></p>'
    '<p id="figure1_p1">A photo.<a class="note-ref" href="#note3"><sup class="marker"></sup></a></p>'
    '<footer class="notes"><p class="title" id="note_title1">Notes</p><ol>'
    '<li id="note1"><p id="p_yySqc">See <a class="scripture-ref" href="/study/scriptures/bofm/moro/10?lang=eng&amp;id=p4%2C5#p4">Moroni 10:4, 5</a>.</p></li>'
    '<li id="note2"><p id="note2_p1">James E. Faust, “Salt Lake Tabernacle Rededication,” <cite>Liahona</cite>, May 2007, 39.</p></li>'
    '<li id="note3"><p id="note3_p1">Photo by someone.</p></li></ol></footer>'
)
talk = fetch.read_talk(church)
assert talk.paras == [("p1", "Ask in faith."), ("p2", "Read D&C 76:58–59 often.")], talk.paras
assert talk.notes == [(1, 1, "See Moroni 10:4, 5."), (2, 2, "James E. Faust, “Salt Lake Tabernacle Rededication,” Liahona, May 2007, 39.")], talk.notes
assert talk.links == [(2, None, "/study/scriptures/dc-testament/dc/76?lang=eng&id=p58-p59#p58"), (1, 1, "/study/scriptures/bofm/moro/10?lang=eng&id=p4%2C5#p4")], talk.links
assert paragraphs(church) == talk.paras
# A marker's link names its footnote; the number it shows can differ ("#note4" showing 2) and doesn't count.
shown_other = fetch.read_talk('<p id="p1">Saints.<a class="note-ref" href="#note4"><sup class="marker">2</sup></a></p><p id="p2">Later.<a class="note-ref" href="#note2"><sup class="marker">3</sup></a></p>'
                              '<ol><li id="note2"><p id="x">Second.</p></li><li id="note4"><p id="y">Fourth.</p></li></ol>')
assert shown_other.notes == [(1, 4, "Fourth."), (2, 2, "Second.")], shown_other.notes
# Older pages put a footnote's paragraphs loose (note1_p1, note1_p2): one footnote, links from both.
loose = fetch.read_talk('<p id="p1">Pray.<a href="#note1"><sup>1</sup></a></p><p id="note1_p1">See <a href="/study/scriptures/bofm/moro/10?lang=eng&amp;id=p4#p4">Moroni 10:4</a>.</p><p id="note1_p2">Also a comment.</p>')
assert loose.notes == [(1, 1, "See Moroni 10:4. Also a comment.")] and loose.links == [(1, 1, "/study/scriptures/bofm/moro/10?lang=eng&id=p4#p4")], loose
# BYU: the API text has bare numbered markers; the notes come from the public page's hidden panel, numbers and all.
byu_text = "<p>Whosoever will lose his life for my sake shall find it”<sup>2</sup> and then explained.</p>"
panel = '<p id=note-1>1. Aims.</p><p id=note-2 class=p1>2. <a href="https://www.churchofjesuschrist.org/study/scriptures/nt/matt/10.39?lang=eng">Matthew 10:39</a>; quoted in Marion G. Romney.</p>'
real_get = fetch.get
fetch.get = lambda url: f"<div class=individual-speech__notes-body id=is-notes-body hidden>{panel}</div><footer>x</footer>"
spoken = fetch.byu_talk("https://speeches.byu.edu/talks/x/y/", byu_text)
assert spoken.paras == [(None, "Whosoever will lose his life for my sake shall find it” and then explained.")], spoken.paras
assert spoken.notes == [(1, 2, "Matthew 10:39; quoted in Marion G. Romney.")], spoken.notes
assert spoken.links == [(1, 2, "https://www.churchofjesuschrist.org/study/scriptures/nt/matt/10.39?lang=eng")], spoken.links
# A note BYU left without its id is still a footnote (numbered from its text), never a paragraph of the speech.
idless = fetch.read_talk("<p>Walk in all the commandments of God blameless.<sup>32</sup></p>",
                         '<div id=is-notes-body hidden><p class=p2>32<a href="https://www.churchofjesuschrist.org/study/scriptures/dc-testament/dc/88.133?lang=eng">. Doctrine and Covenants 88:133</a>.</p></div>')
assert idless.paras == [(None, "Walk in all the commandments of God blameless.")] and idless.notes == [(1, 32, "Doctrine and Covenants 88:133.")] and len(idless.links) == 1, idless
fetch.get = lambda url: "<html>a new layout</html>"
assert fetch.byu_talk("https://speeches.byu.edu/talks/x/y/", byu_text).notes == []  # no panel: saved without footnotes
def busy(url):
    raise urllib.error.HTTPError(url, 503, "test", None, None)
fetch.get = busy  # a failed request: the text is saved now, the footnotes on the next update
unfinished = fetch.byu_talk("https://speeches.byu.edu/talks/x/y/", byu_text)
assert unfinished.paras == spoken.paras and unfinished.notes == [] and not unfinished.complete, unfinished
assert fetch.byu_talk("https://speeches.byu.edu/talks/x/y/", byu_text.replace("<sup>2</sup>", "")).complete
assert fetch.byu_talk("https://speeches.byu.edu/talks/x/old/", "<p>No markers here.</p>").paras  # no markers: no request
fetch.get = real_get

# Links: verses are in the id (Church) or after a dot (BYU); no verses is a whole chapter; other targets aren't verses.
G = "https://www.churchofjesuschrist.org/study/scriptures"
assert fetch.cited("/study/scriptures/pgp/abr/3?lang=eng&id=p26#p26") == (f"{G}/pgp/abr/3?lang=eng", [26])
assert fetch.cited("/study/scriptures/nt/john/7?lang=eng&id=p16%2Cp28#p16")[1] == [16, 28]
assert fetch.cited("/study/scriptures/dc-testament/dc/18?lang=eng&id=p10-p13%2Cp15#p10")[1] == [10, 11, 12, 13, 15]
assert fetch.cited("/study/scriptures/ot/job/42?lang=eng&id=p10%2C12-p13#p10")[1] == [10, 12, 13]  # the p can be missing
assert fetch.cited("/study/scriptures/nt/john/1?lang=eng") == (f"{G}/nt/john/1?lang=eng", [])
assert fetch.cited("https://www.churchofjesuschrist.org/scriptures/dc-testament/dc/84.43-45")[1] == [43, 44, 45]
assert fetch.cited("https://www.churchofjesuschrist.org/study/scriptures/dc-testament/dc/84.54,57?lang=eng") == (f"{G}/dc-testament/dc/84?lang=eng", [54, 57])
assert fetch.cited("/study/scriptures/bd/baptism?lang=eng") is None and fetch.cited("/study/scriptures/jst/jst-matt/7?lang=eng&id=p1-p2") is None

# Citations are checked against the verses: a verse or chapter that isn't there is dropped.
cc = connect(":memory:")
chapter_links = {}
for book, vol, ch, verses in [("Moroni", "bofm/moro", 10, (3, 4, 5)), ("Doctrine and Covenants", "dc-testament/dc", 76, (58, 59)),
                              ("Doctrine and Covenants", "dc-testament/dc", 107, (19,)), ("Doctrine and Covenants", "dc-testament/dc", 6, (34,)),
                              ("Doctrine and Covenants", "dc-testament/dc", 78, (17, 18)), ("Isaiah", "ot/isa", 53, (5,)), ("Helaman", "bofm/hel", 5, (12,))]:
    chapter_links[book, ch] = f"{G}/{vol}/{ch}?lang=eng"
    cc.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?,?)", [(f"{book} {ch}:{v}", "x", "", book, ch, v, chapter_links[book, ch], f"p{v}") for v in verses])
moro, dc = chapter_links["Moroni", 10], lambda ch: chapter_links["Doctrine and Covenants", ch]
assert fetch.citations(cc, "General Conference", talk) == [(2, dc(76), 58, None), (2, dc(76), 59, None), (1, moro, 4, 1), (1, moro, 5, 1)]
odd = fetch.Reading([], links=[(1, None, "/study/scriptures/bofm/moro/10?lang=eng"), (1, None, "/study/scriptures/dc-testament/dc/77?lang=eng"),
                              (1, None, "/study/scriptures/bofm/moro/10?lang=eng&id=p9#p9"), (1, None, "/study/scriptures/bofm/moro/10?lang=eng")])
assert fetch.citations(cc, "Liahona", odd) == [(1, moro, None, None)]  # a whole chapter, once; D&C 77 and Moroni 10:9 aren't stored
# BYU speeches with no links: references typed in parentheses or brackets, the book carried to a part without one.
typed = fetch.Reading([(None, "We are told (see D&C 76:58; 107:19) and [D&C 6:34, 78:17–18]."),
                       (None, "Behold (Isaiah 53:5, 24–25) and (Hel. 5:12), but not (JD 1:156; 2:3) or (HC 4:540).")])
assert fetch.citations(cc, "BYU Speeches", typed) == [
    (1, dc(76), 58, None), (1, dc(107), 19, None), (1, dc(6), 34, None), (1, dc(78), 17, None), (1, dc(78), 18, None),
    (2, chapter_links["Isaiah", 53], 5, None), (2, chapter_links["Helaman", 5], 12, None)], fetch.citations(cc, "BYU Speeches", typed)
assert fetch.citations(cc, "Ensign", typed) == []  # Church pages link their references
# Saving keeps footnotes, citations and the compressed page; a joint talk's second speaker doesn't double them.
for slug in ("dallin-h-oaks", "henry-b-eyring"):
    fetch.save(cc, slug, "General Conference", "Ask", "2025-04", "https://x/ask?lang=eng", talk, "Dallin H. Oaks and Henry B. Eyring")
assert cc.execute("SELECT url, para, number, text FROM footnotes").fetchall() == [("https://x/ask?lang=eng", *n) for n in talk.notes]
assert cc.execute("SELECT para, chapter, verse, footnote FROM citations").fetchall() == fetch.citations(cc, "General Conference", talk)
assert zlib.decompress(cc.execute("SELECT html FROM pages WHERE url = 'https://x/ask?lang=eng'").fetchone()[0]).decode() == church

# The one-time re-read: fresh paragraphs for every speaker on a talk, whats_new untouched, a removed page's text kept,
# and a failed request left for next time; the version is set only when every talk is done.
up = connect(":memory:")
up.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?,?)", cc.execute("SELECT * FROM verses"))
uchtdorf = "https://www.churchofjesuschrist.org/study/general-conference/2022/04/57x?lang=eng"
gone = "https://www.churchofjesuschrist.org/study/ensign/1990/01/gone?lang=eng"
speech_url = "https://speeches.byu.edu/talks/x/y/"
for row in [("Ask", "Old reading of the talk.", "dallin-h-oaks", "Both", "General Conference", "2022-04", uchtdorf, "p1"),
            ("Ask", "Old reading of the talk.", "henry-b-eyring", "Both", "General Conference", "2022-04", uchtdorf, "p1"),
            ("Gone", "Text we still have.", "dallin-h-oaks", "Dallin H. Oaks", "Ensign", "1990-01", gone, "p1"),
            ("Y", "Old BYU text.", "dallin-h-oaks", "Dallin H. Oaks", "BYU Speeches", "2015-01-01", speech_url, None)]:
    up.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", row)
up.execute("INSERT INTO added (url, speaker, name, source, date, title) VALUES (?, 'dallin-h-oaks', 'Both', 'General Conference', '2022-04', 'Ask')", (uchtdorf,))
def site_api(kind, uri):
    if uri == "/general-conference/2022/04/57x":
        return {"meta": {}, "content": {"body": church}}
    raise urllib.error.HTTPError(uri, 404, "test", None, None)
def site_get(url):
    if "wp-json" in url:
        return json.dumps([{"link": speech_url, "date": "2015-01-01", "title": {"rendered": "Y"}, "content": {"rendered": byu_text}}])
    return notes_page(url)
fetch.api, fetch.get, notes_page = site_api, site_get, busy
assert fetch.reread(up) is False  # the BYU notes request failed: its text is saved, the talk left for next time
assert up.execute("PRAGMA user_version").fetchone()[0] == 0
assert up.execute("SELECT speaker, text, anchor FROM passages WHERE url = ? ORDER BY rowid", (uchtdorf,)).fetchall() == [
    (s, t, a) for s in ("dallin-h-oaks", "henry-b-eyring") for a, t in talk.paras]
assert up.execute("SELECT para, number FROM footnotes WHERE url = ?", (uchtdorf,)).fetchall() == [(1, 1), (2, 2)]
assert up.execute("SELECT text FROM passages WHERE url = ?", (gone,)).fetchall() == [("Text we still have.",)]
assert up.execute("SELECT text FROM passages WHERE url = ?", (speech_url,)).fetchall() == [(spoken.paras[0][1],)]
assert up.execute("SELECT COUNT(*) FROM added").fetchone()[0] == 1  # re-saved talks aren't new
assert "Citation data is still being built: 2 of 3 talks done." in recent_additions(up, None)
notes_page = lambda url: f"<div id=is-notes-body hidden>{panel}</div>"
assert fetch.reread(up) is True and up.execute("PRAGMA user_version").fetchone()[0] == fetch.VERSION
assert up.execute("SELECT number, text FROM footnotes WHERE url = ?", (speech_url,)).fetchall() == [(2, "Matthew 10:39; quoted in Marion G. Romney.")]
assert "Citation data" not in recent_additions(up, None)
fetch.api, fetch.get = real_api, real_get

# A database upgraded before the footnote columns were renamed from "note" gets them renamed, rows and all.
old_db = os.path.join(tempfile.mkdtemp(), "old.db")
with closing(sqlite3.connect(old_db)) as db:
    db.execute("CREATE TABLE footnotes (url TEXT, para INTEGER, note INTEGER, text TEXT)")
    db.execute("CREATE TABLE citations (url TEXT, para INTEGER, chapter TEXT, verse INTEGER, note INTEGER)")
    db.execute("INSERT INTO footnotes VALUES ('u', 1, 3, 'See Moroni 10:4.')")
    db.commit()
renamed = connect(old_db)
assert renamed.execute("SELECT number, text FROM footnotes").fetchall() == [(3, "See Moroni 10:4.")]
assert [c[1] for c in renamed.execute("PRAGMA table_info(citations)")] == ["url", "para", "chapter", "verse", "footnote"]
renamed.close()
assert [c[1] for c in connect(old_db).execute("PRAGMA table_info(footnotes)")] == ["url", "para", "number", "text"]  # once only

# Citation counts in get_verses: asked-for verses only, zeros left out, a whole chapter's own count, a pointer to cites.
intent = "https://www.churchofjesuschrist.org/study/general-conference/2023/10/intent?lang=eng"
up.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Real Intent", "Ask God with real intent and the Holy Ghost will manifest the truth of it unto you.",
                                                          "dallin-h-oaks", "Dallin H. Oaks", "General Conference", "2023-10", intent, "p1"))
up.execute("INSERT INTO citations VALUES (?, 1, ?, 4, 3)", (intent, moro))
long_note = "See Moroni 10:4. " + "word " * 68  # 70 words
up.execute("INSERT INTO footnotes VALUES (?, 1, 3, ?)", (intent, long_note.strip()))
up.execute("INSERT INTO reread VALUES (?)", (intent,))
pointer = 'To read the citing passages, call search with cites="Moroni 10:4-5" (query can be empty).'
assert lookup_verses(up, "Moroni 10:4-5").endswith("\n\nTalks citing each verse: 4 — 2 · 5 — 1\n" + pointer), lookup_verses(up, "Moroni 10:4-5")
assert "\n\nTalks by Henry B. Eyring citing each verse: 4 — 1 · 5 — 1\n" in lookup_verses(up, "Moroni 10:4-5", speaker="henry-b-eyring")
assert lookup_verses(up, "Moroni 10:3").endswith("\n\nNo talks cite these verses.")
assert lookup_verses(up, "Moroni 10:4", speaker="gerrit-w-gong").endswith("\n\nNo talks by Gerrit W. Gong cite these verses.")
up.execute("INSERT INTO citations VALUES (?, 1, ?, NULL, NULL)", (gone, moro))  # a whole-chapter citation
assert lookup_verses(up, "Moroni 10").endswith(
    "\n\nTalks citing each verse: 4 — 2 · 5 — 1\nMoroni 10 is also cited as a whole chapter by 1 talk.\n"
    'To read the citing passages, call search with cites="Moroni 10" (query can be empty).'), lookup_verses(up, "Moroni 10")
assert "whole chapter" not in lookup_verses(up, "Moroni 10:4-5")  # verse lookups never show chapter citations

# The cites filter: the citing paragraph, a Cites line saying where, newest first with no words, a total first.
four = search_passages(up, "", None, cites="Moroni 10:4")
assert four.startswith("2 talks cite Moroni 10:4; showing 2 passages, newest first.\n\n## 1. Dallin H. Oaks, \"Real Intent\" ¶1\n"), four
assert "\nCites: Moroni 10:4 (footnote 3)\n\nAsk God with real intent" in four, four
assert "## 2. Both, \"Ask\" ¶1\n" in four and "\nCites: Moroni 10:4 (footnote 1)\n\nAsk in faith." in four and four.count("Ask in faith.") == 1, four  # a joint talk once
# Footnotes under each passage, numbered the talk's way; a long one is cut at 60 words and points to get_talk.
assert "\n\nFootnotes:\n1. See Moroni 10:4, 5." in four, four
assert "\n\nFootnotes:\n3. See Moroni 10:4. " + "word " * 56 + "word … (rest in get_talk, ¶1)" in four, four
assert "Cites: Moroni 10:4-5 (footnote 1)" in search_passages(up, "", None, cites="Moroni 10:4-5")  # a range, as a range
chapter_hits = search_passages(up, "", None, cites="Moroni 10")
assert chapter_hits.startswith("3 talks cite Moroni 10;") and "Cites: Moroni 10 (whole chapter)\n\nText we still have." in chapter_hits, chapter_hits
assert search_passages(up, "real intent", None, cites="Moroni 10").startswith("1 talk cites Moroni 10; showing 1 passage, best matches first.\n")
assert search_passages(up, "", None, cites="Moroni 10:4", limit=1).startswith(
    "2 talks cite Moroni 10:4; showing 1 passage, newest first. Narrow with from_date/to_date, speakers or sources to see the rest.\n")
assert "Narrow with from_date/to_date or sources to see" in search_passages(up, "", ["dallin-h-oaks"], cites="Moroni 10:4", limit=1)
assert search_passages(up, "", None, cites="Moroni 10:4", from_date="2024") == "2 talks cite Moroni 10:4, but none match the other filters."
assert search_passages(up, "", ["gerrit-w-gong"], cites="Moroni 10:4") == "No talks by Gerrit W. Gong cite Moroni 10:4."
up.execute("INSERT INTO passages VALUES ('Steady', 'x', 'kevin-j-hathaway', 'Kevin J. Hathaway', 'General Conference', '2026-10', 'https://h/s', 'p1')")
assert search_passages(up, "", ["kevin-j-hathaway"], cites="Moroni 10:4") == "No talks by Kevin J. Hathaway cite Moroni 10:4."
up.execute("DELETE FROM passages WHERE speaker = 'kevin-j-hathaway'")
assert search_passages(up, "", None, cites="Moroni 10:3") == "No talks cite Moroni 10:3."
assert search_passages(up, "", None, cites="Hezekiah 1:1") == 'No book called "Hezekiah" in the standard works.'
assert search_passages(up, "", None, cites="Moroni 10:9") == "Moroni 10 has no verse 9."
assert search_passages(up, "", None) == "Give a few words to search for."
# While the re-read runs, counts give way to progress and cites says some talks may be missing.
up.execute("PRAGMA user_version = 0")
assert lookup_verses(up, "Moroni 10:4").endswith("\n\nCitation data is still being built: 4 of 4 talks done.")
assert search_passages(up, "", None, cites="Moroni 10:4").startswith("Citation data is still being built: 4 of 4 talks done, so some citing talks may be missing.\n2 talks cite")
up.execute(f"PRAGMA user_version = {fetch.VERSION}")
# get_talk: footnotes whole, indented under their paragraph.
assert talk_text(up, "general-conference/2022/04/57x").endswith(
    "\n\n¶1 Ask in faith.\n    1. See Moroni 10:4, 5.\n¶2 Read D&C 76:58–59 often.\n    2. James E. Faust, “Salt Lake Tabernacle Rededication,” Liahona, May 2007, 39."), talk_text(up, "general-conference/2022/04/57x")
assert talk_text(up, intent).endswith("\n    3. " + long_note.strip())

# An update starts when no full check has finished or the last is over a week old, and never while one is running.
started = []
real_popen = server.subprocess.Popen
server.subprocess.Popen = lambda *a, **k: started.append(a)
def set_version(n):
    with closing(sqlite3.connect(fetch.DB)) as db:
        db.execute(f"PRAGMA user_version = {n}")
try:
    set_version(fetch.VERSION)
    fetch.CHECKED.unlink(missing_ok=True)
    server.update_if_stale()
    assert len(started) == 1, "no full check yet: update"
    fetch.CHECKED.touch()
    server.update_if_stale()
    assert len(started) == 1, "checked just now: wait"
    eight_days_ago = time.time() - 8 * 86400
    os.utime(fetch.CHECKED, (eight_days_ago, eight_days_ago))
    server.update_if_stale()
    assert len(started) == 2, "over a week old: update"
    running = hold_lock()
    server.update_if_stale()
    assert len(started) == 2, "an update is running: leave it alone"
    running.close()
    fetch.CHECKED.touch()
    set_version(0)
    server.update_if_stale()
    assert len(started) == 3, "talks still need their one-time re-read: update now, not in a week"
finally:
    server.subprocess.Popen = real_popen

# Real saved pages, on a machine that has them (GitHub doesn't): re-reading each with today's reader gives the paragraphs
# stored for it, so ¶ numbers and the footnotes and citations keyed to them still line up, and its footnote markers resolve.
saved = os.path.join(os.path.dirname(os.path.abspath(fetch.__file__)), "prophets.db")
if os.path.exists(saved):
    with closing(sqlite3.connect(f"file:{saved}?mode=ro", uri=True, timeout=10)) as db:  # read-only: an update may be writing
        stored: dict[str, list[str]] = {}
        for url, speaker, text in db.execute("SELECT url, speaker, text FROM passages WHERE url IN (SELECT url FROM reread) ORDER BY rowid"):
            if speaker == stored.setdefault(url, [speaker])[0]:  # a joint talk's copies match; compare the first
                stored[url].append(text)
        pages = db.execute("SELECT url, html FROM pages WHERE url IN (SELECT url FROM reread)").fetchall()
    problems, missing = [], []
    for url, blob in pages:
        reader = fetch._Paragraphs()
        reader.feed(zlib.decompress(blob).decode())
        if [t for _, t, _, _ in reader.found] != stored[url][1:]:
            problems.append(f"{url}: re-reading its saved page gives other paragraphs")
        unresolved = {m for *_, markers, _ in reader.found for m in markers} - set(reader.notes)
        if reader.notes and unresolved:  # usually a typo on the page (BYU sometimes drops a note), so a warning
            missing.append(f"{url}: {sorted(unresolved)}")
    assert not problems, f"{len(problems)} saved pages read wrong:\n" + "\n".join(problems)
    print(f"  checked {len(pages)} saved pages" + (f"; {len(missing)} have markers with no footnote:\n    " + "\n    ".join(missing) if missing else ""))
print("ok")
