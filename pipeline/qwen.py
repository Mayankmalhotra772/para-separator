"""Qwen client: one streamed completion, thinking off.

Streaming is not cosmetic. Cloudflare fronts the public endpoint and kills a
connection that has sent nothing for ~100 seconds, so every request long enough
to matter died with HTTP 524 and retrying hit the same wall. It also 403s the
default Python-urllib user agent, hence the explicit header.

Key comes from GST_API_KEY, else ./.gst_api_key, else ~/.gst_api_key - never a
command-line argument, so it stays out of shell history.
"""

import json
import os
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

URL = os.environ.get("GST_API_URL", "https://api.jaypokale.me/v1")
MODEL = os.environ.get("GST_MODEL", "Qwen/Qwen3.6-27B-FP8")

# The OCR stage needs a model that accepts images, which the text model need not
# be - sarvam-105b-fp8 answers "is not a multimodal model" to an image payload.
# So vision has its own endpoint, defaulting to the main one when unset.
VLM_URL = os.environ.get("GST_VLM_URL", URL)
VLM_MODEL = os.environ.get("GST_VLM_MODEL", MODEL)
VLM_KEY = os.environ.get("GST_VLM_KEY", "")

RETRIES = 3

# Thinking is off by default and has to be asked for. Left on, sarvam-105b-fp8
# spends the whole budget reasoning - 600 tokens of it on "reply with the single
# word OK", finish_reason "length", no answer - and a reply extraction comes back
# as JSON cut off mid-string. GST_THINK=1 turns it back on for comparison.
THINK_ON = os.environ.get("GST_THINK", "").lower() not in ("", "0", "false", "no")

# GST_JSON_MODE asks the server to constrain decoding to valid JSON. Off by
# default because Qwen already returns valid JSON and there is no reason to
# change a working path. It is what makes sarvam-105b-fp8 usable at all: left to
# itself it closes an array with a quote, leaks </arg_value> into the object, or
# never closes the outer brace, and a document it had read correctly parses to
# nothing. With it, the same call returns 7-8 items instead of 0-4.
JSON_MODE = os.environ.get("GST_JSON_MODE", "").lower() not in ("", "0", "false", "no")

# Some models reason inline and hand back "<think>...</think>" ahead of the
# answer, ignoring enable_thinking entirely. The reasoning is not the reply, and
# leaving it in would let it reach a workbook cell or be counted as grounding.
THINK = re.compile(r"<think>.*?</think>\s*", re.S)
OPEN_THINK = re.compile(r"<think>.*\Z", re.S)


def strip_think(text):
    text = THINK.sub("", text)
    # A reply cut off by max_tokens can open <think> and never close it.
    return OPEN_THINK.sub("", text).strip()


def _key():
    k = os.environ.get("GST_API_KEY", "").strip()
    if k:
        return k
    for p in (ROOT / ".gst_api_key", Path.home() / ".gst_api_key"):
        if p.exists():
            return p.read_text().strip()
    return ""


KEY = _key()


def post(payload, url=None, key=None):
    payload = dict(payload, stream=True)
    req = urllib.request.Request(
        f"{url or URL}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key or KEY}",
                 "User-Agent": "para-separator/2.0",
                 "Accept": "text/event-stream"},
    )
    parts = []
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                delta = json.loads(body)["choices"][0].get("delta", {})
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta.get("content"):
                parts.append(delta["content"])
    return "".join(parts)


def chat(system, user, max_tokens=4000):
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": THINK_ON},
    }
    if JSON_MODE:
        payload["response_format"] = {"type": "json_object"}
    last = None
    for attempt in range(RETRIES):
        try:
            return strip_think(post(payload))
        # Deliberately broad: under load http.client raises ValueError on a
        # socket that died mid-flush, which is not a URLError and used to kill
        # the whole worker thread instead of retrying the one call.
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"model call failed after {RETRIES} tries: {last}")
