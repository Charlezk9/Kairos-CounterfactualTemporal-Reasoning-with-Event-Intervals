from __future__ import annotations

import errno
import io
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
import warnings
import zipfile

import kairos.strategyqa_acquisition as acquisition
from kairos.archive_safety import (
    ArchiveFormat,
    ArchiveInspection,
    MemberKind,
    MemberSummary,
)


DATA0_TMP = "/data0/hk_data/kairos-zx/.tmp"
APPROVED_COMMIT = "79a259b711e17af8363bbe0f0a30ea6020328171"
MEMBERSHIP = {
    "uid": 1001,
    "gid": 1001,
    "username": "yangbin",
    "group_name": "yangbin",
    "explicit_members": [],
    "primary_users": ["yangbin"],
}
ACL = {
    "checked_anchor_count": 4,
    "named_access_acl": "ABSENT",
    "default_acl": "ABSENT",
}


def resource_gate():
    limits = {}
    for name, _resource_id, maximum in acquisition._RESOURCE_RULES:
        limits[name] = {"soft": maximum, "hard": maximum}
    return {
        "limits": limits,
        "cpu_affinity": [0, 1],
        "environment": dict(acquisition._RUNTIME_ENVIRONMENT),
    }


def zip_bytes() -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("strategyqa_train.json", b"[]\n")
        archive.writestr("README.txt", b"synthetic test archive\n")
    return result.getvalue()


def header_bytes(size: int, *, etag: str | None = None) -> bytes:
    token = etag or acquisition.EXPECTED_ETAG_TOKEN
    return (
        "HTTP/2 200\r\n"
        f'ETag: "{token}"\r\n'
        "Last-Modified: Thu, 07 Jan 2021 12:34:56 GMT\r\n"
        "Content-Type: application/zip\r\n"
        f"Content-Length: {size}\r\n"
        "\r\n"
    ).encode("ascii")


def writeout_bytes(size: int, *, url: str = acquisition.SOURCE_URL) -> bytes:
    return (
        f"{acquisition._WRITEOUT_BEGIN}\n"
        "http_code:200\n"
        "num_redirects:0\n"
        f"url_effective:{url}\n"
        "content_type:application/zip\n"
        f"size_download:{size}\n"
        f"{acquisition._WRITEOUT_END}\n"
    ).encode("ascii")


def overwrite_fd(fd: int, content: bytes) -> None:
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    view = memoryview(content)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise AssertionError("synthetic write was short")
        view = view[count:]


def successful_transfer(archive_fd, header_fd, writeout_fd, stderr_fd):
    archive = zip_bytes()
    overwrite_fd(archive_fd, archive)
    overwrite_fd(header_fd, header_bytes(len(archive)))
    overwrite_fd(writeout_fd, writeout_bytes(len(archive)))
    overwrite_fd(stderr_fd, b"")
    return acquisition._ProcessResult(0, "NONE", "NONE")


def chain_anchors(path: Path) -> tuple[acquisition.ChainAnchor, ...]:
    current = Path("/")
    paths = [current]
    for component in path.parts[1:]:
        current = current / component
        paths.append(current)
    values = []
    for item in paths:
        value = os.stat(item, follow_symlinks=False)
        values.append(
            acquisition.ChainAnchor(
                os.fspath(item),
                value.st_dev,
                value.st_ino,
                value.st_uid,
                value.st_gid,
                stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
            )
        )
    return tuple(values)


class TemporaryLayout(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            dir=DATA0_TMP, prefix="strategyqa-acquisition-test."
        )
        os.chmod(self.temporary.name, 0o700)
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir(mode=0o700)
        self.layout = acquisition._Layout(
            self.project,
            "data/raw/strategyqa",
            ".acquire-official-20210107",
            acquisition.REVISION,
        )
        self.anchors = chain_anchors(self.project)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def call_fetch(
        self,
        transfer=None,
        *,
        membership=None,
        acl=None,
        git=None,
    ) -> acquisition.StageReport:
        return acquisition._fetch_layout(
            self.layout,
            self.anchors,
            APPROVED_COMMIT,
            git or (lambda approved: approved),
            membership or (lambda: MEMBERSHIP),
            acl or (lambda _fd: ACL),
            transfer or successful_transfer,
            resource_gate(),
            True,
        )


class FrozenContractTests(unittest.TestCase):
    def test_frozen_source_and_limits(self):
        self.assertEqual(acquisition.DATASET, "strategyqa")
        self.assertEqual(acquisition.REVISION, "official-20210107")
        self.assertEqual(
            acquisition.SOURCE_URL,
            "https://storage.googleapis.com/ai2i/strategyqa/data/strategyqa_dataset.zip",
        )
        self.assertEqual(
            acquisition.EXPECTED_ETAG_TOKEN,
            "f4ae9d9296c06f90d80aee1e4a25d58a",
        )
        self.assertEqual(acquisition.EXPECTED_LAST_MODIFIED_DATE, "2021-01-07")
        self.assertFalse(acquisition.RUNTIME_REDIRECT_SEMANTICS_VERIFIED)
        self.assertEqual(len(acquisition.FROZEN_CHAIN_ANCHORS), 4)
        self.assertEqual(
            acquisition.FROZEN_CHAIN_ANCHORS[-1],
            acquisition.ChainAnchor(
                "/data0/hk_data/kairos-zx",
                2048,
                176553986,
                1001,
                1001,
                stat.S_IFDIR | 0o775,
            ),
        )
        self.assertEqual(
            acquisition.PROJECT_ROOT / acquisition._TRANSACTION_MARKER,
            Path(
                "/data0/hk_data/kairos-zx/"
                ".kairos-strategyqa-official-20210107.incomplete"
            ),
        )

    def test_public_fetch_is_blocked_before_any_subprocess_or_stage(self):
        with mock.patch.object(acquisition, "_fetch_layout") as internal:
            with mock.patch.object(subprocess, "Popen", side_effect=AssertionError):
                with self.assertRaisesRegex(
                    acquisition.StrategyQaAcquisitionError, "UNVERIFIED"
                ):
                    acquisition.fetch(APPROVED_COMMIT)
        internal.assert_not_called()

    def test_curl_argv_is_fixed_and_has_no_timeout_wrapper(self):
        arguments = acquisition._build_curl_argv(17, 19)
        self.assertEqual(arguments[0], acquisition.PRLIMIT_PATH)
        self.assertEqual(arguments[7], acquisition.CURL_PATH)
        self.assertEqual(arguments[8], "--disable")
        self.assertNotIn("timeout", arguments)
        self.assertEqual(arguments[-1], acquisition.SOURCE_URL)
        self.assertEqual(arguments[arguments.index("--max-redirs") + 1], "0")
        self.assertEqual(
            arguments[arguments.index("--dump-header") + 1], "/proc/self/fd/19"
        )
        self.assertEqual(
            arguments[arguments.index("--output") + 1], "/proc/self/fd/17"
        )

    def test_child_environment_is_minimal_and_gpu_hidden(self):
        environment = acquisition._child_environment()
        self.assertEqual(environment["CUDA_VISIBLE_DEVICES"], "")
        self.assertEqual(environment["OMP_NUM_THREADS"], "2")
        self.assertNotIn("HOME", environment)
        self.assertFalse(any("PROXY" in key.upper() for key in environment))

    def test_actual_curl_probe_uses_only_version_and_help(self):
        environment = acquisition._strict_command_environment()
        observations = {}
        for arguments in (("--version",), ("--help", "all")):
            with self.subTest(arguments=arguments):
                code, output = acquisition._run_bounded_command(
                    (acquisition.CURL_PATH, *arguments),
                    timeout_seconds=5.0,
                    output_limit=262_144,
                    environment=environment,
                )
                self.assertEqual(code, 0)
                self.assertTrue(output)
                observations[arguments] = output
        self.assertIn(b"curl 7.68.0", observations[("--version",)])
        for required in (
            b"--disable",
            b"--proto-redir",
            b"--max-redirs",
            b"--max-filesize",
            b"--write-out",
        ):
            self.assertIn(required, observations[("--help", "all")])


