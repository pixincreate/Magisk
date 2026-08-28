"""Bindings between the GrapheneOS contract baseline and this repo.

The drift monitor proves the baseline still matches upstream sources;
this suite proves Magisk's own artifacts still implement that baseline.
If any of these fail, Zygisk silently stops matching GrapheneOS 17.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parents[1]
BASELINE = REPO / "tests/fixtures/grapheneos_zygote_contract/baseline.json"
ZYGISK = REPO / "native/src/core/zygisk"
JNI_HOOKS = ZYGISK / "jni_hooks.hpp"
REPLAY_HEADER = ZYGISK / "exec_spawn_replay.hpp"
GENERATOR = ZYGISK / "gen_jni_hooks.py"
SEPOLICY_RULES = REPO / "native/src/sepolicy/rules.rs"

# Generated variant -> baseline jni_descriptors key
DESCRIPTOR_BINDINGS = {
    "nativeForkAndSpecialize_grapheneos_c": "nativeForkAndSpecialize",
    "nativeSpecializeAppProcess_grapheneos_c": "nativeSpecializeAppProcess",
    "nativeForkSystemServer_grapheneos_u": "nativeForkSystemServer",
}


def baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def descriptor_of_variant(jni_text: str, variant: str) -> str:
    """Extract the canonical JNI descriptor string of one generated variant."""
    lines = jni_text.splitlines()
    try:
        start = lines.index(f"    // {variant}")
    except ValueError:
        raise AssertionError(
            f"jni_hooks.hpp no longer contains variant '{variant}'; "
            "the GrapheneOS binding is gone from gen_jni_hooks.py"
        )
    for line in lines[start + 1 : start + 5]:
        stripped = line.strip()
        if stripped.startswith('"('):
            return stripped.rstrip(",").strip('"')
    raise AssertionError(f"variant '{variant}' has no descriptor string near line {start}")


class GrapheneOsBindingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = baseline()
        self.jni_text = JNI_HOOKS.read_text(encoding="utf-8")

    def test_jni_descriptors_match_baseline(self) -> None:
        for variant, method in DESCRIPTOR_BINDINGS.items():
            expected = self.baseline["jni_descriptors"][method]
            actual = descriptor_of_variant(self.jni_text, variant)
            self.assertEqual(
                actual,
                expected,
                f"{variant} descriptor drifted from GrapheneOS baseline "
                f"({method}). Regenerate hooks or update the baseline "
                "deliberately.",
            )

    def test_native_fork_flags_index_matches_java_flags_index(self) -> None:
        expected = self.baseline["extra_long_args"]["java_indices"]["IDX_FLAGS"]
        match = re.search(r"kGrapheneOsNativeForkFlagsIndex = (\d+)", REPLAY_HEADER.read_text(encoding="utf-8"))
        if match is None:
            self.fail("kGrapheneOsNativeForkFlagsIndex missing from exec_spawn_replay.hpp")
        self.assertEqual(
            int(match.group(1)),
            expected,
            "C++ flags index no longer matches Java extra-long-args IDX_FLAGS; "
            "the replay predicate would read the wrong flag",
        )

    def test_use_zygote_spawning_flag_matches_java_value(self) -> None:
        expected = self.baseline["extra_long_args"]["use_zygote_spawning"]["value"]
        header = REPLAY_HEADER.read_text(encoding="utf-8")
        match = re.search(r"kGrapheneOsUseZygoteSpawning = 1LL << (\d+)", header)
        if match is None:
            self.fail("kGrapheneOsUseZygoteSpawning missing or changed shape")
        self.assertEqual(
            1 << int(match.group(1)),
            expected,
            "USE_ZYGOTE_SPAWNING bit changed upstream; update "
            "kGrapheneOsUseZygoteSpawning and the replay predicate together",
        )

    def test_replay_predicate_keeps_fd_sentinel(self) -> None:
        sentinel = self.baseline["replay"]["fds_to_close_initial_sentinel"]
        header = REPLAY_HEADER.read_text(encoding="utf-8")
        self.assertIn("is_grapheneos_exec_spawn_replay_contract", header)
        for i, fd in enumerate(sentinel):
            self.assertIn(
                f"fds_to_close[{i}] == {fd}",
                header,
                f"replay predicate lost the fds_to_close[{i}] == {fd} sentinel",
            )
        self.assertIn(
            "(native_fork_flags & kGrapheneOsUseZygoteSpawning) == 0",
            header,
            "replay predicate no longer requires USE_ZYGOTE_SPAWNING to be unset",
        )

    def test_generated_jni_hooks_are_fresh(self) -> None:
        committed = JNI_HOOKS.read_bytes()
        proc = None
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copyfile(GENERATOR, Path(tmp) / GENERATOR.name)
            proc = subprocess.run(
                [sys.executable, GENERATOR.name],
                cwd=tmp,
                capture_output=True,
            )
            generated = (Path(tmp) / "jni_hooks.hpp").read_bytes() if proc.returncode == 0 else b""
        if proc is None or proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace") if proc else "generator did not run"
            self.fail(f"gen_jni_hooks.py failed: {stderr}")
        self.assertEqual(
            committed,
            generated,
            "jni_hooks.hpp is stale: regenerate it with "
            "`cd native/src/core/zygisk && python3 gen_jni_hooks.py`",
        )

    def test_memfd_file_sepolicy_rule_present(self) -> None:
        rules = SEPOLICY_RULES.read_text(encoding="utf-8")
        self.assertIn(
            'allow(["domain"], [proc], ["memfd_file"]',
            rules,
            "Android 17 memfd_file sepolicy rule vanished; Zygisk cannot map "
            "executable memory on GrapheneOS without it",
        )
        for perm in ("getattr", "read", "write", "map", "execute"):
            self.assertRegex(
                rules,
                rf'"memfd_file"\], \[[^\]]*"{perm}"',
                f"memfd_file rule lost permission '{perm}'",
            )


if __name__ == "__main__":
    unittest.main()
