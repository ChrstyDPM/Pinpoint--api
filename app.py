from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import logging

# 🔧 App setup
app = Flask(__name__)
CORS(app, origins=["https://thepinpoint.info"])

# 🔐 Environment Variables
google_api_key = os.getenv("GOOGLE_FACTCHECK_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")
pinpoint_api_key = os.getenv("pinpoint_api_key")
pinpoint_openai_instructions_with_factcheck = os.getenv("PINPOINT_OPENAI_INSTRUCTIONS_WITH_FACTCHECK", "")
pinpoint_openai_instructions_no_factcheck = os.getenv("PINPOINT_OPENAI_INSTRUCTIONS_NO_FACTCHECK", "")

# Allow easy model swaps / fallbacks
pinpoint_openai_model = os.getenv("PINPOINT_OPENAI_MODEL", "gpt-5")  # try "gpt-5-mini" if you want cheaper

# 📝 Logging
logging.basicConfig(level=logging.INFO)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_HEADERS = {
    "Authorization": f"Bearer {openai_api_key}",
    "Content-Type": "application/json"
}

def _responses_api_text(resp_json: dict) -> str:
    """
    Extract assistant text from the Responses API JSON.
    Falls back gracefully if the structure changes.
    """
    try:
        # Primary path (Responses API)
        outputs = resp_json.get("output", [])
        for item in outputs:
            if item.get("type") == "message":
                content = item.get("content", [])
                for c in content:
                    # text can show up as output_text or text, depending on snapshot
                    if c.get("type") in ("output_text", "text"):
                        if isinstance(c.get("text"), str):
                            return c["text"].strip()
        # Some snapshots expose a convenience field (SDK usually provides .output_text)
        if "output_text" in resp_json and isinstance(resp_json["output_text"], str):
            return resp_json["output_text"].strip()
    except Exception as e:
        logging.error(f"Failed to parse Responses API payload: {e}")
    return ""

@app.route('/')
def home():
    return "PinPoint API is running securely!"

@app.route('/factcheck', methods=['GET'])
def factcheck():
    # 🔐 Simple header auth
    auth_token = request.headers.get("X-API-Key")
    if auth_token != pinpoint_api_key:
        return jsonify({'error': 'Unauthorized'}), 401

    post = request.args.get('query')
    if not post:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': "", 'error': 'No post provided'}), 400

    # === 1) Claim Extraction (GPT-5 via Responses API) ===
    claim_extraction_prompt = (
        f'Extract a concise, fact-checkable claim or hypothesis from the following social media post:\n\n"{post}"\n\n'
        'Respond with only the claim or hypothesis.'
    )
    claim = ""
    try:
        claim_resp = requests.post(
            OPENAI_RESPONSES_URL,
            headers=OPENAI_HEADERS,
            json={
                "model": pinpoint_openai_model,
                # You can also pass a list of messages, but plain input is fine here.
                "input": [
                    {"role": "user", "content": claim_extraction_prompt}
                ],
                "temperature": 0.5,
                # Optional: GPT-5 reasoning controls if enabled for your org
                # "reasoning": {"effort": "low"}
            },
            timeout=15
        )
        claim_resp.raise_for_status()
        claim = _responses_api_text(claim_resp.json())
        claim = (claim or "").strip()
    except Exception as e:
        logging.error(f"Error extracting claim: {e}")
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': "", 'error': 'Internal error during claim extraction'}), 500

    if not claim:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': "", 'error': 'No claim could be extracted.'}), 400

    logging.info(f"[PinPoint] Extracted Claim: {claim}")

    # === 2) Fact Check Lookup (Google Fact Check API) ===
    factcheck_url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={claim}&key={google_api_key}"
    try:
        response = requests.get(factcheck_url, timeout=8)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Fact Check API error: {e}")
        return jsonify({'results': [], 'total': 0, 'summary': "", 'claim': claim, 'error': 'Internal error during fact check lookup'}), 500

    results_full = []
    for item in data.get("claims", []):
        review = (item.get("claimReview") or [{}])[0]
        results_full.append({
            "claim": item.get("text"),
            "rating": review.get("textualRating"),
            "publisher": (review.get("publisher") or {}).get("name"),
            "url": review.get("url"),
            "reviewDate": review.get("reviewDate")
        })

    results_full = [r for r in results_full if r.get("reviewDate")]
    results_full.sort(key=lambda x: x["reviewDate"], reverse=True)
    results = results_full[:5]

    # === 3) Summary Generation (GPT-5 via Responses API) ===
    source = "Unknown"
    summary = ""
    if results:
        source = "Google Fact Check"
        instructions = pinpoint_openai_instructions_with_factcheck
        top = results[0]
        prompt = (
            f"{instructions}\n\n"
            f'Write a social media post that not only summarizes this fact check claim or hypothesis but sounds like a non-AI person wrote it. Feel free to use humor and human tones and it does not have to be grammatically correct:\n\n'
            f'Claim: {top["claim"]}\nRating: {top["rating"]}\nSource: {top["publisher"]}\nURL: {top["url"]}'
        )
    else:
        source = "OpenAI (No fact-check results)"
        instructions = pinpoint_openai_instructions_no_factcheck
        prompt = (
            f"{instructions}\n\n"
            f'No official fact-checks were found for this claim:\n\n"{claim}"\n\n'
            'Write a short, responsible social media post that explains what the public should consider about this claim. Use general knowledge and avoid speculation. Use a non-AI person tone so someone does not speculate that AI wrote it. Use humor.  Grammer does not have to be followed.'
        )

    try:
        sum_resp = requests.post(
            OPENAI_RESPONSES_URL,
            headers=OPENAI_HEADERS,
            json={
                "model": pinpoint_openai_model,
                "input": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                # Optional: enable if you want to experiment
                # "reasoning": {"effort": "low"}
            },
            timeout=20
        )
        sum_resp.raise_for_status()
        summary = _responses_api_text(sum_resp.json()).strip() or "This topic could not be summarized at this time."
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        summary = "OpenAI error: Unable to generate summary."

    if not summary:
        summary = "No summary was generated."
    summary += " 📌🧠 #PinPoint"

    return jsonify({
        "total": len(results_full),
        "results": results,
        "summary": summary,
        "claim": claim,
        "source": source,
        "error": None
    })

@app.errorhandler(500)
def handle_internal_error(error):
    return jsonify({'error': 'An internal server error occurred.'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
