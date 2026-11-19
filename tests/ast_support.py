"""A Python-version-independent `ast.dump`.

Python 3.13 omits empty lists (`keywords=[]`, `type_ignores=[]`) from `ast.dump` by default; 3.12 prints them. A digest
of a dump therefore differs between the two interpreters for identical source. Structure tests that pin such digests use
`dump` so the digest is the same on 3.12 (CI) and 3.13+: from 3.13 the empty fields are requested explicitly, which
reproduces the 3.12 text.
"""

import ast
import sys


def dump(node: ast.AST) -> str:
    if sys.version_info >= (3, 13):
        return ast.dump(node, show_empty=True)
    return ast.dump(node)
