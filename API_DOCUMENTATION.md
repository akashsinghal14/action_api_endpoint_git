# Fire Door Survey API - Developer Documentation

## Overview

This API provides individual endpoints for analyzing fire door measurements and compliance. Each endpoint is designed to be called independently by developers, returning detailed JSON responses with compliance status, action items, and recommendations.

## Base URL

```
http://localhost:5000/api
```

## API Structure
The API is organized into categories for better organization and scalability:

- **Action Items**: `/api/action_item/` - All measurement analysis and action item generation
- **Reports**: `/api/reports/` - Report generation (future)
- **Analytics**: `/api/analytics/` - Usage analytics (future)
- **Admin**: `/api/admin/` - Admin functions (future)

## Authentication

No authentication required for basic endpoints. OpenAI API key required for AI analysis endpoints.

## Individual Measurement Endpoints

### 1. Head Gap Analysis

**Endpoints:** 
- `POST /api/action_item/head` (JSON body)
- `GET /api/action_item/head/<value>/<unit>` (Path parameters)

**Description:** Analyzes head gap measurement for UK fire door compliance.

**Method 1 - POST with JSON Body:**
```json
{
  "value": 6,
  "unit": "mm"
}
```

**Method 2 - GET with Path Parameters:**
```
GET /api/action_item/head/6/mm
```

**Response:**
```json
{
  "success": true,
  "measurement_type": "head_gap",
  "value": 6,
  "unit": "mm",
  "compliant": false,
  "max_allowed": 4,
  "severity": "high",
  "actionItems": [
    {
      "severity": "high",
      "category": "Head Gap Compliance",
      "dueDate": "15/01/2024",
      "actionDescription": "Head gap (6mm) exceeds maximum allowed (4mm)...",
      "remediationOptions": [
        {
          "option": "Option 1: Quick Fix - Basic Strips",
          "plan": "Install basic intumescent strips at the head of the door..."
        }
      ],
      "confidenceScore": 92
    }
  ],
  "recommendations": "Immediate action required to reduce head gap...",
  "timestamp": "2024-01-12T10:30:00Z"
}
```

### 2. Hinge Gap Analysis

**Endpoint:** `POST /api/action_item/hinge`

**Description:** Analyzes hinge gap measurement for UK fire door compliance.

**Request Body:**
```json
{
  "value": 3,
  "unit": "mm"
}
```

**Response:** Same format as head gap analysis.

### 3. Closing Gap Analysis

**Endpoint:** `POST /api/action_item/closing`

**Description:** Analyzes closing gap measurement for UK fire door compliance.

**Request Body:**
```json
{
  "value": 5,
  "unit": "mm"
}
```

**Response:** Same format as head gap analysis.

### 4. Threshold Gap Analysis

**Endpoint:** `POST /api/action_item/threshold`

**Description:** Analyzes threshold gap measurement for UK fire door compliance.

**Request Body:**
```json
{
  "value": 2,
  "unit": "mm"
}
```

**Response:** Same format as head gap analysis.

### 5. Door Thickness Analysis

**Endpoint:** `POST /api/action_item/doorthick`

**Description:** Analyzes door thickness for UK fire door compliance.

**Request Body:**
```json
{
  "value": 45,
  "unit": "mm"
}
```

**Response:**
```json
{
  "success": true,
  "measurement_type": "door_thickness",
  "value": 45,
  "unit": "mm",
  "compliant": true,
  "min_required": 44,
  "severity": "none",
  "actionItems": [],
  "recommendations": "Door thickness meets minimum requirements",
  "timestamp": "2024-01-12T10:30:00Z"
}
```

## Additional Endpoints

### Field Validation

**Endpoint:** `POST /api/action_item/validate-field`

**Description:** Validates individual form fields.

**Request Body:**
```json
{
  "field_name": "headGap",
  "field_value": "6",
  "field_type": "number",
  "min_value": 0,
  "max_value": 100,
  "required": true
}
```

### AI Analysis

**Endpoint:** `POST /api/action_item/ai-analysis`

**Description:** Comprehensive AI-powered analysis using OpenAI.

**Request Body:**
```json
{
  "survey_data": {
    "fireResistance": "FD30",
    "headGap": 6,
    "hingeGap": 3
  },
  "api_key": "your-openai-api-key",
  "model": "gpt-3.5-turbo"
}
```

