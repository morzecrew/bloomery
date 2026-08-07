"""The Postgres dialect (RFC 0008 D5): the relational-engine port of the M10
port-validation milestone, and the engine-tier execution dialect (RFC 0009
§5.2 tier 5)."""

from __future__ import annotations

from typing import ClassVar

from sqlglot import exp

from bloomery.dialects.base import SQLGlotDialect
from bloomery.typing import (
    BoolType,
    DateType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

__all__ = [
    "PostgresDialect",
]

#: PostgreSQL's reserved key words (PostgreSQL docs, appendix C): the
#: ``reserved`` category plus the ``reserved (can be function or type name)``
#: category — neither may name a table or column unquoted. SQLGlot's postgres
#: generator (at the locked pin) quotes nothing here, unlike its duckdb and
#: trino generators, so an entity named ``order`` would render illegally;
#: :meth:`PostgresDialect.render` quotes these itself.
_RESERVED = frozenset(
    {
        "all", "analyse", "analyze", "and", "any", "array", "as", "asc",
        "asymmetric", "authorization", "binary", "both", "case", "cast",
        "check", "collate", "collation", "column", "concurrently",
        "constraint", "create", "cross", "current_catalog", "current_date",
        "current_role", "current_schema", "current_time",
        "current_timestamp", "current_user", "default", "deferrable", "desc",
        "distinct", "do", "else", "end", "except", "false", "fetch", "for",
        "foreign", "freeze", "from", "full", "grant", "group", "having",
        "ilike", "in", "initially", "inner", "intersect", "into", "is",
        "isnull", "join", "lateral", "leading", "left", "like", "limit",
        "localtime", "localtimestamp", "natural", "not", "notnull", "null",
        "offset", "on", "only", "or", "order", "outer", "overlaps",
        "placing", "primary", "references", "returning", "right", "select",
        "session_user", "similar", "some", "symmetric", "table",
        "tablesample", "then", "to", "trailing", "true", "union", "unique",
        "user", "using", "variadic", "verbose", "when", "where", "window",
        "with",
    }
)  # fmt: skip


class PostgresDialect(SQLGlotDialect):
    """Postgres: SQLGlot's ``postgres`` generator plus Postgres native types.

    ``variant`` maps to ``JSONB``, not ``JSON``: Postgres's binary form is
    the idiomatic semi-structured column (indexable, canonicalized), while
    plain ``JSON`` is a text blob that preserves key order and duplicates —
    properties bloomery's ``variant`` never promises.
    """

    name: str = "postgres"
    sqlglot_dialect: str = "postgres"
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "TEXT",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSONB",
    }

    def render(self, node: exp.Expression) -> str:
        """Render with reserved identifiers quoted and JSON extraction made
        ``jsonb``-safe — the input node is never mutated (the port contract
        shares ASTs across dialects).

        SQLGlot's postgres generator renders extraction as
        ``JSON_EXTRACT_PATH_TEXT(...)``, which exists only for the ``json``
        type — bloomery's ``variant`` is ``JSONB`` (verified live: the
        engine tier fails without this). Single-key paths render as the
        polymorphic ``->``/``->>`` operators; deeper paths keep the function
        form over an explicit ``CAST(... AS JSON)``.
        """
        rewritten = node.copy()
        for identifier in rewritten.find_all(exp.Identifier):
            if identifier.this.lower() in _RESERVED:
                identifier.set("quoted", True)
        for extract in rewritten.find_all(exp.JSONExtract, exp.JSONExtractScalar):
            path = extract.args.get("expression")
            if not isinstance(path, exp.JSONPath):
                continue
            parts = path.expressions
            if len(parts) == 2 and isinstance(parts[1], exp.JSONPathKey):
                extract.set("only_json_types", True)  # ``->``/``->>`` form
            else:
                extract.set("this", exp.cast(extract.this, exp.DataType.build("JSON")))
        return super().render(rewritten)
