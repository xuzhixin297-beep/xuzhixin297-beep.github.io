from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import json
import html

try:
    from .translator import translate_text, validate_config
except ImportError:
    from translator import translate_text, validate_config


# =========================
# Configuration
# =========================

CACHE_PATH = Path("scripts/translation_cache.json")
OVERRIDE_PATH = Path("scripts/translation_overrides.json")

SOURCE_LANGUAGE = "en"
TARGET_LANGUAGE = "zh-CN"

# Bumping the namespace retranslates everything instead of reusing
# translations produced by a previous engine.
CACHE_NAMESPACE = os.environ.get(
    "ZH_CACHE_NAMESPACE", "deepseek-v1"
)

OVERRIDE_PREFIX = f"{SOURCE_LANGUAGE}|{TARGET_LANGUAGE}"
CACHE_PREFIX = (
    f"{CACHE_NAMESPACE}|{SOURCE_LANGUAGE}|{TARGET_LANGUAGE}"
)

DIST_DIRECTORY = Path("dist")
CHINESE_PREFIX = "/zh-cn"

# Per-run counters, printed at the end.
STATS = {
    "override": 0,
    "cache": 0,
    "api": 0,
}

IGNORED_TAGS = {
    "script", "style", "code", "pre", "svg",
}

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr",
    "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
}

TRANSLATABLE_ATTRIBUTES = {
    "placeholder",
    "aria-label",
    "title",
    "alt",
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


def make_cache_key(text, tag, prefix=CACHE_PREFIX):
    return f"{prefix}|{tag}|{text}"


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

    # Manual overrides keep the stable, engine-independent key
    # format so they survive a cache namespace change.

    # 1. Exact tag-specific override
    exact_key = make_cache_key(
        text, tag, prefix=OVERRIDE_PREFIX
    )

    if exact_key in overrides:
        return overrides[exact_key]

    # 2. Universal text override
    generic_key = make_cache_key(
        text, "text", prefix=OVERRIDE_PREFIX
    )

    if generic_key in overrides:
        return overrides[generic_key]

    # 3. Legacy plain-text key
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

def translate_preserving_brand(text, context=None):
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

    # Translate the remaining sentence with the configured provider.
    translated = translate_text(
        protected_text,
        context=context,
    )

    # Restore the original brand name.
    for placeholder, original_name in protected_names:
        translated = translated.replace(placeholder, original_name)

    return translated

def translate_cached(cache, overrides, text, tag, context=None):
    # Manual override has highest priority.
    overridden = get_override(overrides, text, tag)

    if overridden is not None:
        print(f"[OVERRIDE] {text}")
        STATS["override"] += 1
        return overridden

    # Reuse previous translations.
    cached = get_cached_translation(cache, text, tag)

    if cached is not None:
        print(f"[CACHE] {text}")
        STATS["cache"] += 1
        return cached

    # Only genuinely new text reaches the translation API.
    print(f"[API] {text}")
    STATS["api"] += 1

    translated = translate_preserving_brand(
        text,
        context=context,
    )

    store_translation(cache, text, tag, translated)
    save_cache(cache)

    return translated

def is_math_element(tag, attributes):
    classes = set((attributes.get("class") or "").split())

    return (
        tag == "math"
        or bool(classes.intersection({"katex", "katex-display"}))
    )


# =========================
# HTML text scanner
# =========================


class TextScanner(HTMLParser):

    def __init__(self, source):
        super().__init__(convert_charrefs=False)

        self.source = source
        self.text_nodes = []
        self.attribute_nodes = []
        self.tag_stack = []
        self.ignore_depth = 0

        # Convert line/column positions into source offsets.
        self.line_offsets = [0]

        for match in re.finditer(r"\n", source):
            self.line_offsets.append(match.end())

    def get_offset(self):
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def scan_attributes(self, tag, raw_tag, start_offset, ignored):
        if ignored or self.ignore_depth > 0:
            return

        # Start scanning immediately after the tag name.
        tag_match = re.match(r"<\s*[^\s/>]+", raw_tag)

        if not tag_match:
            return

        position = tag_match.end()

        while position < len(raw_tag):

            # Skip whitespace between attributes.
            while position < len(raw_tag) and raw_tag[position].isspace():
                position += 1

            # End of tag.
            if position >= len(raw_tag) or raw_tag[position] in "/>":
                break

            # Read the attribute name.
            name_match = re.match(
                r"[^\s=/>]+",
                raw_tag[position:]
            )

            if not name_match:
                position += 1
                continue

            attribute_name = name_match.group(0).lower()
            position += name_match.end()

            # Skip whitespace before '='.
            while position < len(raw_tag) and raw_tag[position].isspace():
                position += 1

            # Attributes without values are not translatable.
            if position >= len(raw_tag) or raw_tag[position] != "=":
                continue

            position += 1

            # Skip whitespace after '='.
            while position < len(raw_tag) and raw_tag[position].isspace():
                position += 1

            # Only translate quoted attribute values.
            if position >= len(raw_tag) or raw_tag[position] not in "\"'":
                # Skip an unquoted value safely.
                while position < len(raw_tag) and not raw_tag[position].isspace() and raw_tag[position] != ">":
                    position += 1
                continue

            quote = raw_tag[position]
            position += 1

            value_start = position

            # Find the closing quote.
            value_end = raw_tag.find(quote, value_start)

            if value_end == -1:
                break

            raw_value = raw_tag[value_start:value_end]

            # Only translate user-facing attributes.
            if attribute_name in TRANSLATABLE_ATTRIBUTES and raw_value.strip():

                self.attribute_nodes.append({
                    "start": start_offset + value_start,
                    "end": start_offset + value_end,
                    "raw": raw_value,
                    "tag": attribute_name,
                    "attribute": True,
                })

            # Continue after the closing quote.
            position = value_end + 1

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        ignored = (
          tag in IGNORED_TAGS
          or attributes.get("translate") == "no"
          or is_math_element(tag, attributes)
        )

        raw_tag = self.get_starttag_text() or ""
        start_offset = self.get_offset()

        # Scan attributes before handling void tags.
        self.scan_attributes(
            tag,
            raw_tag,
            start_offset,
            ignored
        )

        if tag in VOID_TAGS:
            return

        self.tag_stack.append({
            "tag": tag,
            "ignored": ignored,
        })

        if ignored:
            self.ignore_depth += 1

    def handle_startendtag(self, tag, attrs):
        attributes = dict(attrs)

        ignored = (
          tag in IGNORED_TAGS
          or attributes.get("translate") == "no"
          or is_math_element(tag, attributes)
        )

        raw_tag = self.get_starttag_text() or ""
        start_offset = self.get_offset()

        self.scan_attributes(
            tag,
            raw_tag,
            start_offset,
            ignored
        )

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
            "attribute": False,
        })



