# Project Genesis JARVIS

A local-first JARVIS HTTP bridge for Termux and small local environments.

## Stability and safety model

- Direct commands are an exact allowlist of argv arrays. User text is never passed to a shell.
- The service binds to 127.0.0.1 by default. Only bind to a network interface deliberately.
- Set JARVIS_AUTH_TOKEN before using a non-local bind so POST requests require a Bearer token.
- Request bodies, query length, command time, AI time, and response output are bounded.
- Thermal checks are performed once per request. Missing Termux battery support reports an unknown guard state instead of inventing a temperature.
- TTS and AI tools are optional integrations. Their absence returns an explicit error rather than crashing the service.

## Install

Use Python 3.10 or newer:

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt

Run the regression tests with:

    python -m unittest discover -s tests -v

Start the service with:

    python jarvis_server.py

The default listener is http://127.0.0.1:5000.

## API

Health check:

    GET /health

Command or AI request:

    POST /jarvis
    Content-Type: application/json
    {"query": "list files"}

Direct commands are: list files, time, date, whoami, ip, memory, disk, and battery. Any other query is sent to tgpt when it is installed.

## Configuration

- JARVIS_HOST: listener address, default 127.0.0.1
- JARVIS_PORT: listener port, default PORT or 5000
- JARVIS_AUTH_TOKEN: optional Bearer token for /jarvis
- JARVIS_TEMP_CRITICAL_C: thermal abort threshold, default 48
- JARVIS_MAX_REQUEST_BYTES: request size limit, default 16384
- JARVIS_MAX_QUERY_CHARS: query limit, default 2000
- JARVIS_MAX_OUTPUT_CHARS: output limit, default 8000
- JARVIS_COMMAND_TIMEOUT_S: direct command timeout, default 30
- JARVIS_AI_TIMEOUT_S: tgpt timeout, default 30

Never commit a real authentication token. Provide it through the runtime environment.
