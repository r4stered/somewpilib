"""Tests for the provider dispatch in .fork/cmake/dependencies.cmake.

Run with: python3 -m unittest discover -s .fork/tests

Each test copies the provider into a throwaway fork tree, writes a recipe into
its deps/ dir, and configures a tiny project that switches the provider on the
way a subdirectory consumer does. What a recipe then builds is covered by the
fork CI build, not here.
"""

import subprocess
import textwrap
import unittest

from forktree import ForkTree

# Everything dependencies.cmake includes, besides the recipes in deps/.
PROVIDER_FILES = (
    "dependencies.cmake",
    "stock.cmake",
    "stock-fetch.cmake",
    "compile-workarounds.cmake",
    "version.cmake",
)


class Tree(ForkTree):
    """A throwaway fork root holding the provider, with no recipes of its own."""

    def __init__(self, testcase):
        super().__init__(testcase)
        self.copy(*PROVIDER_FILES)

    def recipe(self, name, text):
        return self.write(f".fork/cmake/deps/{name}", textwrap.dedent(text))

    def real_recipe(self, name):
        """Copies one of the fork's own recipes in."""
        self.copy(f"deps/{name}")

    def checkout(self, text=""):
        """A stand-in for a library's clone, for FETCHCONTENT_SOURCE_DIR_<LIB>."""
        path = self.root / "checkout"
        path.mkdir(exist_ok=True)
        if text:
            self.write("checkout/CMakeLists.txt", textwrap.dedent(text))
        return path

    def configure(self, project, *defines, subdirectory=None):
        """Configures a project that switches the provider on. Returns (ok, output)."""
        source = self.root / "project"
        source.mkdir(exist_ok=True)
        project = textwrap.dedent(project)
        if subdirectory is not None:
            (source / "sub").mkdir(exist_ok=True)
            (source / "sub/CMakeLists.txt").write_text(
                textwrap.dedent(subdirectory), encoding="utf-8"
            )
            project += "add_subdirectory(sub)\n"
        (source / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 4.4)\nproject(probe NONE)\n" + project,
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "cmake",
                "-S",
                str(source),
                "-B",
                str(source / "build"),
                "-DCMAKE_PROJECT_TOP_LEVEL_INCLUDES="
                f"{self.root}/.fork/cmake/dependencies.cmake",
                *[f"-D{d}" for d in defines],
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, result.stdout + result.stderr


FAKE_RECIPE = """\
    macro(_wpilib_provide_Fake)
        message("ARGS=[${ARGN}]")
        set(Fake_FOUND TRUE)
    endmacro()
"""


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)

    def test_a_recipe_answers_find_package_for_its_package(self):
        self.tree.recipe("fake.cmake", FAKE_RECIPE)
        ok, out = self.tree.configure(
            """\
            find_package(Fake REQUIRED)
            message("FOUND=${Fake_FOUND}")
            """
        )
        self.assertTrue(ok, out)
        self.assertIn("FOUND=TRUE", out)

    def test_the_recipe_gets_the_rest_of_the_find_package_arguments(self):
        self.tree.recipe("fake.cmake", FAKE_RECIPE)
        ok, out = self.tree.configure("find_package(Fake 1.2 EXACT REQUIRED)\n")
        self.assertTrue(ok, out)
        self.assertIn("ARGS=[1.2;EXACT;REQUIRED]", out)

    def test_a_package_without_a_recipe_falls_through(self):
        # Nothing answers it, so CMake's own search runs, finds nothing, and
        # reports that as 0 rather than leaving Fake_FOUND unset.
        ok, out = self.tree.configure(
            """\
            find_package(Fake QUIET)
            message("FOUND=[${Fake_FOUND}]")
            """
        )
        self.assertTrue(ok, out)
        self.assertIn("FOUND=[0]", out)

    def test_a_recipe_only_answers_its_own_package(self):
        self.tree.recipe("fake.cmake", FAKE_RECIPE)
        ok, out = self.tree.configure(
            """\
            find_package(Other QUIET)
            message("FOUND=[${Other_FOUND}]")
            """
        )
        self.assertTrue(ok, out)
        self.assertIn("FOUND=[0]", out)
        self.assertNotIn("ARGS=[", out)


# A trivial project that installs an OpenCVConfig.cmake, standing in for the
# real clone so these tests stay off the network. It only has to be found.
STAND_IN_OPENCV = """\
    cmake_minimum_required(VERSION 3.10)
    project(opencv NONE)
    file(
        WRITE "${CMAKE_CURRENT_BINARY_DIR}/OpenCVConfig.cmake"
        "set(OpenCV_FOUND TRUE)\\n"
    )
    install(
        FILES "${CMAKE_CURRENT_BINARY_DIR}/OpenCVConfig.cmake"
        DESTINATION lib/cmake/opencv4
    )
"""


class OpenCVTest(unittest.TestCase):
    """The OpenCV recipe's own switches. What it builds is covered by fork CI."""

    def setUp(self):
        self.tree = Tree(self)
        self.tree.real_recipe("opencv.cmake")

    def test_use_system_hands_the_call_back(self):
        ok, out = self.tree.configure(
            "find_package(OpenCV QUIET)\n", "WPILIB_DEP_OPENCV_USE_SYSTEM=ON"
        )
        self.assertTrue(ok, out)
        # Whatever CMake's own search then found, the recipe built nothing.
        self.assertNotIn("opencv:", out)

    def test_otherwise_it_builds_opencv_itself(self):
        # An empty checkout reaches the sub-build, which then fails there.
        ok, out = self.tree.configure(
            "find_package(OpenCV QUIET)\n",
            f"FETCHCONTENT_SOURCE_DIR_OPENCV={self.tree.checkout()}",
        )
        self.assertFalse(ok)
        self.assertIn("stock opencv: configure failed", out)

    def test_it_builds_once_however_often_the_package_is_asked_for(self):
        # Upstream looks for OpenCV twice: at the top level for cscore, and
        # again inside tools/wpical. The second call must not build it again.
        ok, out = self.tree.configure(
            """\
            find_package(OpenCV REQUIRED)
            message("ONE=${OpenCV_FOUND}")
            """,
            f"FETCHCONTENT_SOURCE_DIR_OPENCV={self.tree.checkout(STAND_IN_OPENCV)}",
            subdirectory="""\
            find_package(OpenCV REQUIRED)
            message("TWO=${OpenCV_FOUND}")
            """,
        )
        self.assertTrue(ok, out)
        # find_package reports a config it found as 1, whatever the config set.
        self.assertIn("ONE=1", out)
        self.assertIn("TWO=1", out)
        self.assertEqual(out.count("opencv: building"), 1, out)

    def test_the_cmake_args_knob_overrides_the_recipe(self):
        # The knob is appended after the recipe's own arguments, so it wins:
        # the recipe passes -DBUILD_TESTS=OFF.
        ok, out = self.tree.configure(
            "find_package(OpenCV REQUIRED)\n",
            f"FETCHCONTENT_SOURCE_DIR_OPENCV={self.tree.checkout(STAND_IN_OPENCV)}",
            "WPILIB_DEP_OPENCV_CMAKE_ARGS=-DBUILD_TESTS=ON",
        )
        self.assertTrue(ok, out)
        cache = (
            self.tree.root / "project/build/_wpilib_deps/build/opencv/CMakeCache.txt"
        ).read_text()
        self.assertRegex(cache, r"(?m)^BUILD_TESTS:[A-Z]+=ON$")


if __name__ == "__main__":
    unittest.main()
