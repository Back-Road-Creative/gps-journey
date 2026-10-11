"""Characterization tests for gps_journey.hugo.markdown_updater.

These pin what HugoMarkdownUpdater does today (frontmatter round trip, backups,
atomic write, YouTube id extraction) so a pure restyle of the module can be shown
to change nothing. Every file lives under tmp_path; the clock is frozen for the one
test that depends on it; nothing touches the network.
"""

from datetime import datetime
from pathlib import Path

import pytest
import yaml

import gps_journey.hugo.markdown_updater as markdown_updater_module
from gps_journey.hugo.markdown_updater import HugoMarkdownUpdater, update_journey_with_youtube

SAMPLE = (
    "---\n"
    "title: Ireland Road Trip\n"
    "draft: false\n"
    "tags:\n"
    "- road\n"
    "- ireland\n"
    "---\n"
    "\n"
    "## Journey Overview\n"
    "\n"
    "Body text with --- dashes inside.\n"
)
SAMPLE_BODY = "\n\n## Journey Overview\n\nBody text with --- dashes inside.\n"
VIDEO_URL = "https://youtu.be/dQw4w9WgXcQ"
VIDEO_ID = "dQw4w9WgXcQ"


class _FrozenDatetime(datetime):
    """datetime whose now() is pinned, so timestamped backup names are predictable."""

    @classmethod
    def now(cls, tz=None):
        return cls(2030, 3, 15, 12, 34, 56)


@pytest.fixture
def md_file(tmp_path):
    path = tmp_path / "journey.md"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


def _frontmatter(path: Path) -> dict:
    """Parse the frontmatter independently of the code under test."""
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


class TestInit:
    def test_defaults(self):
        updater = HugoMarkdownUpdater()
        assert updater.create_backups is True
        assert updater.backup_suffix == ".bak"

    def test_custom_values(self):
        updater = HugoMarkdownUpdater(create_backups=False, backup_suffix=".orig")
        assert updater.create_backups is False
        assert updater.backup_suffix == ".orig"


class TestUpdateFrontmatter:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Markdown file not found"):
            HugoMarkdownUpdater().update_frontmatter(tmp_path / "nope.md", {"a": 1})

    def test_adds_fields_and_preserves_body_exactly(self, md_file):
        result = HugoMarkdownUpdater().update_frontmatter(
            md_file,
            {"youtube_video": VIDEO_URL, "youtube_id": VIDEO_ID},
            create_backup=False,
        )
        assert result == md_file
        assert md_file.read_text(encoding="utf-8") == (
            "---\n"
            "title: Ireland Road Trip\n"
            "draft: false\n"
            "tags:\n"
            "- road\n"
            "- ireland\n"
            f"youtube_video: {VIDEO_URL}\n"
            f"youtube_id: {VIDEO_ID}\n"
            "---\n"
            "\n"
            "## Journey Overview\n"
            "\n"
            "Body text with --- dashes inside.\n"
        )
        assert not md_file.with_suffix(".md.bak").exists()
        assert not md_file.with_suffix(".md.tmp").exists()

    def test_string_path_is_accepted(self, md_file):
        result = HugoMarkdownUpdater().update_frontmatter(
            str(md_file), {"featured": True}, create_backup=False
        )
        assert result == md_file
        assert isinstance(result, Path)
        assert _frontmatter(md_file)["featured"] is True

    def test_existing_key_is_overwritten_in_place(self, md_file):
        HugoMarkdownUpdater().update_frontmatter(md_file, {"draft": True}, create_backup=False)
        text = md_file.read_text(encoding="utf-8")
        assert text.startswith("---\ntitle: Ireland Road Trip\ndraft: true\ntags:\n")
        assert list(_frontmatter(md_file)) == ["title", "draft", "tags"]

    def test_backup_is_made_by_default_from_the_original(self, md_file):
        HugoMarkdownUpdater().update_frontmatter(md_file, {"draft": True})
        backup = md_file.with_suffix(".md.bak")
        assert backup.read_text(encoding="utf-8") == SAMPLE
        assert _frontmatter(md_file)["draft"] is True

    @pytest.mark.parametrize(
        ("default", "override", "expect_backup"),
        [
            (True, None, True),
            (True, False, False),
            (False, None, False),
            (False, True, True),
        ],
    )
    def test_per_call_override_beats_the_default(self, md_file, default, override, expect_backup):
        updater = HugoMarkdownUpdater(create_backups=default)
        updater.update_frontmatter(md_file, {"draft": True}, create_backup=override)
        assert md_file.with_suffix(".md.bak").exists() is expect_backup


