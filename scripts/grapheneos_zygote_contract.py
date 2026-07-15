#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "GrapheneOS/platform_frameworks_base"
BRANCH = "17"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}"
RAW_BASE_URL = f"https://raw.githubusercontent.com/{REPOSITORY}"
USER_AGENT = "Magisk GrapheneOS zygote contract monitor/1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
SOURCE_PATHS = (
    "core/java/com/android/internal/os/ZygoteConnection.java",
    "core/java/com/android/internal/os/ZygoteExtraArgs.java",
    "core/java/com/android/internal/os/ExecSpawning.java",
    "core/jni/com_android_internal_os_Zygote.cpp",
)
JNI_METHODS = (
    "nativeForkAndSpecialize",
    "nativeForkSystemServer",
    "nativeSpecializeAppProcess",
)


class ContractError(RuntimeError):
    pass


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def require(pattern: str, text: str, field: str, flags: int = re.S) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if match is None:
        raise ContractError(f"missing GrapheneOS zygote contract field: {field}")
    return match


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def int_expr(expr: str) -> int:
    clean = expr.replace(" ", "")
    match = re.fullmatch(r"(\d+)(?:<<(\d+))?", clean)
    if match is None:
        raise ContractError(f"unsupported integer expression: {expr}")
    value = int(match.group(1))
    return value << int(match.group(2) or "0")


