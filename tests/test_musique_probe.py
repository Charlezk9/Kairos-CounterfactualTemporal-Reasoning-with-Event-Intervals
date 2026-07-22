from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import kairos.musique_probe as probe


DATA0_TMP = "/data0/hk_data/kairos-zx/.tmp"
APPROVED_COMMIT = "a" * 40


def good_body(size: int = probe.BODY_SIZE) -> bytes:
    if size <= 0:
        return b""
    prefix = probe._ZIP_MAGIC[:size]
    return prefix + b"x" * (size - len(prefix))


def writeout(
    *,
    http_code: int = 206,
    redirects: int = 0,
    effective_url: str = probe.FIXED_URL,
    mime: str = "application/zip",
    size_download: int = probe.BODY_SIZE,
) -> bytes:
    return (
        f"{probe._WRITEOUT_BEGIN}\n"
        f"http_code:{http_code:03d}\n"
        f"num_redirects:{redirects}\n"
        f"url_effective:{effective_url}\n"
        f"content_type:{mime}\n"
        f"size_download:{size_download}\n"
        f"{probe._WRITEOUT_END}\n"
    ).encode("ascii")


class FakeRunner:
    def __init__(
        self,
        *,
        body: bytes | None = None,
        writeout_bytes: bytes | None = None,
        stderr: bytes = b"",
        result: probe._ProcessResult | None = None,
    ) -> None:
        self.body = good_body() if body is None else body
        self.writeout = writeout() if writeout_bytes is None else writeout_bytes
        self.stderr = stderr
        self.result = result or probe._ProcessResult(True, 0, "NONE", None)
        self.calls: list[tuple[int, int, int]] = []

    def __call__(self, body_fd: int, writeout_fd: int, stderr_fd: int) -> probe._ProcessResult:
        self.calls.append((body_fd, writeout_fd, stderr_fd))
        os.write(body_fd, self.body)
        os.write(writeout_fd, self.writeout)
        os.write(stderr_fd, self.stderr)
        return self.result


class ProbeCase(unittest.TestCase):
    def setUp(self) -> None:
        Path(DATA0_TMP).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=DATA0_TMP)
        self.base = Path(self.temporary.name)
        self._case_index = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def new_layout(self) -> probe._Layout:
        self._case_index += 1
        case = self.base / f"case-{self._case_index}"
        project = case / "project"
        repository = case / "repository"
        project.mkdir(mode=0o700, parents=True)
        repository.mkdir(mode=0o700)
        return probe._Layout(
            project,
            repository,
            "data/raw/musique/.probe-fixed-v1",
            "data/raw/musique/fixed-object",
        )

    def execute(
        self,
        layout: probe._Layout,
        runner: FakeRunner,
        git_checker=None,
    ) -> probe.ProbeReport:
        checker = git_checker or (lambda value: value)
        # Shared /data0 ancestors are deliberately not mutated by tests.  Path
        # trust predicates are tested independently with synthetic stat values.
        with mock.patch.object(probe, "_require_trusted_directory"):
            return probe._execute_layout(
                layout, APPROVED_COMMIT, checker, runner
            )

    def verify(self, layout: probe._Layout) -> probe.ProbeReport:
        with mock.patch.object(probe, "_require_trusted_directory"):
            return probe._verify_layout(layout)

    @staticmethod
    def stage(layout: probe._Layout) -> Path:
        return layout.project_root / layout.stage_relative_path

    @staticmethod
    def formal(layout: probe._Layout) -> Path:
        return layout.project_root / layout.formal_relative_path


class ConstantsAndApiTests(unittest.TestCase):
    def test_frozen_source_and_layout_constants(self) -> None:
        self.assertEqual(len(probe.OFFICIAL_REPOSITORY_COMMIT), 40)
        self.assertIn(probe.DRIVE_OBJECT_ID, probe.FIXED_URL)
        self.assertEqual(probe.RANGE_START, 0)
        self.assertEqual(probe.RANGE_END, 65_535)
        self.assertEqual(probe.BODY_SIZE, 65_536)
        self.assertEqual(
            Path(probe.STAGE_RELATIVE_PATH).parent,
            Path(probe.FORMAL_RELATIVE_PATH).parent,
        )
        self.assertEqual(
            Path(probe.FORMAL_RELATIVE_PATH).name,
            probe.OFFICIAL_REPOSITORY_COMMIT,
        )

    def test_layout_rejects_non_sibling_or_same_names(self) -> None:
        cases = (
            ("a/stage", "b/formal"),
            ("a/same", "a/same"),
            ("/absolute", "a/formal"),
            ("a/../stage", "a/formal"),
        )
        for stage, formal in cases:
            with self.subTest(stage=stage, formal=formal):
                with self.assertRaises(probe.ProbeError):
                    probe._Layout(Path("/x"), Path("/y"), stage, formal)

    def test_commit_validation_is_exact(self) -> None:
        self.assertEqual(probe._validate_commit(APPROVED_COMMIT), APPROVED_COMMIT)
        for value in ("a" * 39, "a" * 41, "A" * 40, "g" * 40, True, None):
            with self.subTest(value=value):
                with self.assertRaises(probe.ProbeError):
                    probe._validate_commit(value)  # type: ignore[arg-type]

    def test_report_mapping_has_only_public_status_fields(self) -> None:
        report = probe.ProbeReport(probe.ProbeStatus.INCOMPLETE, "ABSENT", None)
        self.assertEqual(
            report.as_mapping(),
            {"status": "INCOMPLETE", "reason_code": "ABSENT", "observation": None},
        )

    def test_public_exports_are_narrow(self) -> None:
        self.assertEqual(
            set(probe.__all__),
            {"ProbeError", "ProbeReport", "ProbeStatus", "execute", "main", "verify"},
        )


