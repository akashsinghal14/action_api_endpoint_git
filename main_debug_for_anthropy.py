#  FIRE DOOR COMPLIANCE CHECKER (Flask + OpenAI Vision)
from flask import Flask, request, jsonify, render_template_string
from openai import OpenAI
import base64
import httpx
import os
from dotenv import load_dotenv
load_dotenv()  
# Flask App Initialization

app = Flask(__name__)

# Claude API Key

claude_api_key = os.getenv("ANTHROPIC_API_KEY")
print("Claude API Key Loaded:", bool(claude_api_key))

# Encode image from path
def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

# Web interface
@app.route("/")
def index():
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fire Door Compliance Checker</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #d32f2f;
                text-align: center;
                margin-bottom: 30px;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
                color: #333;
            }
            input[type="text"] {
                width: 100%;
                padding: 10px;
                border: 2px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
            }
            button {
                background-color: #d32f2f;
                color: white;
                padding: 12px 30px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
                width: 100%;
            }
            button:hover {
                background-color: #b71c1c;
            }
            .result {
                margin-top: 20px;
                padding: 15px;
                background-color: #f8f9fa;
                border-radius: 5px;
                border-left: 4px solid #d32f2f;
            }
            .error {
                background-color: #ffebee;
                border-left-color: #f44336;
            }
            .success {
                background-color: #e8f5e8;
                border-left-color: #4caf50;
            }
            .loading {
                text-align: center;
                color: #666;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔥 Fire Door Compliance Checker</h1>
            <p style="text-align: center; color: #666; margin-bottom: 30px;">
                Upload a fire door image for UK property compliance analysis
            </p>
            
            <form id="complianceForm">
                <div class="form-group">
                    <label for="imagePath">Image Path:</label>
                    <input type="text" id="imagePath" name="imagePath" 
                           placeholder="C:\path\to\your\fire-door-image.jpg"
                           value="C:\\Users\\AkashSinghal\\Downloads\\Compliance_check\\Compliance_check\\Fire-Door.jpeg">
                </div>
                <button type="submit">Check Fire Door Compliance</button>
            </form>
            
            <div id="result" style="display: none;"></div>
        </div>

        <script>
            document.getElementById('complianceForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const imagePath = document.getElementById('imagePath').value;
                const resultDiv = document.getElementById('result');
                
                if (!imagePath) {
                    showResult('Please enter an image path', 'error');
                    return;
                }
                
                showResult('Analyzing fire door image...', 'loading');
                
                try {
                    const response = await fetch('/api/check_door', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ image_path: imagePath })
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        showResult(data.detections, 'success');
                    } else {
                        showResult('Error: ' + data.error, 'error');
                    }
                } catch (error) {
                    showResult('Error: ' + error.message, 'error');
                }
            });
            
            function showResult(message, type) {
                const resultDiv = document.getElementById('result');
                resultDiv.style.display = 'block';
                resultDiv.className = 'result ' + type;
                resultDiv.innerHTML = '<pre>' + message + '</pre>';
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)
# API Endpoint: Fire Door Compliance Check

