"""rankgrep: BM25 search over large local text for coding agents.

The command line is the only public interface; every module is private.
"""

from rankgrep._cli import main

__all__ = ["main"]
