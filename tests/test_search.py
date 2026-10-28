"""What an agent sees when it searches: hits, ranges, snippets, exit codes."""

from pathlib import Path


def line_of(path: str, text: str) -> int:
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    return next(i for i, line in enumerate(lines, 1) if line.startswith(text))


def test_keywords_find_the_section_and_its_exact_line_range(run, lines_at):
    result = run("PreToolUse hook matcher", "docs-a")

    assert result.code == 0
    top = result.hits[0]
    assert top["path"] == "docs-a/hooks.md"
    assert top["section"] == "Hooks reference > Hook events > PreToolUse"
    assert (top["start"], top["end"]) == (
        line_of("docs-a/hooks.md", "### PreToolUse"),
        line_of("docs-a/hooks.md", "The hook receives the call as JSON"),
    )
    read = lines_at(top)
    assert read[0] == "### PreToolUse"
    assert any("matcher" in line for line in read)
    assert top["text"] == " ".join(lines_at(top, top["line"], top["line"])[0].split())
    assert list(top) == ["path", "start", "end", "score", "section", "line", "text", "matched"]


def test_every_range_reads_back_with_sed(run, lines_at):
    result = run("-k", "100", "setting matcher keeper retry lantern", "docs-a", "docs-b", "book.txt", "twins")

    assert len(result.hits) > 10
    for hit in result.hits:
        read = lines_at(hit)
        assert len(read) == hit["end"] - hit["start"] + 1
        assert read[0].strip() and read[-1].strip()


def test_identifier_query_ranks_exact_spelling_first(run):
    exact = run("max_tokens", "docs-a")
    assert [h["section"].split(" > ")[-1] for h in exact.hits[:2]] == ["Output size", "Truncation"]
    assert exact.hits[0]["score"] > exact.hits[1]["score"]

    for spelling in ("maxTokens", "max tokens"):
        sections = {h["section"].split(" > ")[-1] for h in run(spelling, "docs-a").hits}
        assert {"Output size", "Truncation"} <= sections


def test_camel_case_parts_match_words(run):
    result = run("user id", "docs-a/hooks.md")

    assert result.hits[0]["section"] == "Hooks reference > Identity"
    assert "getUserById" in result.hits[0]["text"]


def test_accents_and_case_are_ignored(run, lines_at):
    accented = run("ação coração", "book.txt")
    folded = run("ACAO Coracao", "book.txt")

    assert accented.code == 0
    assert accented.out == folded.out
    assert any("coração" in line for line in lines_at(accented.hits[0]))
    assert accented.hits[0]["matched"] == ["acao", "coracao"]


def test_hash_lines_in_code_fences_do_not_split_sections(run, lines_at):
    top = run("dangerous commands", "docs-a").hits[0]

    assert top["section"] == "Hooks reference > Hook events > PreToolUse"
    assert lines_at(top)[0] == "### PreToolUse"
    assert "# block dangerous commands" in top["text"]


def test_long_sections_and_long_text_are_windowed(run, lines_at):
    hits = run("-k", "100", "setting default restart keeper storm tide", "docs-a/settings.md", "book.txt").hits
    settings = [h for h in hits if h["path"] == "docs-a/settings.md"]
    book = [h for h in hits if h["path"] == "book.txt"]

    assert len(settings) > 2 and len(book) > 2
    for hit in hits:
        read = lines_at(hit)
        assert len(read) <= 80
        assert len("\n".join(read)) <= 4000 or hit["start"] == hit["end"]
    for hit in settings:
        after = lines_at(hit, hit["end"] + 1, hit["end"] + 1)
        assert after == [] or after[0] == "" or after[0].startswith("#### ")


def test_llms_full_txt_gets_heading_sections_and_plain_text_does_not(run):
    assert run("retry backoff 429", "docs-b").hits[0]["section"] == "Library > Rate limits"
    assert run("glimmerwidget", "mixed").hits[0]["section"] == "Page > Widgets"
    assert run("release checklist", "docs-a/notes.txt").hits[0]["section"] == ""
    assert run("keeper storm", "book.txt").hits[0]["section"] == ""


