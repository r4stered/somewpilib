"""Tests for .fork/sync.py. Run with: python3 -m unittest discover -s .fork/tests"""

import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import sync  # noqa: E402


def manifest(*lines):
    return sync.Manifest.parse("\n".join(lines))


class MatcherTest(unittest.TestCase):
    def test_directory_pattern_removes_everything_under_it(self):
        m = manifest("wpilibj/")
        self.assertTrue(m.removes("wpilibj/build.gradle"))
        self.assertTrue(m.removes("wpilibj/src/main/java/Foo.java"))
        self.assertFalse(m.removes("wpilibc/build.gradle"))
        self.assertFalse(m.removes("wpilibjExamples/foo.cpp"))

    def test_negation_reincludes_a_file_under_a_removed_directory(self):
        m = manifest("wpilibj/", "!wpilibj/src/generate/*.json")
        self.assertFalse(m.removes("wpilibj/src/generate/hids.json"))
        self.assertTrue(m.removes("wpilibj/src/generate/hids.json.jinja"))
        self.assertTrue(m.removes("wpilibj/src/generate/java/Foo.java"))

    def test_negated_directory_can_be_removed_again_by_a_later_pattern(self):
        m = manifest(
            "**/thirdparty/*/",
            "!thirdparty/catch2/",
            "**/BUILD.bazel",
        )
        self.assertFalse(m.removes("thirdparty/catch2/src/catch.cpp"))
        self.assertTrue(m.removes("thirdparty/catch2/BUILD.bazel"))
        self.assertTrue(m.removes("thirdparty/imgui_suite/imgui/imgui.h"))

    def test_last_matching_pattern_wins(self):
        m = manifest("!keep.txt", "keep.txt")
        self.assertTrue(m.removes("keep.txt"))

    def test_pattern_without_slash_matches_at_any_depth(self):
        m = manifest("*.gradle", "Info.plist")
        self.assertTrue(m.removes("build.gradle"))
        self.assertTrue(m.removes("wpiutil/build.gradle"))
        self.assertTrue(m.removes("tools/sysid/Info.plist"))
        self.assertFalse(m.removes("wpiutil/build.gradle.kts"))

    def test_pattern_with_a_slash_is_anchored_to_the_root(self):
        m = manifest("src/dev/", "/gradle/")
        self.assertTrue(m.removes("src/dev/main.cpp"))
        self.assertFalse(m.removes("hal/src/dev/main.cpp"))
        self.assertTrue(m.removes("gradle/wrapper.jar"))
        self.assertFalse(m.removes("shared/gradle/x"))

    def test_double_star_matches_any_number_of_directories(self):
        m = manifest("**/java/", "a/**/b.txt", "c/**")
        self.assertTrue(m.removes("java/Foo.java"))
        self.assertTrue(m.removes("wpiutil/src/main/java/Foo.java"))
        self.assertTrue(m.removes("a/b.txt"))
        self.assertTrue(m.removes("a/x/y/b.txt"))
        self.assertTrue(m.removes("c/d/e"))
        self.assertFalse(m.removes("c"))

    def test_trailing_slash_matches_directories_only(self):
        m = manifest("**/java/")
        self.assertFalse(m.removes("tools/java"))
        self.assertTrue(m.removes("tools/java/x"))
        # mrcal_java is not a directory named java.
        self.assertFalse(
            m.removes("tools/wpical/src/main/native/thirdparty/mrcal_java/src/w.cpp")
        )

    def test_star_does_not_cross_slashes(self):
        m = manifest("upstream_utils/*_patches/")
        self.assertTrue(m.removes("upstream_utils/eigen_patches/0001.patch"))
        self.assertFalse(m.removes("upstream_utils/eigen.py"))
        self.assertFalse(m.removes("upstream_utils/a/b_patches/0001.patch"))

    def test_question_mark_and_character_class(self):
        m = manifest("file?.[ch]", "x[!a].txt")
        self.assertTrue(m.removes("file1.c"))
        self.assertTrue(m.removes("dir/fileA.h"))
        self.assertFalse(m.removes("file12.c"))
        self.assertFalse(m.removes("file1.cpp"))
        self.assertTrue(m.removes("xb.txt"))
        self.assertFalse(m.removes("xa.txt"))

    def test_comments_blank_lines_and_escapes(self):
        m = manifest("# a comment", "", "   ", "\\#literal", "\\!bang", "a.txt   ")
        self.assertTrue(m.removes("#literal"))
        self.assertTrue(m.removes("!bang"))
        self.assertTrue(m.removes("a.txt"))
        self.assertFalse(m.removes("# a comment"))

    def test_double_star_not_next_to_a_slash_is_a_single_star(self):
        m = manifest("foo**bar")
        self.assertTrue(m.removes("fooXYbar"))
        self.assertFalse(m.removes("foo/q/bar"))
        m = manifest("a**/b")
        self.assertTrue(m.removes("aXY/b"))
        self.assertFalse(m.removes("a/x/b"))

    def test_character_class_never_matches_a_slash(self):
        m = manifest("x[!a]y")
        self.assertTrue(m.removes("xby"))
        self.assertFalse(m.removes("x/y"))

    def test_dots_are_literal(self):
        m = manifest(".bazel*", "copy.bara.sky")
        self.assertTrue(m.removes(".bazelrc"))
        self.assertFalse(m.removes("xbazelrc"))
        self.assertFalse(m.removes("copyXbaraXsky"))


