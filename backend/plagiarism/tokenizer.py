"""
tokenizer.py
Turns source code into a normalized token stream so that plagiarism
detection survives the "cheap disguises": renamed variables, different
whitespace/indentation, reordered comments, changed literal values.

Identifiers -> "ID"
Numbers     -> "NUM"
Strings     -> "STR"
Comments    -> dropped entirely
Keywords / operators / punctuation -> kept as-is (these carry the real
structural signal: a for-loop is still a for-loop after renaming `i`).
"""

import io
import keyword
import re
import tokenize as pytokenize

JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "true", "false", "null",
}

JAVA_TOKEN_RE = re.compile(
    r"""
      (?P<STRING>"(?:\\.|[^"\\])*")
    | (?P<CHAR>'(?:\\.|[^'\\])*')
    | (?P<NUMBER>\b\d+\.?\d*\b)
    | (?P<IDENT>[A-Za-z_]\w*)
    | (?P<OP>[{}()\[\];,.<>=+\-*/%!&|^~?:]+)
    """,
    re.VERBOSE,
)


def _strip_java_comments(code: str) -> str:
    # Remove /* ... */ block comments and // line comments (naive but
    # sufficient here since we've already excluded string contents below
    # by processing this before tokenizing).
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.DOTALL)
    code = re.sub(r"//[^\n]*", " ", code)
    return code


def tokenize_python(code: str) -> list[str]:
    tokens = []
    try:
        stream = io.StringIO(code).readline
        for tok in pytokenize.generate_tokens(stream):
            tok_type, tok_string, *_ = tok
            if tok_type in (pytokenize.COMMENT, pytokenize.NL, pytokenize.NEWLINE,
                             pytokenize.INDENT, pytokenize.DEDENT, pytokenize.ENCODING):
                continue
            if tok_type == pytokenize.NAME:
                tokens.append(tok_string if keyword.iskeyword(tok_string) else "ID")
            elif tok_type == pytokenize.NUMBER:
                tokens.append("NUM")
            elif tok_type == pytokenize.STRING:
                tokens.append("STR")
            elif tok_string.strip():
                tokens.append(tok_string)
    except (pytokenize.TokenizeError, IndentationError, SyntaxError):
        # Fall back to a crude whitespace split so a syntax error in one
        # submission doesn't crash the whole plagiarism run.
        tokens = code.split()
    return tokens


def tokenize_java(code: str) -> list[str]:
    code = _strip_java_comments(code)
    tokens = []
    for m in JAVA_TOKEN_RE.finditer(code):
        if m.lastgroup == "STRING" or m.lastgroup == "CHAR":
            tokens.append("STR")
        elif m.lastgroup == "NUMBER":
            tokens.append("NUM")
        elif m.lastgroup == "IDENT":
            word = m.group()
            tokens.append(word if word in JAVA_KEYWORDS else "ID")
        else:
            tokens.append(m.group())
    return tokens


def tokenize(code: str, language: str) -> list[str]:
    if language == "python":
        return tokenize_python(code)
    if language == "java":
        return tokenize_java(code)
    raise ValueError(f"Unsupported language for tokenizing: {language}")