class ResourceGateTests(unittest.TestCase):
    def test_resource_observation_accepts_exact_or_stricter_soft_limits(self):
        value = resource_gate()
        value["limits"]["address_space"]["soft"] -= 1
        value["cpu_affinity"] = [7]
        self.assertEqual(acquisition._validate_resource_observation(value), value)

    def test_resource_observation_rejects_each_unenforced_gate(self):
        cases = (
            ("address_space", acquisition.RESOURCE_AS_LIMIT + 1),
            ("cpu_seconds", acquisition.RESOURCE_CPU_LIMIT + 1),
            ("core_bytes", 1),
            ("open_files", acquisition.RESOURCE_NOFILE_LIMIT + 1),
            ("file_size_bytes", acquisition.RESOURCE_FSIZE_LIMIT + 1),
        )
        for name, unsafe in cases:
            with self.subTest(name=name):
                value = resource_gate()
                value["limits"][name]["soft"] = unsafe
                with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                    acquisition._validate_resource_observation(value)
        value = resource_gate()
        value["cpu_affinity"] = [0, 1, 2]
        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            acquisition._validate_resource_observation(value)
        value = resource_gate()
        value["environment"]["CUDA_VISIBLE_DEVICES"] = "0"
        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            acquisition._validate_resource_observation(value)
        for hard in (acquisition.resource.RLIM_INFINITY, acquisition.RESOURCE_AS_LIMIT + 1):
            with self.subTest(address_space_hard=hard):
                value = resource_gate()
                value["limits"]["address_space"]["hard"] = hard
                with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                    acquisition._validate_resource_observation(value)

    def test_cli_gate_lowers_only_soft_limits_and_affinity(self):
        current = {
            resource_id: (acquisition.resource.RLIM_INFINITY, 123)
            for _name, resource_id, _maximum in acquisition._RESOURCE_RULES
        }
        current[acquisition.resource.RLIMIT_CORE] = (5, 5)
        set_calls = []

        def getrlimit(resource_id):
            return current[resource_id]

        def setrlimit(resource_id, pair):
            set_calls.append((resource_id, pair))
            current[resource_id] = pair

        with mock.patch.object(acquisition.resource, "getrlimit", side_effect=getrlimit):
            with mock.patch.object(
                acquisition.resource, "setrlimit", side_effect=setrlimit
            ):
                with mock.patch.object(
                    os, "sched_getaffinity", side_effect=({7, 8, 9}, {7, 8})
                ):
                    with mock.patch.object(os, "sched_setaffinity") as set_affinity:
                        with mock.patch.dict(os.environ, {}, clear=True):
                            observed = acquisition._apply_cli_resource_gate()
        self.assertTrue(set_calls)
        self.assertEqual(current[acquisition.resource.RLIMIT_CORE], (0, 0))
        maxima = {
            resource_id: maximum
            for _name, resource_id, maximum in acquisition._RESOURCE_RULES
        }
        self.assertTrue(
            all(
                0 <= pair[0] <= pair[1] <= maxima[resource_id]
                for resource_id, pair in set_calls
            )
        )
        self.assertTrue(
            all(
                pair[1] == min(123, maxima[resource_id])
                for resource_id, pair in set_calls
                if resource_id != acquisition.resource.RLIMIT_CORE
            )
        )
        set_affinity.assert_called_once_with(0, (7, 8))
        self.assertEqual(observed["cpu_affinity"], [7, 8])

    def test_direct_apis_only_validate_and_fetch_blocks_first(self):
        with mock.patch.object(
            acquisition, "_validate_runtime_gate", side_effect=AssertionError
        ):
            with mock.patch.object(os, "open", side_effect=AssertionError):
                with self.assertRaisesRegex(
                    acquisition.StrategyQaAcquisitionError, "UNVERIFIED"
                ):
                    acquisition.fetch("not-even-a-commit")
        with mock.patch.object(
            acquisition,
            "_validate_runtime_gate",
            side_effect=acquisition.StrategyQaAcquisitionError("gate absent"),
        ):
            with mock.patch.object(acquisition, "_verify_stage_layout") as verifier:
                with self.assertRaisesRegex(
                    acquisition.StrategyQaAcquisitionError, "gate absent"
                ):
                    acquisition.verify_stage()
        verifier.assert_not_called()

    def test_public_fetch_true_flag_wires_internal_arguments_without_io(self):
        expected = acquisition.StageReport(
            acquisition.StageStatus.BLOCKED, "SYNTHETIC", None
        )
        resources = resource_gate()
        with mock.patch.object(
            acquisition, "RUNTIME_REDIRECT_SEMANTICS_VERIFIED", True
        ):
            with mock.patch.object(
                acquisition, "_validate_runtime_gate", return_value=resources
            ) as gate:
                with mock.patch.object(
                    acquisition, "_fetch_layout", return_value=expected
                ) as internal:
                    with mock.patch.object(os, "open", side_effect=AssertionError):
                        self.assertEqual(acquisition.fetch(APPROVED_COMMIT), expected)
        gate.assert_called_once_with()
        internal.assert_called_once_with(
            acquisition._PRODUCTION_LAYOUT,
            acquisition.FROZEN_CHAIN_ANCHORS,
            APPROVED_COMMIT,
            acquisition._git_clean_head,
            acquisition._verify_private_group,
            acquisition._verify_chain_acl,
            acquisition._run_transfer,
            resources,
            True,
        )

    def test_resource_read_set_and_affinity_failures_are_fatal(self):
        with mock.patch.object(
            acquisition.resource,
            "getrlimit",
            side_effect=OSError(errno.EIO, "getrlimit"),
        ):
            with self.assertRaises(OSError):
                acquisition._resource_observation()
        with mock.patch.object(
            acquisition.resource, "getrlimit", return_value=(-1, -1)
        ):
            with mock.patch.object(
                acquisition.resource,
                "setrlimit",
                side_effect=OSError(errno.EPERM, "setrlimit"),
            ):
                with mock.patch.dict(os.environ, {}, clear=True):
                    with self.assertRaises(OSError):
                        acquisition._apply_cli_resource_gate()
        current = {
            resource_id: (maximum, -1)
            for _name, resource_id, maximum in acquisition._RESOURCE_RULES
        }
        with mock.patch.object(
            acquisition.resource,
            "getrlimit",
            side_effect=lambda resource_id: current[resource_id],
        ):
            with mock.patch.object(acquisition.resource, "setrlimit"):
                with mock.patch.object(
                    os, "sched_getaffinity", return_value={0, 1, 2}
                ):
                    with mock.patch.object(
                        os,
                        "sched_setaffinity",
                        side_effect=OSError(errno.EPERM, "affinity"),
                    ):
                        with mock.patch.dict(os.environ, {}, clear=True):
                            with self.assertRaises(OSError):
                                acquisition._apply_cli_resource_gate()


class PolicyGateTests(unittest.TestCase):
    def test_acl_absence_uses_held_descriptor(self):
        observed = []

        def absent(fd, name):
            observed.append((fd, name))
            raise OSError(errno.ENODATA, "absent")

        with mock.patch.object(os, "getxattr", side_effect=absent):
            self.assertEqual(
                acquisition._verify_chain_acl((41, 42, 43, 44)), ACL
            )
        self.assertEqual(
            observed,
            [
                (fd, name)
                for fd in (41, 42, 43, 44)
                for name in (
                    "system.posix_acl_access",
                    "system.posix_acl_default",
                )
            ],
        )

    def test_acl_present_or_unqueryable_is_rejected(self):
        for effect in (b"acl", OSError(errno.EOPNOTSUPP, "unsupported")):
            with self.subTest(effect=repr(effect)):
                if isinstance(effect, BaseException):
                    patcher = mock.patch.object(os, "getxattr", side_effect=effect)
                else:
                    patcher = mock.patch.object(os, "getxattr", return_value=effect)
                with patcher:
                    with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                        acquisition._verify_chain_acl((41, 42, 43, 44))

    def test_private_group_exact_population(self):
        def getent(arguments, _limit):
            if arguments == ("group", "1001"):
                return 0, b"yangbin:x:1001:\n"
            self.assertEqual(arguments, ("passwd",))
            return 0, b"root:x:0:0:root:/root:/bin/bash\nyangbin:x:1001:1001::/home/yangbin:/bin/bash\n"

        with mock.patch.object(acquisition, "_run_getent", side_effect=getent):
            with mock.patch.object(os, "geteuid", return_value=1001):
                result = acquisition._verify_private_group()
        self.assertEqual(result["primary_users"], ["yangbin"])
        self.assertEqual(result["explicit_members"], [])

    def test_private_group_rejects_another_member(self):
        responses = iter(
            (
                (0, b"yangbin:x:1001:yangbin,other\n"),
                (0, b"yangbin:x:1001:1001::/home/yangbin:/bin/bash\n"),
            )
        )
        with mock.patch.object(
            acquisition, "_run_getent", side_effect=lambda *_args: next(responses)
        ):
            with mock.patch.object(os, "geteuid", return_value=1001):
                with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                    acquisition._verify_private_group()

    def test_private_group_rejects_wrong_name_duplicates_and_empty_members(self):
        group_records = (
            b"lab:x:1001:\n",
            b"yangbin:x:1001:yangbin,yangbin\n",
            b"yangbin:x:1001:yangbin,\n",
        )
        passwd = b"yangbin:x:1001:1001::/home/yangbin:/bin/bash\n"
        for group in group_records:
            with self.subTest(group=group):
                responses = iter(((0, group), (0, passwd)))
                with mock.patch.object(
                    acquisition,
                    "_run_getent",
                    side_effect=lambda *_args: next(responses),
                ):
                    with mock.patch.object(os, "geteuid", return_value=1001):
                        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                            acquisition._verify_private_group()

    def test_policy_gate_rejects_self_consistent_nonfrozen_callback_values(self):
        fake = {**MEMBERSHIP, "group_name": "lab"}
        with mock.patch.object(acquisition, "_assert_absolute_chain"):
            with self.assertRaisesRegex(
                acquisition.StrategyQaAcquisitionError, "frozen policy"
            ):
                acquisition._policy_gate(
                    acquisition._PRODUCTION_LAYOUT,
                    (),
                    (),
                    lambda: fake,
                    lambda _fds: ACL,
                )

    def test_git_gate_uses_three_exact_queries(self):
        responses = iter(
            (
                (0, (APPROVED_COMMIT + "\n").encode()),
                (0, b""),
                (0, (APPROVED_COMMIT + "\n").encode()),
            )
        )
        calls = []

        def run_git(arguments):
            calls.append(arguments)
            return next(responses)

        with mock.patch.object(acquisition, "_run_git", side_effect=run_git):
            self.assertEqual(acquisition._git_clean_head(APPROVED_COMMIT), APPROVED_COMMIT)
        self.assertEqual(calls[0], ("rev-parse", "--verify", "HEAD"))
        self.assertEqual(calls[2], calls[0])
        self.assertEqual(calls[1][0], "status")

    def test_git_gate_rejects_dirty_tree(self):
        responses = iter(
            (
                (0, (APPROVED_COMMIT + "\n").encode()),
                (0, b"?? untracked\n"),
                (0, (APPROVED_COMMIT + "\n").encode()),
            )
        )
        with mock.patch.object(
            acquisition, "_run_git", side_effect=lambda _args: next(responses)
        ):
            with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                acquisition._git_clean_head(APPROVED_COMMIT)