class Repo:
    """A throwaway git repo for exercising prune and the invariants."""

    def __init__(self, testcase):
        tmp = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout

    def write(self, path, text="x\n"):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def tracked(self):
        return set(self.git("ls-files").split())

    def files_on_disk(self):
        return {
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(self.root).parts
        }


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        for path in [
            "CMakeLists.txt",
            "wpilibj/build.gradle",
            "wpilibj/src/generate/hids.json",
            "wpiutil/src/main/java/Foo.java",
            "wpiutil/src/main/native/cpp/a.cpp",
        ]:
            self.repo.write(path)
        self.repo.commit()
        self.manifest = manifest("wpilibj/", "!wpilibj/src/generate/*.json", "**/java/")

    def test_removes_exactly_the_matching_tracked_files(self):
        removed = sync.prune(self.repo.root, self.manifest)
        self.assertEqual(
            set(removed), {"wpilibj/build.gradle", "wpiutil/src/main/java/Foo.java"}
        )
        kept = {
            "CMakeLists.txt",
            "wpilibj/src/generate/hids.json",
            "wpiutil/src/main/native/cpp/a.cpp",
        }
        self.assertEqual(self.repo.tracked(), kept)
        self.assertEqual(self.repo.files_on_disk(), kept)
        self.assertFalse((self.repo.root / "wpiutil/src/main/java").exists())

    def test_running_twice_is_a_no_op(self):
        sync.prune(self.repo.root, self.manifest)
        status = self.repo.git("status", "--porcelain")
        self.assertEqual(sync.prune(self.repo.root, self.manifest), [])
        self.assertEqual(self.repo.git("status", "--porcelain"), status)

    def test_removes_untracked_output_written_into_removed_paths(self):
        self.repo.write("wpiutil/src/generated/main/java/Gen.java")
        self.repo.write("wpiutil/src/generated/main/native/cpp/Gen.cpp")
        removed = sync.prune(self.repo.root, self.manifest)
        self.assertIn("wpiutil/src/generated/main/java/Gen.java", removed)
        self.assertFalse(
            (self.repo.root / "wpiutil/src/generated/main/java").exists()
        )
        self.assertTrue(
            (self.repo.root / "wpiutil/src/generated/main/native/cpp/Gen.cpp").exists()
        )

    def test_leaves_a_nested_repository_alone(self):
        nested = Repo(self)
        nested.write("f.txt")
        nested.commit()
        (self.repo.root / "wpilibj").mkdir(exist_ok=True)
        nested.root.rename(self.repo.root / "wpilibj/nested")
        sync.prune(self.repo.root, self.manifest)
        self.assertTrue((self.repo.root / "wpilibj/nested/f.txt").exists())

    def test_handles_paths_git_would_quote(self):
        self.repo.write("wpilibj/sp ace/ünï.txt")
        self.repo.commit()
        sync.prune(self.repo.root, self.manifest)
        self.assertNotIn("wpilibj/sp ace/ünï.txt", self.repo.files_on_disk())


