#!/usr/bin/env python3

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ZYGISK_DIR = Path(__file__).resolve().parent


def generated_method_block(header: str, name: str) -> str:
    marker = f"// {name}"
    start = header.index(marker)
    next_method = header.find("\n    // ", start + len(marker))
    end = len(header) if next_method == -1 else next_method
    return header[start:end]


class GrapheneOsExecSpawnReplayTest(unittest.TestCase):
    def test_replay_contract(self) -> None:
        source = textwrap.dedent(
            """
            #include <array>
            #include <cassert>
            #include <cstdint>

            #include "exec_spawn_replay.hpp"

            int main() {
                constexpr std::int64_t ordinary_spawning =
                    zygisk::kGrapheneOsUseZygoteSpawning;

                assert(zygisk::is_grapheneos_exec_spawn_replay_contract(
                    0, std::array{-1, -1}));
                assert(!zygisk::is_grapheneos_exec_spawn_replay_contract(
                    ordinary_spawning, std::array{-1, -1}));
                assert(!zygisk::is_grapheneos_exec_spawn_replay_contract(
                    0, std::array{3, 4}));
                assert(!zygisk::is_grapheneos_exec_spawn_replay_contract(
                    0, std::array{-1, 4}));
                assert(!zygisk::is_grapheneos_exec_spawn_replay_contract(
                    0, std::array{-1}));
                assert(!zygisk::is_grapheneos_exec_spawn_replay_contract(
                    0, std::array{-1, -1, 7}));
            }
            """
        )

        with tempfile.TemporaryDirectory() as directory:
            temp_dir = Path(directory)
            source_path = temp_dir / "exec_spawn_replay_test.cpp"
            binary_path = temp_dir / "exec_spawn_replay_test"
            source_path.write_text(source)

            subprocess.run(
                [
                    os.environ.get("CXX", "c++"),
                    "-std=c++20",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ZYGISK_DIR),
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                check=True,
            )
            subprocess.run([str(binary_path)], check=True)

    def test_generated_grapheneos_c_replay_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["python3", str(ZYGISK_DIR / "gen_jni_hooks.py")],
                cwd=directory,
                check=True,
            )
            header = (Path(directory) / "jni_hooks.hpp").read_text()

        grapheneos_c = generated_method_block(
            header, "nativeForkAndSpecialize_grapheneos_c"
        )
        self.assertIn(
            "([JII[II[[IILjava/lang/String;Ljava/lang/String;[I[IZLjava/lang/String;Ljava/lang/String;ZZ[Ljava/lang/String;[Ljava/lang/String;ZZZ)I",
            grapheneos_c,
        )
        self.assertIn("jlongArray grapheneos_extra_args", grapheneos_c)
        self.assertIn(
            "is_grapheneos_exec_spawn_replay(env, grapheneos_extra_args, fds_to_close)",
            grapheneos_c,
        )
        self.assertIn("ctx.nativeForkAndSpecialize_in_place_pre();", grapheneos_c)
        self.assertIn("jint result = reinterpret_cast<jint(*)", grapheneos_c)
        self.assertIn(
            "ctx.nativeForkAndSpecialize_in_place_post(result == 0);", grapheneos_c
        )
        self.assertIn("return result;", grapheneos_c)
        self.assertIn("ctx.nativeForkAndSpecialize_pre();", grapheneos_c)
        self.assertIn("ctx.nativeForkAndSpecialize_post();", grapheneos_c)
        self.assertIn("return ctx.pid;", grapheneos_c)

        for method in (
            "nativeForkAndSpecialize_grapheneos_u",
            "nativeForkAndSpecialize_grapheneos_b",
            "nativeForkSystemServer_grapheneos_u",
        ):
            block = generated_method_block(header, method)
            self.assertNotIn("is_grapheneos_exec_spawn_replay", block)
            self.assertNotIn("nativeForkAndSpecialize_in_place", block)

    def test_in_place_path_preserves_fd_containment_without_forking(self) -> None:
        module = (ZYGISK_DIR / "module.cpp").read_text()
        start = module.index(
            "void ZygiskContext::nativeForkAndSpecialize_in_place_pre()"
        )
        end = module.index(
            "void ZygiskContext::nativeForkAndSpecialize_in_place_post", start
        )
        in_place_pre = module[start:end]

        snapshot = in_place_pre.index("record_open_fds();")
        module_pre = in_place_pre.index("app_specialize_pre();")
        sanitize = in_place_pre.index("sanitize_fds();")
        self.assertLess(snapshot, module_pre)
        self.assertLess(module_pre, sanitize)
        self.assertNotIn("fork_pre();", in_place_pre)
        self.assertNotIn("old_fork()", in_place_pre)

    def test_boot_complete_keeps_native_bridge_for_late_zygotes(self) -> None:
        daemon = (ZYGISK_DIR / "daemon.rs").read_text()
        start = daemon.index("pub fn reset(&mut self")
        end = daemon.index("pub fn set_prop(&mut self)", start)
        reset = daemon[start:end]

        boot_complete = reset[
            reset.index("if restore {") : reset.index("self.sockets")
        ]
        self.assertIn("self.set_prop();", boot_complete)
        self.assertNotIn("self.restore_prop();", boot_complete)
        self.assertRegex(boot_complete, r"self\.set_prop\(\);\s+return;")

        crash_rollback = reset[reset.index("self.start_count += 1;") :]
        threshold = crash_rollback.index("if self.start_count > 3 {")
        restore = crash_rollback.index("self.restore_prop();", threshold)
        fallback = crash_rollback.index("} else {", restore)
        rearm = crash_rollback.index("self.set_prop();", fallback)
        self.assertLess(threshold, restore)
        self.assertLess(restore, fallback)
        self.assertLess(fallback, rearm)


if __name__ == "__main__":
    unittest.main()
