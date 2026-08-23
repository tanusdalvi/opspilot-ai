"""Phase 9 tests: CSV upload hardening.

Covers size limits, extension/empty rejection, friendly parse-error
mapping for malformed/binary/empty CSVs, the explicit duplicate-basename
replacement policy, and preserved traversal sanitization.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from app import orchestrator  # noqa: E402
from core.constants import (  # noqa: E402
    MAX_UPLOAD_BYTES,
    UPLOAD_DUPLICATE_POLICY,
    UPLOAD_ROW_ADVISORY,
)
from core.exceptions import DataValidationError  # noqa: E402

VALID_CSV = (
    b"date,region,product,units_sold,revenue,cost,lead_time_days\n"
    b"2024-01-01,North,P1,10,100,80,2\n"
)


class TestUploadLimits:
    def test_constants_are_demo_safe(self):
        assert MAX_UPLOAD_BYTES >= 1024 * 1024
        assert UPLOAD_ROW_ADVISORY >= 1
        assert UPLOAD_DUPLICATE_POLICY == "replace"

    def test_oversized_upload_rejected_before_parsing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(orchestrator, "MAX_UPLOAD_BYTES", 16)
        with pytest.raises(DataValidationError, match="too large"):
            orchestrator.stage_upload("big.csv", b"x" * 32)

    def test_real_limit_rejects_without_disk_write(self, tmp_path, monkeypatch):
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", tmp_path / "uploads")
        payload = b"a,b\n" + b"1,2\n" * (MAX_UPLOAD_BYTES // 4)
        assert len(payload) > MAX_UPLOAD_BYTES
        with pytest.raises(DataValidationError, match="too large"):
            orchestrator.stage_upload("huge.csv", payload)
        staged = list((tmp_path / "uploads").iterdir()) if (tmp_path / "uploads").exists() else []
        assert staged == []


class TestUploadRejections:
    def test_empty_content_rejected(self):
        with pytest.raises(DataValidationError, match="[Ee]mpty"):
            orchestrator.stage_upload("empty.csv", b"")

    def test_wrong_extension_rejected(self):
        with pytest.raises(DataValidationError, match="Only CSV"):
            orchestrator.stage_upload("data.txt", VALID_CSV)

    def test_missing_name_rejected(self):
        with pytest.raises(DataValidationError):
            orchestrator.stage_upload("   ", VALID_CSV)

    def test_traversal_sanitized_to_basename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", tmp_path / "uploads")
        staged = orchestrator.stage_upload("../evil.csv", VALID_CSV)
        assert staged.parent == tmp_path / "uploads"
        assert staged.name == "evil.csv"


class TestFriendlyParseErrors:
    def test_malformed_csv_maps_to_typed_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", tmp_path / "uploads")
        malformed = b'date,region\n"unclosed,2024-01-01\n'
        with pytest.raises(DataValidationError, match="well-formed CSV"):
            orchestrator.load_uploaded_dataset("broken.csv", malformed)

    def test_binary_upload_maps_to_typed_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", tmp_path / "uploads")
        binary = bytes(range(256)) * 4
        with pytest.raises(DataValidationError, match="read as text|binary|encoding"):
            orchestrator.load_uploaded_dataset("binary.csv", binary)

    def test_no_columns_file_maps_to_typed_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", tmp_path / "uploads")
        with pytest.raises(DataValidationError, match="no CSV data"):
            orchestrator.load_uploaded_dataset("blank.csv", b"\n\n")

    @pytest.mark.parametrize("bad_content,label", [
        (b"\xff\xfe\x00\x00binary-ish", "encoding"),
        (b'{"not":"a csv"}\n', None),  # valid text, parses as single-column frame
    ])
    def test_parse_error_paths_never_leak_raw_details(
        self, tmp_path, monkeypatch, capsys, bad_content, label
    ):
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", tmp_path / "uploads")
        try:
            orchestrator.load_uploaded_dataset("odd.csv", bad_content)
        except DataValidationError as exc:
            assert "Traceback" not in str(exc)
        except UnicodeDecodeError:
            pytest.fail("raw decode error escaped the boundary")


class TestDuplicateFilenamePolicy:
    def test_same_basename_deterministically_replaces(
        self, tmp_path, monkeypatch
    ):
        uploads = tmp_path / "uploads"
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", uploads)
        first = orchestrator.stage_upload("dup.csv", b"a,b\n1,2\n")
        second = orchestrator.stage_upload("dup.csv", b"c,d\n3,4\n")
        assert first == second
        assert first.read_bytes() == b"c,d\n3,4\n"
        assert len(list(uploads.iterdir())) == 1


class TestValidUploadStillWorks:
    def test_valid_csv_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(orchestrator, "UPLOAD_DIR", tmp_path / "uploads")
        frame = orchestrator.load_uploaded_dataset("good.csv", VALID_CSV)
        assert isinstance(frame, pd.DataFrame)
        assert list(frame.columns) == [
            "date",
            "region",
            "product",
            "units_sold",
            "revenue",
            "cost",
            "lead_time_days",
        ]
        assert len(frame) == 1
