# OCR Bill Parser Service

Python microservice for extracting bill information using OCR (Tesseract + EasyOCR).

## Features

- 📄 PDF and image bill parsing
- 🔍 Smart field extraction with fuzzy matching
- 💰 Amount, date, bill number extraction
- 🏢 Biller identification and categorization
- 🎯 Confidence scoring for each field
- 🚀 REST API with Flask

## Installation

### Prerequisites

- Python 3.9+
- Tesseract OCR

#### Install Tesseract

**Windows:**
```bash
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH: C:\Program Files\Tesseract-OCR
```

**Linux:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng poppler-utils
```

**macOS:**
```bash
brew install tesseract poppler
```

### Setup

1. **Install dependencies:**
```bash
cd ocr-service
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. **Run the service:**
```bash
python app.py
```

The service will start on `http://localhost:5000`

## API Endpoints

### Health Check
```http
GET /health
```

Response:
```json
{
  "status": "healthy",
  "service": "OCR Bill Parser",
  "version": "1.0.0"
}
```

### Parse Bill from URL
```http
POST /api/parse-bill
Content-Type: application/json

{
  "file_url": "https://supabase.co/storage/bill.pdf",
  "use_easyocr": false
}
```

Response:
```json
{
  "success": true,
  "data": {
    "amount": {
      "value": 1234.56,
      "confidence": 0.85
    },
    "bill_number": {
      "value": "BILL-12345",
      "confidence": 0.90
    },
    "consumer_number": {
      "value": "CONS-67890",
      "confidence": 0.88
    },
    "biller_info": {
      "biller_name": "ELECTRICITY BOARD",
      "category": "ELECTRICITY",
      "confidence": 0.92
    },
    "billing_date": {
      "value": "2024-01-15",
      "confidence": 0.80
    },
    "due_date": {
      "value": "2024-02-15",
      "confidence": 0.75
    },
    "units_consumed": {
      "value": 150.5,
      "confidence": 0.70
    },
    "overall_confidence": 0.83
  }
}
```

### Parse Bill from Base64
```http
POST /api/parse-bill-base64
Content-Type: application/json

{
  "image_base64": "base64_encoded_image_data",
  "use_easyocr": false
}
```

## Docker Deployment

```bash
# Build image
docker build -t ocr-bill-parser .

# Run container
docker run -p 5000:5000 ocr-bill-parser
```

## Testing

```bash
# Test with curl
curl -X POST http://localhost:5000/api/parse-bill \
  -H "Content-Type: application/json" \
  -d '{"file_url": "https://example.com/bill.pdf"}'
```

## Architecture

```
ocr-service/
├── app.py                  # Flask application
├── config.py               # Configuration
├── ocr_processor.py        # OCR extraction (Tesseract/EasyOCR)
├── field_extractor.py      # Smart field extraction
├── file_downloader.py      # File download utility
├── requirements.txt        # Python dependencies
├── Dockerfile             # Docker configuration
└── .env.example           # Environment template
```

## Supported Bill Types

- ⚡ Electricity bills
- 💧 Water bills
- 📱 Mobile/Telecom bills
- 🔥 Gas bills

## Confidence Scoring

Each extracted field includes a confidence score (0.0 - 1.0):
- **0.8 - 1.0**: High confidence
- **0.6 - 0.8**: Medium confidence
- **0.0 - 0.6**: Low confidence (manual review recommended)
