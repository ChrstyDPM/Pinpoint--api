from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

api_key = 'AIzaSyBzCuON3M4Jg_wKY-EIlTxexqjjILLt76I'

@app.route('/')
def home():
    return "PinPoint API is running!"


    url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={query}&key={api_key}"
    response = requests.get(url)

    # 👇👇👇 THIS must be INSIDE the function, not floating by itself
    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch from Fact Check API'}), 500

    data = response.json()

    results = []
    for claim in data.get("claims", []):
        results.append({
            "claim": claim.get("text"),
            "rating": claim.get("claimReview", [{}])[0].get("textualRating"),
            "publisher": claim.get("claimReview", [{}])[0].get("publisher", {}).get("name"),
            "url": claim.get("claimReview", [{}])[0].get("url")
        })

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
