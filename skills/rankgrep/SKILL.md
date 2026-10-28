---
name: rankgrep
description: Find where a topic is covered in a large body of local text, such as documentation folders, llms-full.txt files, or long plain-text books. Ranks sections against keywords with BM25 and returns exact line ranges to read. Use when you need to look something up in long text and don't know the exact wording. Use rg instead when you already know the exact string.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/rankgrep *)
---

# rankgrep

`${CLAUDE_PLUGIN_ROOT}/bin/rankgrep "<keywords>" <path>...` splits the named files and folders into sections, ranks the sections against your keywords, and prints one JSON line per hit. If your harness left `${CLAUDE_PLUGIN_ROOT}` unexpanded, use the launcher at `../../bin/rankgrep`, relative to the folder that holds this file, as an absolute path. The launcher needs `uv`.

The first search on a set of paths builds an index, which takes about 1.5 seconds for 10 MB of text. Later searches reuse it and take a fraction of a second, until a file changes.

## Search loop

1. Search with 2 to 6 keywords that the text itself would use: names, identifiers exactly as written (`max_tokens`, `PreToolUse`), error codes, and distinctive nouns. Write keywords, not a sentence. Word order doesn't matter.
2. Read the best hit's line range with your file tools. Don't read whole files.
3. If the hits don't show what you need, search again with other words: synonyms, singular and plural forms (`matcher matches`), and terms you saw in earlier hits or section names. Don't rerun a query you already ran.
4. Once you know the exact string, use `rg` to find every occurrence.

## Output

```
{"path":"docs/claude-code/llms-full.txt","start":68404,"end":68450,"score":8.54,"section":"Hooks reference > Hook events > PreToolUse","line":68412,"text":"> PreToolUse runs only when Claude calls a tool. By default, files you [reference with `@` in your prompt](/docs/en/common-workflows#reference-files-and-directo…","matched":["pretooluse","pre","tool","use","hooks","reference"]}
```

- `start` and `end` are the section's first and last line, inclusive. Read exactly that range.
- `line` and `text` are the section's best matching line, cut to about 160 characters.
- `section` is the markdown heading path. It is empty for plain text.
- `matched` lists the query words this section contains, lowercased and without accents. Identifiers also match by their parts.
- `score` is relative. Compare it with the other hits of the same search, never across searches.
- Hits come best first. `-k N` changes how many (default 8).
- A stderr note names query words that appear nowhere in the corpus. Replace them.

## Choosing what to search

- Name the folders or files after the query. Several doc sets can go in one search, and each hit's path shows which set it came from:
  `${CLAUDE_PLUGIN_ROOT}/bin/rankgrep "retry backoff 429" docs/claude-code docs/library`
- Pass the same paths each time, so the index is reused.
- Every text file under a folder is searched, except hidden ones and dependency folders such as `node_modules`. Point at documentation folders, not at a whole repository. For a custom file set, pipe a list:
  `git ls-files '*.md' | ${CLAUDE_PLUGIN_ROOT}/bin/rankgrep --files-from - "release checklist"`
- For online docs that publish an `llms-full.txt`, download it once with `curl -fsSL <url> -o docs/<name>/llms-full.txt` and search that file.

## Exit codes

| Code | Meaning | Next step |
| --- | --- | --- |
| 0 | Hits printed | Read the best range |
| 1 | No section contains any query word | Search with other words |
| 2 | The command can't run as written | Do what the one-line stderr message says |
| 3 | Bug in rankgrep | Use rg instead |

If the launcher says it needs uv, tell the user that rankgrep needs uv (https://docs.astral.sh/uv/) and use rg meanwhile.
