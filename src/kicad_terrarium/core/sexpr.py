"""Small, non-serializing S-expression scanner for KiCad files.

Terrarium edits source spans instead of parsing and re-emitting whole KiCad
documents.  Unknown and future fields therefore remain untouched.
"""

from __future__ import annotations

from dataclasses import dataclass


class SExprError(ValueError):
    """Malformed S-expression input."""


@dataclass(frozen=True)
class Form:
    start: int
    end: int
    head: str
    depth: int


@dataclass(frozen=True)
class StringToken:
    value: str
    start: int
    end: int


def _head_at(text: str, start: int) -> str:
    i = start + 1
    while i < len(text) and text[i].isspace():
        i += 1
    begin = i
    while i < len(text) and not text[i].isspace() and text[i] not in '()"':
        i += 1
    return text[begin:i]


def forms(text: str) -> list[Form]:
    """Return every balanced form with source spans and nesting depth."""
    stack: list[tuple[int, str, int]] = []
    found: list[Form] = []
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            stack.append((index, _head_at(text, index), len(stack)))
        elif char == ")":
            if not stack:
                raise SExprError(f"unexpected ')' at offset {index}")
            start, head, depth = stack.pop()
            found.append(Form(start, index + 1, head, depth))

    if in_string:
        raise SExprError("unterminated quoted string")
    if stack:
        raise SExprError(f"unclosed form at offset {stack[-1][0]}")
    return sorted(found, key=lambda form: form.start)


def root_form(text: str, expected_head: str | None = None) -> Form:
    roots = [form for form in forms(text) if form.depth == 0]
    if len(roots) != 1:
        raise SExprError(f"expected one root form, found {len(roots)}")
    root = roots[0]
    if expected_head is not None and root.head != expected_head:
        raise SExprError(f"expected ({expected_head} ...), found ({root.head} ...)")
    return root


def child_forms(all_forms: list[Form], parent: Form, head: str | None = None) -> list[Form]:
    """Immediate child forms of ``parent``, optionally filtered by head."""
    return [
        form
        for form in all_forms
        if form.depth == parent.depth + 1
        and parent.start < form.start
        and form.end < parent.end
        and (head is None or form.head == head)
    ]


def descendant_forms(all_forms: list[Form], parent: Form, head: str | None = None) -> list[Form]:
    return [
        form
        for form in all_forms
        if form.depth > parent.depth
        and parent.start < form.start
        and form.end < parent.end
        and (head is None or form.head == head)
    ]


def _decode_string(raw: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            escaped = raw[i + 1]
            result.append({"n": "\n", "r": "\r", "t": "\t"}.get(escaped, escaped))
            i += 2
        else:
            result.append(raw[i])
            i += 1
    return "".join(result)


def quoted_tokens(text: str, form: Form, *, immediate_only: bool = True) -> list[StringToken]:
    """Quoted strings in a form, with exact spans including quote characters."""
    tokens: list[StringToken] = []
    depth = 0
    in_string = False
    escaped = False
    start = 0
    i = form.start + 1
    while i < form.end - 1:
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                if not immediate_only or depth == 0:
                    tokens.append(StringToken(_decode_string(text[start + 1 : i]), start, i + 1))
                in_string = False
        elif char == '"':
            in_string = True
            start = i
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        i += 1
    if in_string:
        raise SExprError(f"unterminated quoted string in ({form.head} ...) form")
    return tokens


def atoms(text: str, form: Form) -> list[str]:
    """Unquoted immediate atoms after a form's head."""
    body_start = form.start + 1
    while body_start < form.end and text[body_start].isspace():
        body_start += 1
    body_start += len(form.head)
    values: list[str] = []
    token: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    for char in text[body_start : form.end - 1]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            if token:
                values.append("".join(token))
                token = []
            in_string = True
        elif char == "(":
            if depth == 0 and token:
                values.append("".join(token))
                token = []
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and char.isspace():
            if token:
                values.append("".join(token))
                token = []
        elif depth == 0:
            token.append(char)
    if token:
        values.append("".join(token))
    return values


def quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def apply_replacements(text: str, replacements: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping source-span replacements from right to left."""
    ordered = sorted(replacements, key=lambda replacement: replacement[0])
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous[1] > current[0]:
            raise ValueError("overlapping replacements")
    result = text
    for start, end, replacement in reversed(ordered):
        result = result[:start] + replacement + result[end:]
    return result
