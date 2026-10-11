"""Google Photos API client for fetching and downloading photos."""

import logging
import re
from datetime import datetime
from pathlib import Path

import httpx
from googleapiclient.discovery import build

from gps_journey.photos.models import Album, Photo
from gps_journey.photos.oauth import GooglePhotosAuth

logger = logging.getLogger(__name__)


class GooglePhotosClient:
    """Client for interacting with Google Photos API."""

    def __init__(
        self,
        credentials_path: Path = Path("credentials.json"),
        token_path: Path = Path("token.json"),
    ):
        """
        Initialize Google Photos client.

        Args:
            credentials_path: Path to OAuth client credentials
            token_path: Path to OAuth token storage
        """
        self.auth = GooglePhotosAuth(credentials_path, token_path)
        self._service = None

    def authenticate(self) -> None:
        """Authenticate with Google Photos API and build service."""
        creds = self.auth.authenticate()
        self._service = build("photoslibrary", "v1", credentials=creds, static_discovery=False)
        logger.info("Successfully authenticated with Google Photos API")

    def get_album_by_url(self, album_url: str) -> Album:
        """
        Get album metadata from a Google Photos album URL.

        Args:
            album_url: Google Photos album URL (e.g., https://photos.app.goo.gl/xyz123)

        Returns:
            Album object with metadata

        Raises:
            ValueError: If URL format is invalid or album not found
        """
        if not self._service:
            self.authenticate()

        # Check if this is a share link (photos.app.goo.gl)
        is_share_link = "photos.app.goo.gl" in album_url
        album_id = self._extract_album_id(album_url)

        try:
            if is_share_link:
                # For share links, use sharedAlbums endpoint with shareToken parameter
                album = self._service.sharedAlbums().get(shareToken=album_id).execute()
            else:
                # For regular album URLs, use albums endpoint
                album = self._service.albums().get(albumId=album_id).execute()

            return Album(
                id=album["id"],
                title=album.get("title", "Untitled Album"),
                product_url=album.get("productUrl", ""),
                media_items_count=int(album.get("mediaItemsCount", 0)),
                cover_photo_base_url=album.get("coverPhotoBaseUrl"),
            )
        except Exception as e:
            raise ValueError(f"Failed to fetch album: {e}") from e

    def list_albums(self, max_results: int = 50) -> list[Album]:
        """
        List all albums accessible to the user.

        Args:
            max_results: Maximum number of albums to return

        Returns:
            List of Album objects
        """
        if not self._service:
            self.authenticate()

        albums = []
        page_token = None

        while len(albums) < max_results:
            response = (
                self._service.albums()
                .list(pageSize=min(50, max_results - len(albums)), pageToken=page_token)
                .execute()
            )

            for album_data in response.get("albums", []):
                albums.append(
                    Album(
                        id=album_data["id"],
                        title=album_data.get("title", "Untitled"),
                        product_url=album_data.get("productUrl", ""),
                        media_items_count=int(album_data.get("mediaItemsCount", 0)),
                        cover_photo_base_url=album_data.get("coverPhotoBaseUrl"),
                    )
                )

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d albums", len(albums))
        return albums

    def list_photos(self, album_id: str) -> list[Photo]:
        """
        List all photos in an album.

        Args:
            album_id: Album ID from Google Photos

        Returns:
            List of Photo objects
        """
        if not self._service:
            self.authenticate()

        photos = []
        page_token = None

        while True:
            body = {"albumId": album_id, "pageSize": 100}
            if page_token:
                body["pageToken"] = page_token

            response = self._service.mediaItems().search(body=body).execute()

            for item in response.get("mediaItems", []):
                # Only process photos (skip videos for now)
                if item.get("mimeType", "").startswith("image/"):
                    photos.append(self._parse_photo(item))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d photos in album %s", len(photos), album_id)
        return photos

    def list_photos_by_date_range(
        self, start_date: datetime, end_date: datetime, max_results: int = 500
    ) -> list[Photo]:
        """
        List photos from user's library within a date range.

        This method bypasses the deprecated shared albums API by searching
        the user's photo library directly using date filters.

        Args:
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            max_results: Maximum number of photos to return

        Returns:
            List of Photo objects taken within the date range

        Example:
            >>> from datetime import datetime
            >>> client = GooglePhotosClient()
            >>> start = datetime(2030, 1, 5)
            >>> end = datetime(2030, 1, 12)
            >>> photos = client.list_photos_by_date_range(start, end)
            >>> print(f"Found {len(photos)} photos from the trip")
        """
        if not self._service:
            self.authenticate()

        logger.info(f"Searching for photos between {start_date.date()} and {end_date.date()}")

        photos = []
        page_token = None

        while len(photos) < max_results:
            # Build date filter for API
            body = {
                "pageSize": min(100, max_results - len(photos)),
                "filters": {
                    "dateFilter": {
                        "ranges": [
                            {
                                "startDate": {
                                    "year": start_date.year,
                                    "month": start_date.month,
                                    "day": start_date.day,
                                },
                                "endDate": {
                                    "year": end_date.year,
                                    "month": end_date.month,
                                    "day": end_date.day,
                                },
                            }
                        ]
                    },
                    "mediaTypeFilter": {
                        "mediaTypes": ["PHOTO"]  # Exclude videos
                    },
                },
            }

            if page_token:
                body["pageToken"] = page_token

            try:
                response = self._service.mediaItems().search(body=body).execute()

                for item in response.get("mediaItems", []):
                    if item.get("mimeType", "").startswith("image/"):
                        photos.append(self._parse_photo(item))

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            except Exception as e:
                logger.error(f"Error fetching photos: {e}")
                break

        logger.info(f"Found {len(photos)} photos in date range")
        return photos

    def download_photo(self, photo: Photo, output_path: Path, width: int | None = None) -> None:
        """
        Download a photo from Google Photos.

        Args:
            photo: Photo object to download
            output_path: Local path to save photo
            width: Optional width to resize (maintains aspect ratio)
        """
        # Build download URL with optional width parameter
        download_url = photo.base_url + "=d"
        if width:
            download_url = f"{photo.base_url}=w{width}"

        logger.debug("Downloading photo %s to %s", photo.filename, output_path)

        with httpx.Client(timeout=30.0) as client:
            response = client.get(download_url)
            response.raise_for_status()

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)

        logger.debug("Downloaded %s (%d bytes)", photo.filename, len(response.content))

    def _extract_album_id(self, album_url: str) -> str:
        """
        Extract album ID from various Google Photos URL formats.

        Args:
            album_url: Google Photos URL

        Returns:
            Album ID string

        Raises:
            ValueError: If URL format is not recognized
        """
        # Try to extract from share link format
        # Example: https://photos.app.goo.gl/xyz123
        match = re.search(r"photos\.app\.goo\.gl/([a-zA-Z0-9]+)", album_url)
        if match:
            # For share links, we need to resolve them first
            # For now, we'll try to use the share token directly
            # This may need enhancement based on actual API behavior
            return match.group(1)

        # Try to extract from direct album URL
        # Example: https://photos.google.com/album/AF1QipNxxxxx
        match = re.search(r"/album/([a-zA-Z0-9_-]+)", album_url)
        if match:
            return match.group(1)

        # If URL looks like an ID itself
        if re.match(r"^[a-zA-Z0-9_-]+$", album_url):
            return album_url

        raise ValueError(
            f"Could not extract album ID from URL: {album_url}. "
            "Please use a Google Photos album URL or album ID."
        )

    def _parse_photo(self, item: dict) -> Photo:
        """
        Parse Google Photos API media item into Photo object.

        Args:
            item: Media item dict from API

        Returns:
            Photo object
        """
        metadata = item.get("mediaMetadata", {})
        creation_time_str = metadata.get("creationTime", "")

        # Parse ISO 8601 timestamp
        try:
            creation_time = datetime.fromisoformat(creation_time_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            creation_time = datetime.now()

        return Photo(
            id=item["id"],
            filename=item.get("filename", "unknown.jpg"),
            base_url=item["baseUrl"],
            creation_time=creation_time,
            width=int(metadata.get("width", 0)),
            height=int(metadata.get("height", 0)),
            mime_type=item.get("mimeType", "image/jpeg"),
        )