SWITCH_ON = 'list(APPEND CMAKE_PROJECT_TOP_LEVEL_INCLUDES "x.cmake")'


class InvariantsTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.repo.write("CMakeLists.txt", "cmake_minimum_required()\nproject(p)\n")
        self.repo.write("wpiutil/a.cpp", "int a;\n")
        self.repo.write("wpilibj/build.gradle")
        self.base = self.repo.commit("fork point")
        self.manifest = manifest("wpilibj/")
        self.surface = sync.ModifySurface.parse(
            "# the provider switch-on\n" f"CMakeLists.txt +{SWITCH_ON}\n"
        )
        sync.prune(self.repo.root, self.manifest)
        self.repo.write("CMakeLists.txt", f"cmake_minimum_required()\n{SWITCH_ON}\nproject(p)\n")
        self.repo.write(".fork/sync.py", "fork-owned\n")

    def check(self, **kwargs):
        return sync.check(
            self.repo.root, self.manifest, self.surface, self.base, **kwargs
        )

    def test_pass_on_a_pruned_tree_with_exactly_the_modify_surface(self):
        self.assertEqual(self.check(), [])
        self.repo.commit()
        self.assertEqual(self.check(), [])

    def test_fail_when_a_manifest_path_is_tracked(self):
        self.repo.write("wpilibj/src/main/java/Foo.java")
        self.repo.git("add", "-A")
        self.assertEqual(
            self.check(), ["manifest path exists: wpilibj/src/main/java/Foo.java"]
        )

    def test_fail_when_a_manifest_path_is_untracked_on_disk(self):
        self.repo.write("wpilibj/src/main/java/Foo.java")
        self.assertEqual(
            self.check(), ["manifest path exists: wpilibj/src/main/java/Foo.java"]
        )

    def test_fail_on_an_extra_carried_edit(self):
        self.repo.write("wpiutil/a.cpp", "int a;\nint b;\n")
        self.assertEqual(
            self.check(), ["carried edit not in modify surface: wpiutil/a.cpp +int b;"]
        )

    def test_fail_on_a_removed_line_in_a_carried_file(self):
        self.repo.write("wpiutil/a.cpp", "")
        self.assertEqual(
            self.check(), ["carried edit not in modify surface: wpiutil/a.cpp -int a;"]
        )

    def test_edit_containing_a_form_feed_is_reported_whole(self):
        self.repo.write("wpiutil/a.cpp", "int a;\n// x\x0cy\n")
        self.assertEqual(
            self.check(),
            ["carried edit not in modify surface: wpiutil/a.cpp +// x\x0cy"],
        )

    def test_user_diff_config_does_not_change_the_edits(self):
        self.repo.git("config", "diff.external", "false")
        self.repo.git("config", "diff.noprefix", "true")
        self.repo.write("wpiutil/a.cpp", "int a;\nint b;\n")
        self.assertEqual(
            self.check(), ["carried edit not in modify surface: wpiutil/a.cpp +int b;"]
        )

    def test_fail_when_a_carried_file_is_deleted(self):
        (self.repo.root / "wpiutil/a.cpp").unlink()
        self.assertEqual(
            self.check(),
            ["carried edit not in modify surface: wpiutil/a.cpp (deleted)"],
        )

    def test_fail_when_the_modify_surface_is_missing(self):
        self.repo.write("CMakeLists.txt", "cmake_minimum_required()\nproject(p)\n")
        self.assertEqual(
            self.check(),
            [f"modify-surface entry missing from the tree: CMakeLists.txt +{SWITCH_ON}"],
        )

    def test_missing_modify_surface_allowed_when_not_required(self):
        self.repo.write("CMakeLists.txt", "cmake_minimum_required()\nproject(p)\n")
        self.assertEqual(self.check(require_surface=False), [])
        self.repo.write("wpiutil/a.cpp", "int b;\n")
        self.assertEqual(len(self.check(require_surface=False)), 2)

    def test_the_same_edit_twice_is_not_the_surface(self):
        self.repo.write(
            "CMakeLists.txt",
            f"cmake_minimum_required()\n{SWITCH_ON}\n{SWITCH_ON}\nproject(p)\n",
        )
        self.assertEqual(
            self.check(),
            [f"carried edit not in modify surface: CMakeLists.txt +{SWITCH_ON}"],
        )


class CliTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.repo.write("CMakeLists.txt", "project(p)\n")
        self.repo.write("wpilibj/build.gradle")
        self.repo.commit("fork point")
        self.repo.git("branch", "upstream-main")
        self.repo.write(".fork/manifest", "wpilibj/\n")
        self.repo.write(".fork/modify-surface.txt", f"CMakeLists.txt +{SWITCH_ON}\n")
        self.repo.commit("tooling")

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = sync.main([*args, "--upstream", "upstream-main"], self.repo.root)
        return code, out.getvalue()

    def test_prune_then_check(self):
        code, out = self.run_cli("prune")
        self.assertEqual(code, 0, out)
        self.assertNotIn("wpilibj/build.gradle", self.repo.tracked())
        # The switch-on line isn't there yet, so the full check fails ...
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("modify-surface entry missing", out)
        # ... until it is.
        self.repo.write("CMakeLists.txt", f"{SWITCH_ON}\nproject(p)\n")
        self.assertEqual(self.run_cli("check"), (0, ""))

    def test_prune_fails_on_an_extra_carried_edit(self):
        self.repo.write("CMakeLists.txt", "project(q)\n")
        code, out = self.run_cli("prune")
        self.assertEqual(code, 1)
        self.assertIn("carried edit not in modify surface: CMakeLists.txt +project(q)", out)

    def test_base_is_the_merge_base_with_upstream(self):
        # Upstream moved on after the fork point; that isn't a fork edit.
        self.repo.git("checkout", "-q", "upstream-main")
        self.repo.write("CMakeLists.txt", "project(new)\n")
        self.repo.commit("upstream change")
        self.repo.git("checkout", "-q", "-")
        self.assertEqual(self.run_cli("prune")[0], 0)


FORK = pathlib.Path(__file__).resolve().parents[1]


