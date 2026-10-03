"""A throwaway fork tree, shared by the tests that drive .fork/cmake files.

Run the tests with: python3 -m unittest discover -s .fork/tests
"""

import pathlib
import shutil
import tempfile

CMAKE_DIR = pathlib.Path(__file__).resolve().parents[1] / "cmake"


class ForkTree:
    """A throwaway fork root, empty until something is copied or written into
    it. A subclass copies in the .fork/cmake files its own tests drive."""

    def __init__(self, testcase):
        tmp = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)

    def write(self, path, text):
        """Writes text to <root>/<path>, creating the directories it needs."""
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def copy(self, *names):
        """Copies each .fork/cmake/<name> in, at the same path."""
        for name in names:
            dest = self.root / ".fork/cmake" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(CMAKE_DIR / name, dest)
