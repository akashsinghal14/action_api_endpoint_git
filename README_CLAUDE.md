# Fire Door Survey API - Claude Implementation

This is a Claude API-based implementation of the Fire Door Survey API, providing identical functionality to the OpenAI version but using Anthropic's Claude models instead.

## Overview

The Claude API implementation maintains complete compatibility with the existing frontend and API structure while leveraging Claude's advanced reasoning capabilities for fire door compliance analysis.

## Key Features

- **Identical API Structure**: All endpoints, request/response formats match the original OpenAI implementation
- **Claude AI Integration**: Uses Claude-3.5-Sonnet as the default model for analysis
- **UK Fire Safety Compliance**: Maintains all UK property terminology and standards [[memory:8449403]]
- **Port Separation**: Runs on port 5001 to avoid conflicts with OpenAI version
- **Fallback Support**: Rule-based analysis when AI is unavailable

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements_claude.txt
```

### 2. Configure Environment

Copy the environment template:
```bash
cp env_claude.example .env
```

Edit `.env` and add your Claude API keys:
```env
YOUR_KEY=sk-ant-your-claude-api-key-here
DEV_KEY=sk-ant-your-dev-claude-api-key-here
PROD_KEY=sk-ant-your-prod-claude-api-key-here
TEST_KEY=sk-ant-your-test-claude-api-key-here
DEFAULT_AI_MODEL=claude-3-5-sonnet-20241022
```

### 3. Run the Server

```bash
python run_claude.py
```

The API will be available at `http://localhost:5001`

### 4. Test the Implementation

```bash
python test_claude_api.py
```

## API Endpoints

All endpoints are identical to the OpenAI version:

### Individual Measurement Analysis
- `GET /api/action_item/analyze-head-gap/<value>/<unit>`
- `GET /api/action_item/analyze-hinge-gap/<value>/<unit>`
- `GET /api/action_item/analyze-closing-gap/<value>/<unit>`
- `GET /api/action_item/analyze-threshold-gap/<value>/<unit>`
- `GET /api/action_item/analyze-door-thickness/<value>/<unit>`

### POST Endpoints
- `POST /api/action_item/analyze-head-gap` (with JSON body)
- `POST /api/action_item/ai-analysis` (AI-powered comprehensive analysis)
- `POST /api/action_item/contractor-recommendations`
- `POST /api/action_item/calculate-costs`
- `POST /api/action_item/validate-field`
- `POST /api/action_item/fallback-analysis`

## Usage Examples

### Basic Gap Analysis
```bash
# Check head gap compliance
curl http://localhost:5001/api/action_item/analyze-head-gap/6/mm

# Check door thickness
curl http://localhost:5001/api/action_item/analyze-door-thickness/35/mm
```

### AI-Powered Analysis
```bash
curl -X POST http://localhost:5001/api/action_item/ai-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "survey_data": {
      "fireResistance": "FD30",
      "headGap": 6,
      "hingeGap": 3
    },
    "api_key": "YOUR_KEY",
    "model": "claude-3-5-sonnet-20241022"
  }'
```

## Claude Models

The implementation supports these Claude models:

- `claude-3-5-sonnet-20241022` (default, recommended)
- `claude-3-opus-20240229`
- `claude-3-haiku-20240307`

## Key Differences from OpenAI Version

1. **API Integration**: Uses Anthropic's Claude API instead of OpenAI
2. **Port**: Runs on port 5001 instead of 5000
3. **API Keys**: Uses `sk-ant-` prefixed keys instead of `sk-`
4. **Response Parsing**: Adapted for Claude's response format
5. **Cost Calculation**: Simplified (no Claude-specific cost tracking)

## File Structure

```
app_claude.py              # Main Claude API implementation
run_claude.py              # Server startup script
test_claude_api.py         # Test suite
requirements_claude.txt    # Python dependencies
env_claude.example         # Environment configuration template
README_CLAUDE.md          # This documentation
```

## Compatibility

- **Frontend**: Works with existing `frontend.html` (just change port to 5001)
- **API Structure**: Identical to OpenAI version
- **Response Format**: Same JSON structure
- **UK Standards**: Maintains all UK fire safety compliance rules

## Running Both APIs

You can run both OpenAI and Claude APIs simultaneously:

```bash
# Terminal 1 - OpenAI API (port 5000)
python app.py

# Terminal 2 - Claude API (port 5001)  
python run_claude.py
```

## Testing

The test suite verifies:
- All static endpoints work correctly
- POST endpoints accept JSON data
- AI analysis works with valid API keys
- Response formats match expected structure
- UK fire safety standards are maintained

Run tests:
```bash
python test_claude_api.py
```

## Error Handling

- Invalid API keys fall back to static analysis
- Rate limiting prevents API abuse
- Comprehensive error messages for debugging
- Graceful degradation when AI is unavailable

## Support

This implementation maintains the same high-quality fire door compliance analysis as the OpenAI version while leveraging Claude's advanced reasoning capabilities for more nuanced analysis and recommendations.