class HttpEvidenceTests(unittest.TestCase):
    def test_valid_identity_and_retry_transcript(self):
        content = (
            b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n"
            b"HTTP/1.1 103 Early Hints\r\n\r\n"
            + header_bytes(123)
        )
        observed = acquisition._parse_header_blocks(content)
        self.assertEqual(observed.status_code, 200)
        self.assertEqual(observed.retry_failure_statuses, (503,))
        self.assertEqual(observed.content_length, 123)

    def test_identity_and_redirect_fail_closed(self):
        cases = {
            "weak etag": header_bytes(10).replace(b'ETag: "', b'ETag: W/"'),
            "wrong etag": header_bytes(10, etag="0" * 32),
            "mime parameter": header_bytes(10).replace(
                b"application/zip", b"application/zip; charset=binary"
            ),
            "location": header_bytes(10).replace(
                b"Content-Length:", b"Location: https://example.invalid/\r\nContent-Length:"
            ),
            "lf": header_bytes(10).replace(b"\r\n", b"\n"),
            "duplicate identity": header_bytes(10) + header_bytes(10),
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(acquisition._SourceBlocked):
                    acquisition._parse_header_blocks(content)

    def test_writeout_is_exact_and_effective_url_is_pinned(self):
        observed = acquisition._parse_writeout(writeout_bytes(55))
        self.assertEqual(observed.size_download, 55)
        acquisition._validate_effective_url(observed.effective_url)
        with self.assertRaises(acquisition._SourceBlocked):
            acquisition._parse_writeout(writeout_bytes(55) + b"extra")
        with self.assertRaises(acquisition._SourceBlocked):
            acquisition._validate_effective_url("https://example.invalid/file.zip")

    def test_all_terminal_interim_retry_identity_and_control_branches(self):
        cases = {
            "redirect status": header_bytes(10).replace(b"200", b"302", 1),
            "unknown terminal": header_bytes(10).replace(b"200", b"404", 1),
            "interim identity": b"HTTP/1.1 103 Early\r\nETag: x\r\n\r\n" + header_bytes(10),
            "retry identity": b"HTTP/1.1 503 Retry\r\nLast-Modified: x\r\n\r\n" + header_bytes(10),
            "wrong date": header_bytes(10).replace(b"07 Jan 2021", b"08 Jan 2021"),
            "uppercase mime": header_bytes(10).replace(b"application/zip", b"Application/Zip"),
            "negative length": header_bytes(10).replace(b"Content-Length: 10", b"Content-Length: -1"),
            "control reason": header_bytes(10).replace(b"HTTP/2 200", b"HTTP/2 200\tbad"),
            "duplicate etag": header_bytes(10).replace(
                b"ETag:", b'ETag: "extra"\r\nETag:'
            ),
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(acquisition._SourceBlocked):
                    acquisition._parse_header_blocks(content)

    def test_writeout_missing_reordered_redirect_and_numeric_grammar(self):
        base = writeout_bytes(10)
        cases = (
            base.replace(b"num_redirects:0", b"num_redirects:1"),
            base.replace(b"http_code:200", b"http_code:+200"),
            base.replace(b"size_download:10", b"size_download:-1"),
            base.replace(b"http_code:200\nnum_redirects:0", b"num_redirects:0\nhttp_code:200"),
            base.replace(b"content_type:application/zip\n", b""),
            base + b"KAIROS_STRATEGYQA_WRITEOUT_END\n",
        )
        for content in cases[1:]:
            with self.subTest(content=content[:40]):
                with self.assertRaises(acquisition._SourceBlocked):
                    acquisition._parse_writeout(content)
        redirect = acquisition._parse_writeout(cases[0])
        self.assertEqual(redirect.num_redirects, 1)


class ArchiveLimitTests(TemporaryLayout):
    def evaluation_fds(self, archive: bytes):
        directory = Path(
            tempfile.mkdtemp(dir=self.temporary.name, prefix="archive-limit-case.")
        )
        os.chmod(directory, 0o700)
        paths = [directory / f"archive-limit-{index}" for index in range(3)]
        fds = [os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600) for path in paths]
        overwrite_fd(fds[0], archive)
        overwrite_fd(fds[1], header_bytes(len(archive)))
        overwrite_fd(fds[2], writeout_bytes(len(archive)))
        return fds

    def test_archive_byte_member_metadata_and_expanded_limit_plus_one(self):
        archive = zip_bytes()
        cases = (
            ("ARCHIVE_LIMIT", len(archive) - 1, acquisition.StrategyQaAcquisitionError),
            ("MEMBER_LIMIT", 1, None),
            ("METADATA_LIMIT", 1, None),
            ("EXTRACTED_LIMIT", 1, None),
        )
        for constant, limit, raised in cases:
            with self.subTest(constant=constant):
                fds = self.evaluation_fds(archive)
                try:
                    with mock.patch.object(acquisition, constant, limit):
                        result = acquisition._evaluate_stage(
                            acquisition._ProcessResult(0, "NONE", "NONE"),
                            *fds,
                        )
                        self.assertIs(result.status, acquisition.StageStatus.BLOCKED)
                        if constant == "ARCHIVE_LIMIT":
                            self.assertEqual(result.reason_code, "HTTP_SIZE_MISMATCH")
                        else:
                            self.assertEqual(result.reason_code, "ARCHIVE_REJECTED")
                finally:
                    for fd in fds:
                        os.close(fd)

    def test_inventory_is_incremental_at_exact_limit_and_limit_plus_one(self):
        inspection = ArchiveInspection(
            ArchiveFormat.ZIP,
            "0" * 64,
            1,
            1,
            (MemberSummary("a", MemberKind.FILE, 1, "1" * 64),),
        )
        content = acquisition._inventory_bytes(inspection)
        with mock.patch.object(acquisition, "INVENTORY_LIMIT", len(content)):
            self.assertEqual(acquisition._inventory_bytes(inspection), content)
        with mock.patch.object(acquisition, "INVENTORY_LIMIT", len(content) - 1):
            with self.assertRaisesRegex(acquisition._SourceBlocked, "inventory"):
                acquisition._inventory_bytes(inspection)


class FetchIntegrationTests(TemporaryLayout):
    def test_synthetic_success_publishes_replayable_stage(self):
        membership_calls = []
        acl_calls = []
        git_calls = []

        def membership():
            membership_calls.append(True)
            return MEMBERSHIP

        def acl(fd):
            acl_calls.append(fd)
            return ACL

        def git(approved):
            git_calls.append(approved)
            return approved

        report = self.call_fetch(membership=membership, acl=acl, git=git)
        self.assertIs(report.status, acquisition.StageStatus.STAGE_OK)
        self.assertEqual(report.reason_code, "SOURCE_ENVELOPE_VERIFIED")
        self.assertEqual(len(membership_calls), 4)
        self.assertEqual(len(acl_calls), 4)
        self.assertEqual(len(git_calls), 3)
        manifest = report.observation
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["runtime_redirect_semantics"], "UNVERIFIED")
        self.assertEqual(manifest["schema_status"], "UNVERIFIED")
        self.assertEqual(manifest["license_status"], "UNVERIFIED")
        self.assertEqual(manifest["policy"]["membership"], MEMBERSHIP)
        self.assertEqual(manifest["policy"]["acl"], ACL)
        self.assertEqual(manifest["runtime_resources"], resource_gate())
        self.assertFalse((self.project / acquisition._TRANSACTION_MARKER).exists())
        replay = acquisition._verify_stage_layout(self.layout, self.anchors)
        self.assertEqual(replay, report)

    def test_publication_fds_are_closed_before_commit_replay(self):
        original_publish = acquisition._publish_manifest
        original_replay = acquisition._verify_stage_layout_strict
        original_commit = acquisition._commit_transaction_marker
        held = {}
        calls = {"replay": 0, "commit": 0}

        def publish(*args, **kwargs):
            result = original_publish(*args, **kwargs)
            held["guard"] = result.guard_fd
            held["final"] = result.final_fd
            held["fingerprint"] = result.pair_fingerprint
            return result

        def replay(*args, **kwargs):
            calls["replay"] += 1
            self.assertTrue(
                (self.project / acquisition._TRANSACTION_MARKER).exists()
            )
            for name in ("guard", "final"):
                with self.assertRaises(OSError):
                    os.fstat(held[name])
            return original_replay(*args, **kwargs)

        def commit(*args, **kwargs):
            calls["commit"] += 1
            for name in ("guard", "final"):
                with self.assertRaises(OSError):
                    os.fstat(held[name])
            return original_commit(*args, **kwargs)

        with mock.patch.object(acquisition, "_publish_manifest", side_effect=publish):
            with mock.patch.object(
                acquisition, "_verify_stage_layout_strict", side_effect=replay
            ):
                with mock.patch.object(
                    acquisition, "_commit_transaction_marker", side_effect=commit
                ):
                    report = self.call_fetch()
        self.assertIs(report.status, acquisition.StageStatus.STAGE_OK)
        self.assertEqual(calls, {"replay": 1, "commit": 1})
        for name in ("guard", "final"):
            with self.assertRaises(OSError):
                os.fstat(held[name])

    def test_terminal_manifest_fd_close_fault_is_not_retried(self):
        for target_name in ("final", "guard"):
            with self.subTest(target=target_name):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-terminal-manifest-close."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(
                        project,
                        "data/raw/strategyqa",
                        self.layout.stage_leaf,
                        self.layout.formal_leaf,
                    )
                    original_publish = acquisition._publish_manifest
                    original_close = os.close
                    held = {}
                    close_calls = 0

                    def publish(*args, **kwargs):
                        result = original_publish(*args, **kwargs)
                        held["guard"] = result.guard_fd
                        held["final"] = result.final_fd
                        return result

                    def close(fd):
                        nonlocal close_calls
                        if held.get(target_name) == fd:
                            close_calls += 1
                            original_close(fd)
                            raise OSError(errno.EIO, "terminal manifest close")
                        return original_close(fd)

                    with mock.patch.object(
                        acquisition, "_publish_manifest", side_effect=publish
                    ):
                        with mock.patch.object(os, "close", side_effect=close):
                            with self.assertRaises(OSError):
                                acquisition._fetch_layout(
                                    layout,
                                    chain_anchors(project),
                                    APPROVED_COMMIT,
                                    lambda approved: approved,
                                    lambda: MEMBERSHIP,
                                    lambda _fds: ACL,
                                    successful_transfer,
                                    resource_gate(),
                                    True,
                                )
                    self.assertEqual(close_calls, 1)
                    with self.assertRaises(OSError):
                        os.fstat(held[target_name])
                    self.assertTrue(
                        (project / acquisition._TRANSACTION_MARKER).exists()
                    )
                finally:
                    temporary.cleanup()

    def test_postpublication_marker_loss_is_rebuilt_before_error_escape(self):
        calls = 0
        original_inode = None

        def membership():
            nonlocal calls, original_inode
            calls += 1
            if calls == 4:
                marker = self.project / acquisition._TRANSACTION_MARKER
                original_inode = marker.stat().st_ino
                marker.unlink()
            return MEMBERSHIP

        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            self.call_fetch(membership=membership)
        marker = self.project / acquisition._TRANSACTION_MARKER
        self.assertTrue(marker.exists())
        self.assertNotEqual(marker.stat().st_ino, original_inode)
        report = acquisition._verify_stage_layout(self.layout, self.anchors)
        self.assertIs(report.status, acquisition.StageStatus.INCOMPLETE)
        self.assertEqual(report.reason_code, "TRANSACTION_IN_PROGRESS")

    def test_unknown_same_content_marker_is_untouched_and_unconfirmed(self):
        calls = 0
        replacement = {}

        def membership():
            nonlocal calls
            calls += 1
            if calls == 4:
                marker = self.project / acquisition._TRANSACTION_MARKER
                content = marker.read_bytes()
                marker.rename(self.project / "held-original-marker")
                marker.write_bytes(content)
                marker.chmod(0o600)
                value = marker.stat()
                replacement.update(
                    inode=value.st_ino, mode=value.st_mode, content=content
                )
            return MEMBERSHIP

        with self.assertRaisesRegex(
            acquisition.StrategyQaAcquisitionError, "recovery is unconfirmed"
        ):
            self.call_fetch(membership=membership)
        marker = self.project / acquisition._TRANSACTION_MARKER
        after = marker.stat()
        self.assertEqual(after.st_ino, replacement["inode"])
        self.assertEqual(after.st_mode, replacement["mode"])
        self.assertEqual(marker.read_bytes(), replacement["content"])

    def test_terminal_manifest_pair_replacement_and_aba_are_rejected(self):
        for persistent in (True, False):
            with self.subTest(persistent=persistent):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-pair-terminal."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(
                        project,
                        "data/raw/strategyqa",
                        self.layout.stage_leaf,
                        self.layout.formal_leaf,
                    )
                    calls = 0

                    def membership():
                        nonlocal calls
                        calls += 1
                        if calls == 4:
                            guard = layout.stage / acquisition._MANIFEST_GUARD
                            final = layout.stage / acquisition._MANIFEST_FINAL
                            if persistent:
                                content = guard.read_bytes()
                                guard.unlink()
                                final.unlink()
                                guard.write_bytes(content)
                                guard.chmod(0o600)
                                os.link(guard, final)
                            else:
                                held = guard.with_name("manifest-guard.aba")
                                guard.rename(held)
                                held.rename(guard)
                                stage_status = os.stat(
                                    layout.stage, follow_symlinks=False
                                )
                                os.utime(
                                    layout.stage,
                                    ns=(
                                        stage_status.st_atime_ns,
                                        stage_status.st_mtime_ns + 1_000_000,
                                    ),
                                )
                        return MEMBERSHIP

                    with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                        acquisition._fetch_layout(
                            layout,
                            chain_anchors(project),
                            APPROVED_COMMIT,
                            lambda approved: approved,
                            membership,
                            lambda _fds: ACL,
                            successful_transfer,
                            resource_gate(),
                            True,
                        )
                    self.assertTrue(
                        (project / acquisition._TRANSACTION_MARKER).exists()
                    )
                finally:
                    temporary.cleanup()

    def test_offline_manifest_replay_distinguishes_bool_float_and_integer(self):
        mutations = (
            lambda value: value["absolute_chain_anchors"][0].__setitem__(
                "uid", False
            ),
            lambda value: value["http"].__setitem__("status_code", 200.0),
            lambda value: value["runtime_resources"]["cpu_affinity"].__setitem__(
                0, False
            ),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-manifest-number."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(
                        project,
                        "data/raw/strategyqa",
                        self.layout.stage_leaf,
                        self.layout.formal_leaf,
                    )
                    anchors = chain_anchors(project)
                    acquisition._fetch_layout(
                        layout,
                        anchors,
                        APPROVED_COMMIT,
                        lambda approved: approved,
                        lambda: MEMBERSHIP,
                        lambda _fds: ACL,
                        successful_transfer,
                        resource_gate(),
                        True,
                    )
                    final = layout.stage / acquisition._MANIFEST_FINAL
                    guard = layout.stage / acquisition._MANIFEST_GUARD
                    value = acquisition.json.loads(final.read_bytes())
                    mutate(value)
                    content = acquisition._manifest_bytes(value)
                    guard.unlink()
                    final.unlink()
                    guard.write_bytes(content)
                    guard.chmod(0o600)
                    os.link(guard, final)
                    self.assertIs(
                        acquisition._verify_stage_layout(layout, anchors).status,
                        acquisition.StageStatus.INCOMPLETE,
                    )
                finally:
                    temporary.cleanup()

    def test_process_result_requires_canonical_bytes_offline_and_terminal(self):
        self.call_fetch()
        process_path = self.layout.stage / acquisition._PROCESS_RESULT_NAME
        process_path.write_bytes(
            b'{ "watchdog_action": "NONE", "reason_code": "NONE", "returncode": 0 }\n'
        )
        self.assertIs(
            acquisition._verify_stage_layout(self.layout, self.anchors).status,
            acquisition.StageStatus.INCOMPLETE,
        )
        temporary = tempfile.TemporaryDirectory(
            dir=DATA0_TMP, prefix="strategyqa-process-terminal."
        )
        try:
            os.chmod(temporary.name, 0o700)
            project = Path(temporary.name) / "project"
            project.mkdir(mode=0o700)
            layout = acquisition._Layout(
                project,
                "data/raw/strategyqa",
                self.layout.stage_leaf,
                self.layout.formal_leaf,
            )
            calls = 0

            def membership():
                nonlocal calls
                calls += 1
                if calls == 4:
                    (layout.stage / acquisition._PROCESS_RESULT_NAME).write_bytes(
                        b'{ "watchdog_action": "NONE", "reason_code": "NONE", '
                        b'"returncode": 0 }\n'
                    )
                return MEMBERSHIP

            with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                acquisition._fetch_layout(
                    layout,
                    chain_anchors(project),
                    APPROVED_COMMIT,
                    lambda approved: approved,
                    membership,
                    lambda _fds: ACL,
                    successful_transfer,
                    resource_gate(),
                    True,
                )
            self.assertTrue((project / acquisition._TRANSACTION_MARKER).exists())
        finally:
            temporary.cleanup()

    def test_commit_replay_compares_canonical_manifest_bytes(self):
        original = acquisition._verify_stage_layout_strict

        def replay(*args, **kwargs):
            report = original(*args, **kwargs)
            value = acquisition.json.loads(acquisition.canonical_json(report.observation))
            value["limits"]["gpu_count"] = False
            return acquisition.StageReport(report.status, report.reason_code, value)

        with mock.patch.object(
            acquisition, "_verify_stage_layout_strict", side_effect=replay
        ):
            with self.assertRaisesRegex(
                acquisition.StrategyQaAcquisitionError,
                "commit-point stage replay differs",
            ):
                self.call_fetch()
        self.assertTrue((self.project / acquisition._TRANSACTION_MARKER).exists())

    def test_nonzero_transfer_is_durable_blocked_stage(self):
        def transfer(_archive_fd, _header_fd, _writeout_fd, stderr_fd):
            overwrite_fd(stderr_fd, b"synthetic curl failure\n")
            return acquisition._ProcessResult(22, "NONE", "NONE")

        report = self.call_fetch(transfer)
        self.assertIs(report.status, acquisition.StageStatus.BLOCKED)
        self.assertEqual(report.reason_code, "CURL_EXIT_NONZERO")
        stage = self.layout.stage
        self.assertFalse((stage / acquisition._INVENTORY_NAME).exists())
        self.assertEqual(
            acquisition._verify_stage_layout(self.layout, self.anchors), report
        )

    def test_bad_etag_is_blocked_without_inventory(self):
        archive = zip_bytes()

        def transfer(archive_fd, header_fd, writeout_fd, stderr_fd):
            overwrite_fd(archive_fd, archive)
            overwrite_fd(header_fd, header_bytes(len(archive), etag="0" * 32))
            overwrite_fd(writeout_fd, writeout_bytes(len(archive)))
            overwrite_fd(stderr_fd, b"")
            return acquisition._ProcessResult(0, "NONE", "NONE")

        report = self.call_fetch(transfer)
        self.assertIs(report.status, acquisition.StageStatus.BLOCKED)
        self.assertEqual(report.reason_code, "HTTP_IDENTITY_MISMATCH")
        self.assertFalse((self.layout.stage / acquisition._INVENTORY_NAME).exists())

    def test_git_preflight_failure_creates_no_marker_or_stage(self):
        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            self.call_fetch(git=lambda _approved: "0" * 40)
        report = acquisition._verify_stage_layout(self.layout, self.anchors)
        self.assertIs(report.status, acquisition.StageStatus.INCOMPLETE)
        self.assertFalse(self.layout.stage.exists())
        self.assertFalse((self.project / acquisition._TRANSACTION_MARKER).exists())

    def test_second_and_third_git_gate_failures_retain_marker(self):
        for failing_call in (2, 3):
            with self.subTest(failing_call=failing_call):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-git-gate."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(
                        project,
                        "data/raw/strategyqa",
                        self.layout.stage_leaf,
                        self.layout.formal_leaf,
                    )
                    anchors = chain_anchors(project)
                    calls = 0

                    def git(approved):
                        nonlocal calls
                        calls += 1
                        return "0" * 40 if calls == failing_call else approved

                    with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                        acquisition._fetch_layout(
                            layout,
                            anchors,
                            APPROVED_COMMIT,
                            git,
                            lambda: MEMBERSHIP,
                            lambda _fds: ACL,
                            successful_transfer,
                            resource_gate(),
                            True,
                        )
                    self.assertTrue((project / acquisition._TRANSACTION_MARKER).exists())
                    self.assertTrue(layout.stage.exists())
                finally:
                    temporary.cleanup()

    def test_git_checkpoints_have_real_stage_child_and_manifest_timing(self):
        calls = []
        transferred = False

        def transfer(*fds):
            nonlocal transferred
            transferred = True
            return successful_transfer(*fds)

        def git(approved):
            stage_exists = self.layout.stage.exists()
            marker_exists = (self.project / acquisition._TRANSACTION_MARKER).exists()
            evidence = (
                sorted(path.name for path in self.layout.stage.iterdir())
                if stage_exists
                else []
            )
            calls.append((marker_exists, stage_exists, transferred, evidence))
            return approved

        self.call_fetch(transfer=transfer, git=git)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], (False, False, False, []))
        self.assertTrue(calls[1][0] and calls[1][1])
        self.assertFalse(calls[1][2])
        self.assertEqual(set(calls[1][3]), set(acquisition._COMMON_EVIDENCE))
        self.assertTrue(calls[2][0] and calls[2][1] and calls[2][2])
        self.assertIn(acquisition._PROCESS_RESULT_NAME, calls[2][3])

    def test_preexisting_stage_or_formal_revision_is_never_reused(self):
        parent = self.project / "data/raw/strategyqa"
        parent.mkdir(parents=True, mode=0o700)
        os.chmod(self.project / "data", 0o700)
        os.chmod(self.project / "data/raw", 0o700)
        os.chmod(parent, 0o700)
        for leaf in (self.layout.stage_leaf, self.layout.formal_leaf):
            with self.subTest(leaf=leaf):
                target = parent / leaf
                target.mkdir(mode=0o700)
                with self.assertRaises(FileExistsError):
                    self.call_fetch()
                target.rmdir()

    def test_terminal_policy_change_fail_closes_publication(self):
        calls = 0

        def membership():
            nonlocal calls
            calls += 1
            if calls == 4:
                return {**MEMBERSHIP, "explicit_members": ["other"]}
            return MEMBERSHIP

        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            self.call_fetch(membership=membership)
        report = acquisition._verify_stage_layout(self.layout, self.anchors)
        self.assertIs(report.status, acquisition.StageStatus.INCOMPLETE)
        self.assertEqual(report.reason_code, "TRANSACTION_IN_PROGRESS")
        marker = acquisition.json.loads(
            (self.project / acquisition._TRANSACTION_MARKER).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(marker["kairos_git_commit"], APPROVED_COMMIT)
        self.assertEqual(
            marker["transaction_version"], acquisition._TRANSACTION_VERSION
        )

    def test_offline_verify_does_not_spawn_or_query_external_policy(self):
        self.call_fetch()
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError):
            with mock.patch.object(acquisition, "_run_getent", side_effect=AssertionError):
                with mock.patch.object(acquisition, "_run_git", side_effect=AssertionError):
                    report = acquisition._verify_stage_layout(
                        self.layout, self.anchors
                    )
        self.assertIs(report.status, acquisition.StageStatus.STAGE_OK)

    def test_tamper_and_extra_file_are_incomplete(self):
        self.call_fetch()
        archive = self.layout.stage / acquisition._ARCHIVE_NAME
        with archive.open("ab") as handle:
            handle.write(b"tamper")
        self.assertIs(
            acquisition._verify_stage_layout(self.layout, self.anchors).status,
            acquisition.StageStatus.INCOMPLETE,
        )

    def test_preexisting_publication_entry_is_not_modified(self):
        parent = self.project / "publication-parent"
        parent.mkdir(mode=0o700)
        stage = parent / "stage"
        stage.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            guard = stage / acquisition._MANIFEST_GUARD
            guard.write_bytes(b"preexisting\n")
            guard.chmod(0o600)
            with self.assertRaises(FileExistsError):
                acquisition._publish_manifest(
                    parent_fd,
                    "stage",
                    stage_fd,
                    acquisition._identity(acquisition._fingerprint_fd(stage_fd)),
                    {"irrelevant": True},
                )
            self.assertEqual(guard.read_bytes(), b"preexisting\n")
            self.assertFalse((stage / acquisition._INCOMPLETE_MARKER).exists())
        finally:
            os.close(stage_fd)
            os.close(parent_fd)

    def test_project_marker_blocks_offline_success_at_both_boundaries(self):
        self.call_fetch()
        marker = self.project / acquisition._TRANSACTION_MARKER
        marker.write_bytes(b"foreign transaction\n")
        marker.chmod(0o600)
        report = acquisition._verify_stage_layout(self.layout, self.anchors)
        self.assertIs(report.status, acquisition.StageStatus.INCOMPLETE)
        self.assertEqual(report.reason_code, "TRANSACTION_IN_PROGRESS")

    def test_persistent_stage_replacement_is_untouched_and_marker_remains(self):
        replacement_bytes = b"do not modify\n"

        def transfer(*fds):
            result = successful_transfer(*fds)
            stage = self.layout.stage
            stage.rename(stage.parent / "held-original-stage")
            stage.mkdir(mode=0o700)
            sentinel = stage / "sentinel"
            sentinel.write_bytes(replacement_bytes)
            sentinel.chmod(0o600)
            return result

        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            self.call_fetch(transfer)
        self.assertEqual((self.layout.stage / "sentinel").read_bytes(), replacement_bytes)
        self.assertEqual(set(path.name for path in self.layout.stage.iterdir()), {"sentinel"})
        self.assertTrue((self.project / acquisition._TRANSACTION_MARKER).exists())

    def test_parent_and_stage_aba_are_detected_by_full_fingerprint_window(self):
        for target_name in ("stage", "parent"):
            with self.subTest(target=target_name):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-aba."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(
                        project,
                        "data/raw/strategyqa",
                        self.layout.stage_leaf,
                        self.layout.formal_leaf,
                    )
                    anchors = chain_anchors(project)

                    def transfer(*fds):
                        result = successful_transfer(*fds)
                        target = layout.stage if target_name == "stage" else layout.stage.parent
                        held = target.with_name(target.name + ".held")
                        target.rename(held)
                        held.rename(target)
                        status = os.stat(target, follow_symlinks=False)
                        os.utime(
                            target,
                            ns=(status.st_atime_ns, status.st_mtime_ns + 1_000_000),
                        )
                        return result

                    with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                        acquisition._fetch_layout(
                            layout,
                            anchors,
                            APPROVED_COMMIT,
                            lambda approved: approved,
                            lambda: MEMBERSHIP,
                            lambda _fds: ACL,
                            transfer,
                            resource_gate(),
                            True,
                        )
                    self.assertTrue((project / acquisition._TRANSACTION_MARKER).exists())
                finally:
                    temporary.cleanup()

    def test_shared_raw_sibling_ctime_change_does_not_fail_fetch(self):
        def transfer(*fds):
            result = successful_transfer(*fds)
            shared_raw = self.layout.stage.parent.parent
            sibling = shared_raw / "different-dataset-synthetic"
            sibling.mkdir(mode=0o700)
            sibling.rmdir()
            return result

        report = self.call_fetch(transfer)
        self.assertIs(report.status, acquisition.StageStatus.STAGE_OK)
        self.assertFalse((self.project / acquisition._TRANSACTION_MARKER).exists())

    def test_persistent_parent_replacement_is_untouched(self):
        parent = self.layout.stage.parent
        held_parent = parent.with_name("held-strategyqa-parent")

        def transfer(*fds):
            result = successful_transfer(*fds)
            parent.rename(held_parent)
            parent.mkdir(mode=0o700)
            sentinel = parent / "sentinel"
            sentinel.write_bytes(b"replacement parent\n")
            sentinel.chmod(0o600)
            return result

        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            self.call_fetch(transfer)
        self.assertEqual((parent / "sentinel").read_bytes(), b"replacement parent\n")
        self.assertTrue((self.project / acquisition._TRANSACTION_MARKER).exists())

    def test_project_root_persistent_replacement_is_untouched(self):
        original_project = self.project.with_name("held-project-root")

        def transfer(*fds):
            result = successful_transfer(*fds)
            self.project.rename(original_project)
            self.project.mkdir(mode=0o700)
            sentinel = self.project / "sentinel"
            sentinel.write_bytes(b"replacement root\n")
            sentinel.chmod(0o600)
            return result

        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            self.call_fetch(transfer)
        self.assertEqual(
            (self.project / "sentinel").read_bytes(), b"replacement root\n"
        )
        self.assertTrue((original_project / acquisition._TRANSACTION_MARKER).exists())

    def test_terminal_evidence_and_manifest_persistent_or_aba_mutations_fail(self):
        for target_name, persistent in (
            (acquisition._ARCHIVE_NAME, True),
            (acquisition._ARCHIVE_NAME, False),
            (acquisition._MANIFEST_FINAL, True),
            (acquisition._MANIFEST_FINAL, False),
        ):
            with self.subTest(target=target_name, persistent=persistent):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-terminal-race."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(
                        project,
                        "data/raw/strategyqa",
                        self.layout.stage_leaf,
                        self.layout.formal_leaf,
                    )
                    anchors = chain_anchors(project)
                    calls = 0

                    def membership():
                        nonlocal calls
                        calls += 1
                        if calls == 4:
                            target = layout.stage / target_name
                            held = target.with_name(target.name + ".held")
                            target.rename(held)
                            if persistent:
                                target.write_bytes(held.read_bytes())
                                target.chmod(0o600)
                            else:
                                held.rename(target)
                            stage_status = os.stat(layout.stage, follow_symlinks=False)
                            os.utime(
                                layout.stage,
                                ns=(
                                    stage_status.st_atime_ns,
                                    stage_status.st_mtime_ns + 1_000_000,
                                ),
                            )
                        return MEMBERSHIP

                    with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                        acquisition._fetch_layout(
                            layout,
                            anchors,
                            APPROVED_COMMIT,
                            lambda approved: approved,
                            membership,
                            lambda _fds: ACL,
                            successful_transfer,
                            resource_gate(),
                            True,
                        )
                    self.assertTrue((project / acquisition._TRANSACTION_MARKER).exists())
                finally:
                    temporary.cleanup()

    def test_formal_appearance_during_transfer_is_fail_closed(self):
        def transfer(*fds):
            result = successful_transfer(*fds)
            (self.layout.stage.parent / self.layout.formal_leaf).mkdir(mode=0o700)
            return result

        with self.assertRaises(acquisition.StrategyQaAcquisitionError):
            self.call_fetch(transfer)
        self.assertTrue((self.project / acquisition._TRANSACTION_MARKER).exists())

    def test_lost_canonical_stage_publication_never_touches_replacement(self):
        parent = self.project / "parent"
        parent.mkdir(mode=0o700)
        stage = parent / "stage"
        stage.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        identity = acquisition._identity(acquisition._fingerprint_fd(stage_fd))
        stage.rename(parent / "detached")
        stage.mkdir(mode=0o700)
        sentinel = stage / "sentinel"
        sentinel.write_bytes(b"unknown\n")
        sentinel.chmod(0o600)
        before = sentinel.stat()
        try:
            with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                acquisition._publish_manifest(
                    parent_fd,
                    "stage",
                    stage_fd,
                    identity,
                    {"synthetic": True},
                )
            self.assertEqual(sentinel.read_bytes(), b"unknown\n")
            self.assertEqual(set(path.name for path in stage.iterdir()), {"sentinel"})
            after = sentinel.stat()
            self.assertEqual((after.st_ino, after.st_mode), (before.st_ino, before.st_mode))
        finally:
            os.close(stage_fd)
            os.close(parent_fd)

    def test_offline_verifier_detects_parent_stage_manifest_and_evidence_aba(self):
        for target_kind in ("parent", "stage", "manifest", "evidence"):
            with self.subTest(target=target_kind):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-verifier-aba."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(
                        project,
                        "data/raw/strategyqa",
                        self.layout.stage_leaf,
                        self.layout.formal_leaf,
                    )
                    anchors = chain_anchors(project)
                    acquisition._fetch_layout(
                        layout,
                        anchors,
                        APPROVED_COMMIT,
                        lambda approved: approved,
                        lambda: MEMBERSHIP,
                        lambda _fds: ACL,
                        successful_transfer,
                        resource_gate(),
                        True,
                    )
                    original = acquisition._evaluate_stage
                    mutated = False

                    def evaluate_and_mutate(*args, **kwargs):
                        nonlocal mutated
                        result = original(*args, **kwargs)
                        if not mutated:
                            mutated = True
                            targets = {
                                "parent": layout.stage.parent,
                                "stage": layout.stage,
                                "manifest": layout.stage / acquisition._MANIFEST_FINAL,
                                "evidence": layout.stage / acquisition._ARCHIVE_NAME,
                            }
                            target = targets[target_kind]
                            held = target.with_name(target.name + ".aba")
                            target.rename(held)
                            held.rename(target)
                        return result

                    with mock.patch.object(
                        acquisition, "_evaluate_stage", side_effect=evaluate_and_mutate
                    ):
                        report = acquisition._verify_stage_layout(layout, anchors)
                    self.assertTrue(mutated)
                    self.assertIs(report.status, acquisition.StageStatus.INCOMPLETE)
                finally:
                    temporary.cleanup()

    def test_offline_verifier_rejects_marker_created_during_replay(self):
        self.call_fetch()
        original = acquisition._evaluate_stage
        created = False

        def evaluate_and_mark(*args, **kwargs):
            nonlocal created
            result = original(*args, **kwargs)
            if not created:
                created = True
                marker = self.project / acquisition._TRANSACTION_MARKER
                marker.write_bytes(b"late marker\n")
                marker.chmod(0o600)
            return result

        with mock.patch.object(
            acquisition, "_evaluate_stage", side_effect=evaluate_and_mark
        ):
            report = acquisition._verify_stage_layout(self.layout, self.anchors)
        self.assertTrue(created)
        self.assertIs(report.status, acquisition.StageStatus.INCOMPLETE)
        self.assertEqual(report.reason_code, "TRANSACTION_IN_PROGRESS")

    def test_success_path_evidence_close_fault_retains_transaction_marker(self):
        archive_fd = None

        def transfer(*fds):
            nonlocal archive_fd
            archive_fd = fds[0]
            return successful_transfer(*fds)

        original_close = os.close
        failed = False

        def close_fault(fd):
            nonlocal failed
            if fd == archive_fd and not failed:
                failed = True
                raise OSError(errno.EIO, "injected evidence close")
            return original_close(fd)

        with mock.patch.object(os, "close", side_effect=close_fault):
            with self.assertRaises(OSError):
                self.call_fetch(transfer)
        self.assertTrue(failed)
        self.assertTrue((self.project / acquisition._TRANSACTION_MARKER).exists())
        self.assertIs(
            acquisition._verify_stage_layout(self.layout, self.anchors).status,
            acquisition.StageStatus.INCOMPLETE,
        )


