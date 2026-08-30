#!/usr/bin/env python3
"""Local-first JARVIS bridge with bounded, explicit execution paths."""
from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import subprocess
from typing import Any, Sequence

from flask import Flask, jsonify, request


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = _env_int("JARVIS_MAX_REQUEST_BYTES", 16_384)

MAX_QUERY_CHARS = _env_int("JARVIS_MAX_QUERY_CHARS", 2_000)
MAX_OUTPUT_CHARS = _env_int("JARVIS_MAX_OUTPUT_CHARS", 8_000)
TEMP_CRITICAL = _env_float("JARVIS_TEMP_CRITICAL_C", 48.0)
COMMAND_TIMEOUT = _env_float("JARVIS_COMMAND_TIMEOUT_S", 30.0)
AI_TIMEOUT = _env_float("JARVIS_AI_TIMEOUT_S", 30.0)
AUTH_TOKEN = os.getenv("JARVIS_AUTH_TOKEN")

# Direct actions are exact, allowlisted argv arrays. No user input reaches a shell.
DIRECT_COMMANDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "list files": ("list files", ("ls", "-la")),
    "time": ("time", ("date",)),
    "date": ("date", ("date",)),
    "whoami": ("whoami", ("whoami",)),
    "ip": ("public ip", ("curl", "-fsS", "--max-time", "5", "https://ifconfig.me")),
    "memory": ("memory", ("free", "-h")),
    "disk": ("disk", ("df", "-h")),
    "battery": ("battery", ("termux-battery-status",)),
}


def get_temperature() -> float | None:
    """Read Termux battery temperature without making a missing device fatal."""
    try:
        result = subprocess.run(
            ["termux-battery-status"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        payload: Any = json.loads(result.stdout)
        value = payload.get("temperature") if isinstance(payload, dict) else None
        return float(value) if isinstance(value, (int, float)) else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def speak(text: str) -> bool:
    """Best-effort local TTS; an unavailable TTS binary never breaks an API response."""
    binary = shutil.which("termux-tts-speak")
    if not binary:
        return False
    try:
        subprocess.run(
            [binary, text[:300]],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


def _bounded_output(value: str) -> str:
    value = value.strip()
    if len(value) <= MAX_OUTPUT_CHARS:
        return value or "(no output)"
    return value[:MAX_OUTPUT_CHARS] + "\n[output truncated]"


def execute_command(command: Sequence[str]) -> tuple[str, int | None]:
    """Run one pre-approved argv array with explicit timeout and output bounds."""
    if not command or not shutil.which(command[0]):
        return f"Command unavailable: {command[0] if command else 'unknown'}", None
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "Command timed out.", None
    except OSError as error:
        return f"Command could not start: {error.strerror or 'operating system error'}", None
    output = _bounded_output("\n".join(part for part in (result.stdout, result.stderr) if part))
    return output, result.returncode


def _clean_ai_answer(value: str) -> str:
    value = re.sub(r"[\u2800-\u28ff]", "", value)
    return "\n".join(line for line in value.splitlines() if "loading" not in line.casefold()).strip()


@app.before_request
def require_authentication():
    if request.path != "/jarvis" or not AUTH_TOKEN:
        return None
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {AUTH_TOKEN}"
    if not hmac.compare_digest(supplied, expected):
        return jsonify({"error": "Authentication required"}), 401
    return None


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "Request is too large"}), 413


@app.route("/jarvis", methods=["POST"])
def jarvis():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    raw_query = data.get("query")
    if not isinstance(raw_query, str):
        return jsonify({"error": "Query must be a string"}), 400
    query = " ".join(raw_query.split())
    if not query:
        return jsonify({"error": "Missing query"}), 400
    if len(query) > MAX_QUERY_CHARS:
        return jsonify({"error": f"Query exceeds {MAX_QUERY_CHARS} characters"}), 413

    temperature = get_temperature()
    if temperature is not None and temperature >= TEMP_CRITICAL:
        message = f"Overheating: {temperature:.1f}°C. Aborting."
        speak(message)
        return jsonify({"status": "aborted", "message": message, "temperature_c": temperature}), 503

    direct_key = query.casefold().rstrip("?.!")
    direct = DIRECT_COMMANDS.get(direct_key)
    if direct:
        label, command = direct
        speak(f"Running: {label}")
        output, returncode = execute_command(command)
        if returncode != 0:
            return jsonify({"status": "error", "mode": "direct", "command": label, "output": output}), 502
        speak(output[:200])
        return jsonify({"status": "success", "mode": "direct", "command": label, "output": output})

    if not shutil.which("tgpt"):
        message = "AI is offline: tgpt is not installed or not on PATH."
        speak(message)
        return jsonify({"status": "error", "mode": "ai", "message": message}), 503

    try:
        result = subprocess.run(
            ["tgpt", query],
            capture_output=True,
            text=True,
            timeout=AI_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        result = None

    answer = _clean_ai_answer(result.stdout) if result and result.returncode == 0 else ""
    if answer:
        answer = _bounded_output(answer)
        speak(answer)
        return jsonify({"status": "success", "mode": "ai", "response": answer})

    message = "AI is offline or returned no usable response."
    speak(message)
    return jsonify({"status": "error", "mode": "ai", "message": message}), 503


@app.route("/health", methods=["GET"])
def health():
    temperature = get_temperature()
    if temperature is None:
        thermal_status = "unknown"
        service_status = "alive"
    elif temperature >= TEMP_CRITICAL:
        thermal_status = "critical"
        service_status = "degraded"
    else:
        thermal_status = "normal"
        service_status = "alive"
    return jsonify(
        {
            "status": service_status,
            "temp": temperature,
            "temperature_c": temperature,
            "thermal_guard": thermal_status,
        }
    )


if __name__ == "__main__":
    host = os.getenv("JARVIS_HOST", "127.0.0.1")
    port = _env_int("JARVIS_PORT", _env_int("PORT", 5000))
    print(f"JARVIS starting on {host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)