def test_any_text_file_is_searchable_and_binaries_are_skipped(run):
    assert "skipped 1 binary" in run("frobulator", "mixed").err
    for word, path in [("frobulator", "mixed/app.py"), ("zanzibar", "mixed/guide.rst"), ("glimmerwidget", "mixed/page.mdx")]:
        assert [h["path"] for h in run(word, "mixed").hits] == [path]
    assert run("png ihdr", "mixed").code == 1


def test_hidden_files_and_vendored_folders_are_skipped_unless_named(run):
    assert run("secretword", "mixed").code == 1
    assert run("secretword", "mixed/.hidden.md").code == 0
    assert run("quuxvendored", "docs-a").code == 1
    assert run("quuxvendored", "docs-a/node_modules/pkg/readme.md").code == 0


def test_line_numbers_count_newlines_only(run, lines_at):
    top = run("beacon", "mixed/formfeed.txt").hits[0]

    assert top["line"] == 4
    assert "beacon" in lines_at(top, top["line"], top["line"])[0]


def test_legacy_encoding_is_read(run):
    top = run("café", "mixed").hits[0]

    assert top["path"] == "mixed/legacy.txt"
    assert top["text"] == "The café opens at nine."


def test_several_doc_sets_in_one_search(run):
    paths = {h["path"] for h in run("retry matcher", "docs-a", "docs-b").hits}

    assert "docs-a/hooks.md" in paths
    assert "docs-b/llms-full.txt" in paths


def test_paths_are_printed_as_the_caller_named_them(run, corpora):
    relative = run("matcher", "docs-a")
    absolute = run("matcher", str(corpora / "docs-a"))

    assert relative.hits[0]["path"] == "docs-a/hooks.md"
    assert absolute.hits[0]["path"] == str(corpora / "docs-a" / "hooks.md")
    assert absolute.err == ""


def test_output_is_deterministic_and_ties_keep_path_order(run):
    first = run("lantern", "twins")
    second = run("lantern", "twins")

    assert first.out == second.out
    assert [h["path"] for h in first.hits] == ["twins/a.md", "twins/b.md"]
    assert first.hits[0]["score"] == first.hits[1]["score"]


def test_top_limits_hits(run):
    assert len(run("-k", "2", "setting", "docs-a").hits) == 2
    everything = run("-k", "1000", "setting", "docs-a")
    assert everything.code == 0
    assert 2 < len(everything.hits) < 1000


def test_files_from_stdin(run):
    result = run("--files-from", "-", "matcher keeper", stdin="docs-a/hooks.md\n\nbook.txt\n")

    assert {h["path"] for h in result.hits} == {"docs-a/hooks.md", "book.txt"}


def test_unknown_terms_are_named_on_stderr(run):
    result = run("hookz matcher", "docs-a")

    assert result.code == 0
    assert result.err.splitlines()[-1] == "rankgrep: not in this corpus: hookz"


def test_no_match_exits_1(run):
    result = run("frobnicate widget", "docs-a")

    assert (result.code, result.hits) == (1, [])
    lines = result.err.splitlines()
    assert lines[-1].startswith("rankgrep: no matches")
    assert "frobnicate" in lines[-1] and "widget" in lines[-1]


def test_usage_errors_exit_2_with_one_line(run):
    cases = [
        ("matcher",),
        ("matcher", "docs-z"),
        ("logo", "binary-only"),
        ("the of", "docs-a"),
        ("-k", "0", "matcher", "docs-a"),
        ("--files-from", "missing.txt", "matcher"),
    ]
    for argv in cases:
        result = run(*argv)
        assert (result.code, result.out) == (2, ""), argv
        assert result.err.count("\n") == 1 and result.err.startswith("rankgrep: "), argv