# =========================
# HTML processing
# =========================


def iter_translatable_nodes(source):
    """
    Yield (tag, text) for every text or attribute node worth translating.

    This mirrors translate_html's extraction exactly so the
    warm-up pass and the page pass agree on what needs translating.
    """

    parser = TextScanner(source)
    parser.feed(source)
    parser.close()

    nodes = sorted(
        parser.text_nodes + parser.attribute_nodes,
        key=lambda node: node["start"],
    )

    for node in nodes:

        raw = node["raw"]

        leading = re.match(r"^\s*", raw).group()
        trailing = re.search(r"\s*$", raw).group()

        core = raw[
            len(leading):
            len(raw) - len(trailing) if trailing else len(raw)
        ]

        if not core:
            continue

        yield node["tag"], html.unescape(core)


def collect_pending_translations(cache, overrides):
    """
    Find every string that still needs an API translation.

    Returns a dict: cache key -> (text, context).
    """

    pending = {}

    for english_file in find_english_html_files():

        source = english_file.read_text(encoding="utf-8")

        page_context = extract_page_context(
            source,
            english_file,
        )

        for tag, text in iter_translatable_nodes(source):

            if get_override(overrides, text, tag) is not None:
                continue

            if classify_text(text, tag) != "TRANSLATE":
                continue

            if get_cached_translation(cache, text, tag) is not None:
                continue

            key = make_cache_key(text, tag)

            if key in pending:
                continue

            pending[key] = (
                text,
                f"{page_context}; HTML element <{tag}>",
            )

    return pending


