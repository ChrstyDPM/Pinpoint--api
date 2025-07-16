from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import requests
import os
import logging

# 🔧 App setup
app = Flask(__name__)
CORS(app, origins=["https://thepinpoint.info"])

# 🧠 Use hosted Redis (Upstash) from env variable
redis_uri = os.getenv("REDIS_URL", "redis://localhost:6379")
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=redis_uri
)

# 🔐 API keys from environment
google_api_key = os.getenv("GOOGLE_FACTCHECK_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")
pinpoint_api_key = os.getenv("pinpoint_api_key")

# 📋 Instruction environment variables
pinpoint_openai_instructions_with_factcheck = os.getenv("PINPOINT_OPENAI_INSTRUCTIONS_WITH_FACTCHECK", "")
pinpoint_openai_instructions_no_factcheck = os.getenv("PINPOINT_OPENAI_INSTRUCTIONS_NO_FACTCHECK", "")

# 📝 Logging
logging.basicConfig(level=logging.INFO)

@app.route('/')
def home():
    return "PinPoint API is running securely!"

@app.route('/factcheck', methods=['GET'])
@limiter.limit("5 per minute")
def factcheck():
    auth_token = request.headers.get("X-API-Key")
    if auth_token != pinpoint_api_key:
        return jsonify({'error': 'Unauthorized'}), 401

    post = request.args.get('query')
    if not post:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': "", 'error': 'No post provided'}), 400

    # 🧠 Claim Extraction
    claim_extraction_prompt = (
        f'Extract a concise, fact-checkable claim or hypothesis from the following social media post:\n\n"{post}"\n\n'
        'Respond with only the claim or hypothesis.'
    )

    try:
        claim_response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": claim_extraction_prompt}],
                "temperature": 0.5
            },
            timeout=10
        )
        claim_response.raise_for_status()
        claim_data = claim_response.json()
        claim = claim_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        logging.error(f"Error extracting claim: {e}")
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': "", 'error': 'Internal error during claim extraction'}), 500

    if not claim:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': "", 'error': 'No claim could be extracted.'}), 400

    logging.info(f"[PinPoint] Extracted Claim: {claim}")

    # 🔎 Fact Check Lookup
    factcheck_url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={claim}&key={google_api_key}"
    try:
        response = requests.get(factcheck_url, timeout=5)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Fact Check API error: {e}")
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': claim, 'error': 'Internal error during fact check lookup'}), 500

    results_full = []
    for item in data.get("claims", []):
        review = item.get("claimReview", [{}])[0]
        results_full.append({
            "claim": item.get("text"),
            "rating": review.get("textualRating"),
            "publisher": review.get("publisher", {}).get("name"),
            "url": review.get("url"),
            "reviewDate": review.get("reviewDate")
        })

    results_full = [r for r in results_full if r.get("reviewDate")]
    results_full.sort(key=lambda x: x["reviewDate"], reverse=True)
    results = results_full[:5]

    # 🧾 Summary Generation
    if results:
        source = "Google Fact Check"
