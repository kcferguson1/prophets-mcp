"""Self-check for the parser, author matching, search and update safety. Run: uv run test_prophets.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error

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

# A passage names its paragraph (counting the short paragraphs search hides) and its talk ID.
home = "https://www.churchofjesuschrist.org/study/general-conference/2026/04/15gilbert?lang=eng"
for n, text in enumerate(["Brothers and sisters, welcome.", "The prodigal son came to himself in a far country and arose.",
                          "Come home, ye who are weary, for the Father runs to meet every returning child."], 1):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Come Home", text, "clark-g-gilbert", "Clark G. Gilbert", "General Conference", "2026-04", home, f"p{n}"))
passage = search_passages(con, "weary returning child", "clark-g-gilbert")
assert passage.startswith('## 1. Clark G. Gilbert, "Come Home" ¶3\nGeneral Conference, 2026-04\nTalk ID: general-conference/2026/04/15gilbert\nSource: '), passage

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
assert both in search_passages(con, "ministering healing", "j-anette-dennis")

# A reprint under a new title shows its shared paragraph once; a reprint's source note isn't a passage at all.
for url in ("https://b/holier/", "https://e/holier?lang=eng"):
    con.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?)", ("Holier", "Even in declaring His own divinity, Jesus ministered to the one.", "neil-l-andersen", "Neil L. Andersen", "Ensign", "2019-06", url, None))
assert search_passages(con, "ministered divinity", "neil-l-andersen").count("Even in declaring") == 1
assert paragraphs('<p>CES Devotional for Young Adults • May 4, 2014 • San Diego, California</p>') == []
assert paragraphs('<p>From a devotional address, “A Holier Approach to Ministering,” delivered at Brigham Young University on April 10, 2018.</p>'
                  '<p>From the First Vision, we learn that because of the grace of our Savior we too can be forgiven.</p>') == [
    (None, "From the First Vision, we learn that because of the grace of our Savior we too can be forgiven.")]

# A magazine's reprint of a conference talk is skipped; a broadcast with the same title, or a much later article, is not.
assert reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Church broadcast", "Talk A", "2025-11")
assert not reprint(con, "dallin-h-oaks", "Liahona", "Talk A", "2027-01")
assert set(CALLINGS) == set(SPEAKERS), set(CALLINGS) ^ set(SPEAKERS)  # every speaker shows a calling

# whats_new: a saved talk shows once (even when joint), an old addition drops out of the window, and the speaker filter holds.
fetch.save(con, "camille-n-johnson", "Liahona", "New Light", "2026-11", "https://www.churchofjesuschrist.org/study/liahona/2026/11/new-light?lang=eng", [("p1", "x")], both)
fetch.save(con, "j-anette-dennis", "Liahona", "New Light", "2026-11", "https://www.churchofjesuschrist.org/study/liahona/2026/11/new-light?lang=eng", [("p1", "x")], both)
fetch.save(con, "dallin-h-oaks", "BYU Speeches", "Old News", "2020-01-01", "https://o/n/", [(None, "x")])
fetch.save(con, "dallin-h-oaks", "BYU Speeches", "Video Only", "2026-11-01", "https://v/o/", [])  # no transcript: not saved
con.execute("UPDATE added SET at = datetime('now', '-60 days') WHERE title = 'Old News'")
new = recent_additions(con, None, 30)
assert new.count("New Light") == 1 and "Old News" not in new and "Video Only" not in new and "1 added" in new, new
assert ": New Light · Talk ID: liahona/2026/11/new-light · https://" in new, new  # every listed talk shows its ID
assert "- Clark G. Gilbert, 2026-04, General Conference: Come Home · Talk ID: general-conference/2026/04/15gilbert · https://" in list_sources(con, "clark-g-gilbert")
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
assert "## Moroni 10:4\n" in search_verses(con, "sincere intent", None)
assert "No verse matched" in search_verses(con, "sincere intent", "ot")  # volume filter, by short name
assert "Psalm 23:1" in search_verses(con, "shepherd", "Old Testament")

# An update starts when no full check has finished or the last is over a week old, and never while one is running.
started = []
real_popen = server.subprocess.Popen
server.subprocess.Popen = lambda *a, **k: started.append(a)
try:
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
finally:
    server.subprocess.Popen = real_popen
print("ok")
