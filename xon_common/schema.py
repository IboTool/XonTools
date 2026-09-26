"""Structured output from Pydantic models (XONFORGE_SPEC.md §4.2): the strict JSON schema a provider enforces, the
instruction that asks a model without that mode for JSON, and the validation of the text that comes back.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, TypeAdapter

# JSON-schema keywords Claude's structured outputs reject (Claude docs, "JSON Schema limitations", as A1 records them in
# xon/llm/client.py); minItems is accepted only as 0 or 1
ANTHROPIC_UNSUPPORTED = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                                   "minLength", "maxLength", "maxItems", "uniqueItems"})


def strict_schema(schema: type[BaseModel], *, unsupported: frozenset = frozenset(), max_min_items: int | None = None,
                  all_required: bool = False) -> dict:
    """The model's JSON schema with additionalProperties false on every object, as strict structured outputs
    require. A keyword in ``unsupported``, or a minItems above ``max_min_items``, raises ValueError;
    ``all_required`` lists every property of an object as required, as OpenAI's strict mode requires."""
    def strict(node, where: str):
        if isinstance(node, list):
            return [strict(v, where) for v in node]
        if not isinstance(node, dict):
            return node
        bad = sorted(unsupported & node.keys())
        if max_min_items is not None and node.get("minItems", 0) > max_min_items:
            bad.append("minItems")
        if bad:
            raise ValueError(f"{schema.__name__}{where} uses {', '.join(bad)}, which this provider's structured "
                             "outputs reject")
        out = {k: (v if k == "properties" else strict(v, f"{where}.{k}")) for k, v in node.items()}
        if "properties" in node:
            out["properties"] = {name: strict(v, f"{where}.{name}") for name, v in node["properties"].items()}
            if all_required:
                out["required"] = list(node["properties"])
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    return strict(TypeAdapter(schema).json_schema(), "")


def json_instruction(schema: type[BaseModel]) -> str:
    """Appended to the system prompt when the API does not enforce the schema itself."""
    return ("Answer with one JSON object and nothing else. It must match this JSON schema:\n"
            + json.dumps(TypeAdapter(schema).json_schema(), ensure_ascii=False, sort_keys=True))


def with_instruction(system: str, schema: type[BaseModel]) -> str:
    return f"{system}\n\n{json_instruction(schema)}" if system else json_instruction(schema)


def parse_json(text: str, schema: type[BaseModel]) -> BaseModel:
    """The response validated against the schema (pydantic's ValidationError if it does not match). A JSON object in
    a code fence is accepted, as models without a structured-output mode often answer that way."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.rsplit("```", 1)[0]
    return schema.model_validate_json(body)