def warm_cache(cache, overrides, workers=4):
    """
    Translate all pending strings concurrently before writing pages.

    The page pass then reads everything from the cache, which keeps
    the output deterministic even though requests run in parallel.
    """

    pending = collect_pending_translations(cache, overrides)

    print(
        f"[INFO] New strings to translate: {len(pending)}"
    )

    if not pending:
        return

    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:

        futures = {
            pool.submit(
                translate_preserving_brand,
                text,
                context,
            ): key
            for key, (text, context) in pending.items()
        }

        for future in as_completed(futures):

            key = futures[future]
            text = pending[key][0]

            try:
                translated = future.result()
            except RuntimeError as error:
                raise RuntimeError(
                    f"Translation failed for {text!r}: {error}"
                ) from error

            cache[key] = translated

            completed += 1
            STATS["api"] += 1

            if completed % 25 == 0:
                save_cache(cache)

                print(
                    f"[INFO] Translated "
                    f"{completed}/{len(pending)}"
                )

    save_cache(cache)

    print(
        f"[INFO] Warm-up complete: {completed} translations"
    )


def translate_html(source, cache, overrides, page_context=""):
    parser = TextScanner(source)
    parser.feed(source)
    parser.close()

    replacements = []

    # Both collections now exist and have valid source positions.
    all_nodes = sorted(
    parser.text_nodes + parser.attribute_nodes,
    key=lambda node: node["start"]
    )

    for index, node in enumerate(all_nodes, start=1):

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

        # Give the model enough context to translate fragments well.
        context = page_context

        if context:
            context = f"{context}; HTML element <{tag}>"
        else:
            context = f"HTML element <{tag}>"

        if "Previous" in text or "Next" in text:
            print(
            f"[PAGINATION DEBUG] "
            f"tag={tag!r}, "
            f"text={text!r}, "
            f"key={make_cache_key(text, tag)!r}, "
            f"override={get_override(overrides, text, tag)!r}, "
            f"cache={get_cached_translation(cache, text, tag)!r}"
            )

        # Manual overrides always have the highest priority.
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
                    tag,
                    context=context,
                )

        # Escape quotation marks in attributes, but not ordinary text.
        translated_html = html.escape(
            translated,
            quote=node.get("attribute", False)
        )

        replacements.append((
            node["start"],
            node["end"],
            leading + translated_html + trailing,
        ))

    # Apply replacements from right to left so earlier offsets remain valid.
    result = source

    # Apply replacements from right to left using original source positions.
    replacements.sort(key=lambda item: item[0], reverse=True)

    for start, end, replacement in replacements:
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


def extract_page_context(source, english_file):
    """
    Describe the page so the translator understands each fragment.
    """

    relative = english_file.relative_to(DIST_DIRECTORY).as_posix()

    title_match = re.search(
        r"<title>(.*?)</title>",
        source,
        re.IGNORECASE | re.DOTALL,
    )

    page_title = ""

    if title_match:
        page_title = html.unescape(
            title_match.group(1)
        ).strip()

    if not page_title:
        heading_match = re.search(
            r"<h1[^>]*>(.*?)</h1>",
            source,
            re.IGNORECASE | re.DOTALL,
        )

        if heading_match:
            page_title = re.sub(
                r"<[^>]+>", "", heading_match.group(1)
            ).strip()

    parts = [f"Page: /{relative}"]

    if page_title:
        parts.append(f"Title: {page_title}")

    return "; ".join(parts)


def process_page(english_file, cache, overrides):

    print("\n" + "=" * 60)
    print(f"Processing: {english_file}")
    print("=" * 60)

    source = english_file.read_text(encoding="utf-8")

    page_context = extract_page_context(
        source,
        english_file,
    )

    translated = translate_html(
        source,
        cache,
        overrides,
        page_context=page_context,
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

    validate_config()

    cache = load_cache()

    print(f"[INFO] Loaded {len(cache)} cached translations")
    print(f"[INFO] Cache namespace: {CACHE_NAMESPACE}")
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

    warm_cache(cache, overrides)

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
    print(
        "This run: "
        f"{STATS['override']} overrides, "
        f"{STATS['cache']} cache hits, "
        f"{STATS['api']} API translations"
    )
    print(f"Chinese output directory: {DIST_DIRECTORY / 'zh-cn'}")


if __name__ == "__main__":
    main()