class CurlBoundaryTests(unittest.TestCase):
    def test_curl_argv_uses_fixed_wrapper_and_procfd(self) -> None:
        argv = probe._build_curl_argv(17)
        self.assertEqual(argv[:5], (probe.PRLIMIT_PATH, "--fsize=65536:65536", "--cpu=50:50", "--", probe.CURL_PATH))
        self.assertEqual(argv[5], "-q")
        output_index = argv.index("--output")
        self.assertEqual(argv[output_index + 1], "/proc/self/fd/17")
        self.assertEqual(argv[-1], probe.FIXED_URL)

    def test_curl_argv_has_no_redirect_cookie_header_or_config_options(self) -> None:
        argv = probe._build_curl_argv(9)
        forbidden = {
            "--location",
            "-L",
            "--cookie",
            "--cookie-jar",
            "--netrc",
            "--netrc-file",
            "--config",
            "--dump-header",
            "--include",
            "--verbose",
        }
        self.assertTrue(forbidden.isdisjoint(argv))
        self.assertIn("--max-redirs", argv)
        self.assertEqual(argv[argv.index("--max-redirs") + 1], "0")

    def test_curl_argv_fixes_range_time_retry_and_proxy(self) -> None:
        argv = probe._build_curl_argv(11)
        expected = {
            "--range": "0-65535",
            "--connect-timeout": "10",
            "--max-time": "45",
            "--speed-limit": "1024",
            "--speed-time": "10",
            "--retry": "0",
            "--max-filesize": "65536",
            "--proxy": "",
            "--noproxy": "*",
        }
        for option, value in expected.items():
            with self.subTest(option=option):
                self.assertEqual(argv[argv.index(option) + 1], value)

    def test_invalid_body_descriptors_are_rejected(self) -> None:
        for value in (-1, True, "1", None):
            with self.subTest(value=value):
                with self.assertRaises(probe.ProbeError):
                    probe._build_curl_argv(value)  # type: ignore[arg-type]

    def test_child_environment_is_a_three_key_allowlist(self) -> None:
        self.assertEqual(
            probe._child_environment(),
            {"LC_ALL": "C", "LANG": "C", "TZ": "UTC"},
        )
        sensitive = {"HOME", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SSH_AUTH_SOCK", "TOKEN"}
        self.assertTrue(sensitive.isdisjoint(probe._child_environment()))


class WriteoutParserTests(unittest.TestCase):
    def test_valid_writeout_is_parsed_exactly(self) -> None:
        value = probe._parse_writeout(writeout())
        self.assertEqual(value.http_code, 206)
        self.assertEqual(value.num_redirects, 0)
        self.assertEqual(value.effective_url, probe.FIXED_URL)
        self.assertEqual(value.mime, "application/zip")
        self.assertEqual(value.size_download, 65_536)

    def test_missing_extra_duplicate_and_reordered_fields_are_rejected(self) -> None:
        valid = writeout().decode("ascii")
        lines = valid.splitlines()
        cases = (
            "\n".join(lines[:-2] + lines[-1:]) + "\n",
            "\n".join(lines[:-1] + ["extra:x", lines[-1]]) + "\n",
            valid.replace("num_redirects:0", "http_code:206"),
            "\n".join([lines[0], lines[2], lines[1], *lines[3:]]) + "\n",
        )
        for content in cases:
            with self.subTest(content=content[:80]):
                with self.assertRaises(probe.ProbeError):
                    probe._parse_writeout(content.encode("ascii"))

    def test_truncated_bad_sentinel_and_no_final_lf_are_rejected(self) -> None:
        valid = writeout()
        cases = (
            valid[:-1],
            valid[:20],
            valid.replace(probe._WRITEOUT_BEGIN.encode(), b"WRONG"),
            valid.replace(probe._WRITEOUT_END.encode(), b"WRONG"),
        )
        for content in cases:
            with self.subTest(content=content[:40]):
                with self.assertRaises(probe.ProbeError):
                    probe._parse_writeout(content)

    def test_control_invalid_utf8_and_oversize_are_rejected(self) -> None:
        cases = (
            writeout().replace(b"http_code:206", b"http_code:2\r6"),
            writeout().replace(b"application/zip", b"application/\x00zip"),
            writeout() + b"\xff",
            b"x" * (probe._WRITEOUT_LIMIT + 1),
        )
        for content in cases:
            with self.subTest(size=len(content)):
                with self.assertRaises(probe.ProbeError):
                    probe._parse_writeout(content)

    def test_numeric_fields_are_strict_unsigned_decimal(self) -> None:
        cases = (
            writeout().replace(b"http_code:206", b"http_code:20"),
            writeout().replace(b"http_code:206", b"http_code:+206"),
            writeout().replace(b"num_redirects:0", b"num_redirects:-1"),
            writeout().replace(b"size_download:65536", b"size_download:65536.0"),
        )
        for content in cases:
            with self.subTest(content=content[-100:]):
                with self.assertRaises(probe.ProbeError):
                    probe._parse_writeout(content)


class ProcessResultTests(unittest.TestCase):
    def test_process_result_round_trip_for_started_and_spawn_failure(self) -> None:
        values = (
            probe._ProcessResult(True, 0, "NONE", None),
            probe._ProcessResult(True, -signal.SIGXFSZ, "NONE", None),
            probe._ProcessResult(False, None, "NOT_STARTED", "FileNotFoundError"),
        )
        for value in values:
            with self.subTest(value=value):
                content = probe._canonical_json_bytes(value.as_mapping())
                self.assertEqual(probe._parse_process_result(content), value)

    def test_process_result_rejects_inconsistent_states(self) -> None:
        cases = (
            {"process_started": True, "returncode": None, "watchdog_action": "NONE", "spawn_error_type": None},
            {"process_started": False, "returncode": 0, "watchdog_action": "NOT_STARTED", "spawn_error_type": "OSError"},
            {"process_started": False, "returncode": None, "watchdog_action": "NONE", "spawn_error_type": "OSError"},
            {"process_started": True, "returncode": 0, "watchdog_action": "BAD", "spawn_error_type": None},
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(probe.ProbeError):
                    probe._parse_process_result(probe._canonical_json_bytes(value))

    def test_process_result_rejects_duplicate_extra_bool_and_noncanonical(self) -> None:
        valid = probe._canonical_json_bytes(
            probe._ProcessResult(True, 0, "NONE", None).as_mapping()
        )
        cases = (
            valid.replace(b'"returncode":0', b'"returncode":0,"returncode":0'),
            valid[:-2] + b',"extra":1}\n',
            valid.replace(b'"returncode":0', b'"returncode":true'),
            json.dumps(json.loads(valid), indent=2).encode() + b"\n",
        )
        for content in cases:
            with self.subTest(content=content[:80]):
                with self.assertRaises(probe.ProbeError):
                    probe._parse_process_result(content)


class ExecuteAndSizeTests(ProbeCase):
    def test_exact_65536_prefix_is_the_only_probe_ok_size(self) -> None:
        layout = self.new_layout()
        report = self.execute(layout, FakeRunner())
        self.assertIs(report.status, probe.ProbeStatus.PROBE_OK)
        self.assertEqual(report.reason_code, "ALL_GATES_PASSED")
        self.assertIsNotNone(report.observation)
        observation = report.observation
        assert observation is not None
        self.assertEqual(observation["body"]["byte_size"], 65_536)
        self.assertEqual(observation["body"]["hash_read_count"], 65_536)
        self.assertEqual(observation["http"]["size_download"], 65_536)

    def test_frozen_size_boundary_matrix(self) -> None:
        for size in (0, 1, 4, 65_535, 65_536, 65_537):
            with self.subTest(size=size):
                layout = self.new_layout()
                runner = FakeRunner(
                    body=good_body(size),
                    writeout_bytes=writeout(size_download=size),
                )
                report = self.execute(layout, runner)
                expected = probe.ProbeStatus.PROBE_OK if size == 65_536 else probe.ProbeStatus.BLOCKED
                self.assertIs(report.status, expected)
                if size != 65_536:
                    self.assertEqual(report.reason_code, "BODY_SIZE_NOT_EXACT")

    def test_size_download_fstat_and_hash_read_count_must_all_match(self) -> None:
        for advertised in (0, 1, 65_535, 65_537):
            with self.subTest(advertised=advertised):
                layout = self.new_layout()
                runner = FakeRunner(writeout_bytes=writeout(size_download=advertised))
                report = self.execute(layout, runner)
                self.assertIs(report.status, probe.ProbeStatus.BLOCKED)
                self.assertEqual(report.reason_code, "BODY_SIZE_NOT_EXACT")

    def test_success_has_exact_private_file_set_and_no_formal_revision(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        stage = self.stage(layout)
        self.assertEqual({entry.name for entry in stage.iterdir()}, set(probe._FINAL_NAMES))
        self.assertEqual(stat.S_IMODE(stage.stat().st_mode), 0o700)
        for path in stage.iterdir():
            with self.subTest(path=path.name):
                value = path.stat(follow_symlinks=False)
                self.assertTrue(stat.S_ISREG(value.st_mode))
                self.assertEqual(stat.S_IMODE(value.st_mode), 0o600)
                self.assertEqual(value.st_nlink, 1)
        self.assertFalse(self.formal(layout).exists())

    def test_git_checker_runs_before_stage_and_before_publication(self) -> None:
        layout = self.new_layout()
        calls: list[str] = []

        def checker(value: str) -> str:
            calls.append(value)
            return value

        self.execute(layout, FakeRunner(), checker)
        self.assertEqual(calls, [APPROVED_COMMIT, APPROVED_COMMIT])

    def test_git_mismatch_before_execution_creates_no_stage(self) -> None:
        layout = self.new_layout()
        with self.assertRaises(probe.ProbeError):
            self.execute(layout, FakeRunner(), lambda _value: "b" * 40)
        self.assertFalse(self.stage(layout).exists())

    def test_git_mismatch_before_publication_leaves_incomplete_stage(self) -> None:
        layout = self.new_layout()
        calls = 0

        def checker(value: str) -> str:
            nonlocal calls
            calls += 1
            return value if calls == 1 else "b" * 40

        with self.assertRaises(probe.ProbeError):
            self.execute(layout, FakeRunner(), checker)
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)


class VerdictTests(ProbeCase):
    def assert_blocked(self, runner: FakeRunner, reason: str) -> None:
        layout = self.new_layout()
        report = self.execute(layout, runner)
        self.assertIs(report.status, probe.ProbeStatus.BLOCKED)
        self.assertEqual(report.reason_code, reason)
        self.assertEqual(self.verify(layout).reason_code, reason)

    def test_http_200_3xx_and_error_statuses_are_blocked(self) -> None:
        for code in (200, 301, 302, 404, 500):
            with self.subTest(code=code):
                self.assert_blocked(
                    FakeRunner(writeout_bytes=writeout(http_code=code)),
                    "HTTP_STATUS_NOT_206",
                )

    def test_redirect_and_effective_url_change_are_blocked(self) -> None:
        self.assert_blocked(
            FakeRunner(writeout_bytes=writeout(redirects=1)),
            "REDIRECT_OBSERVED",
        )
        self.assert_blocked(
            FakeRunner(writeout_bytes=writeout(effective_url="https://example.com/token")),
            "EFFECTIVE_URL_MISMATCH",
        )

    def test_mime_allowlist_is_exact(self) -> None:
        for mime in sorted(probe._ALLOWED_MIME):
            with self.subTest(mime=mime):
                layout = self.new_layout()
                report = self.execute(layout, FakeRunner(writeout_bytes=writeout(mime=mime)))
                self.assertIs(report.status, probe.ProbeStatus.PROBE_OK)
        for mime in ("text/html", "application/zip; charset=binary", "APPLICATION/ZIP", ""):
            with self.subTest(mime=mime):
                self.assert_blocked(
                    FakeRunner(writeout_bytes=writeout(mime=mime)),
                    "MIME_NOT_ALLOWED",
                )

    def test_missing_zip_magic_and_html_are_blocked(self) -> None:
        self.assert_blocked(
            FakeRunner(body=b"x" * probe.BODY_SIZE),
            "ZIP_MAGIC_MISSING",
        )
        html = b"<!doctype html>" + b"x" * (probe.BODY_SIZE - 15)
        self.assert_blocked(FakeRunner(body=html), "ZIP_MAGIC_MISSING")

    def test_invalid_writeout_is_blocked_and_not_echoed(self) -> None:
        for content in (b"", b"consent html", writeout()[:-1], b"x" * 4097):
            with self.subTest(size=len(content)):
                self.assert_blocked(
                    FakeRunner(writeout_bytes=content),
                    "WRITEOUT_INVALID",
                )

    def test_spawn_failure_nonzero_signal_and_watchdog_are_blocked(self) -> None:
        cases = (
            (probe._ProcessResult(False, None, "NOT_STARTED", "FileNotFoundError"), "PROCESS_SPAWN_FAILED"),
            (probe._ProcessResult(True, 22, "NONE", None), "PROCESS_EXIT_NONZERO"),
            (probe._ProcessResult(True, -signal.SIGXFSZ, "NONE", None), "PROCESS_EXIT_NONZERO"),
            (probe._ProcessResult(True, -signal.SIGTERM, "SIGTERM", None), "WATCHDOG_TIMEOUT"),
            (probe._ProcessResult(True, -signal.SIGKILL, "SIGKILL", None), "WATCHDOG_TIMEOUT"),
        )
        for result, reason in cases:
            with self.subTest(result=result):
                self.assert_blocked(FakeRunner(result=result), reason)

    def test_stderr_over_rlimit_equivalent_is_blocked(self) -> None:
        self.assert_blocked(
            FakeRunner(stderr=b"e" * 65_537),
            "STDERR_LIMIT_EXCEEDED",
        )

    def test_total_archive_size_remains_unverified(self) -> None:
        layout = self.new_layout()
        observation = self.execute(layout, FakeRunner()).observation
        assert observation is not None
        http = observation["http"]
        self.assertIsNone(http["content_range"])
        self.assertIsNone(http["archive_total_size_bytes"])
        self.assertEqual(http["archive_total_size_status"], "UNVERIFIED_NO_CONTENT_RANGE")

    def test_mismatched_effective_url_is_not_persisted_in_observation(self) -> None:
        secret_url = "https://example.com/?secret=do-not-copy"
        layout = self.new_layout()
        report = self.execute(
            layout,
            FakeRunner(writeout_bytes=writeout(effective_url=secret_url)),
        )
        serialized = probe._canonical_json_bytes(report.observation)
        self.assertNotIn(secret_url.encode(), serialized)


class OfflineVerifierTests(ProbeCase):
    def test_missing_parent_and_missing_stage_are_incomplete(self) -> None:
        layout = self.new_layout()
        self.assertEqual(self.verify(layout).reason_code, "STAGE_PARENT_ABSENT")
        parent = layout.project_root / layout.parent_relative_path
        parent.mkdir(mode=0o700, parents=True)
        self.assertEqual(self.verify(layout).reason_code, "STAGE_ABSENT")

    def test_safe_partial_stage_is_incomplete(self) -> None:
        layout = self.new_layout()
        stage = self.stage(layout)
        stage.mkdir(mode=0o700, parents=True)
        body = stage / probe._BODY_NAME
        body.write_bytes(b"partial")
        body.chmod(0o600)
        report = self.verify(layout)
        self.assertIs(report.status, probe.ProbeStatus.INCOMPLETE)
        self.assertEqual(report.reason_code, "OBSERVATION_ABSENT")

    def test_extra_file_symlink_special_and_bad_mode_are_incomplete(self) -> None:
        mutators = (
            lambda stage: (stage / "extra").write_bytes(b"x"),
            lambda stage: (stage / probe._BODY_NAME).symlink_to("missing"),
            lambda stage: os.mkfifo(stage / probe._BODY_NAME, 0o600),
            lambda stage: ((stage / probe._BODY_NAME).write_bytes(b"x"), (stage / probe._BODY_NAME).chmod(0o644)),
        )
        for index, mutate in enumerate(mutators):
            with self.subTest(index=index):
                layout = self.new_layout()
                stage = self.stage(layout)
                stage.mkdir(mode=0o700, parents=True)
                mutate(stage)
                self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_unknown_hardlink_is_incomplete(self) -> None:
        layout = self.new_layout()
        stage = self.stage(layout)
        stage.mkdir(mode=0o700, parents=True)
        body = stage / probe._BODY_NAME
        body.write_bytes(b"x")
        body.chmod(0o600)
        os.link(body, self.base / "outside-link")
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_body_writeout_result_and_manifest_tamper_are_incomplete(self) -> None:
        for name in (*probe._EVIDENCE_NAMES, probe._OBSERVATION_NAME):
            with self.subTest(name=name):
                layout = self.new_layout()
                self.execute(layout, FakeRunner())
                path = self.stage(layout) / name
                content = path.read_bytes()
                path.write_bytes(content + b"tamper")
                path.chmod(0o600)
                self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_same_content_inode_replacement_is_incomplete(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        path = self.stage(layout) / probe._BODY_NAME
        content = path.read_bytes()
        replacement = self.stage(layout) / "replacement"
        replacement.write_bytes(content)
        replacement.chmod(0o600)
        os.replace(replacement, path)
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_observation_temp_and_final_pair_is_incomplete(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        stage = self.stage(layout)
        os.link(stage / probe._OBSERVATION_NAME, stage / probe._OBSERVATION_TEMP)
        report = self.verify(layout)
        self.assertIs(report.status, probe.ProbeStatus.INCOMPLETE)
        self.assertEqual(report.reason_code, "OBSERVATION_PUBLICATION_INCOMPLETE")

    def test_formal_revision_presence_is_incomplete(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        self.formal(layout).mkdir(mode=0o700)
        report = self.verify(layout)
        self.assertIs(report.status, probe.ProbeStatus.INCOMPLETE)
        self.assertEqual(report.reason_code, "FORMAL_REVISION_PRESENT")

    def test_manifest_duplicate_extra_bool_and_wrong_literals_are_incomplete(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        path = self.stage(layout) / probe._OBSERVATION_NAME
        original = path.read_bytes()
        value = json.loads(original)
        cases = []
        extra = copy.deepcopy(value)
        extra["extra"] = 1
        cases.append(probe._canonical_json_bytes(extra))
        wrong = copy.deepcopy(value)
        wrong["limits"]["exact_body_bytes"] = 65_535
        cases.append(probe._canonical_json_bytes(wrong))
        boolean = copy.deepcopy(value)
        boolean["body"]["byte_size"] = True
        cases.append(probe._canonical_json_bytes(boolean))
        duplicate = original.replace(b'"status":"PROBE_OK"', b'"status":"PROBE_OK","status":"PROBE_OK"')
        cases.append(duplicate)
        for index, content in enumerate(cases):
            with self.subTest(index=index):
                path.write_bytes(content)
                path.chmod(0o600)
                self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)
                path.write_bytes(original)
                path.chmod(0o600)


class PathAndPublicationTests(ProbeCase):
    def test_existing_stage_and_formal_are_no_replace_failures(self) -> None:
        for target in ("stage", "formal"):
            with self.subTest(target=target):
                layout = self.new_layout()
                path = self.stage(layout) if target == "stage" else self.formal(layout)
                path.mkdir(mode=0o700, parents=True)
                with self.assertRaises(FileExistsError):
                    self.execute(layout, FakeRunner())

    def test_dangling_stage_and_formal_symlinks_are_not_absent(self) -> None:
        for target in ("stage", "formal"):
            with self.subTest(target=target):
                layout = self.new_layout()
                parent = layout.project_root / layout.parent_relative_path
                parent.mkdir(mode=0o700, parents=True)
                path = self.stage(layout) if target == "stage" else self.formal(layout)
                path.symlink_to("missing")
                with self.assertRaises(FileExistsError):
                    self.execute(layout, FakeRunner())

    def test_parent_symlink_and_not_directory_are_rejected(self) -> None:
        for kind in ("symlink", "file"):
            with self.subTest(kind=kind):
                layout = self.new_layout()
                data = layout.project_root / "data"
                if kind == "symlink":
                    data.symlink_to(self.base)
                else:
                    data.write_bytes(b"not-dir")
                with self.assertRaises((OSError, probe.ProbeError)):
                    self.execute(layout, FakeRunner())

    def test_stage_and_evidence_modes_are_exact(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        stage = self.stage(layout)
        self.assertEqual(stat.S_IMODE(stage.stat().st_mode), 0o700)
        for name in probe._FINAL_NAMES:
            self.assertEqual(stat.S_IMODE((stage / name).stat().st_mode), 0o600)

    def test_manifest_link_failure_leaves_incomplete_without_final(self) -> None:
        layout = self.new_layout()
        real_link = probe.os.link

        def fail_link(src, dst, **kwargs):
            if dst == probe._OBSERVATION_NAME:
                raise OSError("synthetic link failure")
            return real_link(src, dst, **kwargs)

        with mock.patch.object(probe.os, "link", side_effect=fail_link):
            with self.assertRaisesRegex(OSError, "synthetic link failure"):
                self.execute(layout, FakeRunner())
        self.assertFalse((self.stage(layout) / probe._OBSERVATION_NAME).exists())
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_each_late_publication_failure_verifies_incomplete(self) -> None:
        original_publish = probe._publish_observation
        for phase in ("first-fsync", "unlink", "second-fsync"):
            with self.subTest(phase=phase):
                layout = self.new_layout()

                def fail_during_publish(stage_fd, observation):
                    real_fsync = probe.os.fsync
                    real_unlink = probe.os.unlink
                    stage_fsync_calls = 0

                    def fsync(fd):
                        nonlocal stage_fsync_calls
                        if fd == stage_fd:
                            stage_fsync_calls += 1
                            if phase == "first-fsync" and stage_fsync_calls == 1:
                                raise OSError("synthetic first fsync failure")
                            if phase == "second-fsync" and stage_fsync_calls == 2:
                                raise OSError("synthetic second fsync failure")
                        return real_fsync(fd)

                    def unlink(name, **kwargs):
                        if phase == "unlink" and name == probe._OBSERVATION_TEMP:
                            raise OSError("synthetic unlink failure")
                        return real_unlink(name, **kwargs)

                    with mock.patch.object(probe.os, "fsync", side_effect=fsync):
                        with mock.patch.object(probe.os, "unlink", side_effect=unlink):
                            return original_publish(stage_fd, observation)

                with mock.patch.object(
                    probe, "_publish_observation", side_effect=fail_during_publish
                ):
                    with self.assertRaisesRegex(OSError, "synthetic"):
                        self.execute(layout, FakeRunner())
                self.assertIs(
                    self.verify(layout).status, probe.ProbeStatus.INCOMPLETE
                )

    def test_recovery_faults_after_second_fsync_remain_incomplete(self) -> None:
        original_publish = probe._publish_observation
        for phase in ("recovery-link", "recovery-fsync", "recovery-check"):
            with self.subTest(phase=phase):
                layout = self.new_layout()

                def fail_during_publish(stage_fd, observation):
                    real_fsync = probe.os.fsync
                    real_link = probe.os.link
                    stage_fsync_calls = 0

                    def fsync(fd):
                        nonlocal stage_fsync_calls
                        if fd == stage_fd:
                            stage_fsync_calls += 1
                            if stage_fsync_calls == 2:
                                raise OSError("synthetic second fsync failure")
                            if phase == "recovery-fsync" and stage_fsync_calls == 3:
                                raise OSError("synthetic recovery fsync failure")
                        return real_fsync(fd)

                    def link(src, dst, **kwargs):
                        if phase == "recovery-link" and dst == probe._OBSERVATION_TEMP:
                            raise OSError("synthetic recovery link failure")
                        return real_link(src, dst, **kwargs)

                    check = (
                        mock.patch.object(
                            probe,
                            "_recovery_pair_is_bound",
                            side_effect=probe.ProbeError(
                                "synthetic recovery canonical-check failure"
                            ),
                        )
                        if phase == "recovery-check"
                        else contextlib.nullcontext()
                    )
                    with mock.patch.object(probe.os, "fsync", side_effect=fsync):
                        with mock.patch.object(probe.os, "link", side_effect=link):
                            with check:
                                return original_publish(stage_fd, observation)

                with mock.patch.object(
                    probe, "_publish_observation", side_effect=fail_during_publish
                ):
                    with self.assertRaisesRegex(
                        OSError, "synthetic second fsync failure"
                    ):
                        self.execute(layout, FakeRunner())
                self.assertIs(
                    self.verify(layout).status, probe.ProbeStatus.INCOMPLETE
                )

    def test_fail_close_returns_false_when_every_live_mutation_fails(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        stage_fd = os.open(self.stage(layout), probe._dir_flags())
        final_fd = os.open(
            probe._OBSERVATION_NAME,
            probe._regular_read_flags(),
            dir_fd=stage_fd,
        )
        failure = OSError("synthetic recovery mutation failure")
        try:
            with mock.patch.object(probe.os, "link", side_effect=failure):
                with mock.patch.object(
                    probe, "_create_evidence_fd", side_effect=failure
                ):
                    with mock.patch.object(probe.os, "unlink", side_effect=failure):
                        with mock.patch.object(
                            probe.os, "ftruncate", side_effect=failure
                        ):
                            with mock.patch.object(
                                probe.os, "fchmod", side_effect=failure
                            ):
                                with mock.patch.object(
                                    probe.os, "pwrite", side_effect=failure
                                ):
                                    self.assertFalse(
                                        probe._fail_closed_observation_publication(
                                            stage_fd, final_fd
                                        )
                                    )
        finally:
            os.close(final_fd)
            os.close(stage_fd)
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.PROBE_OK)

    def test_fail_close_marker_write_failure_does_not_claim_durability(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        stage_fd = os.open(self.stage(layout), probe._dir_flags())
        final_fd = os.open(
            probe._OBSERVATION_NAME,
            probe._regular_read_flags(),
            dir_fd=stage_fd,
        )
        failure = OSError("synthetic recovery failure")
        try:
            with mock.patch.object(probe.os, "link", side_effect=failure):
                with mock.patch.object(probe, "_write_all", side_effect=failure):
                    with mock.patch.object(probe.os, "unlink", side_effect=failure):
                        with mock.patch.object(
                            probe.os, "ftruncate", side_effect=failure
                        ):
                            with mock.patch.object(
                                probe.os, "fchmod", side_effect=failure
                            ):
                                with mock.patch.object(
                                    probe.os, "pwrite", side_effect=failure
                                ):
                                    self.assertFalse(
                                        probe._fail_closed_observation_publication(
                                            stage_fd, final_fd
                                        )
                                    )
        finally:
            os.close(final_fd)
            os.close(stage_fd)
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_fail_close_fsync_failure_is_live_incomplete_but_unconfirmed(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        stage_fd = os.open(self.stage(layout), probe._dir_flags())
        final_fd = os.open(
            probe._OBSERVATION_NAME,
            probe._regular_read_flags(),
            dir_fd=stage_fd,
        )
        try:
            with mock.patch.object(
                probe.os,
                "fsync",
                side_effect=OSError("synthetic persistent fsync failure"),
            ):
                self.assertFalse(
                    probe._fail_closed_observation_publication(stage_fd, final_fd)
                )
        finally:
            os.close(final_fd)
            os.close(stage_fd)
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_emergency_write_fsync_failure_is_live_incomplete_but_false(self) -> None:
        layout = self.new_layout()
        self.execute(layout, FakeRunner())
        stage_fd = os.open(self.stage(layout), probe._dir_flags())
        final_fd = os.open(
            probe._OBSERVATION_NAME,
            probe._regular_read_flags(),
            dir_fd=stage_fd,
        )
        real_fsync = probe.os.fsync
        failure = OSError("synthetic recovery failure")

        def fsync(fd):
            if fd != stage_fd:
                raise OSError("synthetic emergency file fsync failure")
            return real_fsync(fd)

        try:
            with mock.patch.object(probe.os, "link", side_effect=failure):
                with mock.patch.object(
                    probe, "_create_evidence_fd", side_effect=failure
                ):
                    with mock.patch.object(probe.os, "unlink", side_effect=failure):
                        with mock.patch.object(
                            probe.os, "ftruncate", side_effect=failure
                        ):
                            with mock.patch.object(
                                probe.os, "fchmod", side_effect=failure
                            ):
                                with mock.patch.object(
                                    probe.os, "fsync", side_effect=fsync
                                ):
                                    self.assertFalse(
                                        probe._fail_closed_observation_publication(
                                            stage_fd, final_fd
                                        )
                                    )
        finally:
            os.close(final_fd)
            os.close(stage_fd)
        self.assertTrue(
            (self.stage(layout) / probe._OBSERVATION_NAME)
            .read_bytes()
            .startswith(b"!")
        )
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_terminal_fail_close_false_or_error_is_fatal(self) -> None:
        effects = (
            False,
            OSError("synthetic terminal recovery failure"),
        )
        for effect in effects:
            with self.subTest(effect=effect):
                layout = self.new_layout()
                with mock.patch.object(
                    probe,
                    "_terminal_binding",
                    side_effect=probe.ProbeError("synthetic terminal mismatch"),
                ):
                    with mock.patch.object(
                        probe,
                        "_fail_closed_observation_publication",
                        side_effect=(effect if isinstance(effect, BaseException) else None),
                        return_value=effect,
                    ):
                        with self.assertRaisesRegex(
                            probe.ProbeError,
                            "terminal fail-close unconfirmed",
                        ):
                            self.execute(layout, FakeRunner())

    def test_existing_observation_temp_or_final_prevents_publication(self) -> None:
        for name in (probe._OBSERVATION_TEMP, probe._OBSERVATION_NAME):
            with self.subTest(name=name):
                layout = self.new_layout()

                def runner(body_fd, writeout_fd, stderr_fd):
                    result = FakeRunner()(body_fd, writeout_fd, stderr_fd)
                    path = self.stage(layout) / name
                    path.write_bytes(b"sentinel")
                    path.chmod(0o600)
                    return result

                with self.assertRaises((FileExistsError, probe.ProbeError)):
                    self.execute(layout, runner)  # type: ignore[arg-type]
                self.assertEqual((self.stage(layout) / name).read_bytes(), b"sentinel")

    def test_post_validation_content_tamper_cannot_return_probe_ok(self) -> None:
        layout = self.new_layout()
        original_publish = probe._publish_observation

        def tamper(stage_fd, observation):
            fd = os.open(probe._BODY_NAME, os.O_WRONLY, dir_fd=stage_fd)
            try:
                os.pwrite(fd, b"BAD!", 0)
            finally:
                os.close(fd)
            return original_publish(stage_fd, observation)

        with mock.patch.object(probe, "_publish_observation", side_effect=tamper):
            with self.assertRaises(probe.ProbeError):
                self.execute(layout, FakeRunner())
        self.assertIs(self.verify(layout).status, probe.ProbeStatus.INCOMPLETE)

    def test_stage_canonical_replacement_is_detected(self) -> None:
        layout = self.new_layout()
        original_terminal = probe._terminal_binding

        def replace(*args, **kwargs):
            stage = self.stage(layout)
            moved = stage.with_name(stage.name + "-moved")
            os.rename(stage, moved)
            stage.mkdir(mode=0o700)
            return original_terminal(*args, **kwargs)

        with mock.patch.object(probe, "_terminal_binding", side_effect=replace):
            with self.assertRaises(probe.ProbeError):
                self.execute(layout, FakeRunner())


class ProcessSpawnTests(unittest.TestCase):
    def test_procfd_alias_mismatch_blocks_before_popen(self) -> None:
        first = mock.Mock(st_dev=1, st_ino=1, st_mode=stat.S_IFREG | 0o600, st_uid=os.geteuid(), st_gid=os.getegid(), st_nlink=1, st_size=0, st_mtime_ns=1, st_ctime_ns=1)
        second = mock.Mock(st_dev=1, st_ino=2, st_mode=stat.S_IFREG | 0o600, st_uid=os.geteuid(), st_gid=os.getegid(), st_nlink=1, st_size=0, st_mtime_ns=1, st_ctime_ns=1)
        with mock.patch.object(probe.os, "stat", return_value=first):
            with mock.patch.object(probe.os, "fstat", return_value=second):
                with mock.patch.object(probe.subprocess, "Popen") as popen:
                    with self.assertRaises(probe.ProbeError):
                        probe._run_probe_process(1, 2, 3)
        popen.assert_not_called()

    def test_popen_receives_three_streams_no_shell_and_body_only_pass_fd(self) -> None:
        process = mock.Mock(pid=123, returncode=0)
        process.wait.return_value = 0
        with mock.patch.object(probe, "_verify_procfd_alias"):
            with mock.patch.object(probe.subprocess, "Popen", return_value=process) as popen:
                result = probe._run_probe_process(10, 11, 12)
        self.assertEqual(result, probe._ProcessResult(True, 0, "NONE", None))
        args, kwargs = popen.call_args
        self.assertEqual(args[0], probe._build_curl_argv(10))
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], 11)
        self.assertEqual(kwargs["stderr"], 12)
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["close_fds"])
        self.assertEqual(kwargs["pass_fds"], (10,))
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["env"], probe._child_environment())

    def test_popen_oserror_becomes_sanitized_spawn_failure(self) -> None:
        with mock.patch.object(probe, "_verify_procfd_alias"):
            with mock.patch.object(probe.subprocess, "Popen", side_effect=FileNotFoundError("SECRET")):
                result = probe._run_probe_process(10, 11, 12)
        self.assertEqual(
            result,
            probe._ProcessResult(False, None, "NOT_STARTED", "FileNotFoundError"),
        )

    def test_watchdog_terminates_only_owned_process_group(self) -> None:
        process = mock.Mock(pid=321, returncode=-signal.SIGTERM)
        process.wait.side_effect = [subprocess.TimeoutExpired("curl", 50), -signal.SIGTERM]
        with mock.patch.object(probe, "_verify_procfd_alias"):
            with mock.patch.object(probe.subprocess, "Popen", return_value=process):
                with mock.patch.object(probe.os, "killpg") as killpg:
                    with mock.patch.object(
                        probe, "_wait_owned_process_group_gone", return_value=True
                    ):
                        result = probe._run_probe_process(10, 11, 12)
        killpg.assert_called_once_with(321, signal.SIGTERM)
        self.assertEqual(result.watchdog_action, "SIGTERM")

    def test_watchdog_escalates_to_sigkill_after_grace_timeout(self) -> None:
        process = mock.Mock(pid=654, returncode=-signal.SIGKILL)
        process.wait.side_effect = [
            subprocess.TimeoutExpired("curl", 50),
            -signal.SIGKILL,
        ]
        with mock.patch.object(probe, "_verify_procfd_alias"):
            with mock.patch.object(probe.subprocess, "Popen", return_value=process):
                with mock.patch.object(probe.os, "killpg") as killpg:
                    with mock.patch.object(
                        probe,
                        "_wait_owned_process_group_gone",
                        side_effect=(False, True),
                    ):
                        result = probe._run_probe_process(10, 11, 12)
        self.assertEqual(
            killpg.call_args_list,
            [mock.call(654, signal.SIGTERM), mock.call(654, signal.SIGKILL)],
        )
        self.assertEqual(result.watchdog_action, "SIGKILL")


class RealOfflineFdTransportTests(ProbeCase):
    def run_bounded_writer(self, byte_count: int) -> tuple[int, os.stat_result, os.stat_result, bytes]:
        path = self.base / f"body-{byte_count}.bin"
        fd = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, b"preexisting-sentinel" * 10_000)
            before = os.fstat(fd)
            script = (
                "import os,sys;"
                "fd=int(sys.argv[1]);size=int(sys.argv[2]);"
                "handle=open('/proc/self/fd/'+str(fd),'wb',buffering=0);"
                "written=handle.write(b'x'*size);"
                "sys.exit(97) if written!=size else None;"
                "handle.flush();os.fsync(handle.fileno());"
                "handle.close()"
            )
            process = subprocess.Popen(
                (
                    probe.PRLIMIT_PATH,
                    f"--fsize={probe.BODY_SIZE}:{probe.BODY_SIZE}",
                    "--",
                    sys.executable,
                    "-c",
                    script,
                    str(fd),
                    str(byte_count),
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=probe._child_environment(),
                shell=False,
                close_fds=True,
                pass_fds=(fd,),
                start_new_session=True,
            )
            returncode = process.wait(timeout=10)
            after = os.fstat(fd)
            content = os.pread(fd, probe.BODY_SIZE + 1, 0)
            return returncode, before, after, content
        finally:
            os.close(fd)

    def test_real_prlimit_procfd_writer_truncates_same_inode_at_65536(self) -> None:
        self.assertTrue(sys.executable.startswith("/data0/hk_data/kairos-zx/.conda/"))
        returncode, before, after, content = self.run_bounded_writer(65_536)
        self.assertEqual(returncode, 0)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        self.assertGreater(before.st_size, 65_536)
        self.assertEqual(after.st_size, 65_536)
        self.assertEqual(len(content), 65_536)
        self.assertEqual(content, b"x" * 65_536)

    def test_real_prlimit_procfd_writer_rejects_65537_with_nonzero_terminal(self) -> None:
        returncode, before, after, content = self.run_bounded_writer(65_537)
        self.assertNotEqual(returncode, 0)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        self.assertLessEqual(after.st_size, 65_536)
        self.assertLessEqual(len(content), 65_536)


class RealOfflineBoundedProcessTests(ProbeCase):
    @staticmethod
    def python_argv(source: str, *arguments: str) -> tuple[str, ...]:
        return (sys.executable, "-c", source, *arguments)

    def assert_pid_absent(self, pid: int) -> None:
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail(f"synthetic child {pid} survived bounded reader cleanup")

    def test_normal_small_output_is_returned_and_reaped(self) -> None:
        returncode, output = probe._run_git_bounded(
            self.python_argv("import os;os.write(1,b'ok')"),
            timeout_seconds=1.0,
        )
        self.assertEqual(returncode, 0)
        self.assertEqual(output, b"ok")

    def test_no_output_hang_times_out_and_leaves_no_process(self) -> None:
        pid_path = self.base / "no-output.pid"
        source = (
            "import os,sys,time;"
            "open(sys.argv[1],'w').write(str(os.getpid()));"
            "time.sleep(30)"
        )
        with self.assertRaisesRegex(probe.ProbeError, "timed out"):
            probe._run_git_bounded(
                self.python_argv(source, os.fspath(pid_path)),
                timeout_seconds=0.3,
            )
        self.assert_pid_absent(int(pid_path.read_text()))

    def test_small_output_then_hang_is_deadline_bounded(self) -> None:
        source = "import os,time;os.write(1,b'prefix');time.sleep(30)"
        started = time.monotonic()
        with self.assertRaisesRegex(probe.ProbeError, "timed out"):
            probe._run_git_bounded(
                self.python_argv(source),
                timeout_seconds=0.3,
            )
        self.assertLess(time.monotonic() - started, 3.0)

    def test_exited_leader_descendant_holding_stdout_is_killed_as_a_group(self) -> None:
        record = self.base / "process-group.txt"
        source = (
            "import os,signal,sys,time;"
            "child=os.fork();"
            "(signal.signal(signal.SIGTERM,signal.SIG_IGN),time.sleep(30)) "
            "if child==0 else "
            "(open(sys.argv[1],'w').write(str(os.getpid())+' '+str(child)),os._exit(0))"
        )
        recorded_pgid: int | None = None
        recorded_pids: list[int] = []
        real_popen = subprocess.Popen
        processes: list[subprocess.Popen] = []

        def spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        try:
            with mock.patch.object(probe.subprocess, "Popen", side_effect=spawn):
                with self.assertRaisesRegex(probe.ProbeError, "timed out"):
                    probe._run_git_bounded(
                        self.python_argv(source, os.fspath(record)),
                        timeout_seconds=0.3,
                    )
            leader_pid, descendant_pid = map(int, record.read_text().split())
            recorded_pgid = leader_pid
            recorded_pids = [leader_pid, descendant_pid]
            for pid in recorded_pids:
                self.assert_pid_absent(pid)
        finally:
            if recorded_pgid is None and processes:
                recorded_pgid = processes[0].pid
                recorded_pids.append(processes[0].pid)
            if record.exists():
                file_pgid, descendant_pid = map(int, record.read_text().split())
                recorded_pgid = file_pgid
                recorded_pids = list(
                    dict.fromkeys((*recorded_pids, file_pgid, descendant_pid))
                )
            if recorded_pgid is not None:
                try:
                    os.killpg(recorded_pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for pid in recorded_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for _ in range(100):
                live = []
                for pid in recorded_pids:
                    try:
                        os.kill(pid, 0)
                        live.append(pid)
                    except ProcessLookupError:
                        pass
                if not live:
                    break
                time.sleep(0.01)

    def test_output_over_4096_is_rejected_and_child_reaped(self) -> None:
        pid_path = self.base / "overflow.pid"
        source = (
            "import os,sys,time;"
            "open(sys.argv[1],'w').write(str(os.getpid()));"
            "os.write(1,b'x'*5000);time.sleep(30)"
        )
        with self.assertRaisesRegex(probe.ProbeError, "exceeds"):
            probe._run_git_bounded(
                self.python_argv(source, os.fspath(pid_path)),
                timeout_seconds=1.0,
            )
        self.assert_pid_absent(int(pid_path.read_text()))

    def test_reader_exception_reaps_process_and_closes_pipe(self) -> None:
        pid_path = self.base / "reader-error.pid"
        source = (
            "import os,sys,time;"
            "open(sys.argv[1],'w').write(str(os.getpid()));"
            "os.write(1,b'x');time.sleep(30)"
        )
        real_popen = subprocess.Popen
        processes: list[subprocess.Popen] = []

        def spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        class RaisingSelector:
            def __init__(self) -> None:
                self.delegate = probe.selectors.DefaultSelector()

            def register(self, *args, **kwargs):
                return self.delegate.register(*args, **kwargs)

            def unregister(self, *args, **kwargs):
                return self.delegate.unregister(*args, **kwargs)

            def select(self, _timeout=None):
                raise OSError("synthetic select")

            def close(self) -> None:
                self.delegate.close()

        real_selector = probe.selectors.DefaultSelector

        def selector_factory():
            selector = object.__new__(RaisingSelector)
            selector.delegate = real_selector()
            return selector

        with mock.patch.object(probe.subprocess, "Popen", side_effect=spawn):
            with mock.patch.object(
                probe.selectors, "DefaultSelector", side_effect=selector_factory
            ):
                with self.assertRaisesRegex(OSError, "synthetic select"):
                    probe._run_git_bounded(
                        self.python_argv(source, os.fspath(pid_path)),
                        timeout_seconds=1.0,
                    )
        self.assertEqual(len(processes), 1)
        self.assertTrue(processes[0].stdout.closed)
        self.assert_pid_absent(processes[0].pid)

    def test_invalid_timeout_is_rejected_before_spawn(self) -> None:
        for value in (0, -1, True, "1"):
            with self.subTest(value=value):
                with mock.patch.object(probe.subprocess, "Popen") as popen:
                    with self.assertRaises(probe.ProbeError):
                        probe._run_git_bounded(
                            self.python_argv("pass"),
                            timeout_seconds=value,  # type: ignore[arg-type]
                        )
                popen.assert_not_called()


class BoundedRunnerLifecycleFaultTests(unittest.TestCase):
    class Pipe:
        def __init__(self, events, *, fileno_error=None, close_error=None):
            self.events = events
            self.fileno_error = fileno_error
            self.close_error = close_error

        def fileno(self):
            self.events.append("fileno")
            if self.fileno_error is not None:
                raise self.fileno_error
            return 10

        def close(self):
            self.events.append("pipe-close")
            if self.close_error is not None:
                raise self.close_error

    class Selector:
        def __init__(
            self,
            events,
            *,
            register_error=None,
            select_error=None,
            close_error=None,
        ):
            self.events = events
            self.register_error = register_error
            self.select_error = select_error
            self.close_error = close_error

        def register(self, _fd, _events):
            self.events.append("register")
            if self.register_error is not None:
                raise self.register_error

        def select(self, _timeout):
            self.events.append("select")
            if self.select_error is not None:
                raise self.select_error
            return [(mock.Mock(fd=10), None)]

        def unregister(self, _fd):
            self.events.append("unregister")

        def close(self):
            self.events.append("selector-close")
            if self.close_error is not None:
                raise self.close_error

    @staticmethod
    def process(pipe):
        process = mock.Mock(pid=777, stdout=pipe, returncode=0)
        process.wait.return_value = 0
        return process

    def run_initialization_fault(self, pipe, selector_effect):
        process = self.process(pipe)
        with mock.patch.object(probe.subprocess, "Popen", return_value=process):
            with mock.patch.object(
                probe.selectors, "DefaultSelector", side_effect=selector_effect
            ):
                with mock.patch.object(
                    probe, "_stop_and_reap_owned_process"
                ) as stop:
                    with self.assertRaises(OSError):
                        probe._run_git_bounded((sys.executable, "-c", "pass"))
        stop.assert_called_once_with(process, 777)
        return process

    def test_selector_constructor_fault_reaps_and_closes_pipe(self) -> None:
        events: list[str] = []
        pipe = self.Pipe(events)
        self.run_initialization_fault(
            pipe, OSError("selector constructor failure")
        )
        self.assertEqual(events, ["pipe-close"])

    def test_pipe_fileno_fault_reaps_and_closes_all_resources(self) -> None:
        events: list[str] = []
        pipe = self.Pipe(events, fileno_error=OSError("fileno failure"))
        selector = self.Selector(events)
        self.run_initialization_fault(pipe, lambda: selector)
        self.assertEqual(events, ["fileno", "selector-close", "pipe-close"])

    def test_selector_register_fault_reaps_and_closes_all_resources(self) -> None:
        events: list[str] = []
        pipe = self.Pipe(events)
        selector = self.Selector(
            events, register_error=OSError("register failure")
        )
        process = self.process(pipe)
        with mock.patch.object(probe.subprocess, "Popen", return_value=process):
            with mock.patch.object(
                probe.selectors, "DefaultSelector", return_value=selector
            ):
                with mock.patch.object(probe.os, "set_blocking"):
                    with mock.patch.object(
                        probe, "_stop_and_reap_owned_process"
                    ) as stop:
                        with self.assertRaisesRegex(OSError, "register failure"):
                            probe._run_git_bounded(
                                (sys.executable, "-c", "pass")
                            )
        stop.assert_called_once_with(process, 777)
        self.assertEqual(
            events,
            ["fileno", "register", "selector-close", "pipe-close"],
        )

    def test_cleanup_faults_do_not_mask_active_primary_and_both_close(self) -> None:
        events: list[str] = []
        pipe = self.Pipe(
            events, close_error=OSError("pipe close failure")
        )
        selector = self.Selector(
            events,
            select_error=OSError("primary select failure"),
            close_error=OSError("selector close failure"),
        )
        process = self.process(pipe)
        with mock.patch.object(probe.subprocess, "Popen", return_value=process):
            with mock.patch.object(
                probe.selectors, "DefaultSelector", return_value=selector
            ):
                with mock.patch.object(probe.os, "set_blocking"):
                    with mock.patch.object(
                        probe, "_stop_and_reap_owned_process"
                    ) as stop:
                        with self.assertRaisesRegex(OSError, "primary select failure"):
                            probe._run_git_bounded(
                                (sys.executable, "-c", "pass")
                            )
        stop.assert_called_once_with(process, 777)
        self.assertEqual(events[-2:], ["selector-close", "pipe-close"])

    def test_selector_close_is_first_cleanup_error_after_success(self) -> None:
        events: list[str] = []
        pipe = self.Pipe(
            events, close_error=OSError("pipe close failure")
        )
        selector = self.Selector(
            events, close_error=OSError("selector close failure")
        )
        process = self.process(pipe)
        with mock.patch.object(probe.subprocess, "Popen", return_value=process):
            with mock.patch.object(
                probe.selectors, "DefaultSelector", return_value=selector
            ):
                with mock.patch.object(probe.os, "set_blocking"):
                    with mock.patch.object(probe.os, "read", return_value=b""):
                        with mock.patch.object(
                            probe, "_owned_process_group_alive", return_value=False
                        ):
                            with self.assertRaisesRegex(
                                OSError, "selector close failure"
                            ):
                                probe._run_git_bounded(
                                    (sys.executable, "-c", "pass")
                                )
        process.wait.assert_called_once()
        self.assertEqual(events[-2:], ["selector-close", "pipe-close"])

    def test_pipe_close_error_is_reported_when_selector_close_succeeds(self) -> None:
        events: list[str] = []
        pipe = self.Pipe(
            events, close_error=OSError("pipe close failure")
        )
        selector = self.Selector(events)
        process = self.process(pipe)
        with mock.patch.object(probe.subprocess, "Popen", return_value=process):
            with mock.patch.object(
                probe.selectors, "DefaultSelector", return_value=selector
            ):
                with mock.patch.object(probe.os, "set_blocking"):
                    with mock.patch.object(probe.os, "read", return_value=b""):
                        with mock.patch.object(
                            probe, "_owned_process_group_alive", return_value=False
                        ):
                            with self.assertRaisesRegex(OSError, "pipe close failure"):
                                probe._run_git_bounded(
                                    (sys.executable, "-c", "pass")
                                )
        process.wait.assert_called_once()
        self.assertEqual(events[-2:], ["selector-close", "pipe-close"])


class PublicationProtocolTests(ProbeCase):
    def open_stage(self) -> tuple[Path, int]:
        stage = self.base / f"publication-{self._case_index}"
        self._case_index += 1
        stage.mkdir(mode=0o700)
        return stage, os.open(stage, probe._dir_flags())

    def test_link_fsync_unlink_fsync_order_is_exact(self) -> None:
        stage, stage_fd = self.open_stage()
        events: list[str] = []
        real_link = probe.os.link
        real_unlink = probe.os.unlink
        real_fsync = probe.os.fsync

        def link(*args, **kwargs):
            events.append("link")
            return real_link(*args, **kwargs)

        def unlink(*args, **kwargs):
            events.append("unlink")
            return real_unlink(*args, **kwargs)

        def fsync(fd):
            if fd == stage_fd:
                events.append("stage-fsync")
            return real_fsync(fd)

        try:
            with mock.patch.object(probe.os, "link", side_effect=link):
                with mock.patch.object(probe.os, "unlink", side_effect=unlink):
                    with mock.patch.object(probe.os, "fsync", side_effect=fsync):
                        probe._publish_observation(stage_fd, {"value": 1})
        finally:
            os.close(stage_fd)
        self.assertEqual(events, ["link", "stage-fsync", "unlink", "stage-fsync"])
        self.assertEqual({path.name for path in stage.iterdir()}, {probe._OBSERVATION_NAME})

    def test_each_publication_namespace_step_failure_is_not_success(self) -> None:
        for phase in ("link", "first-fsync", "unlink", "second-fsync"):
            with self.subTest(phase=phase):
                stage, stage_fd = self.open_stage()
                real_link = probe.os.link
                real_unlink = probe.os.unlink
                real_fsync = probe.os.fsync
                stage_fsync_calls = 0

                def link(*args, **kwargs):
                    if phase == "link" and kwargs.get("dst_dir_fd") == stage_fd:
                        raise OSError("synthetic link failure")
                    return real_link(*args, **kwargs)

                def unlink(*args, **kwargs):
                    if phase == "unlink":
                        raise OSError("synthetic unlink failure")
                    return real_unlink(*args, **kwargs)

                def fsync(fd):
                    nonlocal stage_fsync_calls
                    if fd == stage_fd:
                        stage_fsync_calls += 1
                        if phase == "first-fsync" and stage_fsync_calls == 1:
                            raise OSError("synthetic first fsync failure")
                        if phase == "second-fsync" and stage_fsync_calls == 2:
                            raise OSError("synthetic second fsync failure")
                    return real_fsync(fd)

                try:
                    with mock.patch.object(probe.os, "link", side_effect=link):
                        with mock.patch.object(probe.os, "unlink", side_effect=unlink):
                            with mock.patch.object(probe.os, "fsync", side_effect=fsync):
                                with self.assertRaisesRegex(OSError, "synthetic"):
                                    probe._publish_observation(stage_fd, {"value": 1})
                finally:
                    os.close(stage_fd)
                names = {path.name for path in stage.iterdir()}
                self.assertIn(probe._OBSERVATION_TEMP, names)
                if phase == "link":
                    self.assertNotIn(probe._OBSERVATION_NAME, names)
                else:
                    self.assertIn(probe._OBSERVATION_NAME, names)

    def test_publication_fail_close_false_or_error_is_fatal(self) -> None:
        effects = (
            False,
            OSError("synthetic publication recovery failure"),
        )
        for effect in effects:
            with self.subTest(effect=effect):
                stage, stage_fd = self.open_stage()
                real_fsync = probe.os.fsync
                stage_fsync_calls = 0

                def fsync(fd):
                    nonlocal stage_fsync_calls
                    if fd == stage_fd:
                        stage_fsync_calls += 1
                        if stage_fsync_calls == 2:
                            raise OSError("synthetic publication failure")
                    return real_fsync(fd)

                try:
                    with mock.patch.object(probe.os, "fsync", side_effect=fsync):
                        with mock.patch.object(
                            probe,
                            "_fail_closed_observation_publication",
                            side_effect=(
                                effect if isinstance(effect, BaseException) else None
                            ),
                            return_value=effect,
                        ):
                            with self.assertRaisesRegex(
                                probe.ProbeError,
                                "publication fail-close unconfirmed",
                            ):
                                probe._publish_observation(stage_fd, {"value": 1})
                finally:
                    os.close(stage_fd)


class GitAndCliTests(unittest.TestCase):
    def test_git_clean_head_checks_exact_head_then_porcelain(self) -> None:
        with mock.patch.object(
            probe,
            "_run_git_bounded",
            side_effect=((0, (APPROVED_COMMIT + "\n").encode()), (0, b"")),
        ) as run:
            self.assertEqual(probe._git_clean_head(APPROVED_COMMIT), APPROVED_COMMIT)
        self.assertEqual(run.call_count, 2)
        self.assertIn("rev-parse", run.call_args_list[0].args[0])
        self.assertIn("status", run.call_args_list[1].args[0])

    def test_git_dirty_mismatch_failure_and_oversize_are_rejected(self) -> None:
        cases = (
            ((0, ("b" * 40 + "\n").encode()),),
            ((1, b""),),
            ((0, (APPROVED_COMMIT + "\n").encode()), (0, b"?? file\n")),
            ((0, (APPROVED_COMMIT + "\n").encode()), (1, b"")),
        )
        for side_effect in cases:
            with self.subTest(side_effect=side_effect):
                with mock.patch.object(probe, "_run_git_bounded", side_effect=side_effect):
                    with self.assertRaises(probe.ProbeError):
                        probe._git_clean_head(APPROVED_COMMIT)

    def test_cli_status_exit_codes_and_canonical_stdout(self) -> None:
        cases = (
            (probe.ProbeStatus.PROBE_OK, 0),
            (probe.ProbeStatus.BLOCKED, 3),
            (probe.ProbeStatus.INCOMPLETE, 4),
        )
        for status, expected in cases:
            with self.subTest(status=status):
                report = probe.ProbeReport(status, "REASON", None)
                stdout = io.StringIO()
                with mock.patch.object(probe, "verify", return_value=report):
                    with contextlib.redirect_stdout(stdout):
                        self.assertEqual(probe.main(["verify"]), expected)
                self.assertEqual(json.loads(stdout.getvalue())["status"], status.value)

    def test_cli_execute_requires_only_approved_commit(self) -> None:
        report = probe.ProbeReport(probe.ProbeStatus.BLOCKED, "BLOCK", None)
        with mock.patch.object(probe, "execute", return_value=report) as execute:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    probe.main(["execute", "--approved-commit", APPROVED_COMMIT]),
                    3,
                )
        execute.assert_called_once_with(APPROVED_COMMIT)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                probe.main(["verify", "--project-root", "/tmp"])
        self.assertEqual(raised.exception.code, 2)

    def test_cli_expected_errors_are_sanitized(self) -> None:
        errors = (
            probe.ProbeError("SECRET"),
            FileExistsError("SECRET"),
            FileNotFoundError("SECRET"),
            PermissionError("SECRET"),
            OSError("SECRET"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                stderr = io.StringIO()
                with mock.patch.object(probe, "verify", side_effect=error):
                    with contextlib.redirect_stderr(stderr):
                        self.assertEqual(probe.main(["verify"]), 2)
                self.assertNotIn("SECRET", stderr.getvalue())
                self.assertIn(type(error).__name__, stderr.getvalue())

    def test_programming_and_control_flow_errors_propagate(self) -> None:
        for error in (ValueError("bug"), TypeError("bug"), RuntimeError("bug"), KeyboardInterrupt(), SystemExit(9)):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(probe, "verify", side_effect=error):
                    with self.assertRaises(type(error)):
                        probe.main(["verify"])


class ResourceLifecycleTests(unittest.TestCase):
    def test_best_effort_close_attempts_all_and_raises_first(self) -> None:
        events: list[int] = []

        def close(fd: int) -> None:
            events.append(fd)
            raise OSError(str(fd))

        with mock.patch.object(probe.os, "close", side_effect=close):
            with self.assertRaisesRegex(OSError, "1"):
                probe._close_fds_best_effort((("one", 1), ("two", 2)))
        self.assertEqual(events, [1, 2])

    def test_best_effort_close_preserves_active_primary_error(self) -> None:
        events: list[int] = []

        def close(fd: int) -> None:
            events.append(fd)
            raise OSError(str(fd))

        with mock.patch.object(probe.os, "close", side_effect=close):
            probe._close_fds_best_effort(
                (("one", 1), ("two", 2)), ValueError("primary")
            )
        self.assertEqual(events, [1, 2])

    def test_partial_absolute_chain_open_closes_every_held_fd(self) -> None:
        closed: list[int] = []
        directory = mock.Mock(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        directory.st_gid = 0
        with mock.patch.object(probe.os, "open", side_effect=(10, 20, OSError("open"))):
            with mock.patch.object(probe.os, "fstat", return_value=directory):
                with mock.patch.object(probe.os, "close", side_effect=lambda fd: closed.append(fd)):
                    with self.assertRaisesRegex(OSError, "open"):
                        probe._open_absolute_chain(Path("/a/b"))
        self.assertEqual(closed, [20, 10])

    def test_created_child_validation_failure_closes_child_and_parent(self) -> None:
        closed: list[int] = []
        with mock.patch.object(probe.os, "dup", return_value=10):
            with mock.patch.object(
                probe.os,
                "open",
                side_effect=(FileNotFoundError("absent"), 20),
            ):
                with mock.patch.object(probe.os, "mkdir"):
                    with mock.patch.object(probe.os, "fsync"):
                        with mock.patch.object(
                            probe,
                            "_require_owned_directory",
                            side_effect=(None, probe.ProbeError("invalid child")),
                        ):
                            with mock.patch.object(
                                probe.os,
                                "close",
                                side_effect=lambda fd: closed.append(fd),
                            ):
                                with self.assertRaisesRegex(
                                    probe.ProbeError, "invalid child"
                                ):
                                    probe._open_or_create_relative_chain(
                                        9, "component"
                                    )
        self.assertEqual(closed, [20, 10])

    def test_trusted_and_owned_directory_predicates_enforce_owner_and_mode(self) -> None:
        base = dict(st_mode=stat.S_IFDIR | 0o755, st_uid=os.geteuid(), st_gid=os.getegid())
        valid = mock.Mock(**base)
        with mock.patch.object(probe.os, "fstat", return_value=valid):
            probe._require_trusted_directory(1, "valid")
            probe._require_owned_directory(1, "valid")
        invalid = (
            mock.Mock(st_mode=stat.S_IFREG | 0o600, st_uid=os.geteuid(), st_gid=os.getegid()),
            mock.Mock(st_mode=stat.S_IFDIR | 0o777, st_uid=os.geteuid(), st_gid=os.getegid()),
            mock.Mock(st_mode=stat.S_IFDIR | 0o755, st_uid=os.geteuid() + 1, st_gid=os.getegid()),
        )
        for value in invalid:
            with self.subTest(value=value):
                with mock.patch.object(probe.os, "fstat", return_value=value):
                    with self.assertRaises(probe.ProbeError):
                        probe._require_owned_directory(1, "invalid")


if __name__ == "__main__":
    unittest.main()
