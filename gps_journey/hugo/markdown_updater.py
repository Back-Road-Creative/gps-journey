"""Hugo Markdown Updater for journey files.

Safely updates Hugo markdown frontmatter while preserving content.
Used to add YouTube video links after publishing.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class HugoMarkdownUpdater:
    """
    Update Hugo markdown files while preserving formatting.

    Handles:
    - YAML frontmatter parsing/writing
    - Content preservation
    - Atomic file updates (write to temp, then rename)
    - Backup creation
    """

    def __init__(self, create_backups: bool = True, backup_suffix: str = ".bak"):
        """
        Initialize updater.

        Args:
            create_backups: Whether to create backup files before updating.
            backup_suffix: Suffix for backup files.
        """
        self.create_backups = create_backups
        self.backup_suffix = backup_suffix

    def update_frontmatter(
        self, md_file: Path, updates: dict[str, Any], create_backup: bool | None = None
    ) -> Path:
        """
        Update frontmatter fields in Hugo markdown file.

        Args:
            md_file: Path to markdown file.
            updates: Dict of fields to update/add.
            create_backup: Override default backup setting.

        Returns:
            Path to updated file.

        Raises:
            ValueError: If file is not valid Hugo markdown.
            FileNotFoundError: If file doesn't exist.
        """
        md_file = Path(md_file)

        if not md_file.exists():
            raise FileNotFoundError(f"Markdown file not found: {md_file}")

        # Read and parse file
        frontmatter, body = self._parse_markdown(md_file)

        # Apply updates
        for key, value in updates.items():
            frontmatter[key] = value

        # Create backup if requested
        should_backup = create_backup if create_backup is not None else self.create_backups
        if should_backup:
            backup_path = self._create_backup(md_file)
            logger.info(f"Created backup: {backup_path}")

        # Write updated file atomically
        self._write_markdown(md_file, frontmatter, body)

        logger.info(f"Updated frontmatter in {md_file.name}")
        logger.debug(f"Updated fields: {list(updates.keys())}")

        return md_file

    def add_youtube_video(
        self,
        md_file: Path,
        youtube_url: str,
        youtube_id: str | None = None,
        enable_embed: bool = True,
        published_date: datetime | None = None,
    ) -> Path:
        """
        Add YouTube video information to journey markdown.

        Args:
            md_file: Path to journey markdown file.
            youtube_url: Full YouTube video URL.
            youtube_id: Video ID (extracted from URL if not provided).
            enable_embed: Whether to enable video embedding on page.
            published_date: When video was published.

        Returns:
            Path to updated file.
        """
        # Extract video ID if not provided
        if not youtube_id:
            youtube_id = self._extract_youtube_id(youtube_url)

        updates = {
            "youtube_video": youtube_url,
            "youtube_id": youtube_id,
            "youtube_embed": enable_embed,
        }

        if published_date:
            updates["video_published_date"] = published_date.strftime("%Y-%m-%d")

        return self.update_frontmatter(md_file, updates)

    def add_video_metadata(self, md_file: Path, video_data: dict[str, Any]) -> Path:
        """
        Add comprehensive video metadata to journey.

        Args:
            md_file: Path to journey markdown file.
            video_data: Dict containing video information:
                - youtube_url: Full video URL
                - youtube_id: Video ID
                - title: Video title
                - description: Video description
                - thumbnail_url: Thumbnail URL
                - duration_seconds: Video length
                - published_at: Publication datetime

        Returns:
            Path to updated file.
        """
        updates = {}

        # Map video data to frontmatter fields
        field_mapping = {
            "youtube_url": "youtube_video",
            "youtube_id": "youtube_id",
            "title": "video_title",
            "description": "video_description",
            "thumbnail_url": "video_thumbnail",
            "duration_seconds": "video_duration",
            "published_at": "video_published_date",
        }

        for source_key, target_key in field_mapping.items():
            if video_data.get(source_key):
                value = video_data[source_key]

                # Convert datetime to string
                if isinstance(value, datetime):
                    value = value.strftime("%Y-%m-%d")

                updates[target_key] = value

        # Always enable embed if we have a video
        if "youtube_video" in updates or "youtube_id" in updates:
            updates["youtube_embed"] = True

        return self.update_frontmatter(md_file, updates)

    def get_frontmatter(self, md_file: Path) -> dict[str, Any]:
        """
        Read frontmatter from markdown file.

        Args:
            md_file: Path to markdown file.

        Returns:
            Dict of frontmatter data.
        """
        frontmatter, _ = self._parse_markdown(md_file)
        return frontmatter

    def has_youtube_video(self, md_file: Path) -> bool:
        """
        Check if journey already has YouTube video linked.

        Args:
            md_file: Path to markdown file.

        Returns:
            True if youtube_video or youtube_id exists in frontmatter.
        """
        frontmatter = self.get_frontmatter(md_file)
        return bool(frontmatter.get("youtube_video") or frontmatter.get("youtube_id"))

    def _parse_markdown(self, md_file: Path) -> tuple[dict[str, Any], str]:
        """
        Parse Hugo markdown into frontmatter and body.

        Args:
            md_file: Path to markdown file.

        Returns:
            Tuple of (frontmatter dict, body string).

        Raises:
            ValueError: If file is not valid Hugo markdown.
        """
        content = md_file.read_text(encoding="utf-8")

        # Split by YAML delimiters
        if not content.startswith("---"):
            raise ValueError(f"File does not start with YAML delimiter: {md_file}")

        parts = content.split("---", 2)

        if len(parts) < 3:
            raise ValueError(f"Invalid Hugo markdown format: {md_file}")

        frontmatter_text = parts[1].strip()
        body = parts[2]

        try:
            frontmatter = yaml.safe_load(frontmatter_text) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML frontmatter: {e}") from e

        return frontmatter, body

    def _write_markdown(self, md_file: Path, frontmatter: dict[str, Any], body: str) -> None:
        """
        Write markdown file with frontmatter atomically.

        Uses temp file + rename for atomic operation.

        Args:
            md_file: Path to markdown file.
            frontmatter: Frontmatter dict.
            body: Body content string.
        """
        # Serialize frontmatter
        # Use default_flow_style=False for readable output
        # allow_unicode=True for proper character handling
        # sort_keys=False to preserve order
        yaml_content = yaml.dump(
            frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120
        )

        # Reconstruct file
        updated_content = f"---\n{yaml_content}---{body}"

        # Write to temp file first
        temp_file = md_file.with_suffix(".md.tmp")

        try:
            temp_file.write_text(updated_content, encoding="utf-8")

            # Atomic rename
            temp_file.replace(md_file)

        except Exception:
            # Clean up temp file on failure
            if temp_file.exists():
                temp_file.unlink()
            raise

    def _create_backup(self, md_file: Path) -> Path:
        """
        Create backup of markdown file.

        Args:
            md_file: Path to file to backup.

        Returns:
            Path to backup file.
        """
        backup_path = md_file.with_suffix(f".md{self.backup_suffix}")

        # Add timestamp if backup already exists
        if backup_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = md_file.with_suffix(f".md.{timestamp}{self.backup_suffix}")

        shutil.copy2(md_file, backup_path)
        return backup_path

    def _extract_youtube_id(self, url: str) -> str:
        """
        Extract video ID from YouTube URL.

        Supports:
        - https://youtube.com/watch?v=ID
        - https://youtu.be/ID
        - https://www.youtube.com/embed/ID

        Args:
            url: YouTube URL.

        Returns:
            Video ID string.

        Raises:
            ValueError: If ID cannot be extracted.
        """
        import re

        patterns = [
            r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
            r"[?&]v=([a-zA-Z0-9_-]{11})",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        raise ValueError(f"Could not extract YouTube video ID from: {url}")


def update_journey_with_youtube(
    journey_md: Path, youtube_url: str, create_backup: bool = True
) -> Path:
    """
    Convenience function to add YouTube video to journey.

    Args:
        journey_md: Path to journey markdown file.
        youtube_url: YouTube video URL.
        create_backup: Whether to backup original file.

    Returns:
        Path to updated file.
    """
    updater = HugoMarkdownUpdater(create_backups=create_backup)
    return updater.add_youtube_video(journey_md, youtube_url)
