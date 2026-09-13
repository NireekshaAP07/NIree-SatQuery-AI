"""
Unit tests for app.core.storage — LocalStorageBackend.

These tests do NOT need a running database or API server; they exercise
the storage layer in isolation using the tmp_storage_root fixture.
"""
from __future__ import annotations

import pytest
from pathlib import Path


class TestLocalStorageBackend:
    """Tests for LocalStorageBackend."""

    def test_save_upload_creates_file(self, patch_storage):
        """save_upload() should persist bytes and return a resolvable path."""
        backend = patch_storage
        data = b"fake geotiff bytes"
        result = backend.save_upload(data, "test_image.tif")
        assert isinstance(result, Path)
        assert result.exists()
        assert result.read_bytes() == data

    def test_save_upload_unique_filename(self, patch_storage):
        """Two uploads of the same filename should produce different stored paths."""
        backend = patch_storage
        data = b"content"
        p1 = backend.save_upload(data, "same.tif")
        p2 = backend.save_upload(data, "same.tif")
        assert p1 != p2

    def test_save_derived_creates_file(self, patch_storage):
        """save_derived() should persist derived products under the derived/ subdir."""
        backend = patch_storage
        data = b"pdf bytes"
        result = backend.save_derived(data, "report_123.pdf")
        assert result.exists()
        assert result.read_bytes() == data
        assert "derived" in str(result)

    def test_get_object_bytes_roundtrip(self, patch_storage):
        """get_object_bytes() should return exactly the bytes that were saved."""
        backend = patch_storage
        data = b"round trip data"
        p = backend.save_derived(data, "roundtrip.json")
        # get_object_bytes accepts a relative key matching derived/<filename>
        retrieved = backend.get_object_bytes(p)
        assert retrieved == data

    def test_exists_true_for_existing_file(self, patch_storage):
        """exists() should return True for a file that has been saved."""
        backend = patch_storage
        p = backend.save_derived(b"exists", "exists_check.bin")
        assert backend.exists(p) is True

    def test_exists_false_for_missing_file(self, patch_storage, tmp_storage_root):
        """exists() should return False for a path that has not been saved."""
        backend = patch_storage
        missing = tmp_storage_root / "derived" / "nonexistent.bin"
        assert backend.exists(missing) is False

    def test_delete_removes_file(self, patch_storage):
        """delete() should remove a previously saved file."""
        backend = patch_storage
        p = backend.save_derived(b"delete me", "to_delete.bin")
        assert p.exists()
        backend.delete(p)
        assert not p.exists()

    def test_path_traversal_blocked(self, patch_storage):
        """get_path() must raise ValueError for paths escaping the storage root."""
        backend = patch_storage
        with pytest.raises(ValueError, match="traversal"):
            backend.get_path("../../etc/passwd")

    def test_download_file_copies_to_target(self, patch_storage, tmp_path):
        """download_file() should copy the stored bytes to the target path."""
        backend = patch_storage
        data = b"download content"
        src = backend.save_derived(data, "to_download.bin")
        dest = tmp_path / "local_copy.bin"
        result = backend.download_file(src, dest)
        assert result == dest
        assert dest.read_bytes() == data