class TestAddYoutubeVideo:
    def test_extracts_id_from_url_and_enables_embed(self, md_file):
        result = HugoMarkdownUpdater().add_youtube_video(md_file, VIDEO_URL)
        assert result == md_file
        frontmatter = _frontmatter(md_file)
        assert frontmatter["youtube_video"] == VIDEO_URL
        assert frontmatter["youtube_id"] == VIDEO_ID
        assert frontmatter["youtube_embed"] is True
        assert "video_published_date" not in frontmatter

    def test_explicit_id_skips_extraction(self, md_file):
        HugoMarkdownUpdater().add_youtube_video(
            md_file, "https://example.com/not-a-youtube-url", youtube_id="abcdefghijk"
        )
        frontmatter = _frontmatter(md_file)
        assert frontmatter["youtube_id"] == "abcdefghijk"
        assert frontmatter["youtube_video"] == "https://example.com/not-a-youtube-url"

    def test_embed_can_be_disabled(self, md_file):
        HugoMarkdownUpdater().add_youtube_video(md_file, VIDEO_URL, enable_embed=False)
        assert _frontmatter(md_file)["youtube_embed"] is False

    def test_published_date_is_stored_as_iso_day(self, md_file):
        HugoMarkdownUpdater().add_youtube_video(
            md_file, VIDEO_URL, published_date=datetime(2030, 3, 15, 12, 0)
        )
        assert _frontmatter(md_file)["video_published_date"] == "2030-03-15"

    def test_unrecognised_url_without_id_raises_and_leaves_file_alone(self, md_file):
        with pytest.raises(ValueError, match="Could not extract YouTube video ID from"):
            HugoMarkdownUpdater().add_youtube_video(md_file, "https://example.com/video/123")
        assert md_file.read_text(encoding="utf-8") == SAMPLE
        assert not md_file.with_suffix(".md.bak").exists()


class TestAddVideoMetadata:
    def test_maps_every_known_field(self, md_file):
        HugoMarkdownUpdater().add_video_metadata(
            md_file,
            {
                "youtube_url": VIDEO_URL,
                "youtube_id": VIDEO_ID,
                "title": "Ireland in 4K",
                "description": "Two weeks on the road",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hq.jpg",
                "duration_seconds": 754,
                "published_at": datetime(2030, 3, 15, 12, 0),
                "unrelated": "dropped",
            },
        )
        frontmatter = _frontmatter(md_file)
        assert {k: v for k, v in frontmatter.items() if k not in ("title", "draft", "tags")} == {
            "youtube_video": VIDEO_URL,
            "youtube_id": VIDEO_ID,
            "video_title": "Ireland in 4K",
            "video_description": "Two weeks on the road",
            "video_thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hq.jpg",
            "video_duration": 754,
            "video_published_date": "2030-03-15",
            "youtube_embed": True,
        }
        assert frontmatter["title"] == "Ireland Road Trip"

    def test_falsy_and_missing_values_are_skipped(self, md_file):
        HugoMarkdownUpdater().add_video_metadata(
            md_file,
            {"youtube_url": "", "youtube_id": None, "title": "Only a title", "duration_seconds": 0},
        )
        frontmatter = _frontmatter(md_file)
        assert frontmatter["video_title"] == "Only a title"
        for absent in ("youtube_video", "youtube_id", "video_duration", "youtube_embed"):
            assert absent not in frontmatter

    def test_string_published_date_is_kept_as_given(self, md_file):
        HugoMarkdownUpdater().add_video_metadata(md_file, {"published_at": "2030-03-15"})
        assert _frontmatter(md_file)["video_published_date"] == "2030-03-15"

    def test_id_alone_forces_embed_on(self, md_file):
        HugoMarkdownUpdater().add_video_metadata(md_file, {"youtube_id": VIDEO_ID})
        frontmatter = _frontmatter(md_file)
        assert frontmatter["youtube_id"] == VIDEO_ID
        assert frontmatter["youtube_embed"] is True


class TestReadHelpers:
    def test_get_frontmatter_returns_parsed_dict(self, md_file):
        assert HugoMarkdownUpdater().get_frontmatter(md_file) == {
            "title": "Ireland Road Trip",
            "draft": False,
            "tags": ["road", "ireland"],
        }

    def test_has_youtube_video_false_when_absent(self, md_file):
        assert HugoMarkdownUpdater().has_youtube_video(md_file) is False

    @pytest.mark.parametrize(
        "updates",
        [{"youtube_video": VIDEO_URL}, {"youtube_id": VIDEO_ID}],
    )
    def test_has_youtube_video_true_for_either_field(self, md_file, updates):
        updater = HugoMarkdownUpdater()
        updater.update_frontmatter(md_file, updates, create_backup=False)
        assert updater.has_youtube_video(md_file) is True

    def test_has_youtube_video_false_for_empty_values(self, md_file):
        updater = HugoMarkdownUpdater()
        updater.update_frontmatter(
            md_file, {"youtube_video": "", "youtube_id": ""}, create_backup=False
        )
        assert updater.has_youtube_video(md_file) is False


