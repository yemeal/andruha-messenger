from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
CAMEL_CASE = re.compile(r"^[a-z][A-Za-z0-9]*$")

EXAMPLE_SCHEMAS = {
    "identity/user-registered.v1": "identity/events/user-registered.v1.schema.json",
    "messaging/message-send.v1": "messaging/commands/message-send.v1.schema.json",
    "messaging/receipt-advance.v1": "messaging/commands/receipt-advance.v1.schema.json",
    "messaging/message-persisted.v1": "messaging/events/message-persisted.v1.schema.json",
    "messaging/message-created.v1": "messaging/events/message-created.v1.schema.json",
    "messaging/message-rejected.v1": "messaging/events/message-rejected.v1.schema.json",
    "messaging/receipt-watermark-advanced.v1": (
        "messaging/events/receipt-watermark-advanced.v1.schema.json"
    ),
    "envelope/dlq-envelope.v1": "envelope/dlq-envelope.v1.schema.json",
}


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_catalog() -> tuple[dict[Path, dict[str, object]], Registry]:
    schemas: dict[Path, dict[str, object]] = {}
    resources: list[tuple[str, Resource]] = []
    schema_ids: set[str] = set()

    for path in sorted(CONTRACTS_ROOT.rglob("*.schema.json")):
        schema = load_json(path)
        assert isinstance(schema, dict)
        Draft202012Validator.check_schema(schema)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str):
            raise AssertionError(f"Schema has no string $id: {path}")
        if schema_id in schema_ids:
            raise AssertionError(f"Duplicate schema $id {schema_id}: {path}")
        schema_ids.add(schema_id)
        schemas[path] = schema
        resources.append((schema_id, Resource.from_contents(schema)))

    return schemas, Registry().with_resources(resources)


def iter_object_keys(value: object):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from iter_object_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_object_keys(nested)


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas, cls.registry = schema_catalog()

    def test_all_json_documents_parse(self) -> None:
        for path in sorted(CONTRACTS_ROOT.rglob("*.json")):
            with self.subTest(path=path.relative_to(CONTRACTS_ROOT)):
                load_json(path)

    def test_schema_and_example_keys_are_camel_case(self) -> None:
        for path in sorted(CONTRACTS_ROOT.rglob("*.json")):
            document = load_json(path)
            with self.subTest(path=path.relative_to(CONTRACTS_ROOT)):
                for key in iter_object_keys(document):
                    if key.startswith("$") or key in {
                        "additionalProperties",
                        "allOf",
                        "anyOf",
                        "const",
                        "contentEncoding",
                        "description",
                        "enum",
                        "format",
                        "items",
                        "maxItems",
                        "maxLength",
                        "maximum",
                        "minItems",
                        "minLength",
                        "minimum",
                        "pattern",
                        "properties",
                        "required",
                        "title",
                        "type",
                        "uniqueItems",
                    }:
                        continue
                    self.assertRegex(key, CAMEL_CASE)

    def test_valid_examples_are_accepted(self) -> None:
        for example_root, schema_relative in EXAMPLE_SCHEMAS.items():
            schema = self.schemas[CONTRACTS_ROOT / schema_relative]
            validator = Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
                registry=self.registry,
            )
            valid_dir = CONTRACTS_ROOT / "examples" / example_root / "valid"
            examples = sorted(valid_dir.glob("*.json"))
            self.assertTrue(examples, f"No valid example for {example_root}")
            for path in examples:
                with self.subTest(path=path.relative_to(CONTRACTS_ROOT)):
                    errors = list(validator.iter_errors(load_json(path)))
                    self.assertEqual([], errors)

    def test_invalid_examples_are_rejected(self) -> None:
        for example_root, schema_relative in EXAMPLE_SCHEMAS.items():
            schema = self.schemas[CONTRACTS_ROOT / schema_relative]
            validator = Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
                registry=self.registry,
            )
            invalid_dir = CONTRACTS_ROOT / "examples" / example_root / "invalid"
            examples = sorted(invalid_dir.glob("*.json"))
            self.assertTrue(examples, f"No invalid example for {example_root}")
            for path in examples:
                with self.subTest(path=path.relative_to(CONTRACTS_ROOT)):
                    errors = list(validator.iter_errors(load_json(path)))
                    self.assertTrue(errors, f"Invalid fixture was accepted: {path}")


if __name__ == "__main__":
    unittest.main()