class TransferPipeTests(TemporaryLayout):
    class FakeProcess:
        def __init__(
            self,
            arguments,
            *,
            header_content,
            writeout_content,
            stderr_content,
            **kwargs,
        ):
            self.arguments = tuple(arguments)
            self.kwargs = kwargs
            self.pid = 987654
            self.returncode = 0
            header_path = self.arguments[self.arguments.index("--dump-header") + 1]
            header_fd = int(header_path.rsplit("/", 1)[1])
            os.write(header_fd, header_content)
            self.stdout = self._pipe(writeout_content)
            self.stderr = self._pipe(stderr_content)

        @staticmethod
        def _pipe(content):
            read_fd, write_fd = os.pipe()
            os.write(write_fd, content)
            os.close(write_fd)
            return os.fdopen(read_fd, "rb", buffering=0)

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    def evidence_fds(self):
        directory = Path(
            tempfile.mkdtemp(dir=self.temporary.name, prefix="transfer-case.")
        )
        os.chmod(directory, 0o700)
        paths = [directory / f"evidence-{index}" for index in range(4)]
        fds = [os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600) for path in paths]
        return paths, fds

    def test_transfer_drains_three_independent_pipes(self):
        archive = zip_bytes()
        paths, fds = self.evidence_fds()
        overwrite_fd(fds[0], archive)
        factory = lambda arguments, **kwargs: self.FakeProcess(
            arguments,
            header_content=header_bytes(len(archive)),
            writeout_content=writeout_bytes(len(archive)),
            stderr_content=b"synthetic stderr",
            **kwargs,
        )
        try:
            with mock.patch.object(subprocess, "Popen", side_effect=factory) as popen:
                with mock.patch.object(
                    acquisition, "_owned_process_group_alive", return_value=False
                ):
                    result = acquisition._run_transfer(*fds)
            self.assertEqual(result, acquisition._ProcessResult(0, "NONE", "NONE"))
            self.assertEqual(paths[1].read_bytes(), header_bytes(len(archive)))
            self.assertEqual(paths[2].read_bytes(), writeout_bytes(len(archive)))
            self.assertEqual(paths[3].read_bytes(), b"synthetic stderr")
            kwargs = popen.call_args.kwargs
            self.assertTrue(kwargs["start_new_session"])
            self.assertTrue(kwargs["close_fds"])
            self.assertEqual(len(kwargs["pass_fds"]), 2)
        finally:
            for fd in fds:
                os.close(fd)

    def test_header_writer_close_success_then_error_is_not_retried(self):
        archive = zip_bytes()
        _paths, fds = self.evidence_fds()
        overwrite_fd(fds[0], archive)
        original_close = os.close
        header_writer_fd = -1
        close_calls = 0

        def factory(arguments, **kwargs):
            nonlocal header_writer_fd
            header_path = arguments[arguments.index("--dump-header") + 1]
            header_writer_fd = int(header_path.rsplit("/", 1)[1])
            return self.FakeProcess(
                arguments,
                header_content=header_bytes(len(archive)),
                writeout_content=writeout_bytes(len(archive)),
                stderr_content=b"",
                **kwargs,
            )

        def close(fd):
            nonlocal close_calls
            if fd == header_writer_fd:
                close_calls += 1
                original_close(fd)
                raise OSError(errno.EIO, "header writer close")
            return original_close(fd)

        try:
            with mock.patch.object(subprocess, "Popen", side_effect=factory):
                with mock.patch.object(
                    acquisition, "_terminate_owned_group", return_value="SIGTERM"
                ):
                    with mock.patch.object(os, "close", side_effect=close):
                        with self.assertRaises(OSError):
                            acquisition._run_transfer(*fds)
            self.assertEqual(close_calls, 1)
            with self.assertRaises(OSError):
                os.fstat(header_writer_fd)
        finally:
            for fd in fds:
                original_close(fd)

    def test_each_pipe_exact_cap_and_cap_plus_one(self):
        routes = (
            ("HEADER", "HEADER_LIMIT", 1),
            ("WRITEOUT", "WRITEOUT_LIMIT", 2),
            ("STDERR", "STDERR_LIMIT", 3),
        )
        for route, limit_name, evidence_index in routes:
            for extra in (0, 1):
                with self.subTest(route=route, extra=extra):
                    paths, fds = self.evidence_fds()
                    payloads = {"HEADER": b"", "WRITEOUT": b"", "STDERR": b""}
                    payloads[route] = b"x" * (4 + extra)
                    factory = lambda arguments, **kwargs: self.FakeProcess(
                        arguments,
                        header_content=payloads["HEADER"],
                        writeout_content=payloads["WRITEOUT"],
                        stderr_content=payloads["STDERR"],
                        **kwargs,
                    )
                    try:
                        with mock.patch.object(acquisition, limit_name, 4):
                            with mock.patch.object(subprocess, "Popen", side_effect=factory):
                                with mock.patch.object(
                                    acquisition,
                                    "_owned_process_group_alive",
                                    return_value=False,
                                ):
                                    with mock.patch.object(
                                        acquisition,
                                        "_terminate_owned_group",
                                        return_value="SIGTERM",
                                    ) as terminate:
                                        result = acquisition._run_transfer(*fds)
                        if extra:
                            self.assertEqual(result.reason_code, route + "_LIMIT")
                            terminate.assert_called_once()
                        else:
                            self.assertEqual(result.reason_code, "NONE")
                            terminate.assert_not_called()
                        self.assertEqual(paths[evidence_index].read_bytes(), b"x" * 4)
                    finally:
                        for fd in fds:
                            os.close(fd)

    def test_popen_pipe_selector_read_write_wait_and_close_faults_fail(self):
        cases = (
            "pipe",
            "popen",
            "selector",
            "register",
            "unregister",
            "read",
            "write",
            "wait",
            "close",
        )
        for case in cases:
            with self.subTest(case=case):
                paths, fds = self.evidence_fds()
                factory = lambda arguments, **kwargs: self.FakeProcess(
                    arguments,
                    header_content=b"h",
                    writeout_content=b"w",
                    stderr_content=b"e",
                    **kwargs,
                )
                stack = []
                if case == "pipe":
                    stack.append(mock.patch.object(os, "pipe2", side_effect=OSError(errno.EIO, "pipe")))
                elif case == "popen":
                    stack.append(mock.patch.object(subprocess, "Popen", side_effect=OSError(errno.EIO, "popen")))
                else:
                    stack.append(mock.patch.object(subprocess, "Popen", side_effect=factory))
                    stack.append(mock.patch.object(acquisition, "_terminate_owned_group", return_value="SIGTERM"))
                    if case == "selector":
                        stack.append(mock.patch.object(acquisition.selectors, "DefaultSelector", side_effect=OSError(errno.EIO, "selector")))
                    elif case == "register":
                        selector = mock.MagicMock()
                        selector.register.side_effect = OSError(errno.EIO, "register")
                        stack.append(mock.patch.object(acquisition.selectors, "DefaultSelector", return_value=selector))
                    elif case == "read":
                        stack.append(mock.patch.object(os, "read", side_effect=OSError(errno.EIO, "read")))
                    elif case == "unregister":
                        stack.append(
                            mock.patch.object(
                                acquisition.selectors.EpollSelector,
                                "unregister",
                                side_effect=OSError(errno.EIO, "unregister"),
                            )
                        )
                    elif case == "write":
                        stack.append(mock.patch.object(acquisition, "_write_all", side_effect=OSError(errno.EIO, "write")))
                    elif case == "wait":
                        original_wait = self.FakeProcess.wait
                        self.FakeProcess.wait = lambda _self, timeout=None: (_ for _ in ()).throw(OSError(errno.EIO, "wait"))
                    elif case == "close":
                        selector = acquisition.selectors.DefaultSelector()
                        original_selector_close = selector.close

                        def close_fault():
                            original_selector_close()
                            raise OSError(errno.EIO, "close")

                        selector.close = close_fault
                        stack.append(mock.patch.object(acquisition.selectors, "DefaultSelector", return_value=selector))
                entered = []
                try:
                    for patcher in stack:
                        entered.append(patcher)
                        patcher.start()
                    with self.assertRaises((OSError, acquisition.StrategyQaAcquisitionError)):
                        acquisition._run_transfer(*fds, timeout_seconds=0.1)
                finally:
                    for patcher in reversed(entered):
                        patcher.stop()
                    if case == "wait":
                        self.FakeProcess.wait = original_wait
                    for fd in fds:
                        os.close(fd)


