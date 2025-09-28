from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import logging
from typing import List, Tuple

# ======================================
# 🔧 App setup
# ======================================
app = Flask(__name__)
CORS(app, origins=["https://thepinpoint.info"])
logging.basicConfig(level=logging.INFO)

# ======================================
# 🔐 Environment Variables + validation
# ======================================
def require_env(var_name: str) -> str:
    val = os.getenv(var_name)
    if not val:
        # Fail fast with a clear message Bubble can show you
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return val

google_api_key = require_env("GOOGLE_FACTCHECK_API_KEY")
openai_api_key = require_env("OPENAI_API_KEY")
pinpoint_api_key = require_env("pinpoint_api_key")

pinpoint_openai_instructions_with_factcheck = os.getenv(
    "PINPOINT_OPENAI_INSTRUCTIONS_WITH_FACTCHECK", ""
)
pinpoint_openai_instructions_no_factcheck = os.getenv(
    "PINPOINT_OPENAI_INSTRUCTIONS_NO_FACTCHECK", ""
)

# Allow easy model swaps / fallbacks (in order). First item can be overridden via env.
MODEL_CANDIDATES: List[str] = [
    os.getenv("PINPOINT_OPENAI_MODEL", "gpt-5"),
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4o",
]

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_HEADERS = {
    "Authorization": f"Bearer {openai_api_key}",
    "Content-Type": "application/json",
}

# ======================================
# 🧠 Responses API helpers
# ======================================
def _responses_api_text(resp_json: dict) -> str:
    """
    Extract assistant text from the OpenAI Responses API JSON.
    Works across current snapshots and falls back gracefully.
    """
    try:
        # Primary structured path
        outputs = resp_json.get("output", [])
        for item in outputs:
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") in ("output_text", "text"):
                        t = c.get("text")
                        if isinstance(t, str) and t.strip():
                            return t.strip()
        # Convenience field exposed by some SDKs
        if isinstance(resp_json.get("output_text"), str):
            return resp_json["output_text"].strip()
    except Exception as e:
        logging.error(f"Responses parse error: {e}")
    return ""


def _openai_responses_call(prompt: str, temperature: float = 0.5) -> Tuple[str, str]:
    """
    Try each candidate model until one succeeds.
    Returns (text, model_used). Raises an Exception if all fail.
    """
    last_err: Exception | None = None
    for model in MODEL_CANDIDATES:
        try:
            r = requests.post(
                OPENAI_RESPONSES_URL,
                headers=OPENAI_HEADERS,
                json={
                    "model": model,
                    "input": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    # Optional reasoning control if your org has it enabled:
                    # "reasoning": {"effort": "low"},
                },
                timeout=20,
            )
            if r.status_code >= 400:
                logging.warning(f"OpenAI {model} failed: {r.status_code} {r.text[:500]}")
                # If model not accessible, try next candidate
                if r.status_code in (403, 404):
                    last_err = RuntimeError(f"Model {model} not accessible: {r.text}")
                    continue
                r.raise_for_status()

            text = _responses_api_text(r.json())
            if text:
                return text, model

            last_err = RuntimeError(f"Empty output from model {model}")
        except Exception as e:
            logging.warning(f"OpenAI call error with {model}: {e}")
            last_err = e
            continue

    raise last_err or RuntimeError("All OpenAI models failed")


# ======================================
# 🌐 Routes
# ======================================
@app.route("/")
def home():
    return "PinPoint API is running securely!"


@app.route("/health", methods=["GET"])
def health():
    """
    Lightweight health check (does not call OpenAI).
    Confirms critical envs exist and returns OK.
    """
    return jsonify(
        {
            "ok": True,
            "google_api_key": bool(google_api_key),
            "openai_api_key": bool(openai_api_key),
            "pinpoint_api_key": bool(pinpoint_api_key),
            "model_candidates": MODEL_CANDIDATES,
        }
    )