class TestParseMarkdown:
    def test_returns_frontmatter_and_untouched_body(self, md_file):
        frontmatter, body = HugoMarkdownUpdater()._parse_markdown(md_file)
        assert frontmatter == {
            "title": "Ireland Road Trip",
            "draft": False,
            "tags": ["road", "ireland"],
        }
        assert body == SAMPLE_BODY

    def test_missing_opening_delimiter(self, tmp_path):
        path = tmp_path / "plain.md"
        path.write_text("# Just a heading\n", encoding="utf-8")
        with pytest.raises(ValueError, match="File does not start with YAML delimiter"):
            HugoMarkdownUpdater()._parse_markdown(path)

    def test_missing_closing_delimiter(self, tmp_path):
        path = tmp_path / "open.md"
        path.write_text("---\ntitle: never closed\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid Hugo markdown format"):
            HugoMarkdownUpdater()._parse_markdown(path)

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad.md"
        path.write_text("---\nkey: [unclosed\n---\nbody\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid YAML frontmatter"):
            HugoMarkdownUpdater()._parse_markdown(path)

    def test_empty_frontmatter_is_an_empty_dict(self, tmp_path):
        path = tmp_path / "empty.md"
        path.write_text("---\n---\nbody\n", encoding="utf-8")
        assert HugoMarkdownUpdater()._parse_markdown(path) == ({}, "\nbody\n")


class TestWriteMarkdown:
    def test_key_order_block_style_and_unicode(self, tmp_path):
        path = tmp_path / "out.md"
        HugoMarkdownUpdater()._write_markdown(
            path, {"z": "Café", "a": [1, 2], "nested": {"k": "v"}}, "\n\nBody\n"
        )
        assert path.read_text(encoding="utf-8") == (
            "---\nz: Café\na:\n- 1\n- 2\nnested:\n  k: v\n---\n\nBody\n"
        )

    def test_long_values_are_not_folded_before_120_columns(self, tmp_path):
        path = tmp_path / "out.md"
        sentence = " ".join(["word"] * 19)  # 94 characters
        HugoMarkdownUpdater()._write_markdown(path, {"description": sentence}, "\n")
        assert path.read_text(encoding="utf-8") == f"---\ndescription: {sentence}\n---\n"

    def test_temp_file_is_gone_after_success(self, tmp_path):
        path = tmp_path / "out.md"
        HugoMarkdownUpdater()._write_markdown(path, {"a": 1}, "\n")
        assert path.exists()
        assert not path.with_suffix(".md.tmp").exists()

    def test_failed_replace_cleans_up_and_leaves_original(self, md_file, monkeypatch):
        def _boom(self, target):
            raise OSError("disk on fire")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "replace", _boom)
            with pytest.raises(OSError, match="disk on fire"):
                HugoMarkdownUpdater()._write_markdown(md_file, {"title": "New"}, "\n\nNew\n")
        assert md_file.read_text(encoding="utf-8") == SAMPLE
        assert not md_file.with_suffix(".md.tmp").exists()


class TestCreateBackup:
    def test_first_backup_uses_plain_suffix(self, md_file):
        backup = HugoMarkdownUpdater()._create_backup(md_file)
        assert backup == md_file.with_suffix(".md.bak")
        assert backup.read_text(encoding="utf-8") == SAMPLE

    def test_custom_suffix(self, md_file):
        backup = HugoMarkdownUpdater(backup_suffix=".orig")._create_backup(md_file)
        assert backup == md_file.with_suffix(".md.orig")
        assert backup.read_text(encoding="utf-8") == SAMPLE

    def test_existing_backup_is_kept_and_new_one_is_timestamped(self, md_file, monkeypatch):
        older = md_file.with_suffix(".md.bak")
        older.write_text("older backup", encoding="utf-8")
        monkeypatch.setattr(markdown_updater_module, "datetime", _FrozenDatetime)
        backup = HugoMarkdownUpdater()._create_backup(md_file)
        assert backup == md_file.with_suffix(".md.20300315_123456.bak")
        assert backup.read_text(encoding="utf-8") == SAMPLE
        assert older.read_text(encoding="utf-8") == "older backup"


class TestExtractYoutubeId:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?t=42",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
        ],
    )
    def test_supported_forms(self, url):
        assert HugoMarkdownUpdater()._extract_youtube_id(url) == VIDEO_ID

    @pytest.mark.parametrize(
        "url",
        ["https://example.com/video/123", "https://youtu.be/short", ""],
    )
    def test_unsupported_forms_raise(self, url):
        with pytest.raises(ValueError, match="Could not extract YouTube video ID from"):
            HugoMarkdownUpdater()._extract_youtube_id(url)


class TestUpdateJourneyWithYoutube:
    def test_backs_up_by_default(self, md_file):
        result = update_journey_with_youtube(md_file, VIDEO_URL)
        assert result == md_file
        assert md_file.with_suffix(".md.bak").read_text(encoding="utf-8") == SAMPLE
        frontmatter = _frontmatter(md_file)
        assert frontmatter["youtube_video"] == VIDEO_URL
        assert frontmatter["youtube_id"] == VIDEO_ID
        assert frontmatter["youtube_embed"] is True

    def test_backup_can_be_skipped(self, md_file):
        update_journey_with_youtube(md_file, VIDEO_URL, create_backup=False)
        assert not md_file.with_suffix(".md.bak").exists()
        assert _frontmatter(md_file)["youtube_id"] == VIDEO_ID
