"""Timeline building and event management."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EventType(Enum):
    """Types of timeline events."""

    WAYPOINT = "waypoint"
    PHOTO = "photo"
    STOP = "stop"
    LANDMARK = "landmark"


@dataclass
class TimelineEvent:
    """A single event in the journey timeline."""

    timestamp: datetime
    event_type: EventType
    latitude: float
    longitude: float
    data: dict | None = None  # Event-specific data


class Timeline:
    """
    Chronological timeline of journey events.

    Merges GPS points, photos, and detected events into a single timeline.
    """

    def __init__(self):
        """Initialize empty timeline."""
        self.events: list[TimelineEvent] = []

    def add_event(self, event: TimelineEvent) -> None:
        """Add an event to the timeline."""
        self.events.append(event)
        self.events.sort(key=lambda e: e.timestamp)

    def get_events_between(self, start: datetime, end: datetime) -> list[TimelineEvent]:
        """Get events within a time range."""
        return [e for e in self.events if start <= e.timestamp <= end]
