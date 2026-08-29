#!/usr/bin/env python3
import os, json, subprocess, re
from flask import Flask, request, jsonify

app = Flask(__name__)
TEMP_CRITICAL = 48

def get_temp():
    try:
        out = subprocess.check_output(["termux-battery-status"], text=True)
        return json.loads(out).get("temperature", 35)
    except:
        return 35

def speak(text):
    try:
        subprocess.run(["termux-tts-speak", text], check=False)
    except:
        pass

def execute(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr
    except:
        return "Command timed out."

@app.route('/jarvis', methods=['POST'])
def jarvis():
    data = request.get_json()
    query = data.get('query', '').strip()
    if not query:
        return jsonify({"error": "Missing query"}), 400

    # Thermal safety
    if get_temp() >= TEMP_CRITICAL:
        msg = f"Overheating: {get_temp()}°C. Aborting."
        speak(msg)
        return jsonify({"status": "aborted", "message": msg})

    # Direct commands (no AI)
    simples = {
        "list files": "ls -la", "time": "date", "date": "date",
        "whoami": "whoami", "ip": "curl -s ifconfig.me",
        "memory": "free -h", "disk": "df -h", "battery": "termux-battery-status"
    }
    for key, cmd in simples.items():
        if key in query.lower():
            speak(f"Running: {cmd}")
            out = execute(cmd)
            speak(out[:200])
            return jsonify({"status": "success", "mode": "direct", "output": out})

    # AI via tgpt
    try:
        result = subprocess.run(["tgpt", query], capture_output=True, text=True, timeout=30)
        answer = result.stdout.strip()
        if answer:
            # Clean Loading/Spinners
            answer = re.sub(r'[\u2800-\u28FF]', '', answer)
            answer = '\n'.join([l for l in answer.splitlines() if "Loading" not in l])
            speak(answer[:300])
            return jsonify({"status": "success", "mode": "ai", "response": answer})
    except Exception as e:
        pass

    fallback = f"I heard: '{query}', but AI is offline."
    speak(fallback)
    return jsonify({"status": "error", "message": fallback})

@app.route('/health')
def health():
    return jsonify({"status": "alive", "temp": get_temp()})

if __name__ == '__main__':
    print("🔥 Fresh JARVIS starting on port 5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
