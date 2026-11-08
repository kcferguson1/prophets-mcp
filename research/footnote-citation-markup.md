# Footnote and citation markup across sources

Research for issue #6 (map #1). Question: can scripture citations be read reliably from talk pages, to support
"talks that cite this verse", and what else do footnotes carry?

**Short answer:** yes, and more reliably than expected, but not only from footnotes. On Church pages every
scripture citation is a link to `/study/scriptures/...` with the verse numbers in its `id` parameter. Older pages
put those links straight into the paragraph text; newer pages put them in footnotes. A parser that collects every
scripture link in the page body (paragraph or footnote) catches both. BYU speeches are the exception: from 2010 on
their footnotes exist but are missing from the WordPress API that `fetch.py` uses, and older speeches have inline
references, some linked and some plain text.

## Method and sources

All evidence is first-party: the Church Gospel Library content API and the BYU Speeches site, fetched with the
project's own rate-limited helpers (`fetch.api`, `fetch.get`, 0.3 s between requests), plus read-only queries on
`prophets.db`.

- **Sample:** 52 talks drawn at random from `passages`, stratified by source and decade (seeded, so repeatable).
  40 Church pages from `fetch.api("content", uri)["content"]["body"]`; 12 BYU speeches from
  `/wp-json/wp/v2/speech?slug=…` (`content.rendered`), plus the 12 public speech pages, once it turned out the
  notes live only there. One full API record (no `_fields`) was fetched to confirm the notes are not in another field.
- **Database-wide check:** a regex for "Book N:N" run over the stored paragraph text of all 1,974 talks, to estimate
  how parseable in-text references are. This needs no web requests. Stored text keeps the words of in-paragraph links
  but not footnotes (`fetch.py` drops `<li id="noteN">` and `<sup>`).
- **Note classification** (point 5) is a heuristic: a footnote "names a source" if it links to other Church content
  or contains `<em>`/`<cite>`, a year in parentheses, a name like "Russell M. Nelson", or words like *Ensign*,
  *Liahona*, *Hymns* or *devotional*. "Scripture-only" means nothing is left once the scripture links and words like
  "See", "see also" and "emphasis added" are removed. Counts are approximate, not hand-checked.

Counts in the tables come from the sample unless marked "DB-wide".

## 1. Church pages: one chain, two placements

The marker → footnote → link chain is identical wherever footnotes exist, from 1999 to 2026 and across conference,
magazines and broadcasts:

```html
<p id="p3">… <a class="note-ref" href="#note1"><sup class="marker" data-value="1"></sup></a></p>
…
<footer class="notes"> <p class="title" id="note_title1">Notes</p>
 <ol class="decimal" data-type="marker" start="1">
  <li data-marker="1." id="note1" data-full-marker="1.">
   <p data-aid="149808174" id="note1_p3"><a class="scripture-ref"
      href="/study/scriptures/nt/mark/12?lang=eng&amp;id=p41-p44#p41">Mark 12:41–44</a>.</p>
  </li>
```
(General Conference 2022-04, `/general-conference/2022/04/57uchtdorf`)

- **All 255 markers in the 20 footnoted pages resolve** to an `<li id="noteN">`, and every footnote is pointed to by
  exactly one marker. No bare `<sup>` without `class="marker"`, and no footnote with more than one `<p>`.
- Newer footnote paragraphs have random ids (`id="p_yySqc"`, 2025-10), so the note number must come from the `<li>`,
  not the `<p>` (this matches the existing comment in `fetch.py`).
- Footnote title id varies (`notetitle1` vs `note_title1`); harmless.

What differs is **where the scripture links sit**. Older pages, and many magazine pages, have no footnotes and put
the same `scripture-ref` link inside the paragraph:

```html
… (<a class="scripture-ref" href="/study/scriptures/dc-testament/dc/76?lang=eng&amp;id=p58-p59#p58">D&amp;C 76:58–59</a>.)</p>
```
(General Conference 1971-10, `/general-conference/1971/10/strive-for-excellence`)

