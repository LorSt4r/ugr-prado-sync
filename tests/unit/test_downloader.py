"""
Unit tests for SafeDownloader and Content-Disposition parser.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from prado.core.downloader import (
    DownloadResult,
    DownloadStatus,
    SafeDownloader,
    SyncSummary,
    parse_content_disposition,
    resolve_destination_path,
)
from prado.downloader import (
    SafeDownloader as SDTopLevel,
    parse_content_disposition as pcd_top_level,
    resolve_destination_path as rdp_top_level,
)
from prado.exceptions import PradoError


class TestContentDisposition:
    def test_parse_quoted_filename(self):
        hdr = 'attachment; filename="Relacion_1_Eficiencia.pdf"'
        assert parse_content_disposition(hdr) == "Relacion_1_Eficiencia.pdf"

    def test_parse_unquoted_filename(self):
        hdr = "attachment; filename=relacion1.pdf"
        assert parse_content_disposition(hdr) == "relacion1.pdf"

    def test_parse_rfc5987_utf8_filename(self):
        hdr = "attachment; filename*=UTF-8''Presentaci%C3%B3n_T1.pdf"
        assert parse_content_disposition(hdr) == "Presentación_T1.pdf"

    def test_parse_none_or_empty(self):
        assert parse_content_disposition(None) is None
        assert parse_content_disposition("") is None
        assert parse_content_disposition("inline") is None


class TestSafeDownloader:
    def test_download_success_atomic_replace(self, tmp_path):
        dest_file = tmp_path / "downloads" / "tema1.pdf"
        content = b"%PDF-1.4 Simulated PDF Document Content"
        expected_sha = hashlib.sha256(content).hexdigest()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": str(len(content))}
        mock_resp.iter_content.return_value = [content[:10], content[10:]]

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            progress_records = []

            def progress_cb(written, total):
                progress_records.append((written, total))

            res = downloader.download_file(
                url="https://prado.ugr.es/mod/resource/view.php?id=123",
                dest_path=dest_file,
                progress_callback=progress_cb,
            )

        assert res.status == DownloadStatus.DOWNLOADED
        assert res.sha256 == expected_sha
        assert res.size_bytes == len(content)
        assert dest_file.exists()
        assert dest_file.read_bytes() == content
        assert len(progress_records) >= 1

    def test_download_checksum_verification(self, tmp_path):
        dest_file = tmp_path / "tema2.pdf"
        content = b"Content 123"
        correct_sha = hashlib.sha256(content).hexdigest()
        wrong_sha = "0000000000000000000000000000000000000000000000000000000000000000"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.iter_content.return_value = [content]

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            # Correct checksum succeeds
            res1 = downloader.download_file(
                url="https://prado.ugr.es/file",
                dest_path=dest_file,
                expected_hash=correct_sha,
            )
            assert res1.status == DownloadStatus.DOWNLOADED

            # Wrong checksum fails
            res2 = downloader.download_file(
                url="https://prado.ugr.es/file",
                dest_path=dest_file,
                expected_hash=wrong_sha,
            )
            assert res2.status == DownloadStatus.FAILED
            assert "Checksum mismatch" in res2.error

    def test_download_cleanup_on_error(self, tmp_path):
        dest_file = tmp_path / "broken.pdf"

        session = requests.Session()
        with patch.object(session, "get", side_effect=requests.RequestException("Connection drop")):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 0  # speed up test
            res = downloader.download_file(
                url="https://prado.ugr.es/broken",
                dest_path=dest_file,
            )

        assert res.status == DownloadStatus.FAILED
        assert not dest_file.exists()
        # Verify no .prado_tmp_ files left behind
        temp_files = list(tmp_path.glob(".prado_tmp_*"))
        assert len(temp_files) == 0

    def test_download_404_not_found(self, tmp_path):
        dest_file = tmp_path / "not_found.pdf"

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            res = downloader.download_file(
                url="https://prado.ugr.es/missing",
                dest_path=dest_file,
            )

        assert res.status == DownloadStatus.FAILED
        assert "404" in res.error
        assert not dest_file.exists()

    def test_download_zero_byte_file(self, tmp_path):
        dest_file = tmp_path / "empty.dat"
        empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": "0"}
        mock_resp.iter_content.return_value = []

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            res = downloader.download_file(
                url="https://prado.ugr.es/empty",
                dest_path=dest_file,
            )

        assert res.status == DownloadStatus.DOWNLOADED
        assert res.size_bytes == 0
        assert res.sha256 == empty_sha
        assert dest_file.exists()
        assert dest_file.stat().st_size == 0


class TestDestinationResolution:
    def test_resolve_destination_content_disposition(self, tmp_path):
        dest = tmp_path / "Practica_3.pdf"
        mock_resp = MagicMock()
        mock_resp.headers = {
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="Practica_3.zip"',
        }
        mock_resp.url = "https://prado.ugr.es/mod/resource/view.php?id=123"
        dl = SafeDownloader()
        resolved = dl.resolve_destination(dest, "https://prado.ugr.es/mod/resource/view.php?id=123", mock_resp)
        assert resolved == tmp_path / "Practica_3.zip"

    def test_resolve_destination_mime_only(self, tmp_path):
        dest = tmp_path / "Notebook.pdf"
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/x-ipynb+json"}
        mock_resp.url = "https://prado.ugr.es/mod/resource/view.php?id=456"
        dl = SafeDownloader()
        resolved = dl.resolve_destination(dest, "https://prado.ugr.es/mod/resource/view.php?id=456", mock_resp)
        assert resolved == tmp_path / "Notebook.ipynb"

    def test_resolve_destination_clean_url_preserved(self, tmp_path):
        dest = tmp_path / "Tema_1.pdf"
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.url = "https://prado.ugr.es/files/Tema_1.pdf"
        dl = SafeDownloader()
        resolved = dl.resolve_destination(dest, "https://prado.ugr.es/files/Tema_1.pdf", mock_resp)
        assert resolved == tmp_path / "Tema_1.pdf"

    def test_download_file_updates_dest_path_on_content_disposition(self, tmp_path):
        dest_file = tmp_path / "downloads" / "Guion.pdf"
        content = b"PK\x03\x04 fake zip content"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="Guion.zip"',
            "Content-Length": str(len(content)),
        }
        mock_resp.iter_content.return_value = [content]

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            dl = SafeDownloader(session=session)
            res = dl.download_file("https://prado.ugr.es/mod/resource/view.php?id=107913", dest_file)

        assert res.status == DownloadStatus.DOWNLOADED
        assert res.dest_path == tmp_path / "downloads" / "Guion.zip"
        assert (tmp_path / "downloads" / "Guion.zip").exists()
        assert not dest_file.exists()


class TestTopLevelReExports:
    def test_re_exports_match(self):
        assert SDTopLevel is SafeDownloader
        assert pcd_top_level is parse_content_disposition
        assert rdp_top_level is resolve_destination_path
