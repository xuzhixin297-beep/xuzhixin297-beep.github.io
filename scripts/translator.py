"""
Translate English text into Simplified Chinese with an
OpenAI-compatible chat completion API.

The default provider is DeepSeek. Any OpenAI-compatible endpoint
can be used by setting:

    ZH_API_BASE   e.g. https://api.deepseek.com
    ZH_API_KEY    the provider API key
    ZH_MODEL      e.g. deepseek-chat

When no key is configured, a locally running DSH gateway is used
for development:

    http://127.0.0.1:8326/v1
    model: deepseek-account/deepseek-flash

The local gateway only exists while the DSH desktop app is running,
so continuous integration must provide ZH_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


# ==================================================
# Configuration
# ==================================================

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

LOCAL_GATEWAY_KEY_FILE = (
    Path.home() / ".dsh" / "openai-gateway" / "api-key"
)
LOCAL_GATEWAY_BASE_URL = "http://127.0.0.1:8326/v1"
LOCAL_GATEWAY_MODEL = "deepseek-account/deepseek-flash"

# Long Markdown pages are split at paragraph boundaries.
MAX_CHARS = 1800

# Pause between requests so the provider never rate-limits us.
REQUEST_INTERVAL = 0.2

MAX_RETRIES = 4
RETRY_DELAY = 2.0
TIMEOUT_SECONDS = 90

TEMPERATURE = 0.2

# Every protected fragment uses this shape (brand, inline and block
# placeholders all share it), which the model must copy unchanged.
PLACEHOLDER_PATTERN = re.compile(r"ZXQ[A-Z0-9_]*QXZ")

SYSTEM_PROMPT = """\
You are a professional translator working on a personal knowledge website about physics, mathematics, and philosophy. You translate English into natural, precise Simplified Chinese.

