
import re
import os
import json
import hashlib

from pathlib import Path
from translator import translate_text

# --------------------------------------------------
# Configuration
# --------------------------------------------------

CONTENT_DIRECTORY = Path("src/content/articles")
CHINESE_DIRECTORY = CONTENT_DIRECTORY / "zh-cn"

MANIFEST_PATH = Path("scripts/translation-manifest.json")

APP_ID = os.environ.get("BAIDU_APP_ID")
SECRET_KEY = os.environ.get("BAIDU_SECRET_KEY")

if not APP_ID or not SECRET_KEY:
    raise RuntimeError(
        "Missing Baidu credentials. "
        "Check BAIDU_APP_ID and BAIDU_SECRET_KEY."
    )

# --------------------------------------------------
# Discover English Markdown articles
# --------------------------------------------------

def discover_articles():
    """
    Find all English Markdown articles recursively.

    Chinese translations are excluded.
    """

    articles = []

    for path in CONTENT_DIRECTORY.rglob("*.md"):

        # Ignore files inside the Chinese translation directory.
        if CHINESE_DIRECTORY in path.parents:
            continue

        articles.append(path)

    return sorted(articles)


# --------------------------------------------------
# Calculate source fingerprints
# --------------------------------------------------

def calculate_hash(file_path):
    """
    Calculate the SHA-256 fingerprint of a file.
    """

    with open(file_path, "rb") as file:
        content = file.read()

    return hashlib.sha256(content).hexdigest()

# --------------------------------------------------
# Translation manifest
# --------------------------------------------------