| Group (sample) | Pages | With footnotes | Footnotes | Scripture links in footnotes | Scripture links in paragraphs | Scripture links per talk |
|---|---|---|---|---|---|---|
| General Conference 1971–1989 | 5 | 0 | 0 | 0 | 14 | 2.8 |
| General Conference 1990–2009 | 6 | 2 | 36 | 30 | 59 | 14.8 |
| General Conference 2010–2019 | 4 | 4 | 61 | 49 | 18 | 16.8 |
| General Conference 2020–2026 | 4 | 4 | 83 | 78 | 1 | 19.8 |
| Ensign (1972–2015) | 6 | 0 | 0 | 0 | 49 | 8.2 |
| New Era (1986–2013) | 4 | 2 | 3 | 0 | 35 | 8.8 |
| Liahona (2023–2026) | 4 | 4 | 23 | 1 | 43 | 11.0 |
| For the Strength of Youth (2021–2026) | 3 | 1 | 3 | 2 | 5 | 2.3 |
| Church broadcast (2014–2024) | 4 | 3 | 46 | 47 | 4 | 12.8 |
| **All Church pages** | **40** | **20 (50%)** | **255** | **207** | **228** | **10.9** |

- **The switch is per talk, not per year.** In 1990–2009, 1999-04 and 2007-04 use footnotes while 1992, 1996, 1998
  and 2006 use inline links. Since 2010 every conference talk sampled has footnotes.
- **Mixed pages exist.** GC 2013-10 (`no-other-gods`) has 12 footnotes, which cite mostly non-scripture sources, plus 18
  scripture links inline. **Liahona and New Era keep scriptures inline and use footnotes for other sources**
  (Liahona: 43 inline vs 1 in footnotes).
- **Low counts are mostly excerpt pages,** not missing markup: Ensign "conference notebook" and "latter-day counsel"
  pieces, and short pages (149–427 words), have 0–1 links.
- DB-wide, stored paragraph text (which holds the words of inline links) shows the same shift: "Book N:N" appears
  in 92% of 1980s Church talks, 60% in the 2000s and 45% in the 2020s, as citations move into footnotes.

## 2. How verses, ranges and chapters are encoded

The verse numbers are in the `id` query parameter. The `#fragment` is only the first verse, so it must not be used
alone. Of 435 Church scripture links:

| Shape | Example label → href | Count |
|---|---|---|
| Single verse | `Abr. 3:26` → `/study/scriptures/pgp/abr/3?lang=eng&id=p26#p26` | 294 (68%) |
| Range | `D&C 76:58–59` → `…/dc/76?lang=eng&id=p58-p59#p58` | 102 (23%) |
| List (comma is URL-encoded `%2C`) | `John 7:16, 28` → `…/john/7?lang=eng&id=p16%2Cp28#p16` | 14 |
| List with range | `D&C 18:10–13, 15` → `…/dc/18?lang=eng&id=p10-p13%2Cp15#p10` | 7 |
| Whole chapter (no `id`) | `John 1` → `/study/scriptures/nt/john/1?lang=eng` | 12 (3%) |
| Not a verse (Bible Dictionary, JST, proclamation) | `Baptism` → `/study/scriptures/bd/baptism?…`; `Joseph Smith Translation, Matthew 7:1–2` → `/study/scriptures/jst/jst-matt/7?…&id=p1-p2` | 6 (1%) |

- **The `p` prefix is sometimes missing after a comma:** `Job 42:10, 12–13` → `id=p10%2C12-p13`; `26, 28–29` →
  `id=p26%2C28-p29`. A parser should accept `p?\d+`.
- **No cross-chapter range** (like Alma 32:21–33:1) appeared in the sample; each link stays within one chapter.
- **Labels are not enough on their own:** 27 link labels have no chapter:verse (`verses 20–24`, `verse 1`,
  `26, 28–29`, `twelfth article of faith`, `John 1`). Where the label does have one, it matches the href in 447 of
  449 cases; the two exceptions are `Mark 13:11` → `id=p10-p11` and a JST link with no `id`. **Trust the href.**
- **Matching to `verses` needs no book table.** The `verses` table already stores each verse's `url`
  (`https://www.churchofjesuschrist.org/study/scriptures/ot/1-chr/1?lang=eng`) and `anchor` (`p1`). A link's path
  (`/scriptures/ot/1-chr/1`) plus its expanded id list matches rows directly. Links whose volume is not
  `ot`, `nt`, `bofm`, `dc-testament` or `pgp` (such as `bd` and `jst`) have no verse rows and should be skipped or stored apart.

## 3. References written in paragraph text

- **Church pages: essentially always links.** In the sample, the regex found unlinked "Book N:N" text in paragraphs
  only twice in 40 pages, and one of those was a false match ("Studies …"). Footnotes had 4 unlinked references
  (3× Matthew, 1× Ecclesiasticus, which is not in the standard works).
