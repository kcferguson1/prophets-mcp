<div align="center">

# The Prophets

**Prophets, apostles and the women who lead The Church of Jesus Christ of Latter-day Saints, in an MCP.**

The First Presidency, the Quorum of the Twelve, and the Relief Society, Young Women and Primary general presidencies, each turned into a searchable MCP server built from their General Conference talks and BYU speeches.<br>
Add one to Claude, Cursor or Codex. Every answer cites its source.

[Use it](#use-it-in-a-few-minutes) · [Women leaders](#women-leaders) · [Prophets and apostles](#prophets-and-apostles) · [How it works](#how-it-works) · [Content](#content)

[![License: MIT](https://img.shields.io/badge/license-MIT-1f6feb.svg)](LICENSE)
[![Speakers](https://img.shields.io/badge/speakers-27-202020.svg)](#women-leaders)
[![Talks](https://img.shields.io/badge/talks-1%2C098-202020.svg)](#prophets-and-apostles)
[![MCP](https://img.shields.io/badge/MCP-stdio-4a4a4a.svg)](https://modelcontextprotocol.io)

</div>

---

## Use it in a few minutes

You need [uv](https://docs.astral.sh/uv/), the Python package manager.

```bash
git clone https://github.com/kcferguson1/prophets-mcp.git
cd prophets-mcp
uv sync
uv run fetch.py      # downloads every talk into prophets.db (about 20 minutes; rerun any time, it skips what's saved)
```

Then add a server from inside the folder. Leave out `--speaker` to get every speaker in one server.

```bash
# Claude Code: everyone
claude mcp add --scope user prophets -- uv run --directory "$PWD" server.py

# Claude Code: one speaker
claude mcp add johnson -- uv run --directory "$PWD" server.py --speaker camille-n-johnson
```

```bash
# Codex
codex mcp add prophets -- uv run --directory "$PWD" server.py
```

In **Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`) and **Cursor** (`~/.cursor/mcp.json`), add it with the folder's full path:

```json
{
  "mcpServers": {
    "prophets": {
      "command": "uv",
      "args": ["run", "--directory", "/full/path/to/prophets-mcp", "server.py"]
    }
  }
}
```

Then just ask: *"What has Sister Camille N. Johnson taught about finding relief in Jesus Christ?"*, *"What has President Nelson taught about the gathering of Israel?"* or *"How does Sister Emily Belle Freeman describe a covenant relationship with Christ?"*

**ChatGPT** only connects to MCP servers at a public HTTPS address. `uv run server.py --http` serves the same tools over streamable HTTP at `/mcp` on `$PORT`, but there's no public server yet.

### Staying up to date

New talks arrive on their own. When a server starts and the last full check is more than 30 days old, it runs `fetch.py` in the background and keeps answering while it works. Only one update runs at a time, even with several servers open. Progress goes to `prophets-update.log`.

To update right away, run `uv run fetch.py`. When the roster changes, run `git pull` to get the new speaker list.

### Tools

| Server | Tool | What it does |
|---|---|---|
| One speaker (`--speaker <slug>`) | `search(query, limit)` | Searches that speaker's talks and returns passages in their own words, each with title, date and source link |
| | `list_talks()` | Lists every talk and speech in that speaker's collection, newest first |
| Everyone (no `--speaker`) | `search(query, speaker?, limit)` | Searches all speakers, or one if you pass a slug |
| | `list_speakers()` | Lists every speaker, their slug and how many talks they have |
| | `list_talks(speaker)` | Lists one speaker's talks, newest first |

### What an answer looks like

```text
## 1. Clark G. Gilbert, "Come Home"
General Conference, 2026-04
Source: https://www.churchofjesuschrist.org/study/general-conference/2026/04/15gilbert?lang=eng&id=p_vO6YV#p_vO6YV

Come home! Come home! Ye who are weary, come home!
```

Conference links jump straight to the quoted paragraph. BYU links open the speech.

## Women leaders

The women who preside over the Relief Society, Young Women and Primary lead the Church's organizations for women, young women and children around the world. They serve as **general officers** of the Church and sit on its executive councils. (They aren't General Authorities, a title the Church uses for priesthood offices.) Their talks are searchable on equal footing with everyone else's.

| Speaker | Slug | Calling | Serving since | Conference talks | BYU speeches | Passages |
|---|---|---|---|---|---|---|
| Camille N. Johnson | `camille-n-johnson` | Relief Society General President | 2022 | 3 | 1 | 260 |
| J. Anette Dennis | `j-anette-dennis` | First Counselor, Relief Society General Presidency | 2022 | 3 | 1 | 206 |
| Kristin M. Yee | `kristin-m-yee` | Second Counselor, Relief Society General Presidency | 2022 | 3 | 1 | 307 |
| Emily Belle Freeman | `emily-belle-freeman` | Young Women General President | 2023 | 3 | — | 168 |
| Tamara W. Runia | `tamara-w-runia` | First Counselor, Young Women General Presidency | 2023 | 3 | — | 192 |
| Andrea Muñoz Spannaus | `andrea-munoz-spannaus` | Second Counselor, Young Women General Presidency | 2023 | 1 | — | 39 |
| Rosemary K. Chibota | `rosemary-k-chibota` | Primary General President | 2026 | 1 | — | 34 |
| Nina M. Garfield | `nina-m-garfield` | First Counselor, Primary General Presidency | 2026 | — | — | — |
| Theresa A. Collins | `theresa-a-collins` | Second Counselor, Primary General Presidency | 2026 | — | — | — |

Presidencies as listed on the Church's leadership pages in October 2026. The Primary presidency began serving in August 2026. Sister Garfield and Sister Collins haven't spoken in General Conference or at BYU yet, so their talks will appear through the monthly update once they do.

## Prophets and apostles

| Speaker | Slug | Calling | Apostle since | Conference talks | BYU speeches | Passages |
|---|---|---|---|---|---|---|
| Dallin H. Oaks | `dallin-h-oaks` | President of the Church | 1984 | 99 | 33 | 5,673 |
| Henry B. Eyring | `henry-b-eyring` | First Counselor in the First Presidency | 1995 | 106 | 20 | 5,451 |
| D. Todd Christofferson | `d-todd-christofferson` | Second Counselor in the First Presidency | 2008 | 44 | 12 | 2,175 |
| Dieter F. Uchtdorf | `dieter-f-uchtdorf` | Acting President of the Quorum of the Twelve | 2004 | 75 | 6 | 4,332 |
| David A. Bednar | `david-a-bednar` | Quorum of the Twelve | 2004 | 45 | 10 | 2,475 |
| Quentin L. Cook | `quentin-l-cook` | Quorum of the Twelve | 2007 | 41 | 7 | 2,054 |
| Neil L. Andersen | `neil-l-andersen` | Quorum of the Twelve | 2009 | 41 | 10 | 2,600 |
| Ronald A. Rasband | `ronald-a-rasband` | Quorum of the Twelve | 2015 | 29 | 7 | 1,566 |
| Gary E. Stevenson | `gary-e-stevenson` | Quorum of the Twelve | 2015 | 26 | 4 | 1,327 |
| Dale G. Renlund | `dale-g-renlund` | Quorum of the Twelve | 2015 | 25 | 6 | 1,218 |
| Gerrit W. Gong | `gerrit-w-gong` | Quorum of the Twelve | 2018 | 20 | 7 | 1,479 |
| Ulisses Soares | `ulisses-soares` | Quorum of the Twelve | 2018 | 23 | 4 | 789 |
| Patrick Kearon | `patrick-kearon` | Quorum of the Twelve | 2023 | 9 | 4 | 665 |
| Gérald Caussé | `gerald-causse` | Quorum of the Twelve | 2025 | 10 | 2 | 478 |
| Clark G. Gilbert | `clark-g-gilbert` | Quorum of the Twelve | 2026 | 3 | 4 | 332 |
| Russell M. Nelson | `russell-m-nelson` | 17th President of the Church (died 2025) | 1984 | 114 | 22 | 5,468 |
| Jeffrey R. Holland | `jeffrey-r-holland` | President of the Quorum of the Twelve (died 2025) | 1994 | 64 | 36 | 4,163 |
| M. Russell Ballard | `m-russell-ballard` | Acting President of the Quorum of the Twelve (died 2023) | 1985 | 88 | 22 | 4,298 |

Roster as of March 2026, plus apostles who died since October 2021. Counts include talks given before each speaker became an apostle. When callings change, edit `SPEAKERS` in [`fetch.py`](fetch.py) and run it again.

## How it works

Each server is a small, cited search index over one speaker's own words. Nothing is summarized or rewritten, so every passage is a direct quote.

```
speaker pages ──▶ talk text ──▶ paragraphs ──▶ search index ──▶ MCP server
 (conference     (content       (each with     (SQLite FTS5,    (search, list_talks,
  + BYU lists)    APIs)          its own link)  BM25 ranking)    list_speakers)
```

| Step | Command | Output |
|---|---|---|
| 1. Fetch | `uv run fetch.py [slug ...]` | `prophets.db`: every paragraph of every talk, with title, date, source and link |
| 2. Check | `uv run test_prophets.py` | A self-check of the paragraph reader and the search |
| 3. Serve | `uv run server.py [--speaker slug]` | An MCP server over stdio, ready for Claude, Cursor or Codex |
| 4. Update | automatic, monthly | The server reruns step 1 in the background when the last full check is over 30 days old |

- **Sources.** General Conference talks come from the Church's content API on churchofjesuschrist.org. BYU devotionals and forums come from the BYU Speeches site's data API.
- **Search.** SQLite's built-in full-text search (FTS5) ranks paragraphs with BM25, a standard way to score how well text matches a question. Porter stemming means "repenting" also finds "repentance". A matching talk title helps a passage rank, footnotes are left out, and at most two passages come from any one talk, so one long talk can't fill every result.
- **Skipped on purpose.** The sustaining of Church officers, auditing reports and statistical reports are left out. They are read aloud as procedure, not given as teaching.

### Files

- [`fetch.py`](fetch.py) downloads the talks and builds the index. Rerunning it skips talks already saved.
- [`server.py`](server.py) is the MCP server, and it starts the monthly update. It's built on the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
- [`test_prophets.py`](test_prophets.py) is the self-check.

## Content

- This project is **unofficial**. It is not affiliated with or endorsed by The Church of Jesus Christ of Latter-day Saints or Brigham Young University.
- Talks are © Intellectual Reserve, Inc. and Brigham Young University. Their terms allow personal, noncommercial use. Get permission before hosting this publicly.
- The repo contains only code. The talk text is downloaded to your own computer when you run `fetch.py`, and it is never committed.
- Every passage links to its original source, so you can read it in context.

## License

The code is [MIT](LICENSE). Talk content belongs to its owners; see [Content](#content).
