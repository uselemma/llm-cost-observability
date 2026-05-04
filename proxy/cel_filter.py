from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROMOTED_FIELDS: dict[str, str] = {
    "request_id": "String",
    "model": "String",
    "provider": "String",
    "team": "String",
    "status": "String",
    "finish_reason": "String",
    "spend_usd": "Float64",
    "prompt_tokens": "Float64",
    "completion_tokens": "Float64",
    "total_tokens": "Float64",
    "latency_ms": "Float64",
    "ttft_ms": "Float64",
    "num_retries": "Float64",
}

QUERYABLE_CEL_FIELDS: tuple[str, ...] = (
    *tuple(sorted(PROMOTED_FIELDS.keys())),
    "metadata.<key>",
)


@dataclass
class _Token:
    kind: str
    value: str


@dataclass
class _Literal:
    value: str | float | bool | None


@dataclass
class _FieldRef:
    parts: tuple[str, ...]


@dataclass
class _Unary:
    op: str
    expr: Any


@dataclass
class _Binary:
    op: str
    left: Any
    right: Any


@dataclass
class _Compare:
    op: str
    left: Any
    right: Any


@dataclass
class _Call:
    name: str
    args: tuple[Any, ...]


def _tokenize_cel(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(source):
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if source.startswith("&&", i) or source.startswith("||", i) or source.startswith(
            "==", i
        ) or source.startswith("!=", i) or source.startswith("<=", i) or source.startswith(">=", i):
            tokens.append(_Token("op", source[i : i + 2]))
            i += 2
            continue
        if ch in "()!,<>.":
            tokens.append(_Token("punct", ch))
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            i += 1
            out: list[str] = []
            while i < len(source):
                cur = source[i]
                if cur == "\\" and i + 1 < len(source):
                    out.append(source[i + 1])
                    i += 2
                    continue
                if cur == quote:
                    i += 1
                    break
                out.append(cur)
                i += 1
            else:
                raise ValueError("unterminated string literal")
            tokens.append(_Token("string", "".join(out)))
            continue
        if ch.isdigit() or (ch == "-" and i + 1 < len(source) and source[i + 1].isdigit()):
            start = i
            i += 1
            while i < len(source) and (source[i].isdigit() or source[i] == "."):
                i += 1
            number_text = source[start:i]
            try:
                number = float(number_text)
            except ValueError:
                raise ValueError(f"invalid number literal: {number_text}")
            tokens.append(_Token("number", str(number)))
            continue
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < len(source) and (source[i].isalnum() or source[i] == "_"):
                i += 1
            ident = source[start:i]
            if ident in {"true", "false", "null"}:
                tokens.append(_Token("literal", ident))
            else:
                tokens.append(_Token("ident", ident))
            continue
        raise ValueError(f"unexpected character: {ch!r}")
    return tokens


class _CelParser:
    def __init__(self, tokens: list[_Token]):
        self._tokens = tokens
        self._idx = 0

    def parse(self) -> Any:
        expr = self._parse_or()
        if self._peek() is not None:
            raise ValueError(f"unexpected token: {self._peek().value}")
        return expr

    def _parse_or(self) -> Any:
        expr = self._parse_and()
        while self._accept("op", "||"):
            expr = _Binary("||", expr, self._parse_and())
        return expr

    def _parse_and(self) -> Any:
        expr = self._parse_not()
        while self._accept("op", "&&"):
            expr = _Binary("&&", expr, self._parse_not())
        return expr

    def _parse_not(self) -> Any:
        if self._accept("punct", "!") or self._accept("op", "!"):
            return _Unary("!", self._parse_not())
        return self._parse_relation()

    def _parse_relation(self) -> Any:
        left = self._parse_atom()
        comp = self._accept("op", "==", "!=", "<", "<=", ">", ">=") or self._accept(
            "punct", "<", ">"
        )
        if comp:
            right = self._parse_atom()
            return _Compare(comp.value, left, right)
        return left

    def _parse_atom(self) -> Any:
        if self._accept("punct", "("):
            inner = self._parse_or()
            self._expect("punct", ")")
            return inner

        token = self._peek()
        if token is None:
            raise ValueError("unexpected end of expression")
        if token.kind == "string":
            self._idx += 1
            return _Literal(token.value)
        if token.kind == "number":
            self._idx += 1
            return _Literal(float(token.value))
        if token.kind == "literal":
            self._idx += 1
            if token.value == "true":
                return _Literal(True)
            if token.value == "false":
                return _Literal(False)
            return _Literal(None)
        if token.kind == "ident":
            return self._parse_identifier_atom()
        raise ValueError(f"unexpected token: {token.value}")

    def _parse_identifier_atom(self) -> Any:
        first = self._expect("ident")

        # Function style, e.g. has(metadata.trace_id), startsWith(status, "suc")
        if self._accept("punct", "("):
            return _Call(first.value, self._parse_call_args())

        # Field reference and optional method style helper:
        # metadata.customer_id.startsWith("acme")
        parts = [first.value]
        while self._accept("punct", "."):
            next_ident = self._expect("ident")
            if next_ident.value in {"startsWith", "endsWith", "contains"} and self._accept(
                "punct", "("
            ):
                base = _FieldRef(tuple(parts))
                return _Call(next_ident.value, (base, *self._parse_call_args()))
            parts.append(next_ident.value)

        return _FieldRef(tuple(parts))

    def _parse_call_args(self) -> tuple[Any, ...]:
        if self._accept("punct", ")"):
            return tuple()
        args: list[Any] = [self._parse_or()]
        while self._accept("punct", ","):
            args.append(self._parse_or())
        self._expect("punct", ")")
        return tuple(args)

    def _parse_field_ref(self) -> _FieldRef:
        first = self._expect("ident")
        parts = [first.value]
        while self._accept("punct", "."):
            parts.append(self._expect("ident").value)
        return _FieldRef(tuple(parts))

    def _peek(self) -> _Token | None:
        if self._idx >= len(self._tokens):
            return None
        return self._tokens[self._idx]

    def _accept(self, kind: str, *values: str) -> _Token | None:
        token = self._peek()
        if token is None or token.kind != kind:
            return None
        if values and token.value not in values:
            return None
        self._idx += 1
        return token

    def _expect(self, kind: str, value: str | None = None) -> _Token:
        token = self._peek()
        if token is None:
            expected = value if value else kind
            raise ValueError(f"expected {expected}, found end of expression")
        if token.kind != kind or (value is not None and token.value != value):
            expected = value if value else kind
            raise ValueError(f"expected {expected}, found {token.value}")
        self._idx += 1
        return token


class _CelToSqlCompiler:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self._counter = 0

    def compile(self, node: Any) -> tuple[str, str]:
        if isinstance(node, _Literal):
            if isinstance(node.value, bool):
                return ("1" if node.value else "0"), "bool"
            if node.value is None:
                return "NULL", "null"
            if isinstance(node.value, float):
                return self._bind("lit", "Float64", node.value), "number"
            return self._bind("lit", "String", node.value), "string"

        if isinstance(node, _Call):
            return self._compile_call(node)

        if isinstance(node, _Unary):
            inner_sql, inner_type = self.compile(node.expr)
            if inner_type != "bool":
                raise ValueError("logical negation expects a boolean expression")
            return f"(NOT ({inner_sql}))", "bool"

        if isinstance(node, _Binary):
            left_sql, left_type = self.compile(node.left)
            right_sql, right_type = self.compile(node.right)
            if left_type != "bool" or right_type != "bool":
                raise ValueError("logical operators require boolean operands")
            op = "AND" if node.op == "&&" else "OR"
            return f"(({left_sql}) {op} ({right_sql}))", "bool"

        if isinstance(node, _Compare):
            return self._compile_compare(node)

        if isinstance(node, _FieldRef):
            raise ValueError("bare field references are not allowed; use a comparison")

        raise ValueError("unsupported expression")

    def _compile_compare(self, node: _Compare) -> tuple[str, str]:
        left = self._describe_operand(node.left)
        right = self._describe_operand(node.right)
        op = node.op

        if left["kind"] == "metadata" and right["kind"] == "literal":
            return self._metadata_literal_compare(left["path"], op, right["value"])
        if right["kind"] == "metadata" and left["kind"] == "literal":
            flipped = _flip_compare(op)
            return self._metadata_literal_compare(right["path"], flipped, left["value"])

        if left["kind"] == "field" and right["kind"] == "literal":
            return self._field_literal_compare(left["name"], left["type"], op, right["value"])
        if right["kind"] == "field" and left["kind"] == "literal":
            flipped = _flip_compare(op)
            return self._field_literal_compare(right["name"], right["type"], flipped, left["value"])

        if left["kind"] == "field" and right["kind"] == "field":
            if left["type"] != right["type"]:
                raise ValueError("cannot compare fields with different types")
            return f"({left['name']} {op} {right['name']})", "bool"

        raise ValueError("comparison must include at least one supported field reference")

    def _compile_call(self, node: _Call) -> tuple[str, str]:
        if node.name == "has":
            if len(node.args) != 1:
                raise ValueError("has(...) expects exactly one argument")
            arg = node.args[0]
            if not isinstance(arg, _FieldRef):
                raise ValueError("has(...) expects a field reference")
            if len(arg.parts) < 2 or arg.parts[0] != "metadata":
                raise ValueError("has(...) only supports metadata.* paths")
            path = ".".join(arg.parts[1:])
            return f"JSONHas(metadata, {self._bind('meta_path', 'String', path)})", "bool"

        if node.name in {"startsWith", "endsWith", "contains"}:
            return self._compile_string_helper_call(node)

        raise ValueError(f"unsupported function call: {node.name}")

    def _compile_string_helper_call(self, node: _Call) -> tuple[str, str]:
        if len(node.args) != 2:
            raise ValueError(f"{node.name}(...) expects exactly two arguments")

        haystack_expr, exists_guard = self._string_expr_from_field(node.args[0], node.name)
        needle = node.args[1]
        if not isinstance(needle, _Literal) or not isinstance(needle.value, str):
            raise ValueError(f"{node.name}(...) expects a string literal as the second argument")
        needle_param = self._bind("needle", "String", needle.value)

        if node.name == "startsWith":
            predicate = f"startsWith({haystack_expr}, {needle_param})"
        elif node.name == "endsWith":
            predicate = f"endsWith({haystack_expr}, {needle_param})"
        else:
            predicate = f"(positionCaseInsensitive({haystack_expr}, {needle_param}) > 0)"

        if exists_guard:
            return f"({exists_guard} AND ({predicate}))", "bool"
        return predicate, "bool"

    def _string_expr_from_field(self, node: Any, fn_name: str) -> tuple[str, str | None]:
        info = self._describe_operand(node)
        if info["kind"] == "field":
            if info["type"] != "String":
                raise ValueError(f"{fn_name}(...) first argument must be a string field")
            return info["name"], None

        if info["kind"] == "metadata":
            path_param = self._bind("meta_path", "String", info["path"])
            return (
                f"JSONExtractString(metadata, {path_param})",
                f"JSONHas(metadata, {path_param})",
            )

        raise ValueError(f"{fn_name}(...) first argument must be a field reference")

    def _metadata_literal_compare(
        self, path: str, op: str, value: str | float | bool | None
    ) -> tuple[str, str]:
        if value is None:
            if op not in ("==", "!="):
                raise ValueError("metadata null comparisons only support == and !=")
            path_param = self._bind("meta_path", "String", path)
            exists = f"JSONHas(metadata, {path_param})"
            is_null = f"(JSONExtractRaw(metadata, {path_param}) = 'null')"
            if op == "==":
                return f"({exists} AND {is_null})", "bool"
            return f"(NOT ({exists} AND {is_null}))", "bool"

        path_param = self._bind("meta_path", "String", path)
        exists = f"JSONHas(metadata, {path_param})"

        if isinstance(value, bool):
            if op not in ("==", "!="):
                raise ValueError("boolean comparisons only support == and !=")
            rhs = "'true'" if value else "'false'"
            return (
                f"({exists} AND (JSONExtractRaw(metadata, {path_param}) {op} {rhs}))",
                "bool",
            )

        if isinstance(value, float):
            lhs = f"toFloat64OrNull(JSONExtractRaw(metadata, {path_param}))"
            rhs = self._bind("meta_num", "Float64", value)
            return f"({exists} AND ({lhs} {op} {rhs}))", "bool"

        lhs = f"JSONExtractString(metadata, {path_param})"
        rhs = self._bind("meta_str", "String", value)
        return f"({exists} AND ({lhs} {op} {rhs}))", "bool"

    def _field_literal_compare(
        self, field_name: str, field_type: str, op: str, value: str | float | bool | None
    ) -> tuple[str, str]:
        if value is None:
            if op == "==":
                return f"isNull({field_name})", "bool"
            if op == "!=":
                return f"isNotNull({field_name})", "bool"
            raise ValueError("null comparisons only support == and !=")

        if field_type == "String":
            if not isinstance(value, str):
                raise ValueError(f"field {field_name} expects a string literal")
            rhs = self._bind("field_str", "String", value)
            return f"({field_name} {op} {rhs})", "bool"

        if field_type == "Float64":
            if not isinstance(value, float):
                raise ValueError(f"field {field_name} expects a numeric literal")
            rhs = self._bind("field_num", "Float64", value)
            return f"({field_name} {op} {rhs})", "bool"

        raise ValueError(f"unsupported field type for {field_name}")

    def _describe_operand(self, node: Any) -> dict[str, Any]:
        if isinstance(node, _Literal):
            return {"kind": "literal", "value": node.value}
        if isinstance(node, _FieldRef):
            if len(node.parts) >= 2 and node.parts[0] == "metadata":
                return {"kind": "metadata", "path": ".".join(node.parts[1:])}
            name = node.parts[0] if len(node.parts) == 1 else ""
            if name not in PROMOTED_FIELDS:
                raise ValueError(f"unknown field: {'.'.join(node.parts)}")
            return {"kind": "field", "name": name, "type": PROMOTED_FIELDS[name]}
        raise ValueError("unsupported comparison operand")

    def _bind(self, prefix: str, ch_type: str, value: Any) -> str:
        name = f"{prefix}_{self._counter}"
        self._counter += 1
        self.params[name] = value
        return f"{{{name}:{ch_type}}}"


def _flip_compare(op: str) -> str:
    if op == "<":
        return ">"
    if op == "<=":
        return ">="
    if op == ">":
        return "<"
    if op == ">=":
        return "<="
    return op


def compile_cel_filter(expression: str) -> tuple[str, dict[str, Any]]:
    tokens = _tokenize_cel(expression)
    if not tokens:
        raise ValueError("expression is empty")
    ast = _CelParser(tokens).parse()
    compiler = _CelToSqlCompiler()
    sql, out_type = compiler.compile(ast)
    if out_type != "bool":
        raise ValueError("expression must evaluate to boolean")
    return sql, compiler.params


def list_queryable_cel_fields() -> list[str]:
    return list(QUERYABLE_CEL_FIELDS)