def load_manifest():
    """
    Load the translation history.

    Return an empty dictionary if no manifest exists yet.
    """

    if not MANIFEST_PATH.exists():
        return {}

    with open(
        MANIFEST_PATH,
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


def save_manifest(manifest):
    """
    Save the translation history safely.
    """

    MANIFEST_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary_path = MANIFEST_PATH.with_suffix(".tmp")

    with open(
        temporary_path,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            manifest,
            file,
            ensure_ascii=False,
            indent=4
        )

    temporary_path.replace(MANIFEST_PATH)

# --------------------------------------------------
# 1. Separate YAML frontmatter from Markdown body
# --------------------------------------------------


def split_frontmatter(markdown):
    """
    Separate YAML frontmatter from the Markdown body.

    Recognizes opening and closing delimiters even when
    the file uses Windows (CRLF) or Unix (LF) line endings.
    """

    # Remove a possible UTF-8 BOM.
    if markdown.startswith("\ufeff"):
        markdown = markdown[1:]

    # Keep original line endings.
    lines = markdown.splitlines(keepends=True)

    # Find the first non-empty line.
    opening_index = None

    for index, line in enumerate(lines):
        if line.strip():
            opening_index = index
            break

    # No opening delimiter found.
    if opening_index is None or lines[opening_index].strip() != "---":
        return "", markdown

    # Find the closing delimiter.
    closing_index = None

    for index in range(opening_index + 1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break

    # No closing delimiter found.
    if closing_index is None:
        return "", markdown

    # Preserve the original frontmatter and body.
    frontmatter = "".join(lines[:closing_index + 1])
    body = "".join(lines[closing_index + 1:])

    return frontmatter, body



# --------------------------------------------------
# 2. Protect multiline Markdown regions
# --------------------------------------------------

def protect_blocks(markdown):
    """
    Protect fenced code blocks and display-math blocks.

    Returns:
        protected_markdown: Markdown containing placeholders.
        protected_blocks: Original protected content.
    """

    protected_blocks = []

    pattern = re.compile(
        r"```.*?```"
        r"|~~~.*?~~~"
        r"|\$\$.*?\$\$",
        flags=re.DOTALL
    )

    def replace_block(match):
        index = len(protected_blocks)
        placeholder = f"ZXQBLOCK{index}QXZ"

        protected_blocks.append(match.group(0))

        return placeholder

    protected_markdown = pattern.sub(
        replace_block,
        markdown
    )

    return protected_markdown, protected_blocks


# --------------------------------------------------
# 3. Protect inline Markdown content
# --------------------------------------------------


def protect_inline_content(markdown):
    """
    Protect inline math, inline code, URLs, and Markdown
    structural markers.

    Returns:
        protected_markdown: Text containing placeholders.
        protected_items: Original protected content.
    """

    protected_items = []

    pattern = re.compile(
        r"\\\(.*?\\\)"                  # Inline math: \( ... \)
        r"|\\\[.*?\\\]"                 # Math delimiters: \[ ... \]
        r"|`[^`\n]+`"                    # Inline code
        r"|https?://[^\s)\]]+"          # URLs
        r"|^#{1,6}[ \t]+"               # Markdown headings
        r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+"  # Lists
        r"^>[ \t]?",                    # Blockquotes
        flags=re.MULTILINE
    )

    def replace_item(match):
        index = len(protected_items)
        placeholder = f"ZXQINLINE{index}QXZ"

        protected_items.append(match.group(0))

        return placeholder

    protected_markdown = pattern.sub(
        replace_item,
        markdown
    )

    return protected_markdown, protected_items



# --------------------------------------------------
# 4. Restore protected content
# --------------------------------------------------

def restore_inline_content(markdown, protected_items):
    """Restore original inline content."""

    for index, original_item in enumerate(protected_items):
        placeholder = f"ZXQINLINE{index}QXZ"

        markdown = markdown.replace(
            placeholder,
            original_item
        )

    return markdown


def restore_blocks(markdown, protected_blocks):
    """Restore original multiline blocks."""

    for index, original_block in enumerate(protected_blocks):
        placeholder = f"ZXQBLOCK{index}QXZ"

        markdown = markdown.replace(
            placeholder,
            original_block
        )

    return markdown


# --------------------------------------------------
# 5. Translate the Markdown document
# --------------------------------------------------

def translate_markdown(markdown):
    """
    Translate Markdown prose into Chinese while preserving
    frontmatter, equations, code, inline math, and URLs.
    """

    # Separate metadata from the article body.
    frontmatter, body = split_frontmatter(markdown)

    # Protect multiline content first.
    body, protected_blocks = protect_blocks(body)

    # Protect inline content.
    body, protected_inline = protect_inline_content(body)

    # Translate the remaining prose using Baidu.
    translated_body = translate_text(body)

    # Verify that every placeholder survived translation.
    for index in range(len(protected_blocks)):
        placeholder = f"ZXQBLOCK{index}QXZ"

        if translated_body.count(placeholder) != 1:
            raise RuntimeError(
                f"Block placeholder missing or modified: {placeholder}"
            )

    for index in range(len(protected_inline)):
        placeholder = f"ZXQINLINE{index}QXZ"

        if translated_body.count(placeholder) != 1:
            raise RuntimeError(
                f"Inline placeholder missing or modified: {placeholder}"
            )

    # Restore inline content.
    translated_body = restore_inline_content(
        translated_body,
        protected_inline
    )

    # Restore multiline content.
    translated_body = restore_blocks(
        translated_body,
        protected_blocks
    )

    # Reassemble the complete Markdown document.
    return frontmatter + translated_body

def save_translated_markdown(translated_markdown, input_path):
    """
    Save the translated article while preserving
    its original directory structure.
    """

    input_path = Path(input_path)

    relative_path = input_path.relative_to(
        CONTENT_DIRECTORY
    )

    output_path = CHINESE_DIRECTORY / relative_path

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(translated_markdown)

    print(f"Chinese article saved to: {output_path}")

    return output_path
# --------------------------------------------------
# 6. Run a real translation test
# --------------------------------------------------

# --------------------------------------------------
# Main translation process
# --------------------------------------------------

if __name__ == "__main__":

    articles = discover_articles()
    manifest = load_manifest()

    print(f"Discovered {len(articles)} English article(s).")

    translated_count = 0
    skipped_count = 0

    for input_path in articles:

        relative_path = input_path.relative_to(
            CONTENT_DIRECTORY
        ).as_posix()

        current_hash = calculate_hash(input_path)

        output_path = CHINESE_DIRECTORY / relative_path

        previous_record = manifest.get(relative_path, {})

        previous_hash = previous_record.get("source_hash")

        # Skip translation only if the source is unchanged
        # AND the Chinese output still exists.
        if (
            current_hash == previous_hash
            and output_path.exists()
        ):
            print(f"Skipping unchanged article: {relative_path}")
            skipped_count += 1
            continue

        print(f"\nTranslating: {relative_path}")

        with open(
            input_path,
            "r",
            encoding="utf-8-sig"
        ) as file:
            original_markdown = file.read()

        frontmatter, body = split_frontmatter(original_markdown)

        if not frontmatter:
            raise RuntimeError(
                f"Invalid YAML frontmatter: {relative_path}"
            )

        translated_markdown = translate_markdown(
            original_markdown
        )

        save_translated_markdown(
            translated_markdown,
            input_path
        )

        # Update the manifest only after translation succeeds.
        manifest[relative_path] = {
            "source_hash": current_hash,
            "translated_file": (
                CHINESE_DIRECTORY / relative_path
            ).as_posix()
        }

        save_manifest(manifest)

        translated_count += 1

    print("\n--------------------------------")
    print("Translation process completed.")
    print(f"New or updated: {translated_count}")
    print(f"Unchanged: {skipped_count}")
    print("--------------------------------")