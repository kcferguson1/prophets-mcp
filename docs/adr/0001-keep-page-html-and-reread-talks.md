# Keep each talk's page HTML and re-read talks when the reader changes

Footnotes and scripture citations live in page HTML that `fetch.py` used to throw away, so adding them meant downloading every talk again. We decided that this one-time re-download replaces each talk's stored paragraphs with a fresh reading (so footnote markers line up with paragraph numbers, even though a few older talks' ¶ numbers shift once), and that the database keeps each page's HTML, compressed (about 11 MB for Church pages; for BYU only the API text and the footnotes section). Future parsing changes, such as talk-to-talk citations, can then re-read saved pages instead of downloading about 2,000 talks for an hour again.

## Considered Options

- **Match footnotes to the stored paragraphs by text, without replacing them:** keeps ¶ numbers fixed, but paragraphs saved by older versions of the reader don't always match a fresh reading, so some footnotes would land on the wrong paragraph or none.
- **Don't keep the HTML:** saves about 11 MB, but every new idea that needs something from the page costs another full re-download.

## Consequences

- An upgraded database is marked with SQLite's `user_version` (2); an older version triggers the one-time re-download at the next daily check, resumable talk by talk.
- A ¶ number quoted before the upgrade may point one or two paragraphs off afterwards for some older talks; talk IDs never change.
