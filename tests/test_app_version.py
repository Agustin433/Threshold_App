import tempfile
import unittest
from pathlib import Path

from modules.app_version import _read_git_commit


class ReadGitCommitTest(unittest.TestCase):
    def test_loose_and_packed_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git" / "refs" / "heads").mkdir(parents=True)
            (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            (root / ".git" / "packed-refs").write_text("# pack\nabc1234def refs/heads/main\n")
            self.assertEqual(_read_git_commit(root), "abc1234def")
            (root / ".git" / "refs" / "heads" / "main").write_text("fff0000aaa\n")
            self.assertEqual(_read_git_commit(root), "fff0000aaa")

    def test_without_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_read_git_commit(Path(tmp)))
