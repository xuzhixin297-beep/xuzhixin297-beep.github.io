
import re
from translator import translate_text
import os
from pathlib import Path

APP_ID = os.environ.get("BAIDU_APP_ID")
SECRET_KEY = os.environ.get("BAIDU_SECRET_KEY")

if not APP_ID or not SECRET_KEY:
    raise RuntimeError(
        "Missing Baidu credentials. "
        "Check BAIDU_APP_ID and BAIDU_SECRET_KEY."
    )

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
    Save the translated article in the zh-cn content directory.
    """

    input_path = Path(input_path)

    output_directory = Path("src/content/articles/zh-cn")
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / input_path.name

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(translated_markdown)

    print(f"\nChinese article saved to: {output_path}")

    return output_path

# --------------------------------------------------
# 6. Run a real translation test
# --------------------------------------------------

if __name__ == "__main__":

    input_path = "src/content/articles/cycloid.md"

    with open(
        input_path,
        "r",
        encoding="utf-8-sig"
    ) as file:
        original_markdown = file.read()

    print("Reading:", input_path)
    print("\nStarting Markdown translation...\n")

    frontmatter, body = split_frontmatter(original_markdown)

    if not frontmatter:
        raise RuntimeError(
            "Could not recognize YAML frontmatter. "
            "Translation cancelled to protect the article."
        )

    translated_markdown = translate_markdown(original_markdown)

    output_path = save_translated_markdown(
        translated_markdown,
        input_path
    )

    print("\nTranslation completed successfully!")
    print("Output:", output_path)
