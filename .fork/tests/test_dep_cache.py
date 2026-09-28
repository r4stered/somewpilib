"""Tests for .fork/ci/dep_cache.py. Run with: python3 -m unittest discover -s .fork/tests"""

import io
import pathlib
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ci"))

import dep_cache  # noqa: E402


class FakeStore:
    def __init__(self, objects=None, fail=False):
        self.objects = dict(objects or {})
        self.fail = fail
        self.uploads = []

    def _check(self):
        if self.fail:
            raise dep_cache.StoreError("unreachable")

    def exists(self, name):
        self._check()
        return name in self.objects

    def download(self, name, path):
        self._check()
        pathlib.Path(path).write_bytes(self.objects[name])

    def upload(self, path, name):
        self._check()
        self.objects[name] = pathlib.Path(path).read_bytes()
        self.uploads.append(name)


class TempTree:
    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)

    def write(self, rel, text=""):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class DepArgsTest(unittest.TestCase):
    def test_keeps_only_wpilib_dep_definitions(self):
        args = dep_cache.dep_args(
            "-DWPILIB_DEP_OPENCV_CMAKE_ARGS=-DWITH_X=ON -DCMAKE_C_COMPILER=gcc-15"
            " -DWPILIB_DEPS_DIR=/tmp/x -DWPILIB_WITH_TESTS=ON"
        )
        self.assertEqual(args, ["WPILIB_DEP_OPENCV_CMAKE_ARGS=-DWITH_X=ON"])

    def test_order_does_not_matter(self):
        self.assertEqual(
            dep_cache.dep_args("-DWPILIB_DEP_B=1 -DWPILIB_DEP_A=2"),
            dep_cache.dep_args("-DWPILIB_DEP_A=2 -DWPILIB_DEP_B=1"),
        )

    def test_accepts_a_space_after_d(self):
        self.assertEqual(
            dep_cache.dep_args("-D WPILIB_DEP_X_CMAKE_ARGS=-DA=1;-DB=2"),
            ["WPILIB_DEP_X_CMAKE_ARGS=-DA=1;-DB=2"],
        )

    def test_keeps_the_build_type(self):
        self.assertEqual(
            dep_cache.dep_args("-DCMAKE_BUILD_TYPE=Debug -DCMAKE_C_COMPILER=cl"),
            ["CMAKE_BUILD_TYPE=Debug"],
        )

    def test_splits_words_like_the_unquoted_shell_expansion_does(self):
        # The workflow expands CONFIGURE_ARGS unquoted, so bash splits on
        # whitespace and keeps quote characters; the key must see the same.
        self.assertEqual(
            dep_cache.dep_args("-D'WPILIB_DEP_X=a'"), []
        )
        self.assertEqual(
            dep_cache.dep_args("-DWPILIB_DEP_X='a'"), ["WPILIB_DEP_X='a'"]
        )


