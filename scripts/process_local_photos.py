#!/usr/bin/env python3
"""
Process photos from a local directory instead of Google Photos API.

This script:
1. Reads photos from a local folder
2. Extracts EXIF GPS coordinates and timestamps
3. Optimizes for web (resize, compress)
4. Generates thumbnails
5. Matches to GPS timeline
6. Generates Hugo gallery metadata
7. Saves to Hugo static directory

Usage:
    python scripts/process_local_photos.py \
        --photos-dir "path/to/photos" \
        --gpx "path/to/track.gpx" \
        --slug "sample-trip-2030-01" \
        --hugo-static-dir "path/to/site/static" \
        --output "path/to/site/content/journeys/sample-trip-2030-01.md"
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gps_journey.core.gpx_parser import GPXParser
from gps_journey.photos.exif import EXIFExtractor
from gps_journey.photos.matcher import PhotoMatcher
from gps_journey.photos.models import Photo
from gps_journey.photos.optimizer import PhotoOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Process local photos for a journey")
    parser.add_argument(
        "--photos-dir",
        type=Path,
        required=True,
        help="Directory containing photos to process",
    )
    parser.add_argument(
        "--gpx",
        type=Path,
        required=True,
        help="Path to GPX file for GPS matching",
    )
    parser.add_argument(
        "--slug",
        type=str,
        required=True,
        help="Journey slug",
    )
    parser.add_argument(
        "--hugo-static-dir",
        type=Path,
        default=Path("./output/static"),
        help="Hugo static directory (default: ./output/static)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path to append gallery metadata (optional)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.photos_dir.exists():
        logger.error(f"Photos directory not found: {args.photos_dir}")
        sys.exit(1)

    # Find all image files
    image_extensions = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
    photo_files = []
    for ext in image_extensions:
        photo_files.extend(args.photos_dir.glob(f"*{ext}"))
        photo_files.extend(args.photos_dir.glob(f"*{ext.upper()}"))

    photo_files = sorted(set(photo_files))
    logger.info(f"Found {len(photo_files)} photos in {args.photos_dir}")

    if not photo_files:
        logger.error("No photos found!")
        sys.exit(1)

    # Parse GPX for timeline
    logger.info(f"Parsing GPX: {args.gpx}")
    parser = GPXParser()
    journey = parser.parse(str(args.gpx))
    timeline = [
        (wp.timestamp, wp.latitude, wp.longitude) for wp in journey.waypoints if wp.timestamp
    ]
    timeline = sorted(timeline, key=lambda x: x[0])
    logger.info(f"GPS timeline: {len(timeline)} waypoints")

    # Initialize processors
    exif_extractor = EXIFExtractor()
    optimizer = PhotoOptimizer()
    matcher = PhotoMatcher(tolerance_minutes=5)

    # Create output directories
    photos_dir = args.hugo_static_dir / "images" / "journeys" / args.slug
    photos_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir = photos_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    # Process each photo
    photos = []
    photo_metadata_list = []

    for idx, photo_path in enumerate(photo_files, start=1):
        try:
            logger.info(f"Processing {idx}/{len(photo_files)}: {photo_path.name}")

            # Extract EXIF
            metadata = exif_extractor.extract(photo_path, photo_path.stem)
            photo_metadata_list.append(metadata)

            # Optimize
            optimized_path = photos_dir / f"photo-{idx:03d}.jpg"
            optimizer.optimize_for_web(photo_path, optimized_path)

            # Generate thumbnail
            thumb_path = thumbs_dir / f"thumb-{idx:03d}.jpg"
            optimizer.generate_thumbnail(optimized_path, thumb_path)

            # Create Photo object (mock for matcher compatibility)
            photo = Photo(
                id=photo_path.stem,
                filename=photo_path.name,
                base_url="",
                creation_time=metadata.timestamp or datetime.now(),
                width=0,
                height=0,
                mime_type="image/jpeg",
            )
            photos.append(photo)

            logger.info(f"  ✓ Saved: {optimized_path.name}")

        except Exception as e:
            logger.error(f"  ✗ Failed: {e}")
            continue

    # Match photos to GPS timeline
    logger.info("Matching photos to GPS timeline...")
    matched_photos = matcher.match_photos_to_timeline(photos, photo_metadata_list, timeline)

    # Generate gallery metadata
    gallery = matcher.generate_gallery_metadata(
        matched_photos,
        base_path="images/journeys",
        journey_slug=args.slug,
    )

    logger.info(f"\n{'=' * 60}")
    logger.info("✅ Processing complete!")
    logger.info(f"{'=' * 60}")
    logger.info(f"Total photos: {len(photos)}")
    logger.info(f"Matched to GPS: {len(matched_photos)}")
    logger.info(f"Match rate: {len(matched_photos) / len(photos) * 100:.1f}%")
    logger.info(f"\nPhotos saved to: {photos_dir}")
    logger.info(f"Thumbnails: {thumbs_dir}")

    # Print gallery YAML for manual addition
    if gallery:
        print(f"\n{'=' * 60}")
        print("Add this to your journey frontmatter:")
        print(f"{'=' * 60}\n")
        print("gallery:")
        for item in gallery[:5]:  # Show first 5
            print(f"  - path: {item['path']}")
            print(f"    thumb: {item['thumb']}")
            if item.get("location"):
                print(f"    location: {item['location']}")
            if item.get("timestamp"):
                print(f"    timestamp: {item['timestamp']}")
        if len(gallery) > 5:
            print(f"  # ... and {len(gallery) - 5} more photos")

    # Optionally update journey file
    if args.output and args.output.exists():
        logger.info(f"\nNote: To add gallery to {args.output}, update the frontmatter manually")


if __name__ == "__main__":
    main()
