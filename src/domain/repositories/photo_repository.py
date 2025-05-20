from abc import ABC, abstractmethod
from typing import List, Optional, UUID
from src.domain.models.photo import Photo

class PhotoRepository(ABC):
    """
    Abstract base class defining the contract for photo repository operations.
    Follows dependency inversion principle.
    """
    
    @abstractmethod
    def save(self, photo: Photo) -> Photo:
        """
        Save a new photo to the repository.
        
        Args:
            photo (Photo): The photo to be saved
        
        Returns:
            Photo: The saved photo with potential modifications
        """
        pass

    @abstractmethod
    def find_by_id(self, photo_id: UUID) -> Optional[Photo]:
        """
        Retrieve a photo by its unique identifier.
        
        Args:
            photo_id (UUID): Unique identifier of the photo
        
        Returns:
            Optional[Photo]: The found photo or None
        """
        pass

    @abstractmethod
    def find_by_tag(self, tag: str) -> List[Photo]:
        """
        Find photos matching a specific tag.
        
        Args:
            tag (str): Tag to search for
        
        Returns:
            List[Photo]: List of photos with the specified tag
        """
        pass

    @abstractmethod
    def delete(self, photo_id: UUID) -> bool:
        """
        Delete a photo from the repository.
        
        Args:
            photo_id (UUID): Unique identifier of the photo to delete
        
        Returns:
            bool: Whether deletion was successful
        """
        pass