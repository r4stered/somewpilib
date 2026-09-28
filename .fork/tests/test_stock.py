"""Tests for .fork/cmake/stock.cmake. Run with: python3 -m unittest discover -s .fork/tests

Each test copies stock.cmake into a throwaway fork tree and drives it with
`cmake -P`, so only the parts that work in script mode are covered here. The
fetch and the wiring are covered by the fork CI build.
"""

import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

STOCK = pathlib.Path(__file__).resolve().parents[1] / "cmake/stock.cmake"


class Tree:
    """A throwaway fork root holding stock.cmake and whatever a test writes."""

    def __init__(self, testcase):
        tmp = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        (self.root / ".fork/cmake").mkdir(parents=True)
        shutil.copy(STOCK, self.root / ".fork/cmake/stock.cmake")

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def run(self, script, *defines):
        """Runs script after including stock.cmake. Returns (ok, output)."""
        driver = self.write(
            "driver.cmake",
            f'include("{self.root}/.fork/cmake/stock.cmake")\n'
            + textwrap.dedent(script),
        )
        result = subprocess.run(
            ["cmake", *[f"-D{d}" for d in defines], "-P", str(driver)],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, result.stdout + result.stderr


def upstream_py(tag):
    return textwrap.dedent(
        f"""\
        def main():
            name = "double-conversion"
            url = "https://github.com/google/double-conversion.git"
            tag = "{tag}"
        """
    )


TAG = """\
    wpilib_stock_tag(double-conversion tag source)
    message("TAG=${tag}")
    message("SOURCE=${source}")
"""


class TagTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.tree.write("upstream_utils/double-conversion.py", upstream_py("v3.4.0"))

    def test_default_is_the_upstream_utils_tag_line(self):
        ok, out = self.tree.run(TAG)
        self.assertTrue(ok, out)
        self.assertIn("TAG=v3.4.0\n", out)
        self.assertIn("SOURCE=upstream_utils/double-conversion.py", out)

    def test_a_pin_table_entry_overrides_upstream(self):
        self.tree.write(
            ".fork/pins.txt",
            "# lib tag overrides\n\ndouble-conversion v3.5.0 v3.4.0  # ahead\n",
        )
        ok, out = self.tree.run(TAG)
        self.assertTrue(ok, out)
        self.assertIn("TAG=v3.5.0\n", out)
        self.assertIn("SOURCE=.fork/pins.txt", out)

    def test_pin_entries_for_other_libraries_are_ignored(self):
        self.tree.write(".fork/pins.txt", "upb v36.2 v32.1\n")
        ok, out = self.tree.run(TAG)
        self.assertTrue(ok, out)
        self.assertIn("TAG=v3.4.0\n", out)

    def test_the_git_tag_knob_overrides_both(self):
        self.tree.write(".fork/pins.txt", "double-conversion v3.5.0 v3.4.0\n")
        ok, out = self.tree.run(TAG, "WPILIB_DEP_DOUBLE_CONVERSION_GIT_TAG=v3.3.1")
        self.assertTrue(ok, out)
        self.assertIn("TAG=v3.3.1\n", out)
        self.assertIn("SOURCE=-DWPILIB_DEP_DOUBLE_CONVERSION_GIT_TAG", out)

    def test_an_empty_knob_is_unset(self):
        ok, out = self.tree.run(TAG, "WPILIB_DEP_DOUBLE_CONVERSION_GIT_TAG=")
        self.assertTrue(ok, out)
        self.assertIn("TAG=v3.4.0\n", out)

    def test_fails_without_an_upstream_utils_script(self):
        (self.tree.root / "upstream_utils/double-conversion.py").unlink()
        ok, out = self.tree.run(TAG)
        self.assertFalse(ok)
        self.assertIn("upstream_utils/double-conversion.py", out)

    def test_fails_unless_there_is_exactly_one_tag_line(self):
        self.tree.write(
            "upstream_utils/double-conversion.py",
            upstream_py("v3.4.0") + '    tag = "v3.5.0"\n',
        )
        ok, out = self.tree.run(TAG)
        self.assertFalse(ok)
        self.assertIn("found 2", out)

    def test_fails_on_a_pin_entry_without_the_overridden_tag(self):
        self.tree.write(".fork/pins.txt", "double-conversion v3.5.0\n")
        ok, out = self.tree.run(TAG)
        self.assertFalse(ok)
        self.assertIn("pins.txt", out)

    def test_fails_on_a_duplicate_pin_entry(self):
        self.tree.write(
            ".fork/pins.txt",
            "double-conversion v3.5.0 v3.4.0\ndouble-conversion v3.6.0 v3.4.0\n",
        )
        ok, out = self.tree.run(TAG)
        self.assertFalse(ok)
        self.assertIn("more than once", out)


PATCHES = """\
    wpilib_stock_patches(double-conversion patches digest)
    foreach(p IN LISTS patches)
        cmake_path(GET p FILENAME name)
        message("PATCH=${name}")
    endforeach()
    message("DIGEST=${digest}")
"""


class PatchesTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)

    def patch(self, name, exit_condition=True):
        header = "Exit condition: upstream merges the fix.\n" if exit_condition else ""
        return self.tree.write(
            f".fork/patches/double-conversion/{name}", header + "diff --git a b\n"
        )

    def test_no_patches_dir_means_no_patches(self):
        ok, out = self.tree.run(PATCHES)
        self.assertTrue(ok, out)
        self.assertNotIn("PATCH=", out)

    def test_patches_are_listed_in_name_order(self):
        self.patch("0002-b.patch")
        self.patch("0001-a.patch")
        self.tree.write(".fork/patches/double-conversion/README.md", "not a patch")
        ok, out = self.tree.run(PATCHES)
        self.assertTrue(ok, out)
        self.assertIn("PATCH=0001-a.patch\nPATCH=0002-b.patch\n", out)

    def test_the_digest_changes_with_a_patch(self):
        p = self.patch("0001-a.patch")
        _, before = self.tree.run(PATCHES)
        p.write_text(p.read_text() + "+more\n")
        _, after = self.tree.run(PATCHES)
        digest = lambda out: out.split("DIGEST=")[1]
        self.assertNotEqual(digest(before), digest(after))

    def test_fails_on_a_patch_without_an_exit_condition(self):
        self.patch("0001-a.patch", exit_condition=False)
        ok, out = self.tree.run(PATCHES)
        self.assertFalse(ok)
        self.assertIn("Exit condition", out)
        self.assertIn("0001-a.patch", out)


THIRDPARTY = """\
    wpilib_stock_thirdparty_include("${dir}" include)
    wpilib_stock_shim("${include}/wpi/lib/a.h" "#include <lib/a.h>\\n")
    message("INCLUDE=${include}")
"""


class ThirdpartyTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.dir = self.tree.root / "wpiutil/src/main/native/thirdparty/lib"

    def run_thirdparty(self):
        return self.tree.run(THIRDPARTY, f"dir={self.dir}")

    def test_recreates_the_include_dir_with_the_shim(self):
        ok, out = self.run_thirdparty()
        self.assertTrue(ok, out)
        self.assertIn(f"INCLUDE={self.dir}/include\n", out)
        self.assertEqual(
            (self.dir / "include/wpi/lib/a.h").read_text(), "#include <lib/a.h>\n"
        )

    def test_the_recreated_dir_is_ignored_by_git(self):
        ok, out = self.run_thirdparty()
        self.assertTrue(ok, out)
        subprocess.run(["git", "init", "-q"], cwd=self.tree.root, check=True)
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "wpiutil"],
            cwd=self.tree.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(untracked, "")

    def test_rerunning_leaves_an_unchanged_shim_alone(self):
        self.run_thirdparty()
        shim = self.dir / "include/wpi/lib/a.h"
        before = shim.stat().st_mtime_ns
        ok, out = self.run_thirdparty()
        self.assertTrue(ok, out)
        self.assertEqual(before, shim.stat().st_mtime_ns)

    def test_fails_while_the_vendored_copy_is_still_there(self):
        self.tree.write(
            "wpiutil/src/main/native/thirdparty/lib/include/wpi/lib/a.h", "vendored"
        )
        ok, out = self.run_thirdparty()
        self.assertFalse(ok)
        self.assertIn("manifest", out)


CONFIG = """\
    wpilib_stock_config_dependency("${config}" wpiutil double-conversion)
"""

CONFIG_IN = textwrap.dedent(
    """\
    include(CMakeFindDependencyMacro)
    get_filename_component(SELF_DIR "${CMAKE_CURRENT_LIST_FILE}" PATH)
    find_dependency(Threads)

    include(${SELF_DIR}/wpiutil.cmake)
    """
)


class ConfigDependencyTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.config = self.tree.write("build/wpiutil-config.cmake", CONFIG_IN)

    def run_config(self):
        return self.tree.run(CONFIG, f"config={self.config}")

    def test_adds_find_dependency_before_the_targets_are_imported(self):
        ok, out = self.run_config()
        self.assertTrue(ok, out)
        text = self.config.read_text()
        dep = text.index("find_dependency(double-conversion")
        self.assertLess(text.index("find_dependency(Threads)"), dep)
        self.assertLess(dep, text.index("include(${SELF_DIR}/wpiutil.cmake)"))

    def test_searches_the_installed_prefix_first(self):
        self.run_config()
        self.assertIn(
            'find_dependency(double-conversion HINTS "${SELF_DIR}/../..")',
            self.config.read_text(),
        )

    def test_is_idempotent(self):
        self.run_config()
        once = self.config.read_text()
        ok, out = self.run_config()
        self.assertTrue(ok, out)
        self.assertEqual(once, self.config.read_text())

    def test_fails_when_the_config_no_longer_imports_its_targets(self):
        self.config.write_text("include(CMakeFindDependencyMacro)\n")
        ok, out = self.run_config()
        self.assertFalse(ok)
        self.assertIn("wpiutil-config.cmake", out)


if __name__ == "__main__":
    unittest.main()
