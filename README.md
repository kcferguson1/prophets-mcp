# The Prophets

Searchable MCP servers built from the General Conference talks and BYU speeches of the First Presidency and the Quorum of the Twelve Apostles. Every passage comes back in the speaker's own words, with the talk title, date and a source link (conference links jump to the exact paragraph).

Runs locally for personal study.

## Setup

```bash
uv sync
uv run fetch.py              # downloads every speaker into prophets.db (rerun any time; it skips what's saved)
uv run fetch.py dallin-h-oaks  # or just one speaker
uv run test_prophets.py      # self-check
```

## Speakers

| Slug | Name |
|---|---|
| `dallin-h-oaks` | Dallin H. Oaks |
| `henry-b-eyring` | Henry B. Eyring |
| `d-todd-christofferson` | D. Todd Christofferson |
| `dieter-f-uchtdorf` | Dieter F. Uchtdorf |
| `david-a-bednar` | David A. Bednar |
| `quentin-l-cook` | Quentin L. Cook |
| `neil-l-andersen` | Neil L. Andersen |
| `ronald-a-rasband` | Ronald A. Rasband |
| `gary-e-stevenson` | Gary E. Stevenson |
| `dale-g-renlund` | Dale G. Renlund |
| `gerrit-w-gong` | Gerrit W. Gong |
| `ulisses-soares` | Ulisses Soares |
| `patrick-kearon` | Patrick Kearon |
| `gerald-causse` | Gérald Caussé |
| `clark-g-gilbert` | Clark G. Gilbert |
| `russell-m-nelson` | Russell M. Nelson (died 2025) |
| `jeffrey-r-holland` | Jeffrey R. Holland (died 2025) |
| `m-russell-ballard` | M. Russell Ballard (died 2023) |

Roster as of March 2026, plus apostles who died since October 2021. When callings change, edit `SPEAKERS` in `fetch.py` and rerun it.

## Tools

One apostle (`--speaker <slug>`): `search(query, limit)`, `list_talks()`.
Everyone (no `--speaker`): `search(query, speaker?, limit)`, `list_speakers()`, `list_talks(speaker)`.

## Add to a client

Replace `/path/to/the_prophets` with this folder's full path. Drop `--speaker ...` to get everyone in one server.

**Claude Code**
```bash
claude mcp add oaks -- uv run --directory /path/to/the_prophets server.py --speaker dallin-h-oaks
```

**Codex**
```bash
codex mcp add oaks -- uv run --directory /path/to/the_prophets server.py --speaker dallin-h-oaks
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`) and **Cursor** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "oaks": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/the_prophets", "server.py", "--speaker", "dallin-h-oaks"]
    }
  }
}
```

**ChatGPT** only connects to servers at a public HTTPS address, so it needs this hosted somewhere first (not set up here).

## Content

Talks are © Intellectual Reserve, Inc. and BYU. Their terms allow personal, noncommercial use; get permission before hosting this publicly.