@app.route("/api/check_door", methods=["POST"])
def check_door():
    try:
         # Parse JSON input
        data = request.json
        image_path = data.get("image_path")
         # Validate image path
        if not image_path or not os.path.exists(image_path):
            return jsonify({"success": False, "error": "Invalid or missing image_path"}), 400
                # Encode the image for API request
        base64_image = encode_image(image_path)

 # Prompt for Fire Door Analysis
 # The prompt instructs GPT-4o to evaluate multiple compliance parameters
 #and detect any visible physical damage.

        prompt_text = """
You are a fire safety compliance inspector specializing in UK property regulations. Analyze the attached image of a fire door and assess its compliance based on the following criteria:

⚠️ IMPORTANT: You must return a complete JSON object with **all 11 categories**, even if some features are not visible or cannot be verified. Do not omit any category.

For each of the following categories, return:
- `"compliance_status"`: true if the feature is visibly present and appears compliant, false if missing or non-compliant.
- `"compliance_status"`: true if the feature is compliant, false if non-compliant or missing.

Categories to assess:
1. 🔖 Keep Shut Sign
2. 🚪 Self-Closing Device
3. 🔥 Intumescent Strips
4. 🧲 Hold Open Device
5. 📜 Certification Visible
6. 🪟 Contains Glazing
7. 🔥 Pyro Glazing
8. 📏 Gap Measurements
9. 🔩 Hinge Condition
10. 🧱 Frame Integrity
11. 🚨 Door Damage Check


1. 🔖 Keep Shut Sign:
   - Is there a clearly visible 'Fire Door Keep Shut' sign?
   - Is the signage positioned correctly and legible?

2. 🚪 Self-Closing Device:
   - Is a self-closing device present?
   - Does it appear functional and properly installed?

3. 🔥 Intumescent Strips:
   - Are intumescent strips visible around the door edge or frame?
   - Do they appear continuous and properly installed?

4. 🧲 Hold Open Device:
   - Is there a hold-open device present? This may include:
     - Wall-mounted electromagnetic holders
     - Overhead arms or brackets that prevent the door from closing
     - Floor-mounted or frame-mounted mechanical devices
   - If visible, does it appear to comply with fire safety standards (e.g., automatic release on alarm)?
   - If the image shows a device mounted above or beside the door that holds it open, assume it is a hold-open device unless clearly non-compliant.
   - If no hold-open device is visible, mark `"compliance_status": false` and `"details": "Not visible in image"`.
   

5. 📜 Certification Visible:
   - Is there a certification label or plate visible on the door or frame?
   - Is it legible and from a recognized authority?


6. 🪟 Contains Glazing:
   - Does the door contain any glazing (glass panels)?
   - Is the glazing properly sealed and positioned?
   - Set compliance_status: true only if glazing is present, properly sealed, and there are no signs of damage.

7. 🔥 Pyro Glazing:
   - If glazing is present, does it appear to be pyro glazing (fire-rated)?
   - Are there markings or visual indicators of fire resistance?

8. 📏 Gap Measurements:
   - Estimate the gaps around the door edges (top, sides, bottom).
   - Are they within the acceptable range (typically 2–4mm)?

9. 🔩 Hinge Condition:
   - Are there at least three hinges?
   - Are they secure, undamaged, and free of visible wear?

10. 🧱 Frame Integrity:
   - Is the door frame robust and undamaged?
   - Are there signs of warping, cracks, or poor installation?

11. 🚨 Door Damage Check:
- Always include this category.
- Carefully inspect the fire door and all its components for **visible physical damage only**.
- This includes:
  - 🔖 Keep Shut Sign: faded, illegible, cracked, or physically damaged signage
  - 🚪 Self-Closing Device: broken, bent, or visibly malfunctioning closer
  - 🔥 Intumescent Strips: degraded, torn, or improperly installed strips
  - 🪟 Glazing: cracked, shattered, broken, or missing glass panels — this is considered serious door damage
  - 🔥 Pyro Glazing: damaged fire-rated glass or broken markings
  - 📏 Gap Measurements: uneven, excessive gaps that indicate warping  
    📏 Gap Measurements: Only include in `"Door Damage Check"` if gaps are visibly uneven **and clearly indicate structural warping or distortion**. Do not report diagnostic observations (e.g. “may indicate warping”) unless physical damage is confirmed.
  - 🔩 Hinge Condition: bent, loose, rusted, or broken hinges
  - 🧱 Frame Integrity: cracked, split, warped, or poorly fitted frame

- Do **not** include components that are simply missing or not visible — only report actual damage.
- If **any** of these components show visible damage, set `"door_damaged": true`.
- If **all** components are intact and undamaged, set `"door_damaged": false`.
- You must explicitly mention glazing damage in the `details` field if broken glass is visible. 
- If Door is not Damaged Compliance Status should be true else false


Return your findings in the following JSON format:
{
  "compliance_status": true | false, // Overall compliance status
  "door_damaged": true | false,
  "issues_found": [
    {
      "category": "Keep Shut Sign" | "Self-Closing Device" | "Intumescent Strips" | "Hold Open Device" | "Certification Visible" | "Contains Glazing" | "Pyro Glazing" | "Gaps" | "Hinges" | "Frame" | "Door Damage Check",
      "compliance_status": true | false,
      "details": "Brief explanation of what was observed"
    }
  ],
  "overall_comments": "Summary of the inspection and any recommendations"
}

Only include observations based on visible evidence in the image. Do not speculate beyond what is shown.
"""

