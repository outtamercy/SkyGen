import os
import struct
from typing import Dict, Union, Optional, Type, Any, List, Tuple
from datetime import datetime
from pathlib import Path

# noinspection PyUnresolvedReferences
import mobase # type: ignore # This import is provided by MO2 runtime

# Corrected imports to be relative, as intended for package structure
# Assuming SkyGen/extractors/base_extractor.py
# .. means one level up (SkyGen/)
# ..utils means SkyGen/utils/
from ..src.organizer_wrapper import OrganizerWrapper 
from ..utils.logger import LoggingMixin, SkyGenLogger # Keep LoggingMixin, use SkyGenLogger directly


class FileMetadataExtractor(LoggingMixin): # Inherit from LoggingMixin
    """Base class for extracting metadata from different file types."""
    
    def __init__(self, organizer_wrapper: Optional[OrganizerWrapper] = None):
        super().__init__() # Initialize LoggingMixin. This uses the global SkyGenLogger instance.
        self.organizer_wrapper = organizer_wrapper # Store it if needed by subclasses
        self.log_debug("FileMetadataExtractor initialized.", module_name="FileMetadataExtractor")

    _extractors: Dict[str, Type['FileMetadataExtractor']] = {}
    
    _DEFAULT_CACHE_SIZE = 100
    
    _metadata_cache = {}
    _metadata_cache_hits = 0
    _metadata_cache_misses = 0
    _metadata_cache_max_size = 100
    
    @classmethod
    def register_extractor(cls, file_extensions: List[str], extractor_class: Type['FileMetadataExtractor']) -> None:
        """
        Registers an extractor class for specific file extensions.
        """
        # CRITICAL FIX: Directly instantiate SkyGenLogger() to get the singleton instance.
        # This is the correct way to access your SkyGenLogger based on its __new__ method.
        logger_instance = SkyGenLogger() 
        
        for ext in file_extensions:
            if ext in cls._extractors:
                logger_instance.warning(f"Extractor for extension '{ext}' already registered. Overwriting with '{extractor_class.__name__}'.", module_name="FileMetadataExtractor")
            cls._extractors[ext] = extractor_class
            logger_instance.debug(f"Registered extractor '{extractor_class.__name__}' for extension '{ext}'.", module_name="FileMetadataExtractor")

    @classmethod
    def get_extractor(cls, file_extension: str) -> Optional[Type['FileMetadataExtractor']]:
        """
        Retrieves the registered extractor class for a given file extension.
        """
        # CRITICAL FIX: Directly instantiate SkyGenLogger() to get the singleton instance.
        logger_instance = SkyGenLogger() 
        
        extractor = cls._extractors.get(file_extension.lower())
        if not extractor:
            logger_instance.debug(f"No extractor registered for extension '{file_extension}'.", module_name="FileMetadataExtractor")
        return extractor
    
    @classmethod
    def extract_metadata(cls, file_path: Path, use_cache: bool = True) -> Dict[str, Union[str, int]]:
        """
        Extracts metadata from a file using the appropriate registered extractor.
        """
        # CRITICAL FIX: Directly instantiate SkyGenLogger() to get the singleton instance.
        logger_instance = SkyGenLogger() 
        
        if not file_path.is_file():
            logger_instance.error(f"File not found: {file_path}", module_name="FileMetadataExtractor")
            return {"error": "File not found"}

        file_extension = file_path.suffix.lower()
        
        if use_cache and file_path in cls._metadata_cache:
            cls._metadata_cache_hits += 1
            logger_instance.debug(f"Cache hit for {file_path}. Hits: {cls._metadata_cache_hits}, Misses: {cls._metadata_cache_misses}", module_name="FileMetadataExtractor")
            return cls._metadata_cache[file_path]

        extractor_class = cls.get_extractor(file_extension)
        if not extractor_class:
            logger_instance.warning(f"No specific extractor for '{file_extension}'. Using generic file info.", module_name="FileMetadataExtractor")
            metadata = cls.get_generic_file_info(str(file_path)) # Fallback to generic
        else:
            try:
                # Instantiate the specific extractor to call its extract_file_metadata method
                # For base_extractor, its __init__ doesn't require organizer_wrapper for now.
                instance = extractor_class() 
                metadata = instance.extract_file_metadata(file_path) # Call instance method
                logger_instance.debug(f"Extracted metadata for '{file_path}' using '{extractor_class.__name__}'.", module_name="FileMetadataExtractor")
            except Exception as e:
                logger_instance.error(f"Error using extractor '{extractor_class.__name__}' for '{file_path}': {e}", exc_info=True, module_name="FileMetadataExtractor")
                metadata = cls.get_generic_file_info(str(file_path)) # Fallback on error

        if use_cache:
            if len(cls._metadata_cache) >= cls._metadata_cache_max_size:
                cls._metadata_cache.pop(next(iter(cls._metadata_cache))) # Simple LRU-like eviction
            cls._metadata_cache[file_path] = metadata
            cls._metadata_cache_misses += 1
            logger_instance.debug(f"Cache miss for {file_path}. Added to cache. Hits: {cls._metadata_cache_hits}, Misses: {cls._metadata_cache_misses}", module_name="FileMetadataExtractor")

        return metadata

    def extract_file_metadata(self, file_path: Path) -> Dict[str, Union[str, int]]:
        """
        Placeholder for subclasses to implement specific metadata extraction logic.
        """
        self.log_debug(f"Using default extract_file_metadata for {file_path.name}", module_name="FileMetadataExtractor")
        return self.get_generic_file_info(str(file_path))

    @staticmethod
    def format_html_info(metadata: Dict[str, Union[str, int]]) -> str:
        """
        Formats extracted metadata into an HTML string for display.
        """
        html = "<table style='width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 0.9em;'>"\
               "<tr><td colspan='2' style='padding: 10px; background-color: #f0f0f0; font-weight: bold; border-bottom: 2px solid #ccc;'>File Metadata</td></tr>"
        
        for key, value in metadata.items():
            # Basic sanitization for HTML output
            key = str(key).replace('<', '&lt;').replace('>', '&gt;')
            value = str(value).replace('<', '&lt;').replace('>', '&gt;')
            html += f"<tr><td style='padding: 5px; border-bottom: 1px solid #eee; width: 30%; font-weight: bold;'>{key}:</td><td style='padding: 5px; border-bottom: 1px solid #eee;'>{value}</td></tr>"
        
        html += "</table>"
        return html
    
    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """
        Formats a file size in bytes into a human-readable string (KB, MB, GB).
        """
        for unit in ['bytes', 'KB', 'MB', 'GB']:
            if size_bytes < 1024 or unit == 'GB':
                break
            size_bytes /= 1024
        
        if unit == 'bytes':
            return f"{size_bytes} {unit}"
        else:
            return f"{size_bytes:.2f} {unit}"
    
    @staticmethod
    def get_generic_file_info(file_path: str) -> Dict[str, str]:
        """
        Retrieves basic file system information for any given file.
        """
        file_size = os.path.getsize(file_path)
        modified_time = os.path.getmtime(file_path)
        created_time = os.path.getctime(file_path)
        
        modified_str = datetime.fromtimestamp(modified_time).strftime('%Y-%m-%d %H:%M:%S')
        created_str = datetime.fromtimestamp(created_time).strftime('%Y-%m-%d %H:%M:%S')
        
        return {
            "File Name": Path(file_path).name,
            "Full Path": file_path,
            "File Size": FileMetadataExtractor.format_file_size(file_size),
            "Last Modified": modified_str,
            "Created": created_str
        }
