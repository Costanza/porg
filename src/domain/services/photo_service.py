import uuid
from datetime import datetime
from typing import List, Optional

from src.domain.models.photo import Photo
from src.domain.repositories.photo_repository import PhotoRepository

class PhotoService:
    """
    Application service for managing photo-related business logic.
    Coordinates between domain models and repository.
    """
    
    def __init__(self, photo_repository: PhotoRepository):
        """
        Initialize photo service with a repository.
        
        Args:
            photo_repository (PhotoRepository): Repository for photo operations
        """
        self._repository = photo_repository

    def capture_photo(
        self, 
        file_path: str, 
        camera_model: Optional[str] = None, 
        tags: Optional[List[str]] = None
    ) -> Photo:
        """
        Create and save a new photo entry.
        
        Args:
            file_path (str): Path to the photo file
            camera_model (Optional[str]): Camera that captured the photo
            tags (Optional[List[str]]): Optional tags for the photo
        
        Returns:
            Photo: The newly created and saved photo
        """
        new_photo = Photo(
            id=uuid.uuid4(),
            file_path=file_path,
            capture_timestamp=datetime.now(),
            camera_model=camera_model,
            tags=tags or []
        )
        
        return self._repository.save(new_photo)

    def add_photo_tags(self, photo_id: uuid.UUID, tags: List[str]) -> Optional[Photo]:
        """
        Add tags to an existing photo.
        
        Args:
            photo_id (UUID): ID of the photo to tag
            tags (List[str]): Tags to add
        
        Returns:
            Optional[Photo]: Updated photo or None if not found
        """
        photo = self._repository.find_by_id(photo_id)
        
        if not photo:
            return None
        
        unique_tags = set(photo.tags + tags)
        photo.tags = list(unique_tags)
        
        return self._repository.save(photo)