Rules:
1. Output only the translation. No explanations, no quotation marks around it, no markdown fences.
2. Copy every placeholder token of the form ZXQ...QXZ exactly once and unchanged.
3. Keep LaTeX commands and mathematical content unchanged.
4. Preserve the author's tone: thoughtful, elegant, sometimes informal. Do not make it sound like a textbook.
5. The input may be only a fragment of a larger sentence (for example a link label, a heading, or text interrupted by inline markup). Translate the fragment as a fragment: do not invent missing words and do not add punctuation that is not implied.
6. Never translate proper nouns, code, URLs, or the website name Antemundane sprǣc.
7. Short labels (link text, navigation items, headings of one or two words) must become the concise, conventional Chinese label. Never replace a word with a different concept, and keep the label as short as the original.
8. If the input ends in the middle of a sentence, the Chinese must also end in the middle; do not complete it.
"""

_last_request_time = 0.0


# ==================================================
# 1. Provider configuration
# ==================================================

def _read_local_gateway_key():
    try:
        key = LOCAL_GATEWAY_KEY_FILE.read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return ""

    return key


def get_config():
    """
    Return (base_url, api_key, model, source).

    Environment variables win. Without a key, fall back to the
    local DSH gateway so development works without a paid key.
    """

    base_url = os.environ.get("ZH_API_BASE", "").strip()
    api_key = os.environ.get("ZH_API_KEY", "").strip()
    model = os.environ.get("ZH_MODEL", "").strip()

    if api_key:
        return (
            (base_url or DEFAULT_BASE_URL).rstrip("/"),
            api_key,
            model or DEFAULT_MODEL,
            "environment",
        )

    gateway_key = _read_local_gateway_key()

    if gateway_key:
        return (
            (base_url or LOCAL_GATEWAY_BASE_URL).rstrip("/"),
            gateway_key,
            model or LOCAL_GATEWAY_MODEL,
            "local DSH gateway",
        )

    raise RuntimeError(
        "No translation credentials found. "
        "Set ZH_API_KEY (optionally ZH_API_BASE and ZH_MODEL), "
        "or start the DSH desktop app so its local gateway is "
        "available at "
        f"{LOCAL_GATEWAY_BASE_URL}."
    )


def validate_config():
    """
    Fail early with a clear message when no provider is usable.
    """

    base_url, api_key, model, source = get_config()

    print(
        f"[INFO] Translation provider: {source} "
        f"({base_url}, model={model})"
    )

    return base_url, api_key, model


# ==================================================
# 2. Split a long text into API-sized chunks
# ==================================================

def split_text(text, max_chars=MAX_CHARS):
    """
    Split text into chunks small enough for one API request.

    Splitting happens at newlines whenever possible, so paragraphs
    and Markdown blocks are never cut in the middle.
    """

    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_chars:

        window = remaining[:max_chars]

        split_at = window.rfind("\n")

        if split_at <= 0:
            split_at = window.rfind(" ")

        if split_at <= 0:
            split_at = max_chars

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    if remaining:
        chunks.append(remaining)

    return chunks


# ==================================================
# 3. Build the request payload
# ==================================================

def build_messages(text, context=None):
    parts = []

    if context:
        parts.append(
            "Page context:\n"
            f"{context}\n"
        )

    parts.append(
        "Translate the following English text into Simplified "
        "Chinese. It may be a fragment of a sentence.\n\n"
        f"{text}"
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def clean_translation(content):
    """
    Remove whitespace and accidental wrapping the model may add.
    """

    cleaned = content.strip()

    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'“”":
        cleaned = cleaned[1:-1].strip()

    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.startswith("zh"):
            cleaned = cleaned[2:].strip()

    return cleaned


def verify_placeholders(source, translated):
    """
    Every protected token must survive exactly once.
    """

    tokens = PLACEHOLDER_PATTERN.findall(source)

    if not tokens:
        return

    problems = []

    for token in set(tokens):
        expected = tokens.count(token)
        actual = translated.count(token)

        if actual != expected:
            problems.append(
                f"{token}: expected {expected}, found {actual}"
            )

    if problems:
        raise ValueError(
            "Placeholders were lost or duplicated: "
            + "; ".join(problems)
        )


# ==================================================
# 4. One API request
# ==================================================

def translate_chunk(text, context=None):
    """
    Translate one chunk and verify its protected placeholders.
    """

    global _last_request_time

    base_url, api_key, model, source = get_config()

    endpoint = f"{base_url}/chat/completions"

    payload = {
        "model": model,
        "messages": build_messages(text, context),
        "temperature": TEMPERATURE,
        "stream": False,
    }

    body = json.dumps(payload).encode("utf-8")

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        # Respect the provider rate limit between requests.
        elapsed = time.monotonic() - _last_request_time

        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)

        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

        _last_request_time = time.monotonic()

        try:
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT_SECONDS,
            ) as response:
                result = json.loads(
                    response.read().decode("utf-8")
                )

        except urllib.error.HTTPError as error:
            detail = ""

            try:
                detail = error.read().decode(
                    "utf-8", errors="replace"
                )[:400]
            except Exception:
                pass

            retryable = (
                error.code == 429
                or 500 <= error.code <= 599
            )

            if not retryable or attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Translation API HTTP error {error.code} "
                    f"({source}): {detail}"
                ) from error

            last_error = f"HTTP {error.code}"

        except urllib.error.URLError as error:
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Could not reach the translation API "
                    f"({source}) after {MAX_RETRIES} attempts: "
                    f"{error.reason}"
                ) from error

            last_error = str(error.reason)

        except TimeoutError as error:
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    "Translation request timed out after "
                    f"{MAX_RETRIES} attempts."
                ) from error

            last_error = "timeout"

        else:
            try:
                choices = result.get("choices") or []

                if not choices:
                    raise KeyError("no choices in response")

                content = choices[0]["message"]["content"]

                if not isinstance(content, str) or not content.strip():
                    raise KeyError("empty translation")

                translated = clean_translation(content)

                verify_placeholders(text, translated)

                return translated

            except (KeyError, ValueError) as error:
                last_error = str(error)

                if attempt == MAX_RETRIES:
                    raise RuntimeError(
                        "The translation API returned an unusable "
                        f"response: {last_error}"
                    ) from error

        wait_time = RETRY_DELAY * (2 ** (attempt - 1))

        print(
            f"Translation attempt {attempt} failed "
            f"({last_error}). Retrying in "
            f"{wait_time:g} seconds..."
        )

        time.sleep(wait_time)

    raise RuntimeError(
        f"Translation failed after {MAX_RETRIES} attempts."
    )


# ==================================================
# 5. Translate an entire text
# ==================================================

def translate_text(text, context=None):
    """
    Translate a long English text into Simplified Chinese.

    ``context`` is optional background (page path, title, heading)
    that helps the model translate fragments correctly.
    """

    chunks = split_text(text)

    translated_chunks = []

    for index, chunk in enumerate(chunks, start=1):

        if len(chunks) > 1:
            print(
                f"Translating chunk {index}/{len(chunks)}..."
            )

        translated = translate_chunk(chunk, context=context)

        translated_chunks.append(translated)

    return "".join(translated_chunks)


# ==================================================
# 6. Command-line smoke test
# ==================================================

if __name__ == "__main__":

    try:
        sys.stdout.reconfigure(
            encoding="utf-8", errors="replace"
        )
    except AttributeError:
        pass

    validate_config()

    samples = [
        (
            "A collection of ideas explored across physics, "
            "mathematics, and philosophy.",
            "Homepage",
        ),
        (
            "(the origin is indeed a special case in which",
            "Physics overview",
        ),
        (
            "s approaches to physics.",
            "Physics overview, sentence fragment split by "
            "an inline link",
        ),
        (
            "ZXQINLINE0QXZ is the derivative of ZXQINLINE1QXZ.",
            "Inline math test",
        ),
    ]

    for sample, context in samples:
        print("English:", sample)
        print(
            "Chinese:",
            translate_text(sample, context=context),
        )
        print()
