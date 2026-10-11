import google.generativeai as genai
from PIL import Image
from pdf2image import convert_from_path
import io
import logging
import shutil
import os
from typing import Optional, List
from config import Config

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Process images/PDFs and extract text using Google Gemini"""
    
    def __init__(self):
        try:
            if not Config.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not found in environment variables")
                
            genai.configure(api_key=Config.GEMINI_API_KEY)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
            logger.info("Gemini API configured successfully")
        except Exception as e:
            logger.error(f"Failed to configure Gemini API: {str(e)}")
            raise

    def extract_text_from_image(self, image_path: str, use_easyocr: bool = False) -> str:
        """Extract text from image file using Gemini"""
        logger.info(f"Extracting text from image: {image_path}")
        
        try:
            # Upload to Gemini
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            return self._generate_content(image_data, 'image/jpeg') # mime type estimation
        
        except Exception as e:
            logger.error(f"Error extracting text from image: {e}")
            raise
    
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF file"""
        logger.info(f"Extracting text from PDF: {pdf_path}")
        
        try:
            # Convert PDF to images using pdf2image (still needed as Gemini doesn't take local PDF files directly cleanly in one go without upload API, 
            # but for 1.5 flash we can send image data. 
            # Actually, standard Gemini API supports PDF upload via File API, but for simplicity/speed let's convert to images first 
            # or use the file API if we want to be fancy. 
            # Given the existing code used poppler to convert to images, let's keep that pattern but send images to Gemini.
            # However, to be efficient, let's just send the PDF pages as images.)
            
            # Check dependencies for poppler
            if not shutil.which('pdftoppm') and not shutil.which('pdfinfo'):
                 # Fallback or error? The plan said modify dependencies. 
                 # Let's keep using convert_from_path as it's already there
                 pass

            images = convert_from_path(pdf_path, dpi=300)
            
            all_text = []
            for i, image in enumerate(images):
                logger.info(f"Processing page {i+1}/{len(images)}")
                
                # Convert PIL image to bytes
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format='JPEG')
                img_byte_arr = img_byte_arr.getvalue()

                text = self._generate_content(img_byte_arr, 'image/jpeg')
                all_text.append(text)
            
            return '\n\n'.join(all_text)
        
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise
    
    def extract_text_from_bytes(self, image_bytes: bytes, use_easyocr: bool = False) -> str:
        """Extract text from image bytes"""
        logger.info("Extracting text from image bytes")
        
        try:
            return self._generate_content(image_bytes, 'image/jpeg')
        
        except Exception as e:
            logger.error(f"Error extracting text from bytes: {e}")
            raise
    
    def _generate_content(self, data: bytes, mime_type: str) -> str:
        """Helper to call Gemini API"""
        try:
            image_part = {
                "mime_type": mime_type,
                "data": data
            }
            
            prompt = "Extract all text from this image. Provide the text exactly as it appears, maintaining structure and formatting. If no text exists, return empty string."
            
            response = self.model.generate_content([prompt, image_part])
            
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise
