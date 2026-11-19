
import os
import time
import hashlib
import secrets
import json
import urllib.parse
import urllib.request
import urllib.error


# --------------------------------------------------
# 1. Configuration
# --------------------------------------------------

API_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"

MAX_CHARS = 900
REQUEST_INTERVAL = 1.1
MAX_RETRIES = 4
RETRY_DELAY = 3


# --------------------------------------------------
# 2. Retrieve credentials
# --------------------------------------------------

def get_credentials():
    """
    Read Baidu credentials from environment variables.
    Never store credentials directly in this file.
    """

    app_id = os.environ.get("BAIDU_APP_ID")
    secret_key = os.environ.get("BAIDU_SECRET_KEY")

    if not app_id or not secret_key:
        raise RuntimeError(
            "Baidu credentials are missing. "
            "Check BAIDU_APP_ID and BAIDU_SECRET_KEY."
        )

    return app_id, secret_key


# --------------------------------------------------
# 3. Divide text into smaller chunks
# --------------------------------------------------


def split_text(text, max_chars=MAX_CHARS):
    """
    Split text into chunks while preserving every source character.
    Prefer newline boundaries when possible.
    """

    if not text:
        return []

    chunks = []
    remaining = text

    while len(remaining) > max_chars:

        # Find the last newline within the allowed chunk size.
        cut_position = remaining.rfind(
            "\n", 0, max_chars
        )

        # If there is no suitable newline, split by character count.
        if cut_position <= 0:
            cut_position = max_chars
        else:
            # Include the newline in the preceding chunk.
            cut_position += 1

        chunks.append(remaining[:cut_position])
        remaining = remaining[cut_position:]

    if remaining:
        chunks.append(remaining)

    return chunks



# --------------------------------------------------
# 4. Translate one chunk
# --------------------------------------------------

_last_request_time = 0.0


def translate_chunk(text):
    """
    Send one authenticated translation request to Baidu.
    """

    global _last_request_time

    app_id, secret_key = get_credentials()

    # Respect the standard edition's request-rate limit.
    elapsed = time.monotonic() - _last_request_time

    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)

    salt = secrets.token_hex(8)

    sign_string = app_id + text + salt + secret_key

    sign = hashlib.md5(
        sign_string.encode("utf-8")
    ).hexdigest()

    parameters = {
        "q": text,
        "from": "en",
        "to": "zh",
        "appid": app_id,
        "salt": salt,
        "sign": sign,
    }

    encoded_parameters = urllib.parse.urlencode(
        parameters
    ).encode("utf-8")

    request = urllib.request.Request(
        API_URL,
        data=encoded_parameters,
        method="POST",
    )

    _last_request_time = time.monotonic()

    result = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            # Request succeeded.
            break

        except urllib.error.HTTPError as error:

            # Retry temporary server errors or rate limiting.
            retryable = (
                error.code == 429
                or 500 <= error.code <= 599
            )

            if not retryable or attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Baidu HTTP error: {error.code}"
                ) from error

            wait_time = RETRY_DELAY * (2 ** (attempt - 1))

            print(
                f"HTTP {error.code}. "
                f"Retry {attempt}/{MAX_RETRIES - 1} "
                f"in {wait_time} seconds..."
            )

            time.sleep(wait_time)

        except urllib.error.URLError as error:

            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Could not connect to Baidu after "
                    f"{MAX_RETRIES} attempts: {error.reason}"
                ) from error

            wait_time = RETRY_DELAY * (2 ** (attempt - 1))

            print(
                f"Connection failed. "
                f"Retry {attempt}/{MAX_RETRIES - 1} "
                f"in {wait_time} seconds..."
            )

            time.sleep(wait_time)

        except TimeoutError as error:

            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Request timed out after "
                    f"{MAX_RETRIES} attempts."
                ) from error

            wait_time = RETRY_DELAY * (2 ** (attempt - 1))

            print(
                f"Request timed out. "
                f"Retry {attempt}/{MAX_RETRIES - 1} "
                f"in {wait_time} seconds..."
            )

            time.sleep(wait_time)

    if "error_code" in result:
        raise RuntimeError(
            "Baidu API error: "
            f"{result['error_code']} - "
            f"{result.get('error_msg', 'Unknown error')}"
        )

    translations = result.get("trans_result")

    if not translations:
        raise RuntimeError(
            "Baidu returned no translation result."
        )

    return "\n".join(
        item["dst"] for item in translations
    )


# --------------------------------------------------
# 5. Translate an entire text
# --------------------------------------------------

def translate_text(text):
    """
    Translate a long English text into Simplified Chinese.
    """

    chunks = split_text(text)

    translated_chunks = []

    for index, chunk in enumerate(chunks, start=1):

        print(
            f"Translating chunk {index}/{len(chunks)}..."
        )

        translated = translate_chunk(chunk)

        translated_chunks.append(translated)

    return "".join(translated_chunks)

# Temporary added lines
if __name__ == "__main__":

    sample = (
        "First paragraph.\n\n"
        "Second paragraph is somewhat longer.\n"
        "Third paragraph."
    )

    chunks = split_text(sample, max_chars=20)

    print("Original:")
    print(repr(sample))

    print("\nChunks:")
    for chunk in chunks:
        print(repr(chunk))

    print("\nReconstructed:")
    print(repr("".join(chunks)))

    assert "".join(chunks) == sample

    print("\nChunking test passed!")