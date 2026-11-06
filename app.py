from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import os
import requests
import json
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["3 per minute"]
)

MASTER_SECRET = os.environ.get("MASTER_SECRET", os.urandom(32))
API_SIGNING_KEY = os.environ.get("API_SIGNING_KEY", os.urandom(32))

USED_NONCES = set()

def get_real_ip():
    for header in ["CF-Connecting-IP", "True-Client-IP", "X-Real-IP", "X-Forwarded-For"]:
        val = request.headers.get(header)
        if val:
            return val.split(",")[0].strip()
    return get_remote_address()

def analyze_client_behavior(ip, headers):
    if ip in ["127.0.0.1", "::1", "localhost"]:
        return False
    
    user_agent = headers.get("User-Agent", "").lower()
    if not user_agent or len(user_agent) < 5:
        return True 

    try:
        res = requests.get(f"https://ipwho.is/{ip}", timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            conn = data.get("connection", {})
            t = (conn.get("type", "") + conn.get("domain", "")).lower()
            if any(k in t for k in ["hosting", "datacenter", "vpn", "proxy", "tor", "server", "ovh", "hetzner", "digitalocean", "aws"]):
                return True
    except:
        pass
    return False

@app.after_request
def secure_headers(response):
    response.headers["Server"] = "Vortex-Core"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    return response

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Secure Oracle Online"}), 200

@app.route("/verify", methods=["POST"])
@limiter.limit("2 per minute")
def verify():
    ip = get_real_ip()
    
    if analyze_client_behavior(ip, request.headers):
        return jsonify({
            "error": "Access Denied: Automated or Suspicious Environment Detected.",
            "message": "try do it again and i we'll fuck you"
        }), 403

    data = request.get_json()
    if not data or not all(k in data for k in ["fingerprint", "timestamp", "nonce", "signature"]):
        return jsonify({
            "error": "Invalid payload structure.",
            "message": "try do it again and i we'll fuck you"
        }), 400

    timestamp = data["timestamp"]
    nonce = data["nonce"]

    if abs(time.time() - timestamp) > 8:
        return jsonify({
            "error": "Request timeout expired.",
            "message": "try do it again and i we'll fuck you"
        }), 403

    if nonce in USED_NONCES:
        return jsonify({
            "error": "Replay attack payload blocked.",
            "message": "try do it again and i we'll fuck you"
        }), 403
    
    if len(USED_NONCES) > 15000:
        USED_NONCES.clear()
    USED_NONCES.add(nonce)

    fingerprint = data["fingerprint"]
    client_signature = data["signature"]

    payload_check = {
        "fingerprint": fingerprint,
        "timestamp": timestamp,
        "nonce": nonce
    }
    canonical_data = json.dumps(payload_check, sort_keys=True).encode()
    expected_signature = hmac.new(API_SIGNING_KEY, canonical_data, hashlib.sha3_256).hexdigest()

    if not hmac.compare_digest(expected_signature, client_signature):
        return jsonify({
            "error": "Cryptographic signature validation failed.",
            "message": "try do it again and i we'll fuck you"
        }), 403

    expected_fp = hashlib.sha3_256(b"VALID_ENVIRONMENT_SIGNATURE").hexdigest()
    if not hmac.compare_digest(expected_fp, fingerprint):
        return jsonify({
            "error": "Environment integrity check failed.",
            "message": "try do it again and i we'll fuck you"
        }), 403

    salt = os.urandom(32)
    hkdf = HKDF(
        algorithm=hashes.SHA3_256(),
        length=32,
        salt=salt,
        info=b"vortex_isolated_session_derivation",
        backend=default_backend()
    )
    dynamic_key = hkdf.derive(MASTER_SECRET)

    return jsonify({
        "status": "success",
        "salt": salt.hex(),
        "dynamic_key": dynamic_key.hex()
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
