"""Tests for pinned content functionality.

Tests cover:
- repo_serializer module (serialization, hashing, budget validation)
- PinnedContentService (pin, staleness, repin operations)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, UTC

from app.agents.repo_serializer import (
    REPOSITORY_CONTEXT_PREAMBLE,
    calculate_content_hash,
    calculate_file_hash,
    calculate_file_hashes,
    estimate_tokens,
    estimate_tokens_for_mime,
    serialize_content,
    build_xml_wrapper,
    validate_pinned_content_budget,
    should_ignore_file,
    is_text_file,
    escape_xml_content,
)


# =============================================================================
# repo_serializer Tests
# =============================================================================


class TestEstimateTokens:
    """Tests for token estimation."""

    def test_estimate_tokens_text(self):
        """Test text token estimation (char/4 heuristic)."""
        # 100 chars = ~25 tokens
        text = "a" * 100
        assert estimate_tokens(text) == 25

    def test_estimate_tokens_empty_string(self):
        """Test empty string returns 0."""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_bytes(self):
        """Test binary token estimation."""
        # Binary uses ~1 token per 100 bytes, minimum 258
        small_binary = b"x" * 100
        assert estimate_tokens(small_binary) == 258  # Minimum

        large_binary = b"x" * 50000
        assert estimate_tokens(large_binary) == 500


class TestEstimateTokensForMime:
    """Tests for MIME-type aware token estimation."""

    def test_small_image(self):
        """Small images get minimum 258 tokens."""
        content = b"x" * 50_000  # 50KB
        assert estimate_tokens_for_mime(content, "image/png") == 258

    def test_medium_image(self):
        """Medium images get 768 tokens."""
        content = b"x" * 500_000  # 500KB
        assert estimate_tokens_for_mime(content, "image/jpeg") == 768

    def test_large_image(self):
        """Large images get 1290 tokens."""
        content = b"x" * 2_000_000  # 2MB
        assert estimate_tokens_for_mime(content, "image/webp") == 1290

    def test_audio(self):
        """Audio uses ~2 tokens per KB."""
        content = b"x" * 100_000  # 100KB
        tokens = estimate_tokens_for_mime(content, "audio/mp3")
        assert tokens >= 32  # Minimum
        # 100KB / 1024 * 2 ≈ 195, int truncation gives 194
        assert 190 <= tokens <= 200

    def test_video(self):
        """Video uses ~2 tokens per KB."""
        content = b"x" * 500_000  # 500KB
        tokens = estimate_tokens_for_mime(content, "video/mp4")
        assert tokens >= 258  # Minimum


class TestCalculateHashes:
    """Tests for hash calculation."""

    def test_calculate_file_hash(self):
        """Test individual file hash."""
        content = "Hello, World!"
        hash1 = calculate_file_hash(content)
        assert len(hash1) == 64  # SHA256 hex

        # Same content = same hash
        hash2 = calculate_file_hash(content)
        assert hash1 == hash2

        # Different content = different hash
        hash3 = calculate_file_hash("Different content")
        assert hash1 != hash3

    def test_calculate_file_hash_bytes(self):
        """Test hash for binary content."""
        content = b"\x00\x01\x02\x03"
        hash_val = calculate_file_hash(content)
        assert len(hash_val) == 64

    def test_calculate_content_hash(self):
        """Test combined content hash for cache key."""
        files = {
            "file1.py": "print('hello')",
            "file2.py": "print('world')",
        }
        hash1 = calculate_content_hash(files)
        assert len(hash1) == 16  # Truncated to 16 chars

        # Order shouldn't matter (files are sorted)
        files_reordered = {
            "file2.py": "print('world')",
            "file1.py": "print('hello')",
        }
        hash2 = calculate_content_hash(files_reordered)
        assert hash1 == hash2

    def test_calculate_file_hashes(self):
        """Test batch file hash calculation."""
        files = {
            "a.py": "content a",
            "b.py": "content b",
        }
        hashes = calculate_file_hashes(files)
        assert len(hashes) == 2
        assert "a.py" in hashes
        assert "b.py" in hashes
        assert len(hashes["a.py"]) == 64


class TestShouldIgnoreFile:
    """Tests for file filtering."""

    def test_ignore_git_directory(self):
        """Should ignore .git directory."""
        assert should_ignore_file(".git/config")
        assert should_ignore_file("src/.git/HEAD")

    def test_ignore_node_modules(self):
        """Should ignore node_modules."""
        assert should_ignore_file("node_modules/package/index.js")

    def test_ignore_pycache(self):
        """Should ignore __pycache__."""
        assert should_ignore_file("app/__pycache__/module.cpython-313.pyc")

    def test_ignore_lock_files(self):
        """Should ignore lock files."""
        assert should_ignore_file("package-lock.json")
        assert should_ignore_file("poetry.lock")
        assert should_ignore_file("yarn.lock")

    def test_ignore_ds_store(self):
        """Should ignore .DS_Store."""
        assert should_ignore_file(".DS_Store")
        assert should_ignore_file("folder/.DS_Store")

    def test_allow_regular_files(self):
        """Should allow regular source files."""
        assert not should_ignore_file("src/main.py")
        assert not should_ignore_file("components/Button.tsx")
        assert not should_ignore_file("README.md")


class TestIsTextFile:
    """Tests for text file detection."""

    def test_python_files(self):
        """Python files are text."""
        assert is_text_file("main.py")
        assert is_text_file("src/app.py")

    def test_javascript_files(self):
        """JavaScript/TypeScript files are text."""
        assert is_text_file("index.js")
        assert is_text_file("component.tsx")

    def test_config_files(self):
        """Config files are text."""
        assert is_text_file("config.json")
        assert is_text_file("settings.yaml")
        assert is_text_file(".env.example")

    def test_makefile(self):
        """Makefile (no extension) is text."""
        assert is_text_file("Makefile")
        assert is_text_file("Dockerfile")

    def test_binary_not_text(self):
        """Binary files are not text without MIME hint."""
        # Without MIME type, extension determines
        assert not is_text_file("image.png")
        assert not is_text_file("video.mp4")


class TestEscapeXmlContent:
    """Tests for XML content escaping."""

    def test_escape_angle_brackets(self):
        """Should escape < and >."""
        content = "if (a < b && b > c) {}"
        escaped = escape_xml_content(content)
        assert "&lt;" in escaped
        assert "&gt;" in escaped

    def test_escape_ampersand(self):
        """Should escape &."""
        content = "foo & bar"
        escaped = escape_xml_content(content)
        assert "&amp;" in escaped

    def test_preserve_regular_text(self):
        """Should not modify regular text."""
        content = "def hello(): print('world')"
        escaped = escape_xml_content(content)
        assert escaped == content


class TestBuildXmlWrapper:
    """Tests for XML structure building."""

    def test_empty_files(self):
        """Empty dict produces minimal wrapper with preamble."""
        xml = build_xml_wrapper({})
        assert REPOSITORY_CONTEXT_PREAMBLE.strip() in xml
        assert "<repository_context>" in xml
        assert "</repository_context>" in xml

    def test_single_file(self):
        """Single file is wrapped correctly with preamble."""
        files = {"main.py": "print('hello')"}
        xml = build_xml_wrapper(files)
        # Verify preamble comes before repository_context
        preamble_pos = xml.find(REPOSITORY_CONTEXT_PREAMBLE.strip().split('\n')[0])
        context_pos = xml.find("<repository_context>")
        assert preamble_pos < context_pos
        assert '<file path="main.py">' in xml
        assert "print('hello')" in xml
        assert "</file>" in xml

    def test_multiple_files_sorted(self):
        """Multiple files are sorted by path."""
        files = {
            "z.py": "z content",
            "a.py": "a content",
        }
        xml = build_xml_wrapper(files)
        # a.py should come before z.py
        a_pos = xml.find("a.py")
        z_pos = xml.find("z.py")
        assert a_pos < z_pos

    def test_path_escaping(self):
        """Paths with special chars are escaped."""
        files = {"path/with<special>.py": "content"}
        xml = build_xml_wrapper(files)
        assert "&lt;special&gt;" in xml


class TestSerializeContent:
    """Tests for content serialization."""

    def test_text_files_only(self):
        """Text files are serialized to XML."""
        files = {
            "main.py": "print('hello')",
            "utils.py": "def util(): pass",
        }
        parts, tokens = serialize_content(files)

        assert len(parts) == 1  # Single text part
        assert parts[0].text is not None
        assert "<repository_context>" in parts[0].text
        assert tokens > 0

    def test_binary_files(self):
        """Binary files become inline_data parts."""
        files = {
            "image.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        }
        mime_types = {"image.png": "image/png"}
        parts, tokens = serialize_content(files, mime_types)

        assert len(parts) == 1
        assert parts[0].inline_data is not None
        assert parts[0].inline_data.mime_type == "image/png"

    def test_mixed_content(self):
        """Mixed text and binary produces multiple parts."""
        files = {
            "main.py": "print('hello')",
            "logo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        }
        mime_types = {"logo.png": "image/png"}
        parts, tokens = serialize_content(files, mime_types)

        # Should have text part + binary part
        assert len(parts) == 2

    def test_ignored_files_skipped(self):
        """Ignored files are not included."""
        files = {
            "main.py": "print('hello')",
            "node_modules/pkg/index.js": "module.exports = {}",
        }
        parts, tokens = serialize_content(files)

        # node_modules should be filtered out
        assert "node_modules" not in parts[0].text


class TestValidatePinnedContentBudget:
    """Tests for budget validation."""

    @patch("app.agents.repo_serializer.settings")
    def test_within_budget(self, mock_settings):
        """Content within budget passes."""
        mock_settings.MAX_PINNED_CONTEXT_PERCENT = 40
        mock_settings.PINNED_CONTEXT_WARNING_PERCENT = 30

        result = validate_pinned_content_budget(
            total_tokens=100_000,  # Small amount
            model_name="gemini-2.5-flash",  # ~891K budget
        )

        assert result["within_budget"] is True
        assert result["warning"] is None
        assert result["error"] is None

    @patch("app.agents.repo_serializer.settings")
    def test_warning_threshold(self, mock_settings):
        """Content at 30-40% triggers warning."""
        mock_settings.MAX_PINNED_CONTEXT_PERCENT = 40
        mock_settings.PINNED_CONTEXT_WARNING_PERCENT = 30

        result = validate_pinned_content_budget(
            total_tokens=300_000,  # ~34% of 891K
            model_name="gemini-2.5-flash",
        )

        assert result["within_budget"] is True
        assert result["warning"] is not None
        assert "Large context" in result["warning"]

    @patch("app.agents.repo_serializer.settings")
    def test_over_budget(self, mock_settings):
        """Content over 40% triggers error."""
        mock_settings.MAX_PINNED_CONTEXT_PERCENT = 40
        mock_settings.PINNED_CONTEXT_WARNING_PERCENT = 30

        result = validate_pinned_content_budget(
            total_tokens=400_000,  # ~45% of 891K
            model_name="gemini-2.5-flash",
        )

        assert result["within_budget"] is False
        assert result["error"] is not None
        assert "exceeds" in result["error"]


# =============================================================================
# PinnedContentService Tests
# =============================================================================


class TestPinnedContentService:
    """Tests for PinnedContentService."""

    @pytest.mark.anyio
    async def test_check_staleness_no_pinned_content(self):
        """Check staleness when nothing pinned returns False."""
        from app.services.pinned_content import PinnedContentService

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        service = PinnedContentService(mock_db)
        result = await service.check_staleness(uuid4(), {"file.py": "abc123"})

        assert result["is_stale"] is False
        assert result["has_pinned_content"] is False

    @pytest.mark.anyio
    async def test_check_staleness_with_changes(self):
        """Check staleness detects changed files."""
        from app.services.pinned_content import PinnedContentService
        from app.db.models.conversation import ConversationPinnedContent

        # Create mock pinned content
        mock_pinned = MagicMock(spec=ConversationPinnedContent)
        mock_pinned.file_hashes = {
            "file1.py": "hash1",
            "file2.py": "hash2",
        }

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_pinned
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = PinnedContentService(mock_db)

        # Changed hash for file1
        result = await service.check_staleness(
            uuid4(),
            {
                "file1.py": "changed_hash",
                "file2.py": "hash2",
            },
        )

        assert result["is_stale"] is True
        assert "file1.py" in result["changed_files"]
        assert result["has_pinned_content"] is True

    @pytest.mark.anyio
    async def test_check_staleness_with_added_files(self):
        """Check staleness detects added files."""
        from app.services.pinned_content import PinnedContentService
        from app.db.models.conversation import ConversationPinnedContent

        mock_pinned = MagicMock(spec=ConversationPinnedContent)
        mock_pinned.file_hashes = {"file1.py": "hash1"}

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_pinned
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = PinnedContentService(mock_db)

        result = await service.check_staleness(
            uuid4(),
            {
                "file1.py": "hash1",
                "newfile.py": "newhash",
            },
        )

        assert result["is_stale"] is True
        assert "newfile.py" in result["added_files"]

    @pytest.mark.anyio
    async def test_get_pinned_content_info_none(self):
        """Get pinned info returns None when nothing pinned."""
        from app.services.pinned_content import PinnedContentService

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        service = PinnedContentService(mock_db)
        result = await service.get_pinned_content_info(uuid4())

        assert result is None

    @pytest.mark.anyio
    async def test_get_pinned_content_hash(self):
        """Get pinned content hash returns correct value."""
        from app.services.pinned_content import PinnedContentService
        from app.db.models.conversation import ConversationPinnedContent

        mock_pinned = MagicMock(spec=ConversationPinnedContent)
        mock_pinned.content_hash = "abc123def456"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_pinned
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = PinnedContentService(mock_db)
        result = await service.get_pinned_content_hash(uuid4())

        assert result == "abc123def456"

    @pytest.mark.anyio
    async def test_get_pinned_tokens(self):
        """Get pinned tokens returns correct count."""
        from app.services.pinned_content import PinnedContentService
        from app.db.models.conversation import ConversationPinnedContent

        mock_pinned = MagicMock(spec=ConversationPinnedContent)
        mock_pinned.total_tokens = 50000

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_pinned
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = PinnedContentService(mock_db)
        result = await service.get_pinned_tokens(uuid4())

        assert result == 50000
