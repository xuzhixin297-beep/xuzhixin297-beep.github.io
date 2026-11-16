
import os
import hashlib
import json
import secrets
import urllib.parse
import urllib.request


# 1. Read credentials from environment variables
app_id = os.environ["BAIDU_APP_ID"]
secret_key = os.environ["BAIDU_SECRET_KEY"]


# 2. Prepare the sentence
text = "The cycloid is a remarkable mathematical curve."

# 3. Generate a unique random value
salt = secrets.token_hex(8)

# 4. Generate Baidu's authentication signature
sign_string = app_id + text + salt + secret_key

sign = hashlib.md5(
    sign_string.encode("utf-8")
).hexdigest()


# 5. Prepare the API request
url = "https://fanyi-api.baidu.com/api/trans/vip/translate"

parameters = {
    "q": text,
    "from": "en",
    "to": "zh",
    "appid": app_id,
    "salt": salt,
    "sign": sign,
}

request_url = url + "?" + urllib.parse.urlencode(parameters)

request = urllib.request.Request(request_url)

# 6. Send the request and receive the response
with urllib.request.urlopen(request, timeout=30) as response:
    result = json.loads(response.read().decode("utf-8"))


# 7. Check whether translation succeeded
if "error_code" in result:
    raise RuntimeError(
        f"Baidu API error: {result['error_code']} - "
        f"{result.get('error_msg', 'Unknown error')}"
    )

translated_text = result["trans_result"][0]["dst"]

print("Original:", text)
print("Translated:", translated_text)