### Fallback Analysis

**Endpoint:** `POST /api/action_item/fallback-analysis`

**Description:** Rule-based analysis when AI is unavailable.

**Request Body:**
```json
{
  "survey_data": {
    "fireResistance": "Unknown",
    "headGap": 6
  }
}
```

### Contractor Recommendations

**Endpoint:** `POST /api/action_item/contractor-recommendations`

**Description:** Get contractor recommendations based on action items.

**Request Body:**
```json
{
  "action_items": [
    {
      "severity": "high",
      "category": "Head Gap Compliance"
    }
  ],
  "api_key": "your-openai-api-key"
}
```

### Cost Calculation

**Endpoint:** `POST /api/action_item/calculate-costs`

**Description:** Calculate total costs from action items.

**Request Body:**
```json
{
  "action_items": [
    {
      "remediationOptions": [
        {
          "cost": "£50-100 (basic strips) + £40-80 (labor)"
        }
      ]
    }
  ]
}
```

## Usage Examples

### cURL Examples

**Method 1 - POST with JSON Body:**
```bash
# Check head gap compliance
curl -X POST http://localhost:5000/api/action_item/head \
  -H "Content-Type: application/json" \
  -d '{"value": 6, "unit": "mm"}'

# Check door thickness
curl -X POST http://localhost:5000/api/action_item/doorthick \
  -H "Content-Type: application/json" \
  -d '{"value": 35, "unit": "mm"}'
```

**Method 2 - GET with Path Parameters:**
```bash
# Check head gap compliance (simpler!)
curl http://localhost:5000/api/action_item/head/6/mm

# Check door thickness (simpler!)
curl http://localhost:5000/api/action_item/doorthick/35/mm
```

**Browser-Friendly URLs:**
```
http://localhost:5000/api/action_item/head/6/mm
http://localhost:5000/api/action_item/hinge/3/mm
http://localhost:5000/api/action_item/closing/5/mm
http://localhost:5000/api/action_item/threshold/2/mm
http://localhost:5000/api/action_item/doorthick/35/mm
```

### Python Example

```python
import requests

# Check head gap
response = requests.post(
    'http://localhost:5000/api/action_item/head',
    json={'value': 6, 'unit': 'mm'}
)
result = response.json()
print(f"Compliant: {result['compliant']}")
print(f"Action Items: {len(result['actionItems'])}")
```

### JavaScript Example

```javascript
// Check hinge gap
fetch('http://localhost:5000/api/action_item/hinge', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    value: 3,
    unit: 'mm'
  })
})
.then(response => response.json())
.then(data => {
  console.log('Compliant:', data.compliant);
  console.log('Action Items:', data.actionItems);
});
```

## Response Format

All measurement endpoints return responses in this format:

```json
{
  "success": true,
  "measurement_type": "string",
  "value": number,
  "unit": "string",
  "compliant": boolean,
  "max_allowed": number,  // For gap measurements
  "min_required": number, // For thickness measurements
  "severity": "none|low|medium|high",
  "actionItems": [
    {
      "severity": "string",
      "category": "string",
      "dueDate": "DD/MM/YYYY",
      "actionDescription": "string",
      "remediationOptions": [
        {
          "option": "string",
          "plan": "string"
        }
      ],
      "confidenceScore": number
    }
  ],
  "recommendations": "string",
  "timestamp": "ISO 8601 timestamp"
}
```

## Error Handling

All endpoints return appropriate HTTP status codes:

- `200` - Success
- `400` - Bad Request (missing or invalid data)
- `500` - Internal Server Error

Error responses:
```json
{
  "error": "Error message describing what went wrong"
}
```

## UK Fire Door Standards

The API follows UK fire door compliance standards:

- **Maximum gaps:** 4mm (BS 476, Building Regulations Approved Document B)
- **Minimum door thickness:** 44mm for most fire doors
- **Required components:** Intumescent strips, self-closing devices, certification labels
- **Signage:** Must meet BS 5499 standards
- **Glazing:** Must be fire-rated pyro glazing if present

## Rate Limiting

- AI analysis endpoints have a 3-second rate limit between calls
- Other endpoints have no rate limiting

## Testing

Run the test suite to verify all endpoints:

```bash
python test_api.py
```

This will test all 10 endpoints with sample data to ensure they're working correctly.
