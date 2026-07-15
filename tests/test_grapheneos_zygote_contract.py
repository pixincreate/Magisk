from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import grapheneos_zygote_contract as contract

FIXTURE = Path(__file__).parent / "fixtures" / "grapheneos_zygote_contract"
SOURCES = FIXTURE / "sources"
BASELINE = FIXTURE / "baseline.json"


class GrapheneOsZygoteContractTest(unittest.TestCase):
    def test_extract_contract_from_offline_fixture(self) -> None:
        current = contract.extract_contract(contract.read_sources(SOURCES))

        self.assertEqual(current, json.loads(BASELINE.read_text(encoding="utf-8")))

    def test_formatting_tolerance_for_jni_descriptor_fragments(self) -> None:
        native = (SOURCES / "core/jni/com_android_internal_os_Zygote.cpp").read_text(encoding="utf-8")
        native = native.replace('"nativeForkSystemServer", "(II[II[[IJJ)I"', '"nativeForkSystemServer",\n         "(II[II[[IJJ)I"')
        sources = contract.read_sources(SOURCES)
        sources["core/jni/com_android_internal_os_Zygote.cpp"] = native

        current = contract.extract_contract(sources)

        self.assertEqual(current["canonical_sha256"], "a19bec7b1ff9fb0b8211fdfc777e5e8c15a6e386c9fa84cc2b52d94101f26829")

    def test_missing_field_fails_loudly(self) -> None:
        sources = contract.read_sources(SOURCES)
        sources["core/java/com/android/internal/os/ZygoteExtraArgs.java"] = sources[
            "core/java/com/android/internal/os/ZygoteExtraArgs.java"
        ].replace("int USE_ZYGOTE_SPAWNING = 1 << 3;", "")

        with self.assertRaisesRegex(contract.ContractError, "USE_ZYGOTE_SPAWNING"):
            contract.extract_contract(sources)

    def test_partial_extra_args_order_fails_loudly(self) -> None:
        sources = contract.read_sources(SOURCES)
        sources["core/java/com/android/internal/os/ZygoteExtraArgs.java"] = sources[
            "core/java/com/android/internal/os/ZygoteExtraArgs.java"
        ].replace("res[IDX_FLAGS] = flags;", "")

        with self.assertRaisesRegex(contract.ContractError, "Java extra-long-args order"):
            contract.extract_contract(sources)

    def test_exec_spawning_semantic_flip_fails_loudly(self) -> None:
        sources = contract.read_sources(SOURCES)
        sources["core/java/com/android/internal/os/ZygoteExtraArgs.java"] = sources[
            "core/java/com/android/internal/os/ZygoteExtraArgs.java"
        ].replace("return !hasFlag(Flag.USE_ZYGOTE_SPAWNING);", "return hasFlag(Flag.USE_ZYGOTE_SPAWNING);")

        with self.assertRaisesRegex(contract.ContractError, "shouldUseExecSpawning contract"):
            contract.extract_contract(sources)

    def test_socket_assignment_outside_replay_guard_fails_loudly(self) -> None:
        sources = contract.read_sources(SOURCES)
        connection = sources["core/java/com/android/internal/os/ZygoteConnection.java"]
        connection = connection.replace(
            "if (fd != null) { fdsToClose[0] = fd.getInt$(); }",
            "if (fd != null) { }",
        ).replace(
            "boolean shouldUseExecSpawning",
            "fdsToClose[0] = fd.getInt$();\n        boolean shouldUseExecSpawning",
        )
        sources["core/java/com/android/internal/os/ZygoteConnection.java"] = connection

        with self.assertRaisesRegex(contract.ContractError, "guarded fdsToClose assignments"):
            contract.extract_contract(sources)

    def test_canonical_hash_is_stable_under_key_order(self) -> None:
        current = contract.extract_contract(contract.read_sources(SOURCES))
        shuffled = {"upstream": current["upstream"], "replay": current["replay"], "jni_descriptors": current["jni_descriptors"], "extra_long_args": current["extra_long_args"]}

        self.assertEqual(contract.canonical_hash(shuffled), current["canonical_sha256"])

    def test_source_revision_is_not_semantic_drift(self) -> None:
        sources = contract.read_sources(SOURCES)
        first = contract.extract_contract(sources, "a" * 40)
        second = contract.extract_contract(sources, "b" * 40)

        self.assertEqual(contract.canonical_hash(first), contract.canonical_hash(second))

    def test_drift_report_names_current_and_baseline_hashes(self) -> None:
        current = contract.extract_contract(contract.read_sources(SOURCES))
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        baseline["replay"]["fds_to_close_initial_sentinel"] = [0, -1]
        baseline["canonical_sha256"] = contract.canonical_hash(baseline)

        report = contract.markdown_report(current, baseline)

        self.assertIn("<!-- grapheneos-zygote-contract-monitor:v1 -->", report)
        self.assertIn("Semantic contract drift detected", report)
        self.assertIn(current["canonical_sha256"], report)
        self.assertIn(baseline["canonical_sha256"], report)

    def test_cli_returns_zero_for_match_and_two_for_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_json = tmp_path / "current.json"
            report = tmp_path / "report.md"
            self.assertEqual(contract.main_with_args_for_test(SOURCES, BASELINE, out_json, report), 0)
            drift = tmp_path / "drift.json"
            shutil.copyfile(BASELINE, drift)
            data = json.loads(drift.read_text(encoding="utf-8"))
            data["upstream"]["branch"] = "drift"
            drift.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(contract.main_with_args_for_test(SOURCES, drift, out_json, report), 2)

    def test_cli_writes_report_when_extraction_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sources = tmp_path / "sources"
            shutil.copytree(SOURCES, sources)
            extra_args = sources / "core/java/com/android/internal/os/ZygoteExtraArgs.java"
            extra_args.write_text(
                extra_args.read_text(encoding="utf-8").replace(
                    "int USE_ZYGOTE_SPAWNING = 1 << 3;", ""
                ),
                encoding="utf-8",
            )
            report = tmp_path / "report.md"
            argv = [
                "grapheneos_zygote_contract.py",
                "--source-dir",
                str(sources),
                "--baseline",
                str(BASELINE),
                "--out-json",
                str(tmp_path / "current.json"),
                "--report",
                str(report),
            ]

            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(contract.main(), 1)

            self.assertIn("contract extraction failed", report.read_text(encoding="utf-8"))

    def test_workflow_handles_empty_issue_bodies_and_uploads_failure_report(self) -> None:
        workflow = (
            Path(__file__).parents[1]
            / ".github/workflows/grapheneos_zygote_contract_monitor.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('(.body // \\"\\") | contains', workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("if-no-files-found: warn", workflow)
        self.assertIn(
            'elif [ -n "$issue_number" ] && [ "$issue_state" = "OPEN" ]; then',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