class CacheKeyTest(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree(self)
        self.tree.write(".fork/cmake/dependencies.cmake", "provider v1")
        self.tree.write("upstream_utils/libuv.py", 'tag = "v1.50.0"')

    def key(self, dep_args=""):
        return dep_cache.cache_key(
            self.tree.root, "Linux", "X64", "gcc-15", dep_args
        )

    def test_shape_is_os_arch_compiler_hash(self):
        self.assertRegex(self.key(), r"^linux-x64-gcc-15-[0-9a-f]{16}$")

    def test_rejects_characters_unsafe_in_an_object_name(self):
        with self.assertRaises(ValueError):
            dep_cache.cache_key(self.tree.root, "Linux", "X64", "g++-15", "")

    def test_is_stable(self):
        self.assertEqual(self.key(), self.key())

    def test_changes_with_the_recipe(self):
        before = self.key()
        self.tree.write(".fork/cmake/dependencies.cmake", "provider v2")
        self.assertNotEqual(before, self.key())

    def test_changes_with_an_upstream_pin(self):
        before = self.key()
        self.tree.write("upstream_utils/libuv.py", 'tag = "v1.51.0"')
        self.assertNotEqual(before, self.key())

    def test_changes_with_a_fork_pin_or_patch(self):
        before = self.key()
        self.tree.write(".fork/patches/libuv/0001-fix.patch", "diff")
        patched = self.key()
        self.assertNotEqual(before, patched)
        self.tree.write(".fork/pins.cmake", "set(libuv v1.50.0)")
        self.assertNotEqual(patched, self.key())

    def test_changes_with_a_new_recipe_file(self):
        before = self.key()
        self.tree.write(".fork/cmake/deps/opencv.cmake", "recipe")
        self.assertNotEqual(before, self.key())

    def test_changes_with_wpilib_dep_args_and_build_type_only(self):
        before = self.key()
        self.assertEqual(before, self.key("-DWPILIB_WITH_GUI=ON"))
        self.assertNotEqual(before, self.key("-DWPILIB_DEP_LIBUV_GIT_TAG=v1.49.0"))
        self.assertNotEqual(before, self.key("-DCMAKE_BUILD_TYPE=Debug"))

    def test_ignores_files_that_do_not_build_deps(self):
        before = self.key()
        self.tree.write(".fork/cmake/version.cmake", "stamp")
        self.tree.write("wpiutil/src/main.cpp", "int main() {}")
        self.assertEqual(before, self.key())

    def test_a_renamed_input_changes_the_key(self):
        before = self.key()
        self.tree.root.joinpath("upstream_utils/libuv.py").rename(
            self.tree.root / "upstream_utils/libuv2.py"
        )
        self.assertNotEqual(before, self.key())


class RestoreSaveTest(unittest.TestCase):
    def setUp(self):
        self.deps = TempTree(self)

    def populate(self):
        self.deps.write("prefix/libuv/lib/libuv.a", "archive")
        self.deps.write("download/libuv/src/uv.c", "source")
        (self.deps.root / "prefix/libuv/lib/libuv.so").symlink_to("libuv.a")

    def test_save_then_restore_round_trips_prefix_and_download(self):
        self.populate()
        store = FakeStore()
        self.assertEqual(
            dep_cache.save(store, "k", self.deps.root, write=True), "uploaded"
        )

        target = TempTree(self).root
        self.assertTrue(dep_cache.restore(store, "k", target))
        self.assertEqual(
            (target / "prefix/libuv/lib/libuv.a").read_text(), "archive"
        )
        self.assertEqual((target / "download/libuv/src/uv.c").read_text(), "source")
        self.assertTrue((target / "prefix/libuv/lib/libuv.so").is_symlink())

    def test_object_name_lives_under_deps(self):
        self.populate()
        store = FakeStore()
        dep_cache.save(store, "k", self.deps.root, write=True)
        self.assertEqual(store.uploads, ["deps/k.tar.gz"])

    def test_save_leaves_the_build_tree_out(self):
        self.populate()
        self.deps.write("build/libuv/CMakeCache.txt", "x")
        store = FakeStore()
        dep_cache.save(store, "k", self.deps.root, write=True)

        target = TempTree(self).root
        dep_cache.restore(store, "k", target)
        self.assertFalse((target / "build").exists())

    def test_read_only_save_uploads_nothing(self):
        self.populate()
        store = FakeStore()
        self.assertEqual(
            dep_cache.save(store, "k", self.deps.root, write=False), "read-only"
        )
        self.assertEqual(store.uploads, [])

    def test_save_skips_a_key_that_already_exists(self):
        self.populate()
        store = FakeStore({"deps/k.tar.gz": b"old"})
        self.assertEqual(
            dep_cache.save(store, "k", self.deps.root, write=True), "exists"
        )
        self.assertEqual(store.uploads, [])

    def test_save_with_nothing_built_uploads_nothing(self):
        store = FakeStore()
        self.assertEqual(
            dep_cache.save(store, "k", self.deps.root, write=True), "empty"
        )
        self.assertEqual(store.uploads, [])

    def test_restore_miss(self):
        self.assertFalse(dep_cache.restore(FakeStore(), "k", self.deps.root))

    def test_store_errors_propagate_as_store_error(self):
        with self.assertRaises(dep_cache.StoreError):
            dep_cache.restore(FakeStore(fail=True), "k", self.deps.root)

    def test_restore_rejects_members_outside_the_deps_dir(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name in ("prefix/ok.txt", "../escape.txt"):
                info = tarfile.TarInfo(name)
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
        store = FakeStore({"deps/k.tar.gz": buf.getvalue()})
        with self.assertRaises(dep_cache.StoreError):
            dep_cache.restore(store, "k", self.deps.root)
        self.assertFalse((self.deps.root.parent / "escape.txt").exists())
        # A half-finished extract is removed, so recipes never see it.
        self.assertFalse((self.deps.root / "prefix").exists())

    def test_a_corrupt_tarball_is_a_store_error_and_leaves_nothing(self):
        store = FakeStore({"deps/k.tar.gz": b"not a tarball"})
        with self.assertRaises(dep_cache.StoreError):
            dep_cache.restore(store, "k", self.deps.root)
        self.assertEqual(list(self.deps.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
