# rankgrep

rankgrep is a BM25 search command for large local text, packaged as a plugin for Claude Code and Codex. You give it keywords and the folders or files to search. It splits them into sections, ranks the sections, and prints the exact line range of each hit as one JSON line. The agent then reads only those lines with its own file tools.

It is built for an agent that works alone. It searches documentation sets, `llms-full.txt` files, and long plain-text books, with no setup step, no server, and no index to manage.

## Why lexical search

`rg` finds a string you already know. An agent looking something up in a 10 MB documentation file usually knows the topic but not the wording, and reading the whole file costs millions of tokens. rankgrep ranks sections with BM25 and prints where each one starts and ends. A short skill teaches the agent the loop: search with keywords, read the range, search again with the words the docs use, then switch to `rg`.

The claim this repository makes is that one good lexical search tool is enough for an agent to find what it needs in a lot of text. It uses no embeddings, no vector database, and no model calls. The index builds itself on the first search, notices every file change, and stays correct when two agents search at once.

## Install

rankgrep needs [uv](https://docs.astral.sh/uv/). The plugin runs the CLI from its own source through uv, so there is nothing else to install.

Claude Code:

```
/plugin marketplace add janozeli/rankgrep
/plugin install rankgrep@rankgrep
```

Codex:

```
codex plugin marketplace add janozeli/rankgrep
codex plugin add rankgrep@rankgrep
```

From a clone, without a plugin:

```
git clone https://github.com/janozeli/rankgrep
rankgrep/bin/rankgrep "keywords" path/to/docs
```

## Usage

The examples run in a folder that holds the Claude Code docs as `docs/claude-code/llms-full.txt` (10 MB, 125,764 lines), a small library doc set in `docs/library/`, and a plain-text book. Inside the plugin, the skill gives the agent the launcher's full path. The examples write it as `rankgrep`.

To search docs that publish an `llms-full.txt`, download the file once and search it:

```
$ curl -fsSL https://code.claude.com/docs/llms-full.txt -o docs/claude-code/llms-full.txt
$ rankgrep -k 2 "skill frontmatter allowed-tools" docs/claude-code
rankgrep: indexed 1 files (6049 sections) in 1.2s
{"path":"docs/claude-code/llms-full.txt","start":47508,"end":47538,"score":10.66,"section":"Extend Claude with skills > Configure skills > Pre-approve tools for a skill","line":47529,"text":"…lyCustomization`, a personal or project skill whose frontmatter declares `hooks` loses its `allowed-tools` pre-approval, apart from the [skills that keep it](/d…","matched":["skill","frontmatter","allowed-tools","allowed","tools"]}
{"path":"docs/claude-code/llms-full.txt","start":47311,"end":47328,"score":9.95,"section":"Extend Claude with skills > Configure skills > Frontmatter reference","line":47325,"text":"Unexpected key(s) in SKILL.md frontmatter: argument-hint. Allowed properties are: allowed-tools, compatibility, description, license, metadata, name","matched":["skill","frontmatter","allowed-tools","allowed","tools"]}
```

The same search again prints the same bytes, with no stderr note, in about 0.2 seconds. The agent reads lines 47508 to 47538 with `sed -n '47508,47538p'` or its Read tool.

Several doc sets go in one search. Each hit's path shows which set it came from, and the output composes with `jq`:

```
$ rankgrep "retry backoff 429" docs/claude-code docs/library | jq -r '"\(.path):\(.start)-\(.end)  \(.section)"' | head -3
docs/library/llms-full.txt:5-8  Library > Rate limits
docs/claude-code/llms-full.txt:23342-23351  Error reference > Automatic retries > Tune retry behavior
docs/claude-code/llms-full.txt:73257-73266  Claude Code gateway compatibility guide > Response headers
```

A plain-text book has no headings, so `section` is empty and the book is split at blank lines:

```
$ rankgrep -k 1 "keeper storm lamp" books/the-long-coast.txt | jq -c '{path,start,end,section,line}'
{"path":"books/the-long-coast.txt","start":75,"end":125,"section":"","line":75}
```

For a custom file set, pipe a list of paths:

```
git ls-files '*.md' | rankgrep --files-from - "release checklist"
```

## Output

stdout carries only hits, one JSON object per line, best first. Every key is always present, in this order:

| Key | Type | Meaning |
| --- | --- | --- |
| `path` | string | The file, spelled the way you named its folder or file |
| `start`, `end` | integer | First and last line of the section, 1-based and inclusive, counted the way `sed -n` counts |
| `score` | number | BM25 score, rounded to 2 decimals. Compare it only within one search |
| `section` | string | Markdown heading path, such as `Hooks reference > Hook events > PreToolUse`. Empty for plain text |
| `line` | integer | The section's line with the most distinct query words |
| `text` | string | That line, whitespace collapsed, cut to about 160 characters around the first match |
| `matched` | array of strings | Query words this section contains, lowercased and without accents |

Ties are ordered by path and line, so the same corpus and query always print the same bytes. `-k N` sets how many hits to print (default 8). Notes go to stderr, one line each, starting with `rankgrep: `.

## Exit codes

| Code | Meaning | Example stderr |
| --- | --- | --- |
| 0 | Hits printed | `rankgrep: not in this corpus: hookz` when some words matched nothing |
| 1 | No section contains any query word | `rankgrep: no matches. Not in this corpus: frobnicate, widgetry. Try other words.` |
| 2 | The command can't run as written | `rankgrep: no such file or directory: docs/claude-cod. Pass existing files or folders.` |
| 3 | Internal error | `rankgrep: internal error: ... Please report it at https://github.com/janozeli/rankgrep/issues; use rg meanwhile.` |

## How it works

**A corpus is the paths you pass.** There is no registry and no `add` step. rankgrep walks the named folders, skips hidden entries and dependency folders (`node_modules`, `__pycache__`, `venv`, `site-packages`), and skips binary files, which it detects by a NUL byte in the first 8 KiB. It doesn't read `.gitignore`, because downloaded doc sets usually live in ignored folders. Pipe `git ls-files` into `--files-from -` when you want only tracked files.

**Markdown splits at headings, everything else at blank lines.** Files ending in `.md`, `.markdown`, or `.mdx`, and `.txt` files with at least three H1 to H3 headings (the `llms-full.txt` shape), split at H1 to H3 headings outside fenced code. Any other text file is one section. Long sections are cut into windows of at most 80 lines and 4,000 characters, preferably before a deeper heading or after a blank line. A heading with no body is dropped, because a one-line section would outrank the sections that hold the content.

**One tokenizer serves documents and queries.** It folds case and accents, so `ação` matches `acao`, and drops English and Portuguese stopwords. An identifier yields itself and its parts: `max_tokens` yields `max_tokens`, `max`, and `tokens`. The whole identifier is the rarer term, so a section that spells `max_tokens` outranks one that says "max tokens", and both still match. There is no stemming.

**bm25s ranks the sections.** rankgrep uses its Lucene defaults (k1 1.5, b 0.75), scores every section with `get_scores`, and sorts with a stable sort, so ties keep reading order.

**The index is a content-addressed snapshot, with no locks.** Each search hashes rankgrep's own source, the bm25s version, and the path, size, and modification time of every file. That hash names a snapshot directory in the user cache. If the directory exists, the index is current. If not, rankgrep builds the index into a private temporary directory and renames it into place. A rename is atomic, so a snapshot is either complete or absent. When two agents build the same corpus at once, one rename wins and both print the same output. No lock file exists for a crash to leave behind. A snapshot that fails to load is discarded and rebuilt.

**The cache is never required.** rankgrep tries `$RANKGREP_CACHE_DIR` alone when it is set. Otherwise it tries the platform cache directory (`~/.cache/rankgrep` on Linux), then a per-user directory under the system temp directory, which sandboxes usually allow. When nothing is writable, it searches an in-memory index and says so on stderr.

**The launcher keeps the CLI in step with the plugin.** `bin/rankgrep` runs `uv run --frozen --no-dev --project <plugin root>` with the environment in `~/.cache/rankgrep/env-<id>`. The editable install picks up a plugin update on the next call and writes nothing into the plugin folder. `uv tool run --from <plugin root>` was tested and rejected, because it kept serving its first build after the source changed.

## Performance

Measured on Linux with 12 cores and the Claude Code `llms-full.txt` (10 MB, 6,049 sections), median of 5 runs through `bin/rankgrep`:

| Case | Time |
| --- | --- |
| First search, builds the index | 1.38 s (range 1.35 to 1.48 s) |
| Later searches | 0.20 s (range 0.19 to 0.22 s) |

Tokenizing in Python is most of the build. Python startup plus importing bm25s and numpy is 0.11 s of every search, and uv adds about 0.03 s.

## Limitations

- **No stemming.** "matcher" doesn't match "matches". On the Claude Code docs, `PreToolUse hook matcher` ranks the hooks reference's PreToolUse section 24th, because that section says "Matches". `PreToolUse hooks reference` ranks it first. The skill tells the agent to add word variants and the words it sees in section names.
- **No phrase or boolean queries.** Word order is ignored.
- **Any file change rebuilds the whole index.** There is no incremental update. The rebuild costs the first-search time above.
- **Each distinct set of paths has its own index.** `docs/a`, `docs/b`, and both together are three indexes, because BM25 statistics depend on the whole corpus.
- **Only markdown headings get structure.** RST, HTML, and other formats are split at blank lines.
- **The cache keeps one snapshot per set of paths** until the files change. Delete `~/.cache/rankgrep` to reclaim the space.
- **claude.ai and Cowork don't install plugins with a top-level `bin/` directory.** The plugin targets Claude Code and Codex.
- **The first launch needs uv and network access** to create its environment. If your agent runs in a sandbox without network access, run `<plugin root>/bin/rankgrep --version` once outside it.
- Windows is not tested.

## Development

```
uv run pytest                       # behavior tests, driven through the CLI
uv run scripts/sync_plugin.py       # regenerate the plugin manifests from pyproject.toml
```

`pyproject.toml` is the single source for the package and for both plugin manifests. A test runs `scripts/sync_plugin.py --check` and fails when a committed manifest is stale.

## License

MIT. See [LICENSE](LICENSE).
