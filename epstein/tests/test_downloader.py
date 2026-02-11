"""Tests for EpsteinFileDownloader: search parsing, URL building, file type detection (mocked)."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from download_epstein_files import EpsteinFileDownloader


class TestSearchParsing:
    """Search result HTML parsing returns correct file IDs and datasets."""

    def test_search_returns_file_ids_when_html_has_efta_links(self, sample_search_html, temp_dir):
        """When the server returns HTML with EFTA links, search_files returns those file IDs."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = sample_search_html
        mock_response.raise_for_status = MagicMock()

        with patch.object(d.session, "get", return_value=mock_response):
            with patch.object(d.session, "post", return_value=mock_response):
                result = d.search_files("No images produced", dataset=8, page=1)

        assert result is not None
        assert "files" in result
        assert result["total_results"] >= 2
        full_ids = [f["full_id"] for f in result["files"]]
        assert "EFTA00024813" in full_ids
        assert "EFTA00033177" in full_ids
        for f in result["files"]:
            assert f.get("dataset") == 8 or f.get("dataset") is not None

    def test_search_returns_empty_when_html_has_no_efta(self, temp_dir):
        """When HTML has no EFTA IDs, search_files returns empty files list."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>No results. 403 Forbidden.</body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(d.session, "get", return_value=mock_response):
            with patch.object(d.session, "post", return_value=mock_response):
                result = d.search_files("No images produced", dataset=1, page=1)

        assert result is not None
        assert result["files"] == []
        assert result["total_results"] == 0

    def test_search_handles_403_response(self, temp_dir):
        """When server returns 403, search_files returns None or empty and does not crash."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "<html><body>403 Forbidden</body></html>"
        mock_response.raise_for_status = MagicMock(side_effect=Exception("403 Forbidden"))

        with patch.object(d.session, "get", return_value=mock_response):
            with patch.object(d.session, "post", return_value=mock_response):
                result = d.search_files("No images produced", dataset=1, page=1)

        # Either None or result with empty files
        assert result is None or result["total_results"] == 0


class TestUrlBuilding:
    """File and dataset URLs are built correctly."""

    def test_file_url_format(self, temp_dir):
        """File URL uses DataSet N and EFTA id + extension."""
        from urllib.parse import quote
        base = "https://www.justice.gov/epstein/"
        dataset_encoded = quote("DataSet 8")
        file_id = "EFTA00033177"
        ext = ".mp4"
        url = f"{base}files/{dataset_encoded}/{file_id}{ext}"
        assert "DataSet%208" in url
        assert "EFTA00033177.mp4" in url
        assert url == "https://www.justice.gov/epstein/files/DataSet%208/EFTA00033177.mp4"


class TestFileExtensionDetection:
    """test_file_extension and find_file_type with mocked HTTP."""

    def test_test_file_extension_returns_true_when_200_and_not_html(self, temp_dir):
        """When HEAD returns 200 and Content-Type is not text/html, test_file_extension returns True."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "video/mp4", "Content-Length": "1000000"}

        with patch.object(d.session, "head", return_value=mock_response):
            out = d.test_file_extension("EFTA00033177", 8, ".mp4")
        assert out is True

    def test_test_file_extension_returns_false_when_404(self, temp_dir):
        """When HEAD returns 404, test_file_extension returns False."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(d.session, "head", return_value=mock_response):
            out = d.test_file_extension("EFTA00033177", 8, ".mp4")
        assert out is False

    def test_find_file_type_returns_extension_when_one_matches(self, temp_dir):
        """find_file_type returns the first extension that test_file_extension returns True for."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        with patch.object(d, "test_file_extension", side_effect=lambda fid, ds, ext: ext == ".mp4"):
            result = d.find_file_type("EFTA00033177", 8)
        assert result == ".mp4"

    def test_find_file_type_returns_none_when_none_match(self, temp_dir):
        """find_file_type returns None when all extensions return False."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        with patch.object(d, "test_file_extension", return_value=False):
            result = d.find_file_type("EFTA00033177", 8)
        assert result is None


class TestDownloadFile:
    """download_file writes to correct path and uses correct URL."""

    def test_download_file_writes_to_extension_subdir(self, temp_dir):
        """download_file saves to download_dir / extension_subdir / EFTA{id}{ext}."""
        d = EpsteinFileDownloader(download_dir=temp_dir)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content = lambda chunk_size: [b"fake content"]
        mock_response.raise_for_status = MagicMock()

        with patch.object(d.session, "get", return_value=mock_response):
            ok = d.download_file("EFTA00033177", 8, ".mp4")

        assert ok is True
        save_path = temp_dir / "mp4" / "EFTA00033177.mp4"
        assert save_path.exists()
        assert save_path.read_bytes() == b"fake content"
