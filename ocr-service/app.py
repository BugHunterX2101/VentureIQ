from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os
from typing import Dict
from pydantic import BaseModel, ValidationError

from config import Config
from ocr_processor import OCRProcessor
from field_extractor import FieldExtractor
from file_downloader import FileDownloader

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize services
ocr_processor = OCRProcessor()
field_extractor = FieldExtractor(confidence_threshold=Config.OCR_CONFIDENCE_THRESHOLD)


# Request/Response Models
class ParseBillRequest(BaseModel):
    file_url: str
    use_easyocr: bool = False


class ParseBillResponse(BaseModel):
    success: bool
    data: Dict = None
    error: str = None


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'OCR Bill Parser',
        'version': '1.0.0'
    }), 200


@app.route('/api/parse-bill', methods=['POST'])
def parse_bill():
    """
    Parse bill from file URL
    
    Request Body:
    {
        "file_url": "https://supabase.co/storage/...",
        "use_easyocr": false
    }
    
    Response:
    {
        "success": true,
        "data": {
            "amount": {"value": 1234.56, "confidence": 0.85},
            "bill_number": {"value": "BILL-12345", "confidence": 0.90},
            "consumer_number": {"value": "CONS-67890", "confidence": 0.88},
            "biller_info": {
                "biller_name": "ELECTRICITY BOARD",
                "category": "ELECTRICITY",
                "confidence": 0.92
            },
            "billing_date": {"value": "2024-01-15", "confidence": 0.80},
            "due_date": {"value": "2024-02-15", "confidence": 0.75},
            "units_consumed": {"value": 150.5, "confidence": 0.70},
            "raw_text": "First 500 chars of extracted text..."
        }
    }
    """
    temp_file_path = None
    
    try:
        # Validate request
        try:
            request_data = ParseBillRequest(**request.get_json())
        except ValidationError as e:
            return jsonify({
                'success': False,
                'error': f'Invalid request: {str(e)}'
            }), 400
        
        logger.info(f"Parsing bill from URL: {request_data.file_url}")
        
        # Download file
        temp_file_path = FileDownloader.download_from_url(request_data.file_url)
        
        # Determine file type
        file_extension = os.path.splitext(temp_file_path)[1].lower()
        
        # Extract text based on file type
        if file_extension == '.pdf':
            extracted_text = ocr_processor.extract_text_from_pdf(temp_file_path)
        elif file_extension in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            extracted_text = ocr_processor.extract_text_from_image(
                temp_file_path,
                use_easyocr=request_data.use_easyocr
            )
        else:
            return jsonify({
                'success': False,
                'error': f'Unsupported file type: {file_extension}'
            }), 400
        
        logger.info(f"Extracted text length: {len(extracted_text)} characters")
        
        # Extract fields
        extracted_fields = field_extractor.extract_fields(extracted_text)
        
        # Calculate overall confidence
        confidences = []
        for key, value in extracted_fields.items():
            if isinstance(value, dict) and 'confidence' in value:
                confidences.append(value['confidence'])
            elif key == 'biller_info' and isinstance(value, dict):
                confidences.append(value.get('confidence', 0))
        
        overall_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        response_data = {
            **extracted_fields,
            'overall_confidence': round(overall_confidence, 2)
        }
        
        logger.info(f"Parsing completed. Overall confidence: {overall_confidence:.2f}")
        
        return jsonify({
            'success': True,
            'data': response_data
        }), 200
    
    except RuntimeError as e:
        logger.error(f"Dependency error: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'code': 'DEPENDENCY_MISSING'
        }), 503
    
    except Exception as e:
        logger.error(f"Error parsing bill: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    
    finally:
        # Cleanup temporary file
        if temp_file_path:
            FileDownloader.cleanup_file(temp_file_path)


@app.route('/api/parse-bill-base64', methods=['POST'])
def parse_bill_base64():
    """
    Parse bill from base64 encoded image
    
    Request Body:
    {
        "image_base64": "base64_encoded_image_data",
        "use_easyocr": false
    }
    """
    try:
        data = request.get_json()
        
        if 'image_base64' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing image_base64 field'
            }), 400
        
        import base64
        image_bytes = base64.b64decode(data['image_base64'])
        use_easyocr = data.get('use_easyocr', False)
        
        # Extract text
        extracted_text = ocr_processor.extract_text_from_bytes(
            image_bytes,
            use_easyocr=use_easyocr
        )
        
        # Extract fields
        extracted_fields = field_extractor.extract_fields(extracted_text)
        
        return jsonify({
            'success': True,
            'data': extracted_fields
        }), 200
    
    except RuntimeError as e:
        logger.error(f"Dependency error: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'code': 'DEPENDENCY_MISSING'
        }), 503

    except Exception as e:
        logger.error(f"Error parsing bill from base64: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500


if __name__ == '__main__':
    logger.info("Starting OCR Bill Parser Service...")
    logger.info(f"Configuration: {Config.__dict__}")
    
    app.run(
        host='0.0.0.0',
        port=Config.PORT,
        debug=Config.FLASK_DEBUG
    )