class PublicationAndTransactionFaultTests(TemporaryLayout):
    def publication_layout(self):
        root = Path(
            tempfile.mkdtemp(dir=self.project, prefix="publication-case.")
        )
        os.chmod(root, 0o700)
        parent = root / "publication-parent"
        parent.mkdir(mode=0o700)
        stage = parent / "stage"
        stage.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        return parent, stage, parent_fd, stage_fd

    def test_publication_link_unlink_fsync_and_close_faults_never_succeed(self):
        operations = {"link": 2, "unlink": 1, "fsync": 3}
        for operation, occurrence_count in operations.items():
            for failing_occurrence in range(1, occurrence_count + 1):
                with self.subTest(
                    operation=operation, failing_occurrence=failing_occurrence
                ):
                    self._assert_publication_operation_fault(
                        operation, failing_occurrence
                    )

    def _assert_publication_operation_fault(self, operation, failing_occurrence):
        temporary = tempfile.TemporaryDirectory(
            dir=DATA0_TMP, prefix="strategyqa-publication-fault."
        )
        try:
            root = Path(temporary.name)
            os.chmod(root, 0o700)
            parent = root / "parent"
            parent.mkdir(mode=0o700)
            stage = parent / "stage"
            stage.mkdir(mode=0o700)
            parent_fd = os.open(
                parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            stage_fd = os.open(
                stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            identity = acquisition._identity(
                acquisition._fingerprint_fd(stage_fd)
            )
            original = getattr(os, operation)
            failed = False
            seen = 0

            def fault(*args, **kwargs):
                nonlocal failed, seen
                seen += 1
                if seen == failing_occurrence:
                    failed = True
                    raise OSError(errno.EIO, f"injected {operation}")
                return original(*args, **kwargs)

            with mock.patch.object(os, operation, side_effect=fault):
                with self.assertRaises(
                    (OSError, acquisition.StrategyQaAcquisitionError)
                ):
                    acquisition._publish_manifest(
                        parent_fd,
                        "stage",
                        stage_fd,
                        identity,
                        {"synthetic": operation},
                    )
            self.assertTrue(failed)
            self.assertFalse((stage / acquisition._INCOMPLETE_MARKER).exists())
            os.close(stage_fd)
            os.close(parent_fd)
        finally:
            temporary.cleanup()

    def test_publication_temp_close_failure_is_fatal_without_stage_invalidation(self):
        _parent, stage, parent_fd, stage_fd = self.publication_layout()
        identity = acquisition._identity(acquisition._fingerprint_fd(stage_fd))
        original_create = acquisition._create_private_file
        original_close = os.close
        temp_fd = -1

        def create(directory_fd, name):
            nonlocal temp_fd
            result = original_create(directory_fd, name)
            if name.startswith(".stage-manifest."):
                temp_fd = result
            return result

        close_calls = 0

        def close(fd):
            nonlocal close_calls
            if fd == temp_fd:
                close_calls += 1
                if close_calls == 1:
                    original_close(fd)
                    raise OSError(errno.EIO, "injected temp close")
            return original_close(fd)

        try:
            with mock.patch.object(acquisition, "_create_private_file", side_effect=create):
                with mock.patch.object(os, "close", side_effect=close):
                    with self.assertRaises(OSError):
                        acquisition._publish_manifest(
                            parent_fd, "stage", stage_fd, identity, {"synthetic": True}
                        )
            self.assertEqual(close_calls, 1)
            with self.assertRaises(OSError):
                os.fstat(temp_fd)
            self.assertFalse((stage / acquisition._INCOMPLETE_MARKER).exists())
        finally:
            original_close(stage_fd)
            original_close(parent_fd)

    def test_preexisting_incomplete_or_final_is_unchanged(self):
        for name in (acquisition._INCOMPLETE_MARKER, acquisition._MANIFEST_FINAL):
            with self.subTest(name=name):
                _parent, stage, parent_fd, stage_fd = self.publication_layout()
                target = stage / name
                target.write_bytes(b"unknown publication object\n")
                target.chmod(0o600)
                before = target.stat()
                try:
                    with self.assertRaises(FileExistsError):
                        acquisition._publish_manifest(
                            parent_fd,
                            "stage",
                            stage_fd,
                            acquisition._identity(acquisition._fingerprint_fd(stage_fd)),
                            {"synthetic": True},
                        )
                    after = target.stat()
                    self.assertEqual(target.read_bytes(), b"unknown publication object\n")
                    self.assertEqual(
                        (after.st_ino, after.st_mode), (before.st_ino, before.st_mode)
                    )
                    self.assertEqual(set(path.name for path in stage.iterdir()), {name})
                finally:
                    os.close(stage_fd)
                    os.close(parent_fd)

    def test_guard_replacement_before_final_link_is_detected_and_untouched(self):
        _parent, stage, parent_fd, stage_fd = self.publication_layout()
        identity = acquisition._identity(acquisition._fingerprint_fd(stage_fd))
        original_link = os.link
        calls = 0
        replacement = {}

        def link(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                guard = stage / acquisition._MANIFEST_GUARD
                content = guard.read_bytes()
                guard.unlink()
                guard.write_bytes(content)
                guard.chmod(0o600)
                value = guard.stat()
                replacement.update(
                    inode=value.st_ino, mode=value.st_mode, content=content
                )
            return original_link(*args, **kwargs)

        try:
            with mock.patch.object(os, "link", side_effect=link):
                with self.assertRaises(acquisition.StrategyQaAcquisitionError):
                    acquisition._publish_manifest(
                        parent_fd, "stage", stage_fd, identity, {"synthetic": True}
                    )
            guard = stage / acquisition._MANIFEST_GUARD
            self.assertEqual(guard.stat().st_ino, replacement["inode"])
            self.assertEqual(guard.stat().st_mode, replacement["mode"])
            self.assertEqual(guard.read_bytes(), replacement["content"])
            self.assertFalse((stage / acquisition._INCOMPLETE_MARKER).exists())
        finally:
            os.close(stage_fd)
            os.close(parent_fd)

    def test_marker_restore_existing_missing_unknown_and_fault_matrix(self):
        for case in ("existing", "missing", "unknown", "fsync", "rebind", "close"):
            with self.subTest(case=case):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-marker-restore."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    project_fd = os.open(
                        project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    )
                    marker_fd, content, facts = acquisition._create_transaction_marker(
                        project_fd, APPROVED_COMMIT
                    )
                    marker = project / acquisition._TRANSACTION_MARKER
                    original_inode = marker.stat().st_ino
                    try:
                        if case == "missing":
                            marker.unlink()
                            os.fsync(project_fd)
                            self.assertTrue(
                                acquisition._restore_transaction_marker(
                                    project_fd, marker_fd, content, facts
                                )
                            )
                            self.assertNotEqual(marker.stat().st_ino, original_inode)
                        elif case == "unknown":
                            marker.unlink()
                            marker.write_bytes(content)
                            marker.chmod(0o600)
                            before = marker.stat()
                            with mock.patch.object(
                                acquisition,
                                "_open_private_file",
                                side_effect=AssertionError("unknown marker opened"),
                            ) as open_private:
                                with mock.patch.object(
                                    acquisition,
                                    "_file_facts",
                                    side_effect=AssertionError("unknown marker read"),
                                ) as file_facts:
                                    self.assertFalse(
                                        acquisition._restore_transaction_marker(
                                            project_fd, marker_fd, content, facts
                                        )
                                    )
                            open_private.assert_not_called()
                            file_facts.assert_not_called()
                            after = marker.stat()
                            self.assertEqual(
                                (after.st_ino, after.st_mode, marker.read_bytes()),
                                (before.st_ino, before.st_mode, content),
                            )
                        elif case == "fsync":
                            with mock.patch.object(
                                os, "fsync", side_effect=OSError(errno.EIO, "fsync")
                            ):
                                self.assertFalse(
                                    acquisition._restore_transaction_marker(
                                        project_fd, marker_fd, content, facts
                                    )
                                )
                        elif case == "rebind":
                            original_open = acquisition._open_private_file
                            calls = 0
                            replacement = {}

                            def open_private(*args, **kwargs):
                                nonlocal calls
                                calls += 1
                                if calls == 2:
                                    marker.unlink()
                                    marker.write_bytes(content)
                                    marker.chmod(0o600)
                                    value = marker.stat()
                                    replacement.update(
                                        inode=value.st_ino,
                                        mode=value.st_mode,
                                        content=content,
                                    )
                                return original_open(*args, **kwargs)

                            with mock.patch.object(
                                acquisition,
                                "_open_private_file",
                                side_effect=open_private,
                            ):
                                self.assertFalse(
                                    acquisition._restore_transaction_marker(
                                        project_fd, marker_fd, content, facts
                                    )
                                )
                            self.assertEqual(marker.stat().st_ino, replacement["inode"])
                            self.assertEqual(marker.stat().st_mode, replacement["mode"])
                            self.assertEqual(marker.read_bytes(), replacement["content"])
                        elif case == "close":
                            original_close = os.close
                            failed = False

                            def close(fd):
                                nonlocal failed
                                if fd not in {project_fd, marker_fd} and not failed:
                                    failed = True
                                    original_close(fd)
                                    raise OSError(errno.EIO, "close")
                                return original_close(fd)

                            with mock.patch.object(os, "close", side_effect=close):
                                self.assertFalse(
                                    acquisition._restore_transaction_marker(
                                        project_fd, marker_fd, content, facts
                                    )
                                )
                            self.assertTrue(failed)
                        else:
                            self.assertTrue(
                                acquisition._restore_transaction_marker(
                                    project_fd, marker_fd, content, facts
                                )
                            )
                    finally:
                        os.close(marker_fd)
                        os.close(project_fd)
                finally:
                    temporary.cleanup()

    def test_marker_restore_close_success_then_error_is_never_retried(self):
        cases = (
            "existing_initial_canonical",
            "existing_rebound_canonical",
            "missing_canonical",
            "missing_restored",
        )
        for case in cases:
            with self.subTest(case=case):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-marker-close-once."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    project_fd = os.open(
                        project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    )
                    marker_fd, content, facts = acquisition._create_transaction_marker(
                        project_fd, APPROVED_COMMIT
                    )
                    marker = project / acquisition._TRANSACTION_MARKER
                    if case.startswith("missing_"):
                        marker.unlink()
                        os.fsync(project_fd)
                    original_open = acquisition._open_private_file
                    original_create = acquisition._create_private_file
                    original_close = os.close
                    canonical_fds = []
                    restored_fds = []
                    target_fd = -1
                    close_calls = 0

                    def open_private(*args, **kwargs):
                        result = original_open(*args, **kwargs)
                        canonical_fds.append(result)
                        return result

                    def create_private(*args, **kwargs):
                        result = original_create(*args, **kwargs)
                        if args[1] == acquisition._TRANSACTION_MARKER:
                            restored_fds.append(result)
                        return result

                    def close(fd):
                        nonlocal target_fd, close_calls
                        if case == "existing_initial_canonical" and canonical_fds:
                            target_fd = canonical_fds[0]
                        elif (
                            case == "existing_rebound_canonical"
                            and len(canonical_fds) >= 2
                        ):
                            target_fd = canonical_fds[1]
                        elif case == "missing_canonical" and canonical_fds:
                            target_fd = canonical_fds[0]
                        elif case == "missing_restored" and restored_fds:
                            target_fd = restored_fds[0]
                        if fd == target_fd:
                            close_calls += 1
                            original_close(fd)
                            raise OSError(errno.EIO, "close succeeded then errored")
                        return original_close(fd)

                    try:
                        with mock.patch.object(
                            acquisition,
                            "_open_private_file",
                            side_effect=open_private,
                        ):
                            with mock.patch.object(
                                acquisition,
                                "_create_private_file",
                                side_effect=create_private,
                            ):
                                with mock.patch.object(os, "close", side_effect=close):
                                    self.assertFalse(
                                        acquisition._restore_transaction_marker(
                                            project_fd, marker_fd, content, facts
                                        )
                                    )
                        self.assertEqual(close_calls, 1)
                        with self.assertRaises(OSError):
                            os.fstat(target_fd)
                    finally:
                        original_close(marker_fd)
                        original_close(project_fd)
                finally:
                    temporary.cleanup()

    def test_missing_marker_reopen_rebinds_before_canonical_read(self):
        project_fd = os.open(
            self.project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        marker_fd, content, facts = acquisition._create_transaction_marker(
            project_fd, APPROVED_COMMIT
        )
        marker = self.project / acquisition._TRANSACTION_MARKER
        marker.unlink()
        os.fsync(project_fd)
        original_open = acquisition._open_private_file
        original_facts = acquisition._file_facts
        canonical_fd = -1
        canonical_reads = 0
        replacement = {}

        def open_private(*args, **kwargs):
            nonlocal canonical_fd
            canonical_fd = original_open(*args, **kwargs)
            marker.unlink()
            marker.write_bytes(content)
            marker.chmod(0o600)
            value = marker.stat()
            replacement.update(inode=value.st_ino, mode=value.st_mode)
            return canonical_fd

        def file_facts(fd, *args, **kwargs):
            nonlocal canonical_reads
            if fd == canonical_fd:
                canonical_reads += 1
                raise AssertionError("replacement-bound canonical FD was read")
            return original_facts(fd, *args, **kwargs)

        try:
            with mock.patch.object(
                acquisition, "_open_private_file", side_effect=open_private
            ):
                with mock.patch.object(acquisition, "_file_facts", side_effect=file_facts):
                    self.assertFalse(
                        acquisition._restore_transaction_marker(
                            project_fd, marker_fd, content, facts
                        )
                    )
            self.assertEqual(canonical_reads, 0)
            self.assertEqual(marker.stat().st_ino, replacement["inode"])
            self.assertEqual(marker.stat().st_mode, replacement["mode"])
            self.assertEqual(marker.read_bytes(), content)
        finally:
            os.close(marker_fd)
            os.close(project_fd)

    def test_commit_unlink_and_fsync_faults_require_outer_recovery(self):
        for operation in ("unlink", "fsync"):
            with self.subTest(operation=operation):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-marker-fault."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    layout = acquisition._Layout(project, "data/raw/strategyqa", "stage", "formal")
                    anchors = chain_anchors(project)
                    project_fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    marker_fd, content, facts = acquisition._create_transaction_marker(
                        project_fd, APPROVED_COMMIT
                    )
                    original = getattr(os, operation)
                    failed = False

                    def fault(*args, **kwargs):
                        nonlocal failed
                        if not failed:
                            failed = True
                            raise OSError(errno.EIO, operation)
                        return original(*args, **kwargs)

                    try:
                        with mock.patch.object(os, operation, side_effect=fault):
                            with self.assertRaises(OSError):
                                acquisition._commit_transaction_marker(
                                    layout,
                                    anchors,
                                    project_fd,
                                    marker_fd,
                                    content,
                                    facts,
                                )
                        if operation == "unlink":
                            self.assertTrue((project / acquisition._TRANSACTION_MARKER).exists())
                        else:
                            self.assertFalse((project / acquisition._TRANSACTION_MARKER).exists())
                            self.assertTrue(
                                acquisition._restore_transaction_marker(
                                    project_fd, marker_fd, content, facts
                                )
                            )
                    finally:
                        os.close(marker_fd)
                        os.close(project_fd)
                finally:
                    temporary.cleanup()

    def test_commit_canonical_chain_close_fault_precedes_unlink(self):
        project_fd = os.open(
            self.project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        marker_fd, content, facts = acquisition._create_transaction_marker(
            project_fd, APPROVED_COMMIT
        )
        original_open_chain = acquisition._open_absolute_chain
        original_close = os.close
        chain_fds = set()
        failed = False

        def open_chain(*args, **kwargs):
            result = original_open_chain(*args, **kwargs)
            chain_fds.update(result)
            return result

        def close(fd):
            nonlocal failed
            if fd in chain_fds and not failed:
                failed = True
                original_close(fd)
                raise OSError(errno.EIO, "canonical chain close")
            return original_close(fd)

        try:
            with mock.patch.object(
                acquisition, "_open_absolute_chain", side_effect=open_chain
            ):
                with mock.patch.object(os, "close", side_effect=close):
                    with self.assertRaises(OSError):
                        acquisition._commit_transaction_marker(
                            self.layout,
                            self.anchors,
                            project_fd,
                            marker_fd,
                            content,
                            facts,
                        )
            self.assertTrue(failed)
            self.assertTrue(
                (self.project / acquisition._TRANSACTION_MARKER).exists()
            )
        finally:
            original_close(marker_fd)
            original_close(project_fd)

    def test_post_commit_close_fault_is_warning_not_false_failure(self):
        with mock.patch.object(os, "close", side_effect=OSError(errno.EIO, "close")):
            with self.assertWarnsRegex(RuntimeWarning, "after durable"):
                acquisition._close_after_commit_warning(123, "synthetic")
        with mock.patch.object(os, "close", side_effect=OSError(errno.EIO, "close")):
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                acquisition._close_after_commit_warning(123, "synthetic")

    def test_fetch_last_close_fault_after_commit_is_warning_only(self):
        original_commit = acquisition._commit_transaction_marker
        original_close = os.close
        state = {"committed": False, "recovery_fd": -1, "failed": False}

        def commit(*args, **kwargs):
            state["recovery_fd"] = args[2]
            result = original_commit(*args, **kwargs)
            state["committed"] = True
            return result

        def close(fd):
            if (
                state["committed"]
                and fd == state["recovery_fd"]
                and not state["failed"]
            ):
                state["failed"] = True
                original_close(fd)
                raise OSError(errno.EIO, "last close")
            return original_close(fd)

        with mock.patch.object(
            acquisition, "_commit_transaction_marker", side_effect=commit
        ):
            with mock.patch.object(os, "close", side_effect=close):
                with self.assertWarnsRegex(RuntimeWarning, "after durable"):
                    report = self.call_fetch()
        self.assertTrue(state["failed"])
        self.assertIs(report.status, acquisition.StageStatus.STAGE_OK)
        self.assertFalse((self.project / acquisition._TRANSACTION_MARKER).exists())

    def test_marker_recovery_false_or_error_is_unconfirmed(self):
        for effect in (False, OSError(errno.EIO, "restore")):
            with self.subTest(effect=repr(effect)):
                temporary = tempfile.TemporaryDirectory(
                    dir=DATA0_TMP, prefix="strategyqa-marker-unconfirmed."
                )
                try:
                    os.chmod(temporary.name, 0o700)
                    project = Path(temporary.name) / "project"
                    project.mkdir(mode=0o700)
                    patcher = (
                        mock.patch.object(acquisition, "_restore_transaction_marker", return_value=False)
                        if effect is False
                        else mock.patch.object(acquisition, "_restore_transaction_marker", side_effect=effect)
                    )
                    def fail_transfer(*_fds):
                        raise RuntimeError("terminal synthetic failure")

                    with patcher:
                        with self.assertRaisesRegex(
                            acquisition.StrategyQaAcquisitionError,
                            "recovery is unconfirmed",
                        ):
                            acquisition._fetch_layout(
                                acquisition._Layout(project, "data/raw/strategyqa", "stage", "formal"),
                                chain_anchors(project),
                                APPROVED_COMMIT,
                                lambda approved: approved,
                                lambda: MEMBERSHIP,
                                lambda _fds: ACL,
                                fail_transfer,
                                resource_gate(),
                                True,
                            )
                finally:
                    temporary.cleanup()

class ProcessLifecycleTests(TemporaryLayout):
    def test_parent_watchdog_reaps_its_synthetic_process_group(self):
        pid_file = Path(self.temporary.name) / "synthetic-pids"
        script = """
import os, signal, sys, time
pid_file = sys.argv[1]
child = os.fork()
if child == 0:
    with open(pid_file, 'a', encoding='ascii') as handle:
        handle.write(f'{os.getpid()}\\n')
        handle.flush()
    time.sleep(60)
    raise SystemExit(0)
with open(pid_file, 'a', encoding='ascii') as handle:
    handle.write(f'{os.getpid()}\\n')
    handle.flush()
def terminate(_signum, _frame):
    try:
        os.waitpid(child, 0)
    finally:
        raise SystemExit(0)
signal.signal(signal.SIGTERM, terminate)
print('ready', flush=True)
time.sleep(60)
"""
        with self.assertRaisesRegex(
            acquisition.StrategyQaAcquisitionError, "timed out"
        ):
            acquisition._run_bounded_command(
                (sys.executable, "-B", "-c", script, os.fspath(pid_file)),
                timeout_seconds=0.25,
                output_limit=64,
                environment={
                    **acquisition._strict_command_environment(),
                    "CUDA_VISIBLE_DEVICES": "",
                    "OMP_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                    "NUMEXPR_NUM_THREADS": "2",
                    "TMPDIR": self.temporary.name,
                    "TMP": self.temporary.name,
                    "TEMP": self.temporary.name,
                    "XDG_CACHE_HOME": self.temporary.name,
                    "PYTHONPYCACHEPREFIX": os.fspath(
                        Path(self.temporary.name) / "pycache"
                    ),
                },
            )
        pids = [int(line) for line in pid_file.read_text(encoding="ascii").splitlines()]
        self.assertEqual(len(pids), 2)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if all(not acquisition._owned_process_group_alive(pid) for pid in pids):
                break
            time.sleep(0.01)
        for pid in pids:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_bounded_output_limit_plus_one_reaps_child(self):
        with self.assertRaisesRegex(
            acquisition.StrategyQaAcquisitionError, "output exceeds"
        ):
            acquisition._run_bounded_command(
                (sys.executable, "-B", "-c", "print('x' * 65, end='')"),
                timeout_seconds=2.0,
                output_limit=64,
                environment={
                    **acquisition._strict_command_environment(),
                    "CUDA_VISIBLE_DEVICES": "",
                    "OMP_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                    "NUMEXPR_NUM_THREADS": "2",
                    "TMPDIR": self.temporary.name,
                    "TMP": self.temporary.name,
                    "TEMP": self.temporary.name,
                    "XDG_CACHE_HOME": self.temporary.name,
                    "PYTHONPYCACHEPREFIX": os.fspath(Path(self.temporary.name) / "pycache"),
                },
            )

    def test_git_and_getent_use_bounded_runner_and_disable_fsmonitor(self):
        with mock.patch.object(
            acquisition, "_run_bounded_command", return_value=(0, b"ok")
        ) as bounded:
            acquisition._run_git(("status", "--porcelain=v1"))
            arguments = bounded.call_args.args[0]
            self.assertEqual(arguments[0], acquisition.GIT_PATH)
            self.assertIn("core.fsmonitor=false", arguments)
            self.assertIn("core.untrackedCache=false", arguments)
            self.assertTrue(bounded.call_args.kwargs["environment"]["GIT_CONFIG_NOSYSTEM"] == "1")
        with mock.patch.object(
            acquisition, "_run_bounded_command", return_value=(0, b"ok")
        ) as bounded:
            acquisition._run_getent(("group", "1001"), 10)
            self.assertEqual(
                bounded.call_args.args[0],
                (acquisition.GETENT_PATH, "group", "1001"),
            )
            self.assertEqual(bounded.call_args.kwargs["output_limit"], 10)

    def test_git_and_getent_propagate_bounded_hang_output_and_descendant_failures(self):
        failures = (
            "bounded command timed out",
            "bounded command output exceeds its limit",
            "bounded command group outlived its leader",
        )
        for message in failures:
            for wrapper in ("git", "getent"):
                with self.subTest(message=message, wrapper=wrapper):
                    with mock.patch.object(
                        acquisition,
                        "_run_bounded_command",
                        side_effect=acquisition.StrategyQaAcquisitionError(message),
                    ):
                        with self.assertRaisesRegex(
                            acquisition.StrategyQaAcquisitionError,
                            message.replace(" ", ".*"),
                        ):
                            if wrapper == "git":
                                acquisition._run_git(("status",))
                            else:
                                acquisition._run_getent(("passwd",), 64)

    def test_watchdog_escalates_term_to_kill_and_poll_fault_is_fatal(self):
        process = mock.MagicMock()
        process.wait.return_value = -9
        with mock.patch.object(
            acquisition, "_wait_group_gone", side_effect=(False, True)
        ):
            with mock.patch.object(os, "killpg") as killpg:
                self.assertEqual(
                    acquisition._terminate_owned_group(process, 777, 0.01),
                    "SIGKILL",
                )
        self.assertEqual(
            [call.args[1] for call in killpg.call_args_list],
            [signal.SIGTERM, signal.SIGKILL],
        )
        process.poll.side_effect = OSError(errno.EIO, "poll")
        with mock.patch.object(acquisition, "_owned_process_group_alive", return_value=True):
            with self.assertRaises(OSError):
                acquisition._wait_group_gone(process, 777, 0.01)

    def test_real_cli_resource_gate_runs_only_in_controlled_child(self):
        script = """
import json
import kairos.strategyqa_acquisition as a
print(json.dumps(a._apply_cli_resource_gate(), sort_keys=True))
"""
        code, output = acquisition._run_bounded_command(
            (sys.executable, "-B", "-c", script),
            timeout_seconds=5.0,
            output_limit=16_384,
            environment={
                **acquisition._strict_command_environment(),
                "PYTHONPATH": os.fspath(Path(__file__).resolve().parents[1] / "src"),
                "TMPDIR": self.temporary.name,
                "TMP": self.temporary.name,
                "TEMP": self.temporary.name,
                "XDG_CACHE_HOME": self.temporary.name,
                "PYTHONPYCACHEPREFIX": os.fspath(Path(self.temporary.name) / "pycache"),
            },
        )
        self.assertEqual(code, 0)
        observed = acquisition.json.loads(output)
        acquisition._validate_resource_observation(observed)
        self.assertLessEqual(len(observed["cpu_affinity"]), 2)
        maxima = {
            name: maximum
            for name, _resource_id, maximum in acquisition._RESOURCE_RULES
        }
        for name, pair in observed["limits"].items():
            self.assertLessEqual(pair["soft"], pair["hard"])
            self.assertLessEqual(pair["hard"], maxima[name])
        self.assertEqual(observed["limits"]["core_bytes"], {"soft": 0, "hard": 0})


if __name__ == "__main__":
    unittest.main()
