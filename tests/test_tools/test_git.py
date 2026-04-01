"""Tests for Git tool."""

import os
import subprocess
import tempfile

import pytest

from temper_ai.tools.git import Git


@pytest.fixture
def git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        # Create initial commit
        filepath = os.path.join(tmpdir, "README.md")
        with open(filepath, "w") as f:
            f.write("# Test Repo\n")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True)
        yield tmpdir


class TestGitBasics:
    def test_status(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="status")
        assert result.success
        assert "nothing to commit" in result.result

    def test_log(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="log --oneline")
        assert result.success
        assert "initial" in result.result

    def test_diff_no_changes(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="diff")
        assert result.success

    def test_branch(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="branch")
        assert result.success


class TestGitModifications:
    def test_add_and_commit(self, git_repo):
        # Create a new file
        with open(os.path.join(git_repo, "new.txt"), "w") as f:
            f.write("new file\n")

        git = Git(workspace=git_repo)

        result = git.execute(command="add new.txt")
        assert result.success

        result = git.execute(command="commit -m add-new-file")
        assert result.success

        result = git.execute(command="log --oneline")
        assert "add-new-file" in result.result


class TestGitSafety:
    def test_blocks_force_push(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="push --force origin main")
        assert not result.success
        assert "Force push" in result.error

    def test_blocks_force_push_short_flag(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="push -f origin main")
        assert not result.success

    def test_blocks_filter_branch(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="filter-branch --all")
        assert not result.success
        assert "not allowed" in result.error

    def test_empty_command(self, git_repo):
        git = Git(workspace=git_repo)
        result = git.execute(command="")
        assert not result.success
        assert "Empty" in result.error