@app.route("/factcheck", methods=["GET"])
def factcheck():
    # 🔐 Simple header auth for Bubble or front-end calls
    auth_token = request.headers.get("X-API-Key")
    if auth_token != pinpoint_api_key:
        return jsonify({"error": "Unauthorized"}), 401

    post = request.args.get("query")
    if not post:
        return (
            jsonify(
                {
                    "results": [],
                    "total": 0,
                    "summary": "",
                    "claim": "",
                    "error": "No post provided",
                }
            ),
            400,
        )

    # === 1) Claim Extraction (GPT-5 via Responses API) ===
    claim_extraction_prompt = (
        f'Extract a concise, fact-checkable claim or hypothesis from the following social media post:\n\n"{post}"\n\n'
        "Respond with only the claim or hypothesis."
    )
    try:
        claim, model_used = _openai_responses_call(
            claim_extraction_prompt, temperature=0.5
        )
        claim = (claim or "").strip()
        logging.info(f"[PinPoint] Extracted Claim via {model_used}: {claim}")
    except Exception as e:
        logging.error(f"Claim extraction failed: {e}")
        return (
            jsonify(
                {
                    "results": [],
                    "total": 0,
                    "summary": "",
                    "claim": "",
                    "error": f"Claim extraction failed: {str(e)}",
                }
            ),
            500,
        )

    if not claim:
        return (
            jsonify(
                {
                    "results": [],
                    "total": 0,
                    "summary": "",
                    "claim": "",
                    "error": "No claim could be extracted.",
                }
            ),
            400,
        )

    # === 2) Fact Check Lookup (Google Fact Check API) ===
    factcheck_url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={requests.utils.quote(claim)}&key={google_api_key}"
    try:
        response = requests.get(factcheck_url, timeout=8)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Fact Check API error: {e}")
        return (
            jsonify(
                {
                    "results": [],
                    "total": 0,
                    "summary": "",
                    "claim": claim,
                    "error": "Internal error during fact check lookup",
                }
            ),
            500,
        )

    results_full = []
    for item in data.get("claims", []):
        review = (item.get("claimReview") or [{}])[0]
        results_full.append(
            {
                "claim": item.get("text"),
                "rating": review.get("textualRating"),
                "publisher": (review.get("publisher") or {}).get("name"),
                "url": review.get("url"),
                "reviewDate": review.get("reviewDate"),
            }
        )

    # Sort newest first, keep top 5
    results_full = [r for r in results_full if r.get("reviewDate")]
    results_full.sort(key=lambda x: x["reviewDate"], reverse=True)
    results = results_full[:5]

    # === 3) Summary Generation (GPT-5 via Responses API) ===
    source = "Unknown"
    if results:
        source = "Google Fact Check"
        instructions = pinpoint_openai_instructions_with_factcheck
        top = results[0]
        prompt = (
            f"{instructions}\n\n"
            "Write a social media post that not only summarizes this fact check claim or hypothesis "
            "but sounds like a non-AI person wrote it. Feel free to use humor and human tones and it does not have to be grammatically correct:\n\n"
            f'Claim: {top["claim"]}\nRating: {top["rating"]}\nSource: {top["publisher"]}\nURL: {top["url"]}'
        )
    else:
        source = "OpenAI (No fact-check results)"
        instructions = pinpoint_openai_instructions_no_factcheck
        prompt = (
            f"{instructions}\n\n"
            f'No official fact-checks were found for this claim:\n\n"{claim}"\n\n'
            "Write a short, responsible social media post that explains what the public should consider about this claim. "
            "Use general knowledge and avoid speculation. Use a non-AI person tone so someone does not speculate that AI wrote it. "
            "Use humor.  Grammer does not have to be followed."
        )

    try:
        summary, sum_model = _openai_responses_call(prompt, temperature=0.7)
        logging.info(f"[PinPoint] Summary via {sum_model}")
    except Exception as e:
        logging.error(f"Summary generation failed: {e}")
        summary = "OpenAI error: Unable to generate summary."

    if not summary:
        summary = "No summary was generated."
    summary += " 📌🧠 #PinPoint"

    return jsonify(
        {
            "total": len(results_full),
            "results": results,
            "summary": summary,
            "claim": claim,
            "source": source,
            "error": None,
        }
    )


# ======================================
# ⚠️ Global error handler
# ======================================
@app.errorhandler(500)
def handle_internal_error(error):
    return jsonify({"error": "An internal server error occurred."}), 500


# ======================================
# 🚀 Entry
# ======================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
