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
        return jsonify({'error': 'No query provided'}), 400

    url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={query}&key={api_key}"
    response = requests.get(url)

    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch from Fact Check API'}), 500

    data = response.json()
    results = []

    for claim in data.get("claims", []):
        claim_review = claim.get("claimReview", [{}])[0]

        results.append({
            "claim": claim.get("text"),
            "rating": claim_review.get("textualRating"),
            "publisher": claim_review.get("publisher", {}).get("name"),
            "url": claim_review.get("url"),
            "reviewDate": claim_review.get("reviewDate")
        })

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
