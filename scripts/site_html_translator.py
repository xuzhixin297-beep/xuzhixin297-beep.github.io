from html.parser import HTMLParser
from pathlib import Path
import re
import json
import html

try:
    from .translator import translate_text
except ImportError:
    from translator import translate_text


# =========================
# Configuration
# =========================

CACHE_PATH = Path("scripts/translation_cache.json")
OVERRIDE_PATH = Path("scripts/translation_overrides.json")

SOURCE_LANGUAGE = "en"
TARGET_LANGUAGE = "zh-CN"

DIST_DIRECTORY = Path("dist")
CHINESE_PREFIX = "/zh-cn"

IGNORED_TAGS = {
    "script", "style", "code", "pre", "svg",
}

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr",
    "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
}


# =========================
# Cache and overrides
# =========================

def load_cache():
    if not CACHE_PATH.exists():
        return {}

    with CACHE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_overrides():
    if not OVERRIDE_PATH.exists():
        return {}

    with OVERRIDE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_cache(cache):
    with CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)


def make_cache_key(text, tag):
    return f"{SOURCE_LANGUAGE}|{TARGET_LANGUAGE}|{tag}|{text}"


def get_cached_translation(cache, text, tag):
    # First: exact match for the current HTML tag.
    exact_key = make_cache_key(text, tag)

    if exact_key in cache:
        return cache[exact_key]

    # Second: reuse a generic text translation.
    generic_key = make_cache_key(text, "text")

    if generic_key in cache:
        return cache[generic_key]

    return None


def get_override(overrides, text, tag):
    # 1. Exact HTML-tag override takes priority
    exact_key = make_cache_key(text, tag)

    if exact_key in overrides:
        return overrides[exact_key]

    # 2. Universal text override
    generic_key = make_cache_key(text, "text")

    if generic_key in overrides:
        return overrides[generic_key]

    # 3. Plain-text key (optional)
    if text in overrides:
        return overrides[text]

    return None


def store_translation(cache, text, tag, translated_text):
    cache[make_cache_key(text, tag)] = translated_text


def classify_text(text, tag):
    if not re.search(r"[A-Za-z]", text):
        return "PRESERVE"

    if re.match(r"^\d+\s*/\s*", text):
        return "REVIEW"

    return "TRANSLATE"

def translate_preserving_brand(text):
    brand_pattern = re.compile(
        r"Antemundane\s+(?:sprǣc|sprac)",
        re.IGNORECASE
    )

    protected_names = []

    def protect_brand(match):
        placeholder = f"ZXQBRANDTOKEN{len(protected_names)}QXZ"
        protected_names.append((placeholder, match.group(0)))
        return placeholder

    # Replace the brand name with a temporary token.
    protected_text = brand_pattern.sub(protect_brand, text)

    # Translate the remaining sentence using the existing Baidu translator.
    translated = translate_text(protected_text)

    # Restore the original brand name.
    for placeholder, original_name in protected_names:
        translated = translated.replace(placeholder, original_name)

    return translated

def translate_cached(cache, overrides, text, tag):
    # Manual override has highest priority.
    overridden = get_override(overrides, text, tag)

    if overridden is not None:
        print(f"[OVERRIDE] {text}")
        return overridden

    # Reuse previous translations.
    cached = get_cached_translation(cache, text, tag)

    if cached is not None:
        print(f"[CACHE] {text}")
        return cached

    # Only genuinely new text reaches Baidu.
    print(f"[BAIDU] {text}")

    translated = translate_preserving_brand(text)

    store_translation(cache, text, tag, translated)
    save_cache(cache)

    return translated


# =========================
# HTML text scanner
# =========================

class TextScanner(HTMLParser):

    def __init__(self, source):
        super().__init__(convert_charrefs=False)

        self.source = source
        self.text_nodes = []
        self.tag_stack = []
        self.ignore_depth = 0

        # Convert line/column positions into source offsets.
        self.line_offsets = [0]

        for match in re.finditer(r"\n", source):
            self.line_offsets.append(match.end())

    def get_offset(self):
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
         if tag in VOID_TAGS:
            return

         attributes = dict(attrs)

         ignored = (
            tag in IGNORED_TAGS
            or attributes.get("translate") == "no"
         )

         self.tag_stack.append({
            "tag": tag,
            "ignored": ignored,
         })

         if ignored:
            self.ignore_depth += 1

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        for index in range(len(self.tag_stack) - 1, -1, -1):
            if self.tag_stack[index]["tag"] == tag:

                removed = self.tag_stack[index:]

                for item in removed:
                    if item["ignored"]:
                        self.ignore_depth -= 1

                self.tag_stack = self.tag_stack[:index]
                break

    def handle_data(self, data):
        if self.ignore_depth > 0:
            return

        if not data.strip():
            return

        # Record exact source positions instead of reconstructing HTML.
        start = self.get_offset()
        end = start + len(data)

        tag = (
            self.tag_stack[-1]["tag"]
            if self.tag_stack
            else "text"
        )

        self.text_nodes.append({
            "start": start,
            "end": end,
            "raw": data,
            "tag": tag,
        })


