"""Derive every plugin manifest from pyproject.toml.

    uv run scripts/sync_plugin.py           rewrite the generated files
    uv run scripts/sync_plugin.py --check   list stale files and exit 1, change nothing

The generated files are committed because Claude Code and Codex install
plugins straight from the git repository, with no build step.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def render(pyproject: dict) -> dict[str, str]:
    project = pyproject["project"]
    plugin = pyproject["tool"]["rankgrep"]["plugin"]
    author = project["authors"][0]
    common = {
        "name": project["name"],
        "version": project["version"],
        "description": project["description"],
        "author": {"name": author["name"], "email": author["email"]},
        "homepage": project["urls"]["Homepage"],
        "repository": project["urls"]["Repository"],
        "license": project["license"],
        "keywords": project["keywords"],
    }
    codex = common | {
        "skills": "./skills/",
        "interface": {
            "displayName": plugin["display-name"],
            "shortDescription": plugin["short-description"],
            "longDescription": project["description"],
            "developerName": author["name"],
            "category": plugin["category"],
            "capabilities": ["Read"],
            "defaultPrompt": plugin["default-prompts"],
        },
    }
    claude_marketplace = {
        "name": project["name"],
        "description": project["description"],
        "owner": {"name": author["name"]},
        "plugins": [
            {
                "name": project["name"],
                "source": "./",
                "description": project["description"],
                "version": project["version"],
            }
        ],
    }
    codex_marketplace = {
        "name": project["name"],
        "interface": {"displayName": plugin["display-name"]},
        "plugins": [
            {
                "name": project["name"],
                "source": {"source": "local", "path": "./"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": plugin["category"],
            }
        ],
    }
    files = {
        ".claude-plugin/plugin.json": common,
        ".claude-plugin/marketplace.json": claude_marketplace,
        ".codex-plugin/plugin.json": codex,
        ".agents/plugins/marketplace.json": codex_marketplace,
    }
    return {path: json.dumps(data, indent=2, ensure_ascii=False) + "\n" for path, data in files.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="list stale files and exit 1 instead of writing")
    check = parser.parse_args(argv).check
    expected = render(tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8")))
    stale = []
    for relative, text in expected.items():
        target = REPO / relative
        if target.exists() and target.read_text(encoding="utf-8") == text:
            continue
        stale.append(relative)
        if not check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    if check and stale:
        print(f"stale: {', '.join(stale)}. Run uv run scripts/sync_plugin.py and commit the result.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