class ForkManifestTest(unittest.TestCase):
    """The fork's own .fork/manifest keeps and removes what the spec says."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = sync.Manifest.load(FORK / "manifest")

    def assert_carried(self, *paths):
        for path in paths:
            self.assertFalse(self.manifest.removes(path), path)

    def assert_removed(self, *paths):
        for path in paths:
            self.assertTrue(self.manifest.removes(path), path)

    def test_hid_json_survives_while_wpilibj_goes(self):
        self.assert_carried(
            "wpilibj/src/generate/hids.json",
            "wpilibj/src/generate/hids.schema.json",
            "wpilibj/src/generate/first_ds_hids.json",
            "wpilibj/src/generate/first_ds_hids.schema.json",
        )
        self.assert_removed(
            "wpilibj/build.gradle",
            "wpilibj/generate_hids.py",
            "wpilibj/src/generate/main/java/HID.java.jinja",
        )

    def test_systemcore_interfaces_survive_while_the_backend_goes(self):
        self.assert_carried(
            "hal/src/main/native/include/wpi/hal/cpp/MrcLibDs.hpp",
            "hal/src/main/native/include/wpi/hal/cpp/MrcLibAlert.hpp",
            "wpinet/src/main/native/cpp/SystemCoreResolverClient.cpp",
            "wpinet/src/main/native/include/wpi/net/SystemCoreResolverClient.hpp",
        )
        self.assert_removed(
            "hal/src/main/native/systemcore/HAL.cpp",
            "hal/src/main/native/cpp/mrclib/MrcLibDs.cpp",
            "simulation/halsim_ds_socket/CMakeLists.txt",
        )

    def test_iota_negated_systemcore_files_survive(self):
        self.assert_carried(
            "hal/src/main/native/systemcore/Threads.cpp",
            "hal/src/main/native/systemcore/Notifier.cpp",
            "hal/src/main/native/systemcore/mockdata/DIOData.cpp",
        )

    def test_mrcal_java_cpp_survives(self):
        self.assert_carried(
            "tools/wpical/src/main/native/thirdparty/mrcal_java/src/mrcal_wrapper.cpp",
            "tools/wpical/src/main/native/thirdparty/mrcal_java/include/mrcal_wrapper.h",
        )

    def test_java_and_jni_go_from_kept_modules(self):
        self.assert_removed(
            "wpiutil/src/main/java/org/wpilib/util/Foo.java",
            "ntcore/src/generated/main/java/org/wpilib/Topic.java",
            "cameraserver/multiCameraServer/src/main/java/Main.java",
            "hal/src/main/native/cpp/jni/HAL.cpp",
            "ntcore/src/generate/main/native/cpp/jni/types_jni.cpp.jinja",
            "wpiutil/src/main/native/include/wpi/util/jni_util.hpp",
            "wpiutil/src/test/native/cpp/JniUtilTest.cpp",
        )

    def test_carried_thirdparty_survives_and_new_vendored_libs_go(self):
        self.assert_carried(
            "wpiutil/src/main/native/thirdparty/llvm/include/wpi/util/SmallVector.hpp",
            "wpiutil/src/main/native/thirdparty/json/src/json.cpp",
            "wpiutil/src/main/native/thirdparty/sigslot/include/wpi/util/Signal.h",
            "wpinet/src/main/native/thirdparty/tcpsockets/cpp/TCPStream.cpp",
            "glass/src/lib/native/thirdparty/mrccomm/src/AnsiDisplayState.cpp",
            "thirdparty/imgui_suite/generated/fonts/src/DroidSans.inc",
        )
        self.assert_removed(
            "wpiutil/src/main/native/thirdparty/newlib/include/x.h",
            "thirdparty/newlib/CMakeLists.txt",
            "upstream_utils/eigen_patches/0001-x.patch",
            "wpimath/src/main/native/thirdparty/eigen/include/MODULE.bazel",
            "thirdparty/catch2/build.gradle",
        )
        self.assert_carried("upstream_utils/eigen.py")

    def test_fork_owned_files_survive(self):
        self.assert_carried(
            ".github/workflows/fork-build.yml",
            ".github/README.md",
            ".github/CONTRIBUTING.md",
            ".fork/sync.py",
            ".fork/manifest",
        )
        self.assert_removed(
            ".github/workflows/cmake.yml", ".github/CODEOWNERS", ".github/labeler.yml"
        )

    def test_build_systems_go(self):
        self.assert_removed(
            "BUILD.bazel",
            "MODULE.bazel.lock",
            ".bazelrc",
            "wpiutil/BUILD.bazel",
            "wpiutil/robotpy_pybind_build_info.bzl",
            "build.gradle",
            "gradlew",
            "gradle/wrapper/gradle-wrapper.jar",
            "buildSrc/build.gradle",
            "wpiutil/build.gradle",
            "glass/Info.plist",
        )
        self.assert_carried("CMakeLists.txt", "wpiutil/CMakeLists.txt", "cmake/modules/WPILibMacOSXBundleInfo.plist.in")

    def test_dev_executables_cmake_builds_survive(self):
        self.assert_carried(
            "ntcore/src/dev/native/cpp/main.cpp",
            "wpigui/src/dev/native/cpp/main.cpp",
            "wpiutil/src/dev/native/cpp/main.cpp",
        )
        self.assert_removed("hal/src/dev/native/cpp/main.cpp")

    def test_temporary_negations_are_marked(self):
        text = (FORK / "manifest").read_text()
        block = text.split("# TEMPORARY:")[1].split("# END TEMPORARY")[0]
        negations = [l for l in block.splitlines() if l.startswith("!")]
        self.assertTrue(negations)
        self.assertTrue(all("thirdparty/" in l for l in negations))


class ModifySurfaceTest(unittest.TestCase):
    def test_parse_keeps_leading_whitespace_of_the_line(self):
        s = sync.ModifySurface.parse("# c\n\na/b.txt +  indented\nc.txt -gone\n")
        self.assertEqual(sorted(s.entries), ["a/b.txt +  indented", "c.txt -gone"])


if __name__ == "__main__":
    unittest.main()