- DB-wide, 10,099 "Book N:N" references appear in stored Church paragraph text (mostly the words of inline links), and
  99% have a book name the simple parser below maps to a `verses` book. Misses are abbreviations that aren't
  prefixes of the full name (`1 Jn.` 13, `2 Kgs.` 6, `1 Kgs.` 5, `3 Jn.` 3) and `A of F 1:5` (32).
- Older talks use abbreviated labels (`Matt.` 251, `2 Ne.` 242, `3 Ne.` 172, `Moro.` 127, `Hel.` 44, `D&C` 1,884,
  DB-wide); newer ones spell names out. The href is the same either way.

## 4. BYU speeches

**Two formats, split around 2010, and the API hides the newer one's notes.**

From 2010 on (4 of 4 sampled), speeches have numbered footnotes, but `content.rendered` from the WordPress API holds
only bare markers: `…for my sake shall find it”<sup>2</sup> and then&nbsp;explained:` (2022-08). There is no notes
list, and the full API record has nothing else useful (`acf` is `[]`). The notes are in a hidden panel on the public
page `https://speeches.byu.edu/talks/<speaker>/<slug>/`:

```html
<sup><a class=individual-speech__footnote-ref data-note-index=1 href=#note-1 aria-label="See note 1">1</a></sup>
…
<div class=individual-speech__notes-body id=is-notes-body hidden><p id=note-1>1. <a href=https://catalog.byu.edu/…>Aims of a BYU Education</a> (1 March 1995).</p><p
id=note-2>2. <a href="https://www.churchofjesuschrist.org/study/scriptures/nt/matt/10.39?lang=eng" …>Matthew 10:39</a>; quoted in Marion G. Romney, “<a href="https://www.churchofjesuschrist.org/study/general-conference/1982/10/the-celestial-nature-of-self-reliance?lang=eng" …>The Celestial Nature of Self-Reliance</a>,” <i>Ensign,</i> November 1982.</p>
```
(`/talks/d-todd-christofferson/the-aims-of-a-byu-education/`)

- In all 4, API `<sup>` count = page markers = notes (27, 20, 22, 15; 84 notes total). The page markup is
  unquoted-attribute HTML (minified) and sometimes adds `class=p1` to the note `<p>`.
- **BYU scripture links use a different URL format,** chapter.verse in the path: `…/scriptures/nt/gal/6.7`,
  ranges `…/dc/84.43-45`, lists `…/dc/84.54,57`. Hosts and paths vary (`/study/scriptures/…` and older
  `/scriptures/…` without `/study`; some non-scripture notes still link to `lds.org`). In 118 checkable links, the
  label matched the href every time. 75 BYU scripture links: 52 single verse, 20 range, 3 list.
- 30 scripture links across the 84 notes. Some speeches cite few scriptures: Holland 2016 has 27 notes but only 4
  scripture links; most of its notes cite books and articles.

Before 2010 (8 sampled), speeches have no footnotes and no notes panel. References sit in the text in parentheses
or brackets:

| Style | Count of talks |
|---|---|
| Linked inline (`<a href="https://www.churchofjesuschrist.org/scriptures/bofm/alma/42.25">Alma 42:25</a>`) | 3 (1974, 1995, 2006; 45 links) |
| Plain text only | 3 (1979, 1986, 2000; 54 refs) |
| None (stubs of 36 and 163 words) | 2 (1985, 1992) |

Plain-text styles seen: `(see 1 Samuel 17:19)`, `[Abraham 3:22–25]` after a block quote, `(See Matthew 20:20–24.)`,
`(JSH 1:18)`, `[D&C 6:34, 78:17–18]`, `( HC 4:540)` (History of the Church, not scripture).

**Parseability (DB-wide, all 220 BYU speeches):** 2,199 "Book N:N" references in 149 speeches. A simple parser
maps 95% (2,086) to a `verses` book. The parser accepts exact book names, the aliases `D&C` and `JS—H`, or an
abbreviation that is the start of exactly one book name (`Hel.` → Helaman, `2 Ne.` → 2 Nephi). BYU text mostly spells
names out: `D&C` 540, and every other abbreviation is 2 or fewer (`Matt.`, `Ps.`, `Exod.`, `2 Ne.`…). What it misses:

- Not scripture, correctly rejected: `JD` 36 (Journal of Discourses), `HC` 31, `Writings` 19 (Mark Twain's
  collected *Writings*).
