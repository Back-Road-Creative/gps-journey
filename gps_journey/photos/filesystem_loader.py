"""Load photos from filesystem and extract EXIF data."""

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS

from gps_journey.core.models import Photo

logger = logging.getLogger(__name__)


class FilesystemPhotoLoader:
    """Load photos from local filesystem using PIL for EXIF extraction."""

    def load_photos_from_directory(self, photos_dir: Path) -> list[Photo]:
        """
        Load all photos from a directory and extract EXIF data.

        Args:
            photos_dir: Path to directory containing photos

        Returns:
            List of Photo objects with EXIF metadata
        """
        photos_dir = Path(photos_dir)
        if not photos_dir.exists():
            logger.warning(f"Photos directory does not exist: {photos_dir}")
            return []

        # Find all image files
        image_extensions = {".jpg", ".jpeg", ".png", ".heic"}
        photo_files = []
        for ext in image_extensions:
            photo_files.extend(photos_dir.glob(f"*{ext}"))
            photo_files.extend(photos_dir.glob(f"*{ext.upper()}"))

        logger.info(f"Found {len(photo_files)} photos in {photos_dir}")

        photos = []
        for photo_file in photo_files:
            try:
                # Extract EXIF data directly with PIL
                with Image.open(photo_file) as img:
                    exif_data = img.getexif()

                    if not exif_data:
                        logger.debug(f"No EXIF data in {photo_file.name}, skipping")
                        continue

                    # Extract timestamp (try DateTimeOriginal first, then DateTime)
                    timestamp = None
                    timestamp_str = exif_data.get(36867) or exif_data.get(
                        306
                    )  # DateTimeOriginal or DateTime

                    if timestamp_str:
                        try:
                            timestamp = datetime.strptime(timestamp_str, "%Y:%m:%d %H:%M:%S")
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Failed to parse timestamp for {photo_file.name}: {e}")

                    if not timestamp:
                        logger.debug(f"No EXIF timestamp for {photo_file.name}, skipping")
                        continue

                    # Extract GPS coordinates (if available)
                    gps_lat = None
                    gps_lon = None
                    gps_info = exif_data.get_ifd(0x8825)  # GPS IFD
                    if gps_info:  # noqa: SIM102
                        # GPS coordinates need conversion from DMS to decimal
                        # For simplicity, just check if they exist
                        if 2 in gps_info and 4 in gps_info:  # GPSLatitude and GPSLongitude tags
                            try:
                                lat_dms = gps_info.get(2)
                                lon_dms = gps_info.get(4)
                                lat_ref = gps_info.get(1, "N")
                                lon_ref = gps_info.get(3, "E")

                                if lat_dms and lon_dms:
                                    gps_lat = self._dms_to_decimal(lat_dms, lat_ref)
                                    gps_lon = self._dms_to_decimal(lon_dms, lon_ref)
                            except Exception:
                                pass

                    # Extract camera make
                    camera = None
                    for tag_id in exif_data:
                        tag = TAGS.get(tag_id, tag_id)
                        if tag == "Make":
                            camera = exif_data.get(tag_id)
                            break

                    # Create Photo object
                    photo = Photo(
                        filename=photo_file.name,
                        timestamp=timestamp,
                        latitude=gps_lat,
                        longitude=gps_lon,
                        camera=camera,
                    )
                    photos.append(photo)

            except Exception as e:
                logger.debug(f"Failed to load {photo_file.name}: {e}")
                continue

        logger.info(f"Loaded {len(photos)} photos with EXIF data")
        return photos

    def _dms_to_decimal(self, dms: tuple, ref: str) -> float:
        """Convert GPS DMS (degrees, minutes, seconds) to decimal degrees."""
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])

        decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)

        if ref in ("S", "W"):
            decimal = -decimal

        return decimal
