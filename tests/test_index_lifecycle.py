"""The index an agent never manages: built on first use, reused, rebuilt
when the corpus changes, shared by concurrent searches. Observed through the
CLI's output and the cache directory's contents."""

import os
from pathlib import Path

from conftest import finish


def snapshot_dirs(cache: Path) -> list[Path]:
    return [d for key in cache.iterdir() for d in key.iterdir()]


def test_first_search_builds_and_second_reuses(run):
    first = run("matcher", "docs-a")
    second = run("matcher", "docs-a")

    assert first.err.startswith("rankgrep: indexed 3 files (")
    assert second.err == ""
    assert first.out == second.out


def test_edited_file_is_reflected_on_the_next_search(run, lines_at):
    run("matcher", "docs-a")
    with open("docs-a/hooks.md", "a", encoding="utf-8") as doc:
        doc.write("\n## Quiet mode\n\nThe zephyrine flag silences hook output.\n")

    result = run("zephyrine", "docs-a")

    assert result.err.startswith("rankgrep: indexed")
    assert result.hits[0]["section"] == "Hooks reference > Quiet mode"
    assert "The zephyrine flag silences hook output." in lines_at(result.hits[0])


def test_added_and_deleted_files_are_reflected(run):
    assert run("novelword", "docs-a").code == 1
    Path("docs-a/new.md").write_text("# New\n\nA novelword appears.\n", encoding="utf-8")
    assert run("novelword", "docs-a").hits[0]["path"] == "docs-a/new.md"
    Path("docs-a/new.md").unlink()
    assert run("novelword", "docs-a").code == 1


def test_one_snapshot_remains_after_changes(run, tmp_path):
    for n in range(3):
        Path(f"docs-a/extra{n}.md").write_text(f"# Extra\n\nwordnumber{n}\n", encoding="utf-8")
        run("matcher", "docs-a")

    snapshots = snapshot_dirs(tmp_path / "cache")
    assert len(snapshots) == 1
    assert not snapshots[0].name.startswith(".tmp-")


def test_parallel_first_searches_agree(cli, tmp_path):
    processes = [cli("PreToolUse hook matcher", "docs-a", "docs-b", "book.txt") for _ in range(8)]
    results = [finish(p) for p in processes]

    assert [r.code for r in results] == [0] * 8
    assert len({r.out for r in results}) == 1
    assert results[0].hits
    assert len(snapshot_dirs(tmp_path / "cache")) == 1


def test_corrupt_snapshot_is_rebuilt(run, tmp_path):
    original = run("matcher", "docs-a")
    for file in snapshot_dirs(tmp_path / "cache")[0].iterdir():
        file.write_bytes(b"")

    healed = run("matcher", "docs-a")

    assert healed.code == 0
    assert healed.out == original.out
    assert healed.err.startswith("rankgrep: indexed")


def test_unwritable_cache_still_searches(run, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    monkeypatch.setenv("RANKGREP_CACHE_DIR", str(blocker))

    result = run("matcher", "docs-a")

    assert result.code == 0 and result.hits
    assert result.err.rstrip().endswith("(not saved: no writable cache directory)")


def test_unwritable_user_cache_falls_back_to_temp_dir(cli, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    env = {k: v for k, v in os.environ.items() if k != "RANKGREP_CACHE_DIR"}
    env |= {"XDG_CACHE_HOME": str(blocker), "TMPDIR": str(tmp_path / "tmp")}
    (tmp_path / "tmp").mkdir()

    first = finish(cli("matcher", "docs-a", env=env))
    second = finish(cli("matcher", "docs-a", env=env))

    assert first.code == 0 and "not saved" not in first.err and first.err.startswith("rankgrep: indexed")
    assert second.err == "" and second.out == first.out
    assert len(snapshot_dirs(tmp_path / "tmp" / f"rankgrep-{os.getuid()}")) == 1
