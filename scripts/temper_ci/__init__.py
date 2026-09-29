"""temper-ci: the gate between a commit and temper's master, and between
master and the live server.

Three pieces, one command:

  box      run a commit in a throwaway temper of its own on this machine —
           its own compose project, ports and database, no model keys — put
           the smoke set through it, take screenshots, tear it all down, and
           write a report.
  gate     watch the repository's own branches for the owner's pushes, run
           the box check on each new commit one at a time, and post the
           answer on the commit as the `temper/boxes` status GitHub's branch
           protection requires.
  deploy   after master moves: restart temper once no run is going, check it
           live, and if that fails put master back with a revert commit
           through the same gate and say so.

Everything here is stdlib only, so it runs from a bare python3 in a systemd
user unit with nothing installed.
"""

__all__ = ["paths"]
