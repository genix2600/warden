"""Dump the OpenAPI document, so the interface's types can be generated from it.

Run via ``npm run gen:types`` in ui/. The front end never hand-writes a type that
crosses the process boundary: ``ui/src/generated/api.ts`` is produced from this
document by ``openapi-typescript`` and is gitignored, so a change to a Pydantic
contract that the interface has not caught up with becomes a TypeScript error
instead of a runtime surprise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import Any

from warden.api import create_app
from warden.orchestrator import Agent


def mark_response_fields_required(document: dict[str, Any]) -> int:
    """Make every component property required.

    FastAPI describes these models in *validation* mode, where a field with a
    default is optional because a client may omit it. But these models only ever
    travel in the other direction: Pydantic serialises with every field present,
    so ``notes``, ``attempted_actions`` and the rest are never actually absent
    from a response.

    Left uncorrected, the generated TypeScript makes all of them ``| undefined``
    and the interface fills up with defensive ``?? []`` that can never fire --
    noise that hides the optionality that is real, like ``diagnosis`` being null
    before the reasoner has answered. Those stay nullable here because they are
    declared ``| None`` in Python, which is a different thing from unset.

    Only responses. A schema that a client *sends* must keep its optional
    fields optional -- a field with a default exists precisely so the caller may
    leave it out, and tightening it would force every caller to supply
    everything. Request schemas are therefore found and skipped rather than
    assumed absent, which is what the earlier version did until the settings
    endpoint became the first thing Warden accepts a body for.
    """
    schemas = document.get("components", {}).get("schemas", {})
    incoming = _request_schemas(document)

    changed = 0
    for name, schema in schemas.items():
        if name in incoming:
            continue
        properties = schema.get("properties")
        if not isinstance(properties, dict) or schema.get("type") != "object":
            continue
        if sorted(schema.get("required", [])) != sorted(properties):
            schema["required"] = sorted(properties)
            changed += 1
    return changed


def _request_schemas(document: dict[str, Any]) -> set[str]:
    """Every schema reachable from a request body, transitively.

    Transitively because a body model may nest others, and tightening a nested
    one is just as wrong as tightening the top level.
    """
    schemas = document.get("components", {}).get("schemas", {})
    roots: set[str] = set()
    for path in document.get("paths", {}).values():
        for operation in path.values():
            if not isinstance(operation, dict):
                continue
            body = operation.get("requestBody")
            if isinstance(body, dict):
                roots |= _referenced(body)

    seen: set[str] = set()
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        queue.extend(_referenced(schemas[name]))
    return seen


def _referenced(node: Any) -> set[str]:
    """Schema names mentioned by any $ref anywhere under this node."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            found |= _referenced(value)
    elif isinstance(node, list):
        for value in node:
            found |= _referenced(value)
    return found


def main() -> int:
    # The agent is constructed but never started: generating a schema must not
    # spawn a PowerShell host or touch the machine.
    app = create_app(Agent(), record=False)
    document = app.openapi()
    tightened = mark_response_fields_required(document)

    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "ui/openapi.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"wrote {destination} ({tightened} schemas tightened to always-present)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
