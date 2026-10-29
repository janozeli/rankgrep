# rankgrep

rankgrep is a BM25 search command for large local text, packaged as a plugin for Claude Code and Codex. You give it keywords and the folders or files to search. It splits them into sections, ranks the sections, and prints the exact line range of each hit as one JSON line. The agent then reads only those lines with its own file tools.

It is built for an agent that works alone. It searches documentation sets, `llms-full.txt` files, and long plain-text books, with no setup step, no server, and no index to manage.

## Why lexical search

`rg` finds a string you already know. An agent looking something up in a 10 MB documentation file usually knows the topic but not the wording, and reading the whole file costs millions of tokens. rankgrep ranks sections with BM25 and prints where each one starts and ends. A short skill teaches the agent the loop: search with keywords, read the range, search again with the words the docs use, then switch to `rg`.

The claim this repository makes is that one good lexical search tool is enough for an agent to find what it needs in a lot of text. It uses no embeddings, no vector database, and no model calls. The index builds itself on the first search, notices every file change, and stays correct when two agents search at once. [Does it work?](#does-it-work) tests the claim, and compares rankgrep with plain `rg`.

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

## Does it work?

An agent whose only search tool was rankgrep answered 48 of 50 lookup questions correctly, and for 48 of them it cited lines that state the answer. The same agent with no tools answered 15. With only `rg` it answered 49, for less money and in less time. One lexical search tool was enough on these two texts. These questions don't show rankgrep finding more than `rg`.

| Text | Setup | Correct | Found | Cited lines state the answer | Cost per question | Seconds, median |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Code docs | no tools | 7/25 | 0/25 | 0/25 | $0.007 | 5.1 |
| Claude Code docs | `rg` | 24/25 | 22/25 | 23/25 | $0.036 | 6.0 |
| Claude Code docs | rankgrep | 23/25 | 19/25 | 23/25 | $0.043 | 10.7 |
| Les Misérables | no tools | 8/25 | 0/25 | 0/25 | $0.012 | 9.4 |
| Les Misérables | `rg` | 25/25 | 25/25 | 25/25 | $0.027 | 7.3 |
| Les Misérables | rankgrep | 25/25 | 25/25 | 25/25 | $0.042 | 11.6 |

- **Correct.** A judge model says the answer states the reference fact.
- **Found.** The cited line is inside the section that the question was written from. A script decides this, with no model.
- **Cited lines state the answer.** The judge says the section around the cited line states the reference fact, wherever that section is. The docs repeat facts across pages and in the changelog, so a correct citation can land outside the source section. Four of rankgrep's six docs misses on Found are citations of this kind.

Cost is at API list prices, as `claude -p` reports it. [`evals/results/summary.md`](evals/results/summary.md) adds 95% intervals, token counts, and the outcome of every question.

### What the numbers say

- **The test can't rank the two tools.** On the book, both found all 25. On the docs, only rankgrep found the source section on 2 questions, and only `rg` on 5. An exact sign test on those 7 questions gives p = 0.45, so the gap is within noise.
- **The questions were easier for `rg` than intended.** The question writer was told to avoid the section's words where a paraphrase exists. Even so, a question shares a median 73% (docs) and 67% (book) of its rankgrep search terms with its section, because names such as Jondrette or `extraKnownMarketplaces` survive any paraphrase. With those words, 38 of 50 `rg` runs and 45 of 50 rankgrep runs needed one successful search.
- **rankgrep cost more per question.** The paired median is 1.26 times the `rg` cost on the docs and 1.75 times on the book. Every rankgrep run spends a turn loading the skill. A rankgrep hit prints one line, so 44 of 50 runs then read the line range with the Read tool. `rg -C` prints the lines around each match, and 24 of 50 `rg` runs read nothing more. The median run took 7 turns with rankgrep and 3 or 4 with `rg`. Each turn resends the whole context, which is most of the token count.
- **The model already knows both texts.** With no tools it answered 15 of 50 from memory, including details such as the heap of empty bottles in Marius's ground-floor room. A correct answer alone says little. The citation columns show the lookup.

### How it was measured

The agent is Claude Sonnet 5.5 (`claude-sonnet-5-5`) through `claude -p`, in Claude Code 2.1.312. It answered each question once in each of three setups:

- **No tools.** It answers from what the model already knows.
- **`rg`.** Bash runs only `rg`, and the Read tool works.
- **rankgrep.** Bash runs only the rankgrep launcher, and the Read tool works. The plugin loads with `--plugin-dir`, so the agent sees the skill's description and loads the skill the same way it does after `/plugin install`.

The two texts:

- The Claude Code docs, [`llms-full.txt`](https://code.claude.com/docs/llms-full.txt), 10 MB in 6,049 rankgrep sections.
- *Les Misérables* in Isabel Hapgood's translation, [Project Gutenberg eBook 135](https://www.gutenberg.org/ebooks/135), 3.4 MB in 1,040 sections. It is a long public-domain book with no headings, so rankgrep splits it at blank lines. Its 19th-century wording differs from how a reader asks today.

The harness downloads both at run time and checks each against a pinned sha256. Neither text is in this repository.

Questions. A seeded script picks rankgrep sections at random and shows them to the same model, 6 at a time. For each section, the model writes one question that only that section answers, in other words than the section uses where it can. It also writes a short answer and quotes the line that states it. The script drops a question when its quote also appears outside its section, so that each question has one source in the text. It keeps the first 25 per text. Of the 84 candidates written, the script dropped 8 docs questions whose quote appears elsewhere, the writer skipped 2 sections that state no fact, and 24 were not needed.

The request names the file, asks the question, and asks for a last line of JSON with the answer and a `path:line` citation. Every setup gets the same request.

Isolation. Each setup works in its own folder called `notes-library`, with a clean environment, no user settings, no `CLAUDE.md`, no MCP servers, and no auto memory. Claude Code's `dontAsk` mode still runs read-only commands such as `grep` and `sed` without a permission rule. So a PreToolUse hook, [`evals/guard.py`](evals/guard.py), refuses any Bash command other than the one program, and any pipe, redirection, or path outside the folder. Read works only inside the folder. Both tool setups have the Skill tool. In the `rg` setup no skill may run, so the two tool setups see the same system prompt apart from the rankgrep skill. The no-tools setup gets one extra system-prompt sentence that says it has no tools. Without it, the pilot agent wrote tool calls as plain text until it hit the output limit.

Grading. The judge is the same model with no tools. For each question it sees the question, the reference answer, the source section, the three replies under shuffled labels, and the section around each reply's citation.

### Limits

- **One run per question per setup.** The 6 pilot questions ran twice in all three setups, and 2 of the 18 outcomes changed. With 25 questions per text, a 95% interval is 13 to 35 points wide. A paired difference needs about 6 questions that all go one way to reach p < 0.05.
- **One model family.** Sonnet wrote the questions, answered them, and graded them, because no other family was available here. The verdicts on the 8 questions where a tool setup missed any column were read by hand. One is arguable. On docs-08, the `rg` reply listed the right Bedrock actions, but from the GitHub Actions page instead of the GitLab one, and the judge marked it wrong.
- **One program, no pipes.** All 100 tool runs began with a command that the hook refused, usually a `grep` pipeline or a `cd`, and then adapted. A real user has rankgrep, `rg`, and the whole shell together. This measures each tool alone.
- **Easy questions.** Questions written from random sections keep the section's names and identifiers. Questions that real users ask, with vaguer words, may separate the two tools. These don't. Of 12 questions read by hand against their sections, 10 are specific and have one answer. docs-01 is vague, and docs-11 asks about the structure of a docs page.
- **The docs change.** `llms-full.txt` changes often, and the questions point at line ranges of the pinned version. When the downloaded file no longer matches the pinned sha256, the harness stops. A new question set needs `uv run evals/harness.py questions` and a new pin.

### Reproduce

You need Claude Code with a working `claude -p` login, uv, `rg`, and network access. Then run:

```
uv run evals/harness.py all
```

`all` downloads the texts, runs the 150 agent runs and 50 judge calls, and writes `evals/results/`. It reuses the committed `questions.jsonl`. Every `claude -p` call is cached under `--work`, which defaults to `notes-desk` in the system temp folder, so a rerun repeats only what is missing. The committed run cost $5.18 at list prices, plus $0.59 for the 14 calls that wrote the questions. The agents' folders hold only the two texts, and no path an agent sees mentions the measurement.

## Harder documentation lookups

A second suite searches a mixed library of Python 3.14 and PostgreSQL 18 documentation: 914 files, 24.35 MB, with pinned source versions. It asks 24 questions across four axes: direct lookup, vague symptoms, multiple constraints, and synthesis across different files. Every axis has three Python and three PostgreSQL questions. Agents get the library folder, not the target file.

Both search arms answered all 24 questions correctly. Under the citation rules, `rg` supported 22 answers and rankgrep 21. All five citation failures involved ranges exceeding the requested 40-line maximum; they are not evidence that the search failed. Answering calls cost $0.84 with `rg` and $1.28 with rankgrep. This larger, less literal suite still does not establish a rankgrep advantage.

This suite requires citations supporting every part of an answer. The questions, references, protocol, per-axis results, and reproduction steps are in [evals/HARD.md](evals/HARD.md). Run it with `uv run evals/hard.py all`. The original experiment above remains unchanged.

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
