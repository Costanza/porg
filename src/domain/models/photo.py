from dataclasses import dataclass
from datetime import datetime
from typing import Optional, UUID

@dataclass
class Photo:
    """
    Domain model representing a photo entity.
    Follows clean architecture principles with immutable data representation.
    """
    id: UUID
    file_path: str
    capture_timestamp: datetime
    camera_model: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    tags: list[str] = None

    def __post_init__(self):
        """
        Validate photo attributes after initialization.
        """
        if not self.file_path:
            raise ValueError("Photo must have a valid file path")
        
        if self.tags is None:
            self.tags = []