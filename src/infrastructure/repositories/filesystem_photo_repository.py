import os
import uuid
import re
import shutil
from datetime import datetime
from typing import List, Optional, Set, Dict, Tuple

import exif
from PIL import Image

from src.domain.models.photo import Photo
from src.domain.repositories.photo_repository import PhotoRepository

class FilesystemPhotoRepository(PhotoRepository):
    """
    Concrete implementation of PhotoRepository for filesystem-based photo management.
    
    Handles photo storage, retrieval, and metadata extraction from the filesystem.
    Treats related files (.jpg, .raw, .raf, .mov, .xmp, etc.) as a single logical photo.
    """
    
    # File extension patterns
    RAW_FORMATS = ('.raw', '.raf', '.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2')
    JPEG_FORMATS = ('.jpg', '.jpeg')
    LIVE_PHOTO_FORMATS = ('.mov', '.mp4')
    # Sidecar formats including Adobe XMP, Apple PLIST, etc.
    SIDECAR_FORMATS = ('.xmp', '.xml', '.plist', '.json')
    # All supported file extensions
    SUPPORTED_FORMATS = RAW_FORMATS + JPEG_FORMATS + LIVE_PHOTO_FORMATS + SIDECAR_FORMATS
    
    def __init__(self, base_directory: str):
        """
        Initialize the repository with a base directory for photo storage.
        
        Args:
            base_directory (str): Root directory for storing and managing photos
        """
        self.base_directory = os.path.abspath(base_directory)
        os.makedirs(self.base_directory, exist_ok=True)
        
        # Cache directory for metadata
        self.metadata_dir = os.path.join(self.base_directory, '.metadata')
        os.makedirs(self.metadata_dir, exist_ok=True)

    def _get_file_group_key(self, filename: str) -> str:
        """
        Extract the base name without extension to group related files.
        
        Args:
            filename (str): Filename to process
        
        Returns:
            str: Base name for grouping related files
        """
        # Extract base name without extension
        base_name = os.path.splitext(filename)[0]
        
        # Handle special case for Live Photos with suffix
        base_name = re.sub(r'\.live$', '', base_name)
        
        # Handle sidecar files that might have compound extensions (e.g., image.dng.xmp)
        base_name = re.sub(r'\.(xmp|xml|plist|json)$', '', base_name)
        
        return base_name

    def _find_related_files(self, base_path: str) -> Dict[str, str]:
        """
        Find all files related to a given base path (different formats of same photo).
        
        Args:
            base_path (str): Base path to the photo
            
        Returns:
            Dict[str, str]: Dictionary mapping file types to their paths
        """
        directory = os.path.dirname(base_path)
        base_name = self._get_file_group_key(os.path.basename(base_path))
        
        related_files = {}
        
        # Look for files with same base name but different extensions
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            if os.path.isfile(file_path):
                current_base = self._get_file_group_key(file)
                ext = os.path.splitext(file)[1].lower()
                
                if current_base == base_name and ext in self.SUPPORTED_FORMATS:
                    # Categorize by file type
                    if ext in self.RAW_FORMATS:
                        related_files['raw'] = file_path
                    elif ext in self.JPEG_FORMATS:
                        related_files['jpeg'] = file_path
                    elif ext in self.LIVE_PHOTO_FORMATS:
                        related_files['live'] = file_path
                    elif ext in self.SIDECAR_FORMATS:
                        # Check which format this sidecar belongs to
                        sidecar_full_name = os.path.basename(file_path)
                        if any(sidecar_full_name.endswith(f"{raw_ext}.xmp") for raw_ext in self.RAW_FORMATS):
                            related_files['raw_sidecar'] = file_path
                        elif any(sidecar_full_name.endswith(f"{jpeg_ext}.xmp") for jpeg_ext in self.JPEG_FORMATS):
                            related_files['jpeg_sidecar'] = file_path
                        else:
                            # Generic sidecar that applies to the entire photo
                            related_files['sidecar'] = file_path
        
        return related_files

    def _generate_safe_filename(self, original_filename: str, photo_id: uuid.UUID) -> str:
        """
        Generate a unique, safe filename for storage using the photo ID as base.
        
        Args:
            original_filename (str): Original filename of the photo
            photo_id (uuid.UUID): UUID for the photo
            
        Returns:
            str: Sanitized filename with UUID prefix
        """
        file_ext = os.path.splitext(original_filename)[1].lower()
        unique_filename = f"{photo_id}{file_ext}"
        return unique_filename

    def _extract_photo_metadata(self, file_paths: Dict[str, str]) -> dict:
        """
        Extract metadata from the best available file representation.
        First checks XMP sidecar files, then RAW, then JPEG, then Live Photo.
        
        Args:
            file_paths (Dict[str, str]): Dictionary of available file paths by type
            
        Returns:
            dict: Extracted metadata
        """
        metadata = {}
        
        # First try to extract from XMP sidecar files if available
        for sidecar_type in ['raw_sidecar', 'jpeg_sidecar', 'sidecar']:
            if sidecar_type in file_paths:
                sidecar_metadata = self._extract_metadata_from_xmp(file_paths[sidecar_type])
                if sidecar_metadata:
                    metadata.update(sidecar_metadata)
                    # If we found comprehensive metadata, we might not need to check image files
                    if 'camera_model' in metadata and 'latitude' in metadata and 'longitude' in metadata:
                        return metadata
        
        # Then try extracting from image files in order of preference
        for file_type in ['raw', 'jpeg', 'live']:
            if file_type in file_paths:
                try:
                    file_path = file_paths[file_type]
                    
                    # Only attempt EXIF extraction on RAW and JPEG
                    if file_type in ['raw', 'jpeg']:
                        with open(file_path, 'rb') as img_file:
                            img = exif.Image(img_file)
                            
                            # Extract camera model
                            if hasattr(img, 'model'):
                                metadata['camera_model'] = img.model
                            
                            # Extract GPS coordinates if available
                            if (hasattr(img, 'gps_latitude') and 
                                hasattr(img, 'gps_longitude')):
                                # Convert GPS coordinates to decimal degrees
                                lat = self._convert_gps_coordinates(
                                    img.gps_latitude, 
                                    img.gps_latitude_ref
                                )
                                lon = self._convert_gps_coordinates(
                                    img.gps_longitude, 
                                    img.gps_longitude_ref
                                )
                                
                                metadata['latitude'] = lat
                                metadata['longitude'] = lon
                    
                    # If we found useful metadata, we can stop looking
                    if metadata.get('camera_model') and metadata.get('latitude') and metadata.get('longitude'):
                        break
                        
                except (AttributeError, IOError, ValueError):
                    # Continue to the next file type if extraction fails
                    continue
        
        return metadata

    def _extract_metadata_from_xmp(self, xmp_path: str) -> dict:
        """
        Extract metadata from an XMP sidecar file.
        
        Args:
            xmp_path (str): Path to the XMP file
            
        Returns:
            dict: Extracted metadata
        """
        metadata = {}
        
        try:
            import xml.etree.ElementTree as ET
            
            # Define namespaces used in XMP files
            namespaces = {
                'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                'exif': 'http://ns.adobe.com/exif/1.0/',
                'tiff': 'http://ns.adobe.com/tiff/1.0/',
                'xmp': 'http://ns.adobe.com/xap/1.0/',
                'dc': 'http://purl.org/dc/elements/1.1/',
                'xmpRights': 'http://ns.adobe.com/xap/1.0/rights/',
                'lr': 'http://ns.adobe.com/lightroom/1.0/',
                'crs': 'http://ns.adobe.com/camera-raw-settings/1.0/'
            }
            
            # Parse the XMP file
            tree = ET.parse(xmp_path)
            root = tree.getroot()
            
            # Extract camera model from tiff:Model
            model_element = root.find(".//tiff:Model", namespaces)
            if model_element is not None and model_element.text:
                metadata['camera_model'] = model_element.text
            
            # Extract GPS data
            lat_element = root.find(".//exif:GPSLatitude", namespaces)
            lon_element = root.find(".//exif:GPSLongitude", namespaces)
            
            if lat_element is not None and lat_element.text and lon_element is not None and lon_element.text:
                # Parse the GPS coordinates (typically in format like "38,41.9N")
                lat_text = lat_element.text
                lon_text = lon_element.text
                
                # Simple parsing, would need to be expanded for all possible formats
                try:
                    # Handle formats like "38,41.9N"
                    if 'N' in lat_text or 'S' in lat_text:
                        lat_dir = 'N' if 'N' in lat_text else 'S'
                        lat_value = float(lat_text.replace('N', '').replace('S', '').replace(',', '.'))
                        if lat_dir == 'S':
                            lat_value = -lat_value
                    else:
                        lat_value = float(lat_text.replace(',', '.'))
                    
                    if 'E' in lon_text or 'W' in lon_text:
                        lon_dir = 'E' if 'E' in lon_text else 'W'
                        lon_value = float(lon_text.replace('E', '').replace('W', '').replace(',', '.'))
                        if lon_dir == 'W':
                            lon_value = -lon_value
                    else:
                        lon_value = float(lon_text.replace(',', '.'))
                    
                    metadata['latitude'] = lat_value
                    metadata['longitude'] = lon_value
                except (ValueError, TypeError):
                    # If parsing fails, ignore GPS data
                    pass
            
            # Extract capture date
            date_element = root.find(".//xmp:CreateDate", namespaces)
            if date_element is not None and date_element.text:
                # Store date info for potential use (format varies)
                metadata['capture_date'] = date_element.text
            
        except Exception as e:
            # If XMP parsing fails for any reason, just return empty metadata
            print(f"Error parsing XMP file {xmp_path}: {e}")
        
        return metadata

    def _convert_gps_coordinates(
        self, 
        coordinates: tuple, 
        ref: str
    ) -> Optional[float]:
        """
        Convert GPS coordinates from degrees, minutes, seconds to decimal degrees.
        
        Args:
            coordinates (tuple): GPS coordinates as (degrees, minutes, seconds)
            ref (str): Reference direction (N/S or E/W)
        
        Returns:
            Optional[float]: Decimal degree representation
        """
        try:
            degrees, minutes, seconds = coordinates
            decimal_degrees = degrees + (minutes / 60.0) + (seconds / 3600.0)
            
            # Apply sign based on reference
            if ref in ['S', 'W']:
                decimal_degrees = -decimal_degrees
            
            return decimal_degrees
        except (TypeError, ValueError):
            return None

    def _get_primary_file_path(self, file_paths: Dict[str, str]) -> str:
        """
        Determine the primary file path for a photo from its related files.
        Prefers JPEG, then RAW, then Live Photo.
        
        Args:
            file_paths (Dict[str, str]): Dictionary of available file paths by type
            
        Returns:
            str: Path to the primary file
        """
        # Order of preference for primary file
        for file_type in ['jpeg', 'raw', 'live']:
            if file_type in file_paths:
                return file_paths[file_type]
        
        # If no files are found (should never happen), return empty string
        return ""

    def save(self, photo: Photo) -> Photo:
        """
        Save a photo and all its related files to the filesystem.
        
        Args:
            photo (Photo): Photo to be saved
        
        Returns:
            Photo: Saved photo with updated file path
        """
        # Find all related files
        related_files = self._find_related_files(photo.file_path)
        
        # If no files were found, just use the original file
        if not related_files:
            related_files = {
                'primary': photo.file_path
            }
        
        # Generate a common ID for all related files
        photo_id = photo.id
        
        # Copy all related files to the repository
        saved_files = {}
        for file_type, file_path in related_files.items():
            if os.path.exists(file_path):
                original_filename = os.path.basename(file_path)
                
                # For sidecar files, maintain the relationship in the filename
                if file_type in ['raw_sidecar', 'jpeg_sidecar', 'sidecar']:
                    # Get the related primary file extension
                    if file_type == 'raw_sidecar':
                        primary_ext = '.raw'  # Simplification - would need to be more specific
                        for ext in self.RAW_FORMATS:
                            if f"{ext}.xmp" in original_filename.lower():
                                primary_ext = ext
                                break
                        safe_filename = f"{photo_id}{primary_ext}.xmp"
                    elif file_type == 'jpeg_sidecar':
                        safe_filename = f"{photo_id}.jpg.xmp"
                    else:
                        safe_filename = f"{photo_id}.xmp"
                else:
                    safe_filename = self._generate_safe_filename(original_filename, photo_id)
                
                destination_path = os.path.join(self.base_directory, safe_filename)
                
                # Copy the file to the repository directory
                try:
                    shutil.copy2(file_path, destination_path)
                    saved_files[file_type] = destination_path
                except IOError as e:
                    raise IOError(f"Failed to save {file_type} file: {e}")
        
        # Update primary file path in photo
        if saved_files:
            photo.file_path = self._get_primary_file_path(saved_files)
            
            # Store related files info in metadata
            self._save_related_files_metadata(photo_id, saved_files)
        
        return photo

    def _save_related_files_metadata(self, photo_id: uuid.UUID, files: Dict[str, str]) -> None:
        """
        Save metadata about related files.
        
        Args:
            photo_id (uuid.UUID): Photo ID
            files (Dict[str, str]): Dictionary mapping file types to paths
        """
        metadata_path = os.path.join(self.metadata_dir, f"{photo_id}.meta")
        
        with open(metadata_path, 'w') as f:
            for file_type, file_path in files.items():
                f.write(f"{file_type}:{file_path}\n")

    def _load_related_files_metadata(self, photo_id: uuid.UUID) -> Dict[str, str]:
        """
        Load metadata about related files.
        
        Args:
            photo_id (uuid.UUID): Photo ID
            
        Returns:
            Dict[str, str]: Dictionary mapping file types to paths
        """
        metadata_path = os.path.join(self.metadata_dir, f"{photo_id}.meta")
        related_files = {}
        
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                for line in f:
                    if ':' in line:
                        file_type, file_path = line.strip().split(':', 1)
                        related_files[file_type] = file_path
        
        return related_files

    def find_by_id(self, photo_id: uuid.UUID) -> Optional[Photo]:
        """
        Find a photo by its UUID in the filesystem.
        
        Args:
            photo_id (UUID): Unique identifier of the photo
        
        Returns:
            Optional[Photo]: Found photo or None
        """
        # Try to load from metadata first
        related_files = self._load_related_files_metadata(photo_id)
        
        # If not found in metadata, try to find in the filesystem
        if not related_files:
            for filename in os.listdir(self.base_directory):
                if str(photo_id) in filename and os.path.splitext(filename)[1].lower() in self.SUPPORTED_FORMATS:
                    full_path = os.path.join(self.base_directory, filename)
                    related_files = self._find_related_files(full_path)
                    break
                    
        # If still not found, return None
        if not related_files:
            return None
            
        # Extract metadata
        metadata = self._extract_photo_metadata(related_files)
        
        # Get primary file
        primary_file_path = self._get_primary_file_path(related_files)
        
        if not primary_file_path:
            return None
            
        # Create and return the photo
        try:
            return Photo(
                id=photo_id,
                file_path=primary_file_path,
                capture_timestamp=datetime.fromtimestamp(
                    os.path.getctime(primary_file_path)
                ),
                camera_model=metadata.get('camera_model'),
                latitude=metadata.get('latitude'),
                longitude=metadata.get('longitude')
            )
        except Exception as e:
            print(f"Error creating photo object: {e}")
            return None

    def find_by_tag(self, tag: str) -> List[Photo]:
        """
        Find photos by tag. Note: Tags are not natively supported by filesystem.
        This is a placeholder for potential future implementation.
        
        Args:
            tag (str): Tag to search for
        
        Returns:
            List[Photo]: List of photos matching the tag
        """
        # Future implementation could involve a separate metadata store
        return []

    def delete(self, photo_id: uuid.UUID) -> bool:
        """
        Delete a photo and all its related files from the filesystem.
        
        Args:
            photo_id (UUID): Unique identifier of the photo to delete
        
        Returns:
            bool: Whether deletion was successful
        """
        # Find all related files
        related_files = self._load_related_files_metadata(photo_id)
        
        if not related_files:
            return False
        
        success = True
        
        # Delete all related files
        for file_path in related_files.values():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                success = False
        
        # Delete metadata file
        try:
            metadata_path = os.path.join(self.metadata_dir, f"{photo_id}.meta")
            if os.path.exists(metadata_path):
                os.remove(metadata_path)
        except OSError:
            success = False
        
        return success

    def rename_photo(self, photo_id: uuid.UUID, new_name: str) -> Optional[Photo]:
        """
        Rename all files associated with a photo.
        
        Args:
            photo_id (UUID): Unique identifier of the photo
            new_name (str): New base name for the photo
            
        Returns:
            Optional[Photo]: Updated photo or None if not found
        """
        # Find all related files
        related_files = self._load_related_files_metadata(photo_id)
        
        if not related_files:
            return None
        
        # Create new paths with the new name
        new_paths = {}
        for file_type, old_path in related_files.items():
            if os.path.exists(old_path):
                directory = os.path.dirname(old_path)
                ext = os.path.splitext(old_path)[1]
                
                # Special handling for sidecar files to maintain the relationship
                if file_type in ['raw_sidecar', 'jpeg_sidecar', 'sidecar']:
                    # Get the original filename without the sidecar extension
                    original_filename = os.path.basename(old_path)
                    if file_type == 'raw_sidecar':
                        # Extract the raw format extension from the filename
                        for raw_ext in self.RAW_FORMATS:
                            if f"{raw_ext}.xmp" in original_filename.lower():
                                new_path = os.path.join(directory, f"{new_name}{raw_ext}.xmp")
                                break
                        else:
                            # Default if specific raw format not found
                            new_path = os.path.join(directory, f"{new_name}.raw.xmp")
                    elif file_type == 'jpeg_sidecar':
                        new_path = os.path.join(directory, f"{new_name}.jpg.xmp")
                    else:
                        new_path = os.path.join(directory, f"{new_name}.xmp")
                else:
                    # For live photos
                    suffix = ""
                    if file_type == 'live':
                        suffix = ".live"
                    
                    new_path = os.path.join(directory, f"{new_name}{suffix}{ext}")
                
                try:
                    os.rename(old_path, new_path)
                    new_paths[file_type] = new_path
                except OSError as e:
                    print(f"Error renaming {file_type} file: {e}")
                    # Revert already renamed files if an error occurs
                    for reverted_type, new_p in new_paths.items():
                        original_p = related_files[reverted_type]
                        try:
                            os.rename(new_p, original_p)
                        except OSError:
                            pass
                    return None
        
        # Update metadata
        self._save_related_files_metadata(photo_id, new_paths)
        
        # Return updated photo
        return self.find_by_id(photo_id)

    def list_photos(self) -> List[Photo]:
        """
        List all photos in the repository, grouping related files.
        
        Returns:
            List[Photo]: All photos in the repository
        """
        photos = []
        processed_ids = set()
        
        # First check metadata directory for known photo IDs
        for meta_file in os.listdir(self.metadata_dir):
            if meta_file.endswith('.meta'):
                photo_id_str = os.path.splitext(meta_file)[0]
                try:
                    photo_id = uuid.UUID(photo_id_str)
                    photo = self.find_by_id(photo_id)
                    if photo:
                        photos.append(photo)
                        processed_ids.add(photo_id)
                except ValueError:
                    # Invalid UUID, skip
                    continue
        
        # Then scan the directory for any untracked photos
        file_groups = {}
        
        for filename in os.listdir(self.base_directory):
            if os.path.splitext(filename)[1].lower() in self.SUPPORTED_FORMATS:
                # Skip files we already processed through metadata
                file_path = os.path.join(self.base_directory, filename)
                
                # Try to extract UUID from filename
                try:
                    potential_id = uuid.UUID(os.path.splitext(filename)[0])
                    if potential_id in processed_ids:
                        continue
                except ValueError:
                    # Not a UUID-named file, proceed with grouping
                    pass
                
                # Skip sidecar files as entry points - they'll be found through their primary files
                if os.path.splitext(filename)[1].lower() in self.SIDECAR_FORMATS:
                    continue
                
                base_name = self._get_file_group_key(filename)
                
                if base_name not in file_groups:
                    file_groups[base_name] = {}
                
                ext = os.path.splitext(filename)[1].lower()
                if ext in self.RAW_FORMATS:
                    file_groups[base_name]['raw'] = file_path
                elif ext in self.JPEG_FORMATS:
                    file_groups[base_name]['jpeg'] = file_path
                elif ext in self.LIVE_PHOTO_FORMATS:
                    file_groups[base_name]['live'] = file_path
        
        # Second pass to find sidecar files for each group
        for base_name in file_groups:
            # Find all potential sidecar files
            for filename in os.listdir(self.base_directory):
                if os.path.splitext(filename)[1].lower() in self.SIDECAR_FORMATS:
                    sidecar_base = self._get_file_group_key(filename)
                    if sidecar_base == base_name:
                        # This is a sidecar file for our group
                        file_path = os.path.join(self.base_directory, filename)
                        
                        # Determine which file type this sidecar belongs to
                        if 'raw' in file_groups[base_name] and any(
                            f"{raw_ext}.xmp" in filename.lower() for raw_ext in self.RAW_FORMATS
                        ):
                            file_groups[base_name]['raw_sidecar'] = file_path
                        elif 'jpeg' in file_groups[base_name] and any(
                            f"{jpeg_ext}.xmp" in filename.lower() for jpeg_ext in self.JPEG_FORMATS
                        ):
                            file_groups[base_name]['jpeg_sidecar'] = file_path
                        else:
                            # Generic sidecar
                            file_groups[base_name]['sidecar'] = file_path
        
        # Create photo objects for each group
        for base_name, files in file_groups.items():
            if not files:  # Skip empty groups
                continue
                
            # Create a new UUID for this group
            group_id = uuid.uuid4()
            
            # Get primary file path
            primary_file_path = self._get_primary_file_path(files)
            
            if not primary_file_path:
                continue
                
            # Extract metadata
            metadata = self._extract_photo_metadata(files)
            
            # Save metadata for future reference
            self._save_related_files_metadata(group_id, files)
            
            try:
                photo = Photo(
                    id=group_id,
                    file_path=primary_file_path,
                    capture_timestamp=datetime.fromtimestamp(
                        os.path.getctime(primary_file_path)
                    ),
                    camera_model=metadata.get('camera_model'),
                    latitude=metadata.get('latitude'),
                    longitude=metadata.get('longitude')
                )
                photos.append(photo)
            except Exception:
                # Skip files that can't be processed
                continue
        
        return photos
