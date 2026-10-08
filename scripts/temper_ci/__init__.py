"""temper-ci: the gate between a commit and temper's master, and between
master and the live server.

Two pieces, one command:

  gate     watch the repository's own branches for the owner's pushes, record
           each new commit, and post it on the commit as the `temper/boxes`
           status GitHub's branch protection requires. Nothing is built and
           no temper is started: there is one temper, the live one, and no
           test copy of it (until 2026-10-08 a throwaway temper was built and
           smoke-tested here for every commit).
  deploy   after master moves: restart temper once no run is going on it,
           check it live, and if that fails put master back with a revert
           commit through the same gate and say so.

Everything here is stdlib only, so it runs from a bare python3 in a systemd
user unit with nothing installed.
"""

__all__ = ["paths"]
