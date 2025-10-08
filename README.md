# Fire Door Survey API -   Python Backend

This is a Python Flask API backend that provides separate endpoints for analyzing fire door compliance survey data, similar to the original JavaScript implementation but with modular API endpoints.

## Features

### Separate API Endpoints

1. **Field Validation** (`/api/validate-field`)
   - Validates individual form fields
   - Supports number, text, and required field validation

2. **Gap Analysis** (`/api/analyze-gap`)
   - Analyzes individual gap measurements (head, hinge, closing, threshold)
   - Checks compliance with UK standards (4mm maximum gap)
   - Provides remediation options for non-compliant gaps

3. **Compliance Checks** (`/api/check-compliance`)
   - Checks individual compliance items (intumescent strips, self-closing devices, etc.)
   - Provides specific action items for missing components

4. **Door Thickness Analysis** (`/api/analyze-door-thickness`)
   - Analyzes door thickness against UK standards (44mm minimum)
   - Provides remediation options for undersized doors

5. **AI Analysis** (`/api/ai-analysis`)
   - Uses OpenAI API for comprehensive analysis
   - Generates detailed action items with multiple remediation options
   - Supports GPT-3.5, GPT-4, and GPT-5 models

6. **Fallback Analysis** (`/api/fallback-analysis`)
   - Rule-based analysis when AI is unavailable
   - Provides basic compliance checking

7. **Contractor Recommendations** (`/api/contractor-recommendations`)
   - AI-powered contractor recommendations
   - Fallback to hardcoded UK fire door specialists

8. **Cost Calculation** (`/api/calculate-costs`)
   - Calculates total estimated costs from action items
   - Provides cost ranges and averages

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up OpenAI API key (optional):**
   - Get your API key from [OpenAI Platform](https://platform.openai.com/)
   - Enter it in the frontend form for AI analysis

3. **Run the Flask server:**
   ```bash
   python app.py
   ```

4. **Open the frontend:**
   - Open `frontend.html` in your web browser
   - The frontend will connect to `http://localhost:5000` by default

## Usage

### Using the Frontend

1. Open `frontend.html` in your web browser
2. Configure the API base URL (default: `http://localhost:5000/api`)
3. Optionally enter your OpenAI API key for AI analysis
4. Fill out the fire door survey form
5. Click "Analyze Survey Data" to get results

### Using the API Directly

#### Example: Analyze a gap measurement

```bash
curl -X POST http://localhost:5000/api/analyze-gap \
  -H "Content-Type: application/json" \
  -d '{"gap_type": "head", "gap_value": 6}'
```

#### Example: Check compliance

```bash
curl -X POST http://localhost:5000/api/check-compliance \
  -H "Content-Type: application/json" \
  -d '{"compliance_type": "intumescentStrips", "is_present": false}'
```

#### Example: AI Analysis

```bash
curl -X POST http://localhost:5000/api/ai-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "survey_data": {
      "fireResistance": "FD30",
      "headGap": 6,
      "intumescentStrips": false
    },
    "api_key": "your-openai-api-key",
    "model": "gpt-3.5-turbo"
  }'
```

## API Response Format

All endpoints return JSON responses with the following structure:

```json
{
  "compliant": true/false,
  "actionItems": [
    {
      "severity": "high|medium|low",
      "category": "Issue Category",
      "dueDate": "DD/MM/YYYY",
      "actionDescription": "Detailed description",
      "remediationOptions": [
        {
          "option": "Option Name",
          "plan": "Step-by-step plan",
          "cost": "Estimated cost"
        }
      ],
      "confidenceScore": 85
    }
  ]
}
```

## UK Fire Door Standards

The API follows UK fire door compliance standards:

- **Maximum gaps:** 4mm (BS 476, Building Regulations Approved Document B)
- **Minimum door thickness:** 44mm for most fire doors
- **Required components:** Intumescent strips, self-closing devices, certification labels
- **Signage:** Must meet BS 5499 standards
- **Glazing:** Must be fire-rated pyro glazing if present

## Error Handling

- All endpoints include proper error handling
- Rate limiting prevents API abuse
- Fallback mechanisms ensure the system works even when AI services are unavailable
- Detailed error messages help with debugging

## Development

To extend the API:

1. Add new endpoints in `app.py`
2. Update the frontend to call new endpoints
3. Add new validation rules as needed
4. Extend the fallback analysis for new compliance checks

## License

This project is for educational and development purposes. Ensure compliance with OpenAI's terms of service when using their API.
