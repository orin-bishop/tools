"""Small text helpers. Plain Python, no outside libraries.

Jira Data Center stores descriptions as "wiki markup" (for example *bold*, h3. Heading,
{code} blocks). We turn that into plain words first, so character counts are fair.
"""
import re

# Words that carry no meaning when we compare a summary with a description.
STOP_WORDS = frozenset(
    "a an and are as at be by for from has have i in into is it its of on or so that "
    "the their then these this to up we with want need should will can "
    "each see any all which what when where who how do does did not no also our your my you they".split()
)


def plain_text(value, keep_lines=False):
    """Return Jira text as plain words. None becomes an empty string.

    With keep_lines=True the line breaks are kept (one line per list item or paragraph), which is
    easier to read in a spreadsheet. The default joins everything into one line, which is what the checks want.
    """
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\{code[^}]*\}.*?\{code\}", " ", text, flags=re.S)       # code blocks
    text = re.sub(r"\{noformat\}.*?\{noformat\}", " ", text, flags=re.S)     # preformatted blocks
    text = re.sub(r"\{(?:panel|quote|color|anchor)[^}]*\}", " ", text)       # panel and colour markers
    text = re.sub(r"\[([^\]|]+)\|[^\]]*\]", r"\1", text)                     # [label|url] -> label
    text = re.sub(r"!\S+?!", " ", text)                                      # images
    text = re.sub(r"(?m)^\s*h[1-6]\.\s*", "", text)                          # h3. headings
    text = re.sub(r"(?m)^\s*(?:[*#-]+)\s+", "", text)                        # list bullets
    text = re.sub(r"\{\{(.*?)\}\}", r"\1", text)                             # {{monospace}}
    text = re.sub(r"(?<!\w)\*(\S(?:.*?\S)?)\*(?!\w)", r"\1", text)           # *bold*
    text = re.sub(r"(?<!\w)_(\S(?:.*?\S)?)_(?!\w)", r"\1", text)             # _italic_
    if keep_lines:
        text = re.sub(r"[ \t]+", " ", text)                                  # tidy spaces, keep line breaks
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return re.sub(r"\s+", " ", text).strip()


def stem(word):
    """Cut a common word ending so 'migrate', 'migrating' and 'migration' match.

    This is deliberately simple. It only has to be the same on both sides of a comparison.
    """
    word = word.lower()
    for ending in ("ing", "ion", "ed", "es", "s", "e"):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def tokens(text):
    """All words in the text, lower case, with endings cut. Stop words are kept."""
    return [stem(w) for w in re.findall(r"[a-z0-9]+", str(text).lower())]


def words(text):
    """The meaningful words in the text: no stop words, no single letters."""
    return [t for t in tokens(text) if t not in STOP_WORDS and len(t) > 1]


def contains_phrase(phrase, token_list, max_gap=3):
    """True if the words of `phrase` appear in order in `token_list`.

    Up to `max_gap` other words may sit between them, so 'encrypt database' also
    matches 'encrypt the production database'.
    """
    parts = tokens(phrase)
    if not parts:
        return False
    for start, token in enumerate(token_list):
        if token != parts[0]:
            continue
        position = start
        for wanted in parts[1:]:
            window = token_list[position + 1 : position + 2 + max_gap]
            if wanted in window:
                position = position + 1 + window.index(wanted)
            else:
                break
        else:
            return True
    return False