- Scripture it should catch with two more aliases: `Psalms` 10 (the table says `Psalm`), `JSH` 2.
- So, of the references that really are scripture, about 99% are parseable once `Psalms` and `JSH` are added.

Two gaps a simple parser won't close:

- **References with no book name of their own:** `(D&C 76:69; 107:19)` or `(see D&C 66:2, 132:6)`. There are
  about 120 BYU matches for a bookless `; N:N` or `, N:N` (about 5% of references; some are volume:page in book
  citations, like `1:156`). They need the previous reference's book carried forward.
- **"verse 14" style follow-ups** (68 BYU, 162 Church DB-wide) point to a chapter named earlier in the prose.
  They're not worth chasing for counts.

Note: plain-text BYU references undercount relative to Church links. They don't mark verse lists as precisely, and
they can be wrong in the source, such as `(Isaiah 53:24–25)` in the 1979 speech (Isaiah 53 has 12 verses). Validate
each reference against `verses` before storing it.

## 5. Footnotes that name a quoted source

| | Footnotes | Scripture only | Names a source (talk, book, person) | Other commentary |
|---|---|---|---|---|
| Church (20 pages) | 255 | 130 (51%) | 100 (39%) | 25 (10%) |
| BYU 2010+ (4 pages) | 84 | 24 (29%) | 50 (60%) | 10 (12%) |

Typical shapes:

```html
<!-- talk by another speaker, with a link to it -->
<p id="p_yH2Ec">James E. Faust, “<a class="cross-ref" href="/study/liahona/2007/05/salt-lake-tabernacle-rededication?lang=eng">Salt Lake Tabernacle Rededication</a>,” <cite>Liahona</cite>, May 2007, 39.</p>   (GC 2025-10)
<!-- quoted inside a manual -->
<p id="note6_p1">George A. Smith, in <em><a class="cross-ref" href="/study/manual/teachings-joseph-smith/chapter-19?lang=eng">Teachings of Presidents of the Church: Joseph Smith</a></em> (2007), 235.</p>   (GC 2018-04)
<!-- outside book -->
<p id="note1_p1">See John Reader, <cite>Africa: A Biography of the Continent</cite> (1999), 635–36, 673–79.</p>   (GC 2021-04)
```

- Pattern: **`Speaker Name, “Title,” <cite>/<em>Publication</em>, Month Year, page.`** Shortened repeats appear as
  `Romney, “Celestial Nature.”` (BYU) and need the earlier note to resolve.
- **Church footnotes link to other talks:** 51 `class="cross-ref"` links in 12 of the 20 footnoted pages (35 to
  `/study/general-conference/…`, 5 manual, 4 Ensign, 3 broadcasts, 2 Liahona). Those give talk-to-talk citations
  almost for free. BYU notes link to Church talks and BYU speeches the same way, without the class.
- Newer pages use `<cite>` (10 pages); older ones use `<em>` for titles.
- Footnotes are short (one `<p>` each), so showing the whole footnote beside a search hit is practical. The marker
  sits in a specific paragraph, so each footnote belongs to exactly one paragraph.

## 6. Surprises and risks for a citations table

1. **Don't harvest only footnotes.** Half the Church sample (and most pre-2010 and magazine pages) put the
   citations inline. Collect every `/scriptures/` link in the body, and record its paragraph: the containing `<p>`
   for inline links, or the `<p>` holding the `note-ref` for footnote links. Store which kind it was
   (`inline` or `footnote`) in case it matters later.
2. **BYU needs a second request per speech** (the public page) to get notes for 2010-on speeches, and that page's
   markup is undocumented theme HTML (`individual-speech__…` classes), more fragile than the Church API. About 91
   stored BYU speeches are from 2010 on.
3. **Three URL dialects for one verse:** Church `…/nt/matt/10?id=p39`, BYU `…/study/scriptures/nt/matt/10.39`, older
   BYU `…/scriptures/nt/matt/10.39` (no `/study`). Normalize to the `verses.url` path plus a verse list.
4. **`id` quirks:** URL-encoded commas (`%2C`), a missing `p` after commas, no `id` for whole chapters, and a
   `#fragment` that names only the first verse. Decide how a whole-chapter citation counts (all verses, or a
   chapter-level row).
5. **Non-verse scripture targets** (`bd`, `jst`, the 2020 proclamation under `/scriptures/`) don't exist in `verses`.
6. **Stored text already holds most pre-footnote citations** as plain words ("D&C 76:24"), because `fetch.py` keeps
   link text. Footnote citations, and every href, are lost until `fetch.py` keeps note HTML, so the planned
   re-download is required either way.