def read_response(url: str, timeout: float, max_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > max_bytes:
                raise ContractError(f"response exceeds {max_bytes} bytes: {url}")
            data = response.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise ContractError(f"failed to fetch {url}: {exc}") from exc
    if len(data) > max_bytes:
        raise ContractError(f"response exceeds {max_bytes} bytes: {url}")
    return data


def fetch_sources(timeout: float) -> tuple[dict[str, str], str]:
    try:
        revision = json.loads(read_response(API_URL, timeout, MAX_SOURCE_BYTES))["sha"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ContractError(f"failed to resolve GrapheneOS branch {BRANCH}: {exc}") from exc
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ContractError(f"invalid GrapheneOS revision: {revision!r}")

    sources: dict[str, str] = {}
    for path in SOURCE_PATHS:
        try:
            sources[path] = read_response(
                f"{RAW_BASE_URL}/{revision}/{path}", timeout, MAX_SOURCE_BYTES
            ).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(f"failed to decode {path}: {exc}") from exc
    return sources, revision


def read_sources(source_dir: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in SOURCE_PATHS:
        file_path = source_dir / path
        try:
            sources[path] = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContractError(f"failed to read {file_path}: {exc}") from exc
    return sources


def extract_jni_descriptors(native: str) -> dict[str, str]:
    table = require(r"static\s+const\s+JNINativeMethod\s+gMethods\[\]\s*=\s*\{(?P<body>.*?)\};", native, "JNI table").group("body")
    descriptors: dict[str, str] = {}
    for name in JNI_METHODS:
        pattern = r'\{"' + re.escape(name) + r'"\s*,\s*(?P<parts>(?:"[^"]*"\s*)+)\s*,\s*\(void\*\)'
        parts = require(pattern, table, f"JNI descriptor {name}").group("parts")
        descriptors[name] = "".join(re.findall(r'"([^"]*)"', parts))
    return descriptors


def braced_block(pattern: str, text: str, field: str) -> str:
    match = require(pattern, text, field, 0)
    start = text.find("{", match.end())
    if start == -1:
        raise ContractError(f"missing opening brace for {field}")
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise ContractError(f"missing closing brace for {field}")


def extract_extra_args(extra: str, native: str) -> dict[str, object]:
    clean_extra = strip_comments(extra)
    use_expr = require(r"int\s+USE_ZYGOTE_SPAWNING\s*=\s*([^;]+);", clean_extra, "USE_ZYGOTE_SPAWNING").group(1)
    selinux_idx = require(r"IDX_SELINUX_FLAGS\s*=\s*(\d+)", clean_extra, "IDX_SELINUX_FLAGS").group(1)
    flags_idx = require(r"IDX_FLAGS\s*=\s*(\d+)", clean_extra, "IDX_FLAGS").group(1)
    arr_len = require(r"ARR_LEN\s*=\s*(\d+)", clean_extra, "ARR_LEN").group(1)
    make_body = require(r"long\[\]\s+res\s*=\s*new\s+long\[ARR_LEN\];(?P<body>.*?)return\s+res\s*;", clean_extra, "makeJniLongArray").group("body")
    native_body = require(r"ExtraArgs\(JNIEnv\* env, jlongArray jlongArgs\).*?\{(?P<body>.*?)\n\s*\}", native, "native ExtraArgs constructor").group("body")
    native_flag = require(r"FORCIBLY_ENABLE_MEMORY_TAGGING\s*=\s*([^;]+);", native, "native ExtraArgs flag").group(1)
    java_order = [
        list(item) for item in re.findall(r"res\[(IDX_[A-Z_]+)\]\s*=\s*([A-Za-z0-9_.$]+)", make_body)
    ]
    expected_java_order = [["IDX_SELINUX_FLAGS", "selinuxFlags"], ["IDX_FLAGS", "flags"]]
    if java_order != expected_java_order:
        raise ContractError(f"unexpected Java extra-long-args order: {java_order}")

    native_order = [
        list(item) for item in re.findall(r"(selinux_flags|flags)\s*=.*?jlong_arr\[(\d+)\]", native_body)
    ]
    expected_native_order = [["selinux_flags", "0"], ["flags", "1"]]
    if native_order != expected_native_order:
        raise ContractError(f"unexpected native extra-long-args order: {native_order}")

    exec_body = compact(braced_block(r"boolean\s+shouldUseExecSpawning\s*\(\s*\)", clean_extra, "shouldUseExecSpawning"))
    if exec_body != "return !hasFlag(Flag.USE_ZYGOTE_SPAWNING);":
        raise ContractError(f"unexpected shouldUseExecSpawning contract: {exec_body}")

    return {
        "use_zygote_spawning": {"expression": compact(use_expr), "value": int_expr(use_expr)},
        "should_use_exec_spawning": exec_body,
        "java_indices": {"IDX_SELINUX_FLAGS": int(selinux_idx), "IDX_FLAGS": int(flags_idx), "ARR_LEN": int(arr_len)},
        "java_make_jni_long_array": java_order,
        "native_jlong_array_order": native_order,
        "native_forcibly_enable_memory_tagging": {"expression": compact(native_flag), "value": int_expr(native_flag)},
    }


def extract_replay_contract(connection: str, exec_spawning: str, native: str) -> dict[str, object]:
    clean_conn = strip_comments(connection)
    fds = require(r"int\s*\[\]\s*fdsToClose\s*=\s*\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\};", clean_conn, "fdsToClose replay sentinel")
    guard_body = braced_block(r"if\s*\(\s*!isReplayingZygoteCommands\s*\)", clean_conn[fds.end() :], "fdsToClose replay guard")
    assignments = sorted(
        int(index)
        for index in re.findall(r"fdsToClose\s*\[\s*([01])\s*\]\s*=\s*(?:fd|zygoteFd)\.getInt\$\(\s*\)", guard_body)
    )
    if assignments != [0, 1]:
        raise ContractError(f"unexpected guarded fdsToClose assignments: {assignments}")
    replay_call = require(r"processCommand\(\s*zygoteServer\s*,\s*false\s*,\s*cmd\s*\)", exec_spawning, "replay processCommand false")
    detach = require(r"for\s*\(int\s+fd\s*:\s*fds_to_close\).*?if\s*\(\s*fd\s*==\s*-1\s*&&\s*gIsExecSpawning\s*\)\s*\{\s*continue\s*;\s*\}", native, "native fds_to_close -1 exec sentinel")
    fork = require(r"pid_t\s+pid\s*=\s*gIsExecSpawning\s*\?\s*0\s*:\s*fork\s*\(\s*\)\s*;", native, "gIsExecSpawning fork behavior")
    return {
        "fds_to_close_initial_sentinel": [int(fds.group(1)), int(fds.group(2))],
        "fds_to_close_socket_fill_guard": "!isReplayingZygoteCommands",
        "fds_to_close_guarded_assignments": assignments,
        "replay_process_command_multiple_ok": False,
        "replay_process_command_call": compact(replay_call.group(0)),
        "native_detach_exec_sentinel": compact(detach.group(0)),
        "native_fork_expression": compact(fork.group(0)),
    }


def extract_contract(sources: dict[str, str], source_revision: str | None = None) -> dict[str, object]:
    native = sources["core/jni/com_android_internal_os_Zygote.cpp"]
    contract = {
        "upstream": {"repository": REPOSITORY, "branch": BRANCH},
        "jni_descriptors": extract_jni_descriptors(native),
        "extra_long_args": extract_extra_args(sources["core/java/com/android/internal/os/ZygoteExtraArgs.java"], native),
        "replay": extract_replay_contract(
            sources["core/java/com/android/internal/os/ZygoteConnection.java"],
            sources["core/java/com/android/internal/os/ExecSpawning.java"],
            native,
        ),
    }
    if source_revision is not None:
        contract["source_revision"] = source_revision
    contract["canonical_sha256"] = canonical_hash(contract)
    return contract


def canonical_json(contract: dict[str, object]) -> str:
    semantic = {
        key: value
        for key, value in contract.items()
        if key not in {"canonical_sha256", "source_revision"}
    }
    return json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(contract: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json(contract).encode()).hexdigest()


def write_json(path: Path, contract: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def markdown_report(current: dict[str, object], baseline: dict[str, object] | None) -> str:
    lines = ["<!-- grapheneos-zygote-contract-monitor:v1 -->", "# GrapheneOS Zygote contract drift", ""]
    lines.append(f"Current hash: `{current['canonical_sha256']}`")
    if "source_revision" in current:
        lines.append(f"Source revision: `{current['source_revision']}`")
    if baseline is None:
        lines.append("Baseline: missing")
    else:
        lines.append(f"Baseline hash: `{baseline.get('canonical_sha256', '<missing>')}`")
        if canonical_hash(current) == canonical_hash(baseline):
            lines.append("\nNo semantic contract drift detected.")
        else:
            lines.append("\nSemantic contract drift detected. Review `grapheneos_zygote_contract_current.json`.")
    lines.append("\nMonitored fields: JNI descriptors, extra-long-args indices/flags, replay fds sentinel, replay `processCommand(..., false, ...)`, and exec-spawn fork behavior.")
    return "\n".join(lines) + "\n"


def run(source_dir: Path | None, baseline_path: Path, out_json: Path, report: Path, timeout: float) -> int:
    if source_dir:
        sources = read_sources(source_dir)
        revision = None
    else:
        sources, revision = fetch_sources(timeout)
    current = extract_contract(sources, revision)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    write_json(out_json, current)
    report.write_text(markdown_report(current, baseline), encoding="utf-8")
    return 0 if baseline is not None and canonical_hash(current) == canonical_hash(baseline) else 2


def main_with_args_for_test(source_dir: Path, baseline: Path, out_json: Path, report: Path) -> int:
    return run(source_dir, baseline, out_json, report, 20.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check GrapheneOS zygote semantic contract drift.")
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--baseline", type=Path, default=Path("tests/fixtures/grapheneos_zygote_contract/baseline.json"))
    parser.add_argument("--out-json", type=Path, default=Path("grapheneos_zygote_contract_current.json"))
    parser.add_argument("--report", type=Path, default=Path("grapheneos_zygote_contract_report.md"))
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    try:
        return run(args.source_dir, args.baseline, args.out_json, args.report, args.timeout)
    except ContractError as exc:
        message = f"error: {exc}"
        print(message, file=sys.stderr)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            "<!-- grapheneos-zygote-contract-monitor:v1 -->\n"
            "# GrapheneOS Zygote contract extraction failed\n\n"
            f"`{message}`\n",
            encoding="utf-8",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
