from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import requests
import os
import logging

app = Flask(__name__)

# 🌐 Secure CORS – adjust to your frontend domain
CORS(app, origins=["https://thepinpoint.info"])

# 🛑 Rate limiting – 5 requests/minute per IP
limiter = Limiter(get_remote_address, app=app, default_limits=["5 per minute"])

# 🔐 Load API keys from environment
google_api_key = os.getenv("GOOGLE_FACTCHECK_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")
pinpoint_api_key = os.getenv("PINPOINT_API_KEY")  # New: Protect your API

# 📝 Logging
logging.basicConfig(level=logging.INFO)

@app.route('/')
def home():
    return "PinPoint API is running securely!"

@app.route('/factcheck', methods=['GET'])
@limiter.limit("5 per minute")
def factcheck():
    # 🔐 Simple API token authentication
    auth_token = request.headers.get("X-API-Key")
    if auth_token != pinpoint_api_key:
        return jsonify({'error': 'Unauthorized'}), 401

    post = request.args.get('query')
    if not post:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': "", 'error': 'No post provided'}), 400

    # 🔍 Step 1 – Extract claim from post using OpenAI
    claim_extraction_prompt = f"""Extract a concise, fact-checkable claim from the following social media post:

"{post}"

Respond with only the claim."""

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
            timeout=10  # ✅ Timeout added
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

    # 🔗 Step 2 – Google Fact Check API
    factcheck_url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={claim}&key={google_api_key}"
    try:
        response = requests.get(factcheck_url, timeout=5)  # ✅ Timeout added
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

    # 🧠 Step 3 – Summarize result
    source = "Google Fact Check"
    if results:
        top_result = results[0]
        prompt = f"""Write a social media post that summarizes this fact check:

Claim: {top_result['claim']}
Rating: {top_result['rating']}
Source: {top_result['publisher']}
URL: {top_result['url']}
"""
    else:
        source = "OpenAI (No fact-check results)"
        prompt = f"""No fact-checks were found for the following claim:

"{claim}"

Write a responsible and informative social media response about this claim using your general knowledge."""

    try:
        openai_response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            },
            timeout=10  # ✅ Timeout added
        )
        openai_response.raise_for_status()
        openai_data = openai_response.json()
        summary = openai_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not summary:
            summary = "No summary could be generated."
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        summary = "OpenAI error: Unable to generate summary."

    # 📌 Add PinPoint branding
    summary += " 📌🧠 #PinPoint"

    return jsonify({
        "total": len(results_full),
        "results": results,
        "summary": summary,
        "claim": claim,
        "source": source,
        "error": None
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
