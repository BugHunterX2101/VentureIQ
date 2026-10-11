import os
import tempfile
import requests
import logging
from typing import Optional
from urllib.parse import urlparse
from config import Config

logger = logging.getLogger(__name__)


class FileDownloader:
    """Download files from URLs (Supabase or other sources)"""
    
    @staticmethod
    def download_from_url(url: str, output_path: Optional[str] = None) -> str:
        """
        Download file from URL and save to disk
        
        Args:
            url: File URL to download
            output_path: Optional output path. If None, creates temp file
        
        Returns:
            Path to downloaded file
        """
        logger.info(f"Downloading file from: {url}")
        
        try:
            # Make request with configurable timeout
            response = requests.get(url, timeout=Config.HTTP_TIMEOUT, stream=True)
            response.raise_for_status()
            
            # Determine file extension from URL or content-type
            extension = FileDownloader._get_file_extension(url, response)
            
            # Create output path if not provided
            if output_path is None:
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False, 
                    suffix=extension
                )
                output_path = temp_file.name
                temp_file.close()
            
            # Download file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"File downloaded successfully to: {output_path}")
            return output_path
        
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            raise
    
    @staticmethod
    def _get_file_extension(url: str, response: requests.Response) -> str:
        """Determine file extension from URL or content-type"""
        
        # Try to get from URL
        parsed_url = urlparse(url)
        path = parsed_url.path
        if '.' in path:
            return os.path.splitext(path)[1]
        
        # Try to get from content-type header
        content_type = response.headers.get('content-type', '').lower()
        
        extension_map = {
            'application/pdf': '.pdf',
            'image/png': '.png',
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/tiff': '.tiff',
            'image/bmp': '.bmp'
        }
        
        for ct, ext in extension_map.items():
            if ct in content_type:
                return ext
        
        # Default to .pdf
        return '.pdf'
    
    @staticmethod
    def cleanup_file(file_path: str):
        """Delete temporary file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.warning(f"Could not clean up file {file_path}: {e}")
