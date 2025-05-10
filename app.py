from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

api_key = 'AIzaSyBzCuON3M4Jg_wKY-EIlTxexqjjILLt76I'

@app.route('/')
def home():
    return "PinPoint API is running!"

@app.route('/factcheck', methods=['GET'])
def factcheck():
    query = request.args.get('query')
    if not query:
        return jsonify({'results': [], 'total': 0, 'error': 'No query provided'}), 400

    url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={query}&key={api_key}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return jsonify({'results': [], 'total': 0, 'error': f'Failed to fetch from Fact Check API: {str(e)}'}), 500

    data = response.json()
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
    results = results_full[:5]

    return jsonify({
        "total": len(results_full),
        "results": results,
        "error": None
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
