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
        return jsonify({'error':
