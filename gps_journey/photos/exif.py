"""EXIF metadata extraction from photos."""

import contextlib
import logging
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

from gps_journey.photos.models import PhotoMetadata

logger = logging.getLogger(__name__)


class EXIFExtractor:
    """Extract EXIF metadata from photo files."""

    def extract(self, photo_path: Path, photo_id: str) -> PhotoMetadata:
        """
        Extract all relevant EXIF metadata from a photo.

        Args:
            photo_path: Path to photo file
            photo_id: Photo ID for reference

        Returns:
            PhotoMetadata object with extracted data
        """
        try:
            with Image.open(photo_path) as img:
                exif_data = img.getexif()

                if not exif_data:
                    logger.debug("No EXIF data found in %s", photo_path)
                    return PhotoMetadata(photo_id=photo_id)

                # Extract GPS coordinates
                gps_lat, gps_lon = self._extract_gps(exif_data)

                # Extract timestamp
                timestamp = self._extract_timestamp(exif_data)

                # Extract camera info
                camera_info = self._extract_camera_info(exif_data)

                return PhotoMetadata(
                    photo_id=photo_id,
                    gps_latitude=gps_lat,
                    gps_longitude=gps_lon,
                    timestamp=timestamp,
                    **camera_info,
                )

        except Exception as e:
            logger.warning("Failed to extract EXIF from %s: %s", photo_path, e)
            return PhotoMetadata(photo_id=photo_id)

    def _extract_gps(self, exif_data: dict) -> tuple[float | None, float | None]:
        """
        Extract GPS coordinates from EXIF data.

        Args:
            exif_data: EXIF data dictionary

        Returns:
            Tuple of (latitude, longitude) or (None, None)
        """
        gps_info = {}

        # Find GPS IFD tag
        for tag, value in exif_data.items():
            tag_name = TAGS.get(tag, tag)
            if tag_name == "GPSInfo":
                # Parse GPS tags - value should be a dict-like object
                if hasattr(value, "items"):
                    for gps_tag, gps_value in value.items():
                        gps_tag_name = GPSTAGS.get(gps_tag, gps_tag)
                        gps_info[gps_tag_name] = gps_value
                else:
                    logger.debug(
                        "GPSInfo value is not dict-like: %s (type: %s)", value, type(value)
                    )
                break

        if not gps_info:
            return None, None

        try:
            # Extract latitude
            lat = self._convert_to_degrees(gps_info.get("GPSLatitude"))
            lat_ref = gps_info.get("GPSLatitudeRef")
            if lat and lat_ref == "S":
                lat = -lat

            # Extract longitude
            lon = self._convert_to_degrees(gps_info.get("GPSLongitude"))
            lon_ref = gps_info.get("GPSLongitudeRef")
            if lon and lon_ref == "W":
                lon = -lon

            if lat is not None and lon is not None:
                logger.debug("Extracted GPS: %.6f, %.6f", lat, lon)
                return lat, lon

        except Exception as e:
            logger.debug("Failed to parse GPS coordinates: %s", e)

        return None, None

    def _convert_to_degrees(self, value: tuple | None) -> float | None:
        """
        Convert GPS coordinates from EXIF format to decimal degrees.

        EXIF GPS coordinates are stored as (degrees, minutes, seconds).

        Args:
            value: Tuple of (degrees, minutes, seconds)

        Returns:
            Decimal degrees or None
        """
        if not value or len(value) != 3:
            return None

        try:
            degrees = float(value[0])
            minutes = float(value[1])
            seconds = float(value[2])

            return degrees + (minutes / 60.0) + (seconds / 3600.0)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def _extract_timestamp(self, exif_data: dict) -> datetime | None:
        """
        Extract photo timestamp from EXIF data.

        Tries DateTimeOriginal first (when photo was taken),
        then falls back to DateTime (when photo was modified).

        Args:
            exif_data: EXIF data dictionary

        Returns:
            datetime object or None
        """
        # Try DateTimeOriginal first (most accurate for "when taken")
        for tag_id, tag_name in [
            (36867, "DateTimeOriginal"),
            (36868, "DateTimeDigitized"),
            (306, "DateTime"),
        ]:
            if tag_id in exif_data:
                try:
                    timestamp_str = exif_data[tag_id]
                    # Ensure it's a string
                    if not isinstance(timestamp_str, str):
                        logger.debug(
                            "%s value is not a string: %s (type: %s)",
                            tag_name,
                            timestamp_str,
                            type(timestamp_str),
                        )
                        continue
                    # EXIF datetime format: "YYYY:MM:DD HH:MM:SS"
                    timestamp = datetime.strptime(timestamp_str, "%Y:%m:%d %H:%M:%S")
                    logger.debug("Extracted timestamp from %s: %s", tag_name, timestamp)
                    return timestamp
                except (ValueError, TypeError) as e:
                    logger.debug("Failed to parse timestamp from %s: %s", tag_name, e)
                    continue

        return None

    def _extract_camera_info(self, exif_data: dict) -> dict:
        """
        Extract camera and photo settings from EXIF data.

        Args:
            exif_data: EXIF data dictionary

        Returns:
            Dictionary with camera info fields
        """
        info = {}

        # Camera make and model
        if 271 in exif_data:  # Make
            make = exif_data[271]
            if isinstance(make, str):
                info["camera_make"] = make.strip()
        if 272 in exif_data:  # Model
            model = exif_data[272]
            if isinstance(model, str):
                info["camera_model"] = model.strip()

        # ISO
        if 34855 in exif_data:  # ISOSpeedRatings
            with contextlib.suppress(ValueError, TypeError):
                info["iso"] = int(exif_data[34855])

        # Aperture (F-number)
        if 33437 in exif_data:  # FNumber
            try:
                f_number = exif_data[33437]
                if isinstance(f_number, tuple) and len(f_number) == 2:
                    info["aperture"] = float(f_number[0]) / float(f_number[1])
                else:
                    info["aperture"] = float(f_number)
            except (ValueError, TypeError, ZeroDivisionError):
                pass

        # Shutter speed (exposure time)
        if 33434 in exif_data:  # ExposureTime
            try:
                exposure = exif_data[33434]
                if isinstance(exposure, tuple) and len(exposure) == 2:
                    num, denom = exposure
                    if num == 1:
                        info["shutter_speed"] = f"1/{denom}"
                    else:
                        info["shutter_speed"] = f"{num}/{denom}"
                else:
                    info["shutter_speed"] = str(exposure)
            except (ValueError, TypeError):
                pass

        return info
