# Coding standards

Judgement calls for reviewing changes to this repo. The self-check (`uv run test_prophets.py`) runs on every push; these are the rules no check can enforce.

- **Options before tools.** Extend an existing tool with an option before adding a new tool: every tool's name and description sits in each Claude session's context.
- **Glossary words.** User-facing text (tool descriptions, results, messages, the README) and stored names (tables, columns) use the terms in `GLOSSARY.md`, such as footnote, citation, chapter citation, passage, paragraph and talk ID. A database name is hard to change once databases in the wild carry it.
- **Smallest complete change.** A change reaches every caller, test and doc it affects, and nothing past what was asked; anything else spotted goes in as a suggestion.
- **One test per piece of risky logic**, as an assert in `test_prophets.py`: a parser, a branch, an upgrade step, a message a tool returns. Tests fake the network and never touch the real `prophets.db`.
- **Updates never lose data.** A page or request that fails leaves what's already saved in place and is retried on a later update; one bad page never stops the rest of its source.
- **Comments say why.** One line, for what the code can't show.
