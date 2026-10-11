"""Photo optimization for web delivery."""

import logging
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Try to import piexif for EXIF preservation
try:
    import piexif

    HAS_PIEXIF = True
except ImportError:
    HAS_PIEXIF = False
    logger.debug("piexif not available - EXIF preservation will use PIL fallback")


class PhotoOptimizer:
    """Optimize photos for web delivery."""

    def __init__(
        self,
        max_width: int = 1920,
        quality: int = 85,
        thumbnail_width: int = 400,
        thumbnail_quality: int = 80,
    ):
        """
        Initialize photo optimizer.

        Args:
            max_width: Maximum width for full-size photos (default: 1920px)
            quality: JPEG quality for full-size photos (default: 85%)
            thumbnail_width: Width for thumbnail generation (default: 400px)
            thumbnail_quality: JPEG quality for thumbnails (default: 80%)
        """
        self.max_width = max_width
        self.quality = quality
        self.thumbnail_width = thumbnail_width
        self.thumbnail_quality = thumbnail_quality

    def optimize_for_web(
        self,
        input_path: Path,
        output_path: Path,
        max_width: int | None = None,
        quality: int | None = None,
        preserve_exif: bool = True,
    ) -> tuple[int, int]:
        """
        Optimize photo for web delivery.

        - Resize to maximum width (maintaining aspect ratio)
        - Compress to specified JPEG quality
        - Preserve important EXIF data (DateTimeOriginal, GPS, camera info)
        - Convert to RGB color space if needed

        Args:
            input_path: Path to original photo
            output_path: Path to save optimized photo
            max_width: Override default max width
            quality: Override default quality
            preserve_exif: Keep EXIF metadata (default: True)

        Returns:
            Tuple of (final_width, final_height)
        """
        max_width = max_width or self.max_width
        quality = quality or self.quality

        try:
            with Image.open(input_path) as img:
                # Extract EXIF before any transformations
                exif_bytes = None
                if preserve_exif and HAS_PIEXIF:
                    try:
                        exif_dict = piexif.load(img.info.get("exif", b""))
                        # Update dimensions in EXIF after resize (done later)
                        exif_bytes = piexif.dump(exif_dict)
                    except Exception as e:
                        logger.debug("Could not extract EXIF with piexif: %s", e)
                elif preserve_exif:
                    # Fallback: try to get raw EXIF bytes from PIL
                    exif_bytes = img.info.get("exif")

                # Apply EXIF orientation to get correct rotation
                img = ImageOps.exif_transpose(img)

                # Convert to RGB if needed (handles RGBA, P, etc.)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

                original_size = img.size
                new_size = self._calculate_resize(img.size, max_width)

                # Only resize if image is larger than target
                if new_size != original_size:
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    logger.debug(
                        "Resized %s from %dx%d to %dx%d",
                        input_path.name,
                        original_size[0],
                        original_size[1],
                        new_size[0],
                        new_size[1],
                    )

                # Save with optimization, preserving EXIF if available
                output_path.parent.mkdir(parents=True, exist_ok=True)

                save_kwargs = {
                    "format": "JPEG",
                    "quality": quality,
                    "optimize": True,
                    "progressive": True,
                }

                if exif_bytes and preserve_exif:
                    save_kwargs["exif"] = exif_bytes

                img.save(output_path, **save_kwargs)

                file_size = output_path.stat().st_size
                logger.debug(
                    "Optimized %s: %dx%d, %.1f KB, EXIF=%s",
                    output_path.name,
                    new_size[0],
                    new_size[1],
                    file_size / 1024,
                    "preserved" if exif_bytes else "none",
                )

                return new_size

        except Exception as e:
            logger.error("Failed to optimize %s: %s", input_path, e)
            raise

    def generate_thumbnail(
        self,
        input_path: Path,
        output_path: Path,
        width: int | None = None,
        quality: int | None = None,
    ) -> tuple[int, int]:
        """
        Generate a thumbnail for gallery display.

        Args:
            input_path: Path to original or optimized photo
            output_path: Path to save thumbnail
            width: Override default thumbnail width
            quality: Override default thumbnail quality

        Returns:
            Tuple of (thumbnail_width, thumbnail_height)
        """
        width = width or self.thumbnail_width
        quality = quality or self.thumbnail_quality

        try:
            with Image.open(input_path) as img:
                # Apply EXIF orientation to get correct rotation
                img = ImageOps.exif_transpose(img)

                # Convert to RGB if needed
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

                new_size = self._calculate_resize(img.size, width)

                # Resize
                img = img.resize(new_size, Image.Resampling.LANCZOS)

                # Save
                output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(
                    output_path,
                    "JPEG",
                    quality=quality,
                    optimize=True,
                )

                file_size = output_path.stat().st_size
                logger.debug(
                    "Generated thumbnail %s: %dx%d, %.1f KB",
                    output_path.name,
                    new_size[0],
                    new_size[1],
                    file_size / 1024,
                )

                return new_size

        except Exception as e:
            logger.error("Failed to generate thumbnail for %s: %s", input_path, e)
            raise

    def _calculate_resize(self, original_size: tuple[int, int], max_width: int) -> tuple[int, int]:
        """
        Calculate new dimensions maintaining aspect ratio.

        Args:
            original_size: (width, height) of original image
            max_width: Maximum width constraint

        Returns:
            Tuple of (new_width, new_height)
        """
        width, height = original_size

        # If image is already smaller than max, keep original size
        if width <= max_width:
            return original_size

        # Calculate new height maintaining aspect ratio
        aspect_ratio = height / width
        new_width = max_width
        new_height = int(new_width * aspect_ratio)

        return (new_width, new_height)

    def batch_optimize(
        self,
        input_dir: Path,
        output_dir: Path,
        create_thumbnails: bool = True,
        thumbnail_dir: Path | None = None,
    ) -> int:
        """
        Batch optimize all photos in a directory.

        Args:
            input_dir: Directory containing original photos
            output_dir: Directory to save optimized photos
            create_thumbnails: Whether to also generate thumbnails
            thumbnail_dir: Directory for thumbnails (defaults to output_dir/thumbs)

        Returns:
            Number of photos processed
        """
        if not input_dir.is_dir():
            raise ValueError(f"Input directory does not exist: {input_dir}")

        output_dir.mkdir(parents=True, exist_ok=True)

        if create_thumbnails:
            thumbnail_dir = thumbnail_dir or (output_dir / "thumbs")
            thumbnail_dir.mkdir(parents=True, exist_ok=True)

        # Process all image files
        image_extensions = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
        photo_files = [f for f in input_dir.iterdir() if f.suffix.lower() in image_extensions]

        count = 0
        for photo_file in photo_files:
            try:
                # Optimize full size
                output_file = output_dir / f"{photo_file.stem}.jpg"
                self.optimize_for_web(photo_file, output_file)

                # Generate thumbnail
                if create_thumbnails:
                    thumb_file = thumbnail_dir / f"thumb-{photo_file.stem}.jpg"
                    self.generate_thumbnail(output_file, thumb_file)

                count += 1

            except Exception as e:
                logger.error("Failed to process %s: %s", photo_file, e)
                continue

        logger.info("Batch optimized %d photos", count)
        return count
