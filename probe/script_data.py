"""JSON encoding for data embedded in an HTML script element."""

import json


def dumps(value, **kwargs):
    """Return JSON that cannot terminate its enclosing script element.

    The HTML parser recognizes ``</script`` before JavaScript or JSON parsing. Escaping every
    angle bracket prevents that delimiter from being formed, while JSON decoding restores the
    original strings. Ampersands and JavaScript line separators are escaped as well so the same
    output remains safe if a data block is later moved into executable script source.
    """
    return (json.dumps(value, **kwargs)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))
