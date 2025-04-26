from flask import Flask, request, jsonify
import requests

app = Flask(__name__)  # <<< FIXED here

api_key = 'AIzaSyBzCuON3M4Jg_wKY-EIlTxexqjjILLt76I'

@app.route('/factcheck', methods=['GET'])  
def fact_check():
    query = request.args.get('query')
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={query}&key={api_key}"
    response = requests.get(url)
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

if __name__ == '__main__':  # <<< FIXED here
    app.run(debug=True)