# Claude API setup
        claude_api_key = os.getenv("ANTHROPIC_API_KEY")  # ✅ Correct key name from .env
        
        # Validate API key exists and is not empty
        if not claude_api_key or not claude_api_key.strip():
            return jsonify({"success": False, "error": "ANTHROPIC_API_KEY not found or empty in environment variables"}), 500
        
        # Strip any whitespace from API key
        claude_api_key = claude_api_key.strip()
        
        # Debug: Check if API key is properly loaded (without exposing full key)
        print(f"API Key loaded: {bool(claude_api_key)}, Length: {len(claude_api_key)}")
        
        headers = {
            "x-api-key": claude_api_key,  # ✅ Fixed: Anthropic API requires "x-api-key" header (lowercase)
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Try different models in order of preference (all support vision)
        # BEST FOR OBJECT DETECTION: Claude 3.5 Sonnet models (most accurate for detailed image analysis)
        models_to_try = [
            "claude-3-5-sonnet-20241022",  # ✅ BEST: Claude 3.5 Sonnet - Most advanced for object detection & detailed analysis
            # "claude-3-5-sonnet-20240620",  # Alternative Claude 3.5 Sonnet version
            # "claude-3-sonnet-20240229",  # Claude 3 Sonnet - Good accuracy (older but stable)
            # "claude-sonnet-4-20250514",  # If available (may not be standard API model)
            # "claude-3-haiku-20240307",  # Fastest but less detailed - use only if others fail
        ]
        
        last_error = None
        for model_name in models_to_try:
            payload = {
                "model": model_name,
                "max_tokens": 4096,  # ✅ Increased from 1000 to allow for comprehensive response
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": base64_image
                                }
                            }
                        ]
                             
                    }
                ]
            }
            
            # Send request to Claude with timeout (image analysis can take 60-120 seconds)
            try:
                response = httpx.post(
                    "https://api.anthropic.com/v1/messages", 
                    headers=headers, 
                    json=payload,
                    timeout=120.0  # 120 seconds timeout for image analysis
                )
            except httpx.TimeoutException:
                return jsonify({
                    "success": False, 
                    "error": f"Request timeout (120s) with model {model_name}. The image analysis is taking too long. Try with a smaller image or check your connection."
                }), 500
            except httpx.RequestError as e:
                return jsonify({
                    "success": False, 
                    "error": f"Request error with model {model_name}: {str(e)}"
                }), 500
            
            # If successful, break and use this result
            if response.status_code == 200:
                result = response.json()["content"][0]["text"]
                return jsonify({
                    "success": True, 
                    "detections": result,
                    "model_used": model_name  # ✅ Indicates which model successfully processed the request
                })
            
            # If 404, try next model; otherwise return error immediately
            if response.status_code != 404:
                # Non-404 error (401, 403, 500, etc.) - return immediately
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("error", {}).get("message", error_detail)
                except:
                    pass
                return jsonify({"success": False, "error": f"Anthropic API error ({response.status_code}) with model {model_name}: {error_detail}"}), 500
            
            # 404 error - save for fallback and try next model
            last_error = f"Model {model_name} not found (404)"
        
        # If all models failed with 404
        return jsonify({"success": False, "error": f"All models unavailable. Last error: {last_error}. Please check your Anthropic API access or try a different model."}), 500

    except Exception as e:
        # Handle runtime or API errors
        return jsonify({"success": False, "error": str(e)}), 500
    
# Main Entry Point
if __name__ == "__main__":
     # Start Flask server on port 5002
    app.run(host="0.0.0.0", port=5002, debug=True) 