# =========================
# HTML processing
# =========================

def translate_html(source, cache, overrides):
    parser = TextScanner(source)
    parser.feed(source)
    parser.close()

    replacements = []

    for index, node in enumerate(parser.text_nodes, start=1):

        raw = node["raw"]
        tag = node["tag"]

        # Preserve whitespace surrounding the text.
        leading = re.match(r"^\s*", raw).group()
        trailing = re.search(r"\s*$", raw).group()

        core = raw[len(leading):len(raw) - len(trailing) if trailing else len(raw)]

        if not core:
            continue

        # Decode HTML entities before translation.
        text = html.unescape(core)

        # Manual overrides must always have the highest priority,
        # even for text normally marked PRESERVE or REVIEW.
        overridden = get_override(overrides, text, tag)

        if overridden is not None:
          translated = overridden
          print(f"[OVERRIDE] {text}")

        else:
          category = classify_text(text, tag)

        if category != "TRANSLATE":
          translated = text
          print(f"[{category}] {text}")

        else:
          translated = translate_cached(
              cache,
              overrides,
              text,
              tag
        )

        # Escape translated text so it cannot accidentally become HTML.
        translated_html = html.escape(translated, quote=False)

        replacements.append((
            node["start"],
            node["end"],
            leading + translated_html + trailing,
        ))

    # Apply replacements from right to left so earlier offsets remain valid.
    result = source

    for start, end, replacement in reversed(replacements):
        result = result[:start] + replacement + result[end:]

    return result


# =========================
# Internal link conversion
# =========================

def convert_internal_links(source):
    """
    Redirect links to our own pages into the Chinese site.

    External URLs, anchors, downloads and assets remain unchanged.
    """

    def replace_href(match):
        quote = match.group(1)
        url = match.group(2)

        # Only root-relative internal website links.
        if not url.startswith("/") or url.startswith("//"):
            return match.group(0)

        # Leave anchors, query-only links and existing Chinese links alone.
        if url.startswith(("#", "/zh-cn/", "/assets/")):
            return match.group(0)

        # Avoid translating file/download links.
        if re.search(r"\.(pdf|zip|png|jpg|jpeg|gif|svg|webp|mp4|mp3|css|js)$", url, re.I):
            return match.group(0)

        chinese_url = CHINESE_PREFIX + url

        return f'href={quote}{chinese_url}{quote}'

    return re.sub(
        r'href=(["\'])(/[^"\']*)\1',
        replace_href,
        source
    )


# =========================
# Route generation
# =========================

def get_chinese_output_path(english_file):
    relative = english_file.relative_to(DIST_DIRECTORY)

    return DIST_DIRECTORY / "zh-cn" / relative


def find_english_html_files():
    """
    Scan all HTML pages in dist, excluding the Chinese output directory.
    """

    files = []

    for file in DIST_DIRECTORY.rglob("*.html"):

        relative = file.relative_to(DIST_DIRECTORY)

        # Do not scan our own generated Chinese pages.
        if relative.parts and relative.parts[0] == "zh-cn":
            continue

        files.append(file)

    return sorted(files)


def process_page(english_file, cache, overrides):

    print("\n" + "=" * 60)
    print(f"Processing: {english_file}")
    print("=" * 60)

    source = english_file.read_text(encoding="utf-8")

    translated = translate_html(
        source,
        cache,
        overrides
    )

    translated = convert_internal_links(translated)

    output_file = get_chinese_output_path(english_file)

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file.write_text(
        translated,
        encoding="utf-8"
    )

    print(f"[GENERATED] {output_file}")


# =========================
# Main
# =========================

def main():

    if not DIST_DIRECTORY.exists():
        raise FileNotFoundError(
            "dist directory does not exist. Run the Astro build first."
        )

    cache = load_cache()

    print(f"[INFO] Loaded {len(cache)} cached translations")
    print(f"[INFO] Cache file: {CACHE_PATH.resolve()}")

    overrides = load_overrides()

    print(f"[INFO] Loaded {len(overrides)} manual overrides")
    print(f"[INFO] Override file: {OVERRIDE_PATH.resolve()}")

    english_pages = find_english_html_files()

    print("\n===== ENTIRE SITE SCAN =====")
    print(f"English HTML pages found: {len(english_pages)}")

    for page in english_pages:
        print(f" - {page}")

    print("\n===== TRANSLATING SITE =====")

    for page in english_pages:
        process_page(
            page,
            cache,
            overrides
        )

    save_cache(cache)

    print("\n===== TRANSLATION COMPLETE =====")
    print(f"Pages scanned: {len(english_pages)}")
    print(f"Cache entries: {len(cache)}")
    print(f"Chinese output directory: {DIST_DIRECTORY / 'zh-cn'}")


if __name__ == "__main__":
    main()