7. **Excerpt and stub pages** (Ensign "conference notebook", two BYU stubs of 36 and 163 words) have zero citations.
   Per-source counts will look low for reasons unrelated to markup.
8. **Source errors exist** (`Isaiah 53:24–25`). Check each citation against `verses` and drop or flag misses.

## Sample

Columns: footnotes (`<li id="noteN">`, or BYU `<p id=note-N>`), scripture links in footnotes, scripture links in
paragraphs, and unlinked "Book N:N" text in paragraphs. Church paths are under
`https://www.churchofjesuschrist.org/study`; BYU paths are under `https://speeches.byu.edu`.

| Source | Date | Path | Notes | Scr. links in notes | Scr. links in paragraphs | Plain refs in paragraphs |
|---|---|---|---|---|---|---|
| General Conference | 1971-10 | `/general-conference/1971/10/strive-for-excellence` | 0 | 0 | 6 | 0 |
| General Conference | 1976-04 | `/general-conference/1976/04/learn-obedience-and-service` | 0 | 0 | 0 | 0 |
| General Conference | 1976-10 | `/general-conference/1976/10/the-making-of-a-missionary` | 0 | 0 | 2 | 0 |
| General Conference | 1981-04 | `/general-conference/1981/04/providing-for-our-needs` | 0 | 0 | 3 | 0 |
| General Conference | 1980-04 | `/general-conference/1980/04/you-can-be-the-voice` | 0 | 0 | 3 | 0 |
| General Conference | 1992-10 | `/general-conference/1992/10/the-joy-of-hope-fulfilled` | 0 | 0 | 14 | 0 |
| General Conference | 1999-04 | `/general-conference/1999/04/the-hands-of-the-fathers` | 22 | 15 | 0 | 0 |
| General Conference | 1998-04 | `/general-conference/1998/04/that-we-may-be-one` | 0 | 0 | 14 | 0 |
| General Conference | 1996-10 | `/general-conference/1996/10/witnesses-for-god` | 0 | 0 | 4 | 0 |
| General Conference | 2007-04 | `/general-conference/2007/04/the-tongue-of-angels` | 14 | 15 | 0 | 0 |
| General Conference | 2006-04 | `/general-conference/2006/04/that-we-may-always-have-his-spirit-to-be-with-us` | 0 | 0 | 27 | 0 |
| General Conference | 2010-04 | `/general-conference/2010/04/we-follow-jesus-christ` | 21 | 20 | 0 | 0 |
| General Conference | 2015-04 | `/general-conference/2015/04/latter-day-saints-keep-on-trying` | 12 | 14 | 0 | 0 |
| General Conference | 2018-04 | `/general-conference/2018/04/precious-gifts-from-god` | 16 | 14 | 0 | 0 |
| General Conference | 2013-10 | `/general-conference/2013/10/no-other-gods` | 12 | 1 | 18 | 0 |
| General Conference | 2025-10 | `/general-conference/2025/10/32dennis` | 35 | 31 | 1 | 0 |
| General Conference | 2021-04 | `/general-conference/2021/04/25renlund` | 30 | 31 | 0 | 0 |
| General Conference | 2022-04 | `/general-conference/2022/04/57uchtdorf` | 14 | 13 | 0 | 0 |
| General Conference | 2023-04 | `/general-conference/2023/04/58nelson` | 4 | 3 | 0 | 0 |
| Ensign | 1972-04 | `/ensign/1972/04/the-five-as-of-stewardship` | 0 | 0 | 7 | 0 |
| Ensign | 1988-05 | `/ensign/1988/05/with-god-nothing-shall-be-impossible` | 0 | 0 | 39 | 0 |
| Ensign | 1995-07 | `/ensign/1995/07/anchored-by-faith-and-commitment` | 0 | 0 | 2 | 0 |
| Ensign | 2001-06 | `/ensign/2001/06/latter-day-counsel/safety-peace-joy-and-security-in-christ` | 0 | 0 | 0 | 0 |
| Ensign | 2015-02 | `/ensign/2015/02/october-2014-conference-notebook/follow-the-golden-rule` | 0 | 0 | 1 | 0 |
| Ensign | 2015-08 | `/ensign/2015/08/april-2015-conference-notebook/fast-offerings-change-hearts` | 0 | 0 | 0 | 0 |
| New Era | 1986-10 | `/new-era/1986/10/taking-time-to-care` | 0 | 0 | 3 | 0 |
| New Era | 1997-07 | `/new-era/1997/07/faith-in-every-footstep` | 0 | 0 | 0 | 1 |
| New Era | 2012-02 | `/new-era/2012/02/the-tender-mercies-of-the-lord` | 1 | 0 | 11 | 0 |
| New Era | 2013-10 | `/new-era/2013/10/missionary-preparation/becoming-a-preach-my-gospel-missionary` | 2 | 0 | 21 | 0 |
| Liahona | 2025-10 | `/liahona/2025/10/03-covenants-power-and-promises` | 12 | 0 | 7 | 0 |
| Liahona | 2025-06 | `/liahona/2025/06/03-we-follow-jesus-christ` | 5 | 0 | 22 | 0 |
| Liahona | 2026-03 | `/liahona/2026/03/04-righteous-stewards-disciples-of-jesus-christ` | 5 | 1 | 10 | 1 |
| Liahona | 2023-04 | `/liahona/2023/04/digital-only/trusting-in-the-lord-my-greatest-education` | 1 | 0 | 4 | 0 |
| For the Strength of Youth | 2022-03 | `/ftsoy/2022/03/10_god-can-help-us-in-hard-times` | 3 | 2 | 0 | 0 |
| For the Strength of Youth | 2021-06 | `/ftsoy/2021/06/02_sharing-the-gospel-worldwide` | 0 | 0 | 1 | 0 |
| For the Strength of Youth | 2026-04 | `/ftsoy/2026/04/how-can-i-draw-strength-from-the-saviors-love` | 0 | 0 | 4 | 0 |
| Church broadcast | 2014-01 | `/broadcasts/article/ces-devotionals/2014/01/saving-your-life` | 38 | 38 | 4 | 0 |
| Church broadcast | 2019-12 | `/broadcasts/christmas-devotional/2019/12/13soares` | 3 | 3 | 0 | 0 |
| Church broadcast | 2024-02 | `/broadcasts/worldwide-devotional-for-young-adults/2024/02/17soares` | 0 | 0 | 0 | 0 |
| Church broadcast | 2024-02 | `/broadcasts/language-recording/2024/02/15nelson` | 5 | 6 | 0 | 0 |
| BYU Speeches | 1974-06 | `/talks/jeffrey-r-holland/borne-upon-eagles-wings/` | 0 | 0 | 10 | 0 |
| BYU Speeches | 1979-02 | `/talks/jeffrey-r-holland/mirror-mirror-wall-look-me-decade/` | 0 | 0 | 0 | 6 |
| BYU Speeches | 1986-08 | `/talks/russell-m-nelson/ill-go-ill-ill-three-steps-toward-monumental-life/` | 0 | 0 | 0 | 45 |
| BYU Speeches | 1985-08 | `/talks/russell-m-nelson/truth-and-more/` | 0 | 0 | 0 | 0 |
| BYU Speeches | 1995-01 | `/talks/dallin-h-oaks/adversity/` | 0 | 0 | 26 | 0 |
| BYU Speeches | 1992-07 | `/talks/m-russell-ballard/religious-freedom-provo-1992-freedom-festival/` | 0 | 0 | 0 | 0 |
| BYU Speeches | 2006-09 | `/talks/henry-b-eyring/gifts-spirit-hard-times/` | 0 | 0 | 9 | 0 |
| BYU Speeches | 2000-01 | `/talks/m-russell-ballard/the-lord-has-a-work-for-you-to-do/` | 0 | 0 | 0 | 3 |
| BYU Speeches | 2016-08 | `/talks/jeffrey-r-holland/religion-bound-loving-ties/` | 27 | 4 | 0 | 0 |
| BYU Speeches | 2017-11 | `/talks/m-russell-ballard/questions-and-answers/` | 20 | 7 | 0 | 0 |
| BYU Speeches | 2026-09 | `/talks/neil-l-andersen/settle-this-in-your-hearts/` | 22 | 13 | 0 | 2 |
| BYU Speeches | 2022-08 | `/talks/d-todd-christofferson/the-aims-of-a-byu-education/` | 15 | 6 | 0 | 3 |

For BYU, "scripture links in paragraphs" and "plain refs in paragraphs" come from the API body; notes come from the
public page. For the 2010-on speeches, whether the few paragraph plain refs (2 and 3) duplicate a linked note was not
checked.
