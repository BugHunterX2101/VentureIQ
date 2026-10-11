import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration for OCR Service"""
    
    # Flask
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    PORT = int(os.getenv('PORT', 5000))
    
    # OCR
    TESSERACT_CMD = os.getenv('TESSERACT_CMD', 'tesseract')
    OCR_LANGUAGE = os.getenv('OCR_LANGUAGE', 'eng')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    OCR_CONFIDENCE_THRESHOLD = float(os.getenv('OCR_CONFIDENCE_THRESHOLD', 0.6))
    
    # Supabase / S3
    SUPABASE_PUBLIC_URL = os.getenv('SUPABASE_PUBLIC_URL', '')
    SUPABASE_S3_ACCESS_KEY = os.getenv('SUPABASE_S3_ACCESS_KEY', '')
    SUPABASE_S3_SECRET_KEY = os.getenv('SUPABASE_S3_SECRET_KEY', '')
    SUPABASE_S3_REGION = os.getenv('SUPABASE_S3_REGION', '')
    SUPABASE_BUCKET = os.getenv('SUPABASE_BUCKET', '')
    
    # OCR Service
    OCR_SERVICE_URL = os.getenv('OCR_SERVICE_URL', '')
    OCR_SERVICE_ENABLED = os.getenv('OCR_SERVICE_ENABLED', 'true').lower() == 'true'
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Supported file types
    SUPPORTED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp']
    
    # Max file size (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    # HTTP timeout for file downloads (in seconds)
    HTTP_TIMEOUT = int(os.getenv('HTTP_TIMEOUT', 120))
