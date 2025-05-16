from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# ✅ Load API keys from environment variables
google_api_key = os.getenv("GOOGLE_FACTCHECK_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")

@app.route('/')
def home():
    return "PinPoint API is running!"

@app.route('/factcheck', methods=['GET'])
def factcheck():
    query = request.args.get('query')
    if not query:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'error': 'No query provided'}), 400

    # ✅ Build Fact Check API URL
    url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={query}&key={google_api_key}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'error': f'Failed to fetch from Fact Check API: {str(e)}'}), 500

    results_full = []
    for claim in data.get("claims", []):
        claim_review = claim.get("claimReview", [{}])[0]
        results_full.append({
            "claim": claim.get("text"),
            "rating": claim_review.get("textualRating"),
            "publisher": claim_review.get("publisher", {}).get("name"),
            "url": claim_review.get("url"),
            "reviewDate": claim_review.get("reviewDate")
        })

    results_full = [r for r in results_full if r.get("reviewDate")]
    results_full.sort(key=lambda x: x["reviewDate"], reverse=True)
    results = results_full[:1]  # Only the most recent result

    if not results:
        return jsonify({'results': [], 'total': 0, 'summary': "", 'error': 'No valid results found'}), 404

    # ✅ Compose summary prompt for OpenAI
    fact_string = f"""Summarize this fact-check as a social media post:

Claim: {results[0]['claim']}
Rating: {results[0]['rating']}
Publisher: {results[0]['publisher']}
URL: {results[0]['url']}
"""

    summary = ""
    try:
        openai_response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": fact_string}],
                "temperature": 0.7
            }
        )
        openai_response.raise_for_status()
        openai_data = openai_response.json()
        summary = openai_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not summary:
            summary = "No summary could be generated for this fact-check."

    except Exception as e:
        summary = f"OpenAI error: {str(e)}"

    return jsonify({
        "total": len(results_full),
        "results": results,
        "summary": summary,
        "error": None
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
