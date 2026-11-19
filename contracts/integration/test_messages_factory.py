"""Validate actual Messages factory output against the parent wire contracts.

Run in the Messages uv environment with its src on pytest's configured path.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from app.application.events.factory import EventFactory
from app.application.events.models import AttachmentSnapshotDTO
from app.application.ports.dto.outbox import OutboxMessage
from app.domain.aggregates.message import Message
from app.domain.value_objects.client_message_id import ClientMessageId
from app.domain.value_objects.message_content import MessageContent
from app.domain.value_objects.message_position import MessagePosition

CONTRACTS = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


@pytest.mark.parametrize("event_kind", ["persisted", "created", "rejected", "receipt"])
@pytest.mark.parametrize("with_causation", [False, True])
@pytest.mark.parametrize("with_attachment", [False, True])
def test_real_factory_output_matches_wire_contract(
    event_kind, with_causation, with_attachment
):
    schemas = [
        json.loads(path.read_text()) for path in CONTRACTS.rglob("*.schema.json")
    ]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    factory = EventFactory(clock=lambda: NOW)
    dialog_id, sender_id, recipient_id = uuid7(), uuid7(), uuid7()
    message = Message.create(
        dialog_id=dialog_id,
        sender_id=sender_id,
        client_message_id=ClientMessageId.generate(),
        content=MessageContent.from_text("Wire contract"),
        position=MessagePosition(dialog_id=dialog_id, value=1),
        now=NOW,
    )
    attachments = (
        (
            AttachmentSnapshotDTO(
                object_id=uuid7(),
                media_type="image/png",
                size_bytes=64,
                sha256_base64="A" * 43 + "=",
            ),
        )
        if with_attachment
        else ()
    )
    causation_id = uuid7() if with_causation else None
    context = {"correlation_id": uuid7(), "causation_id": causation_id}
    if event_kind == "persisted":
        events = (
            factory.create_message_persisted(
                message=message,
                attachments=attachments,
                **context,
            ),
        )
    elif event_kind == "created":
        events = factory.create_message_created_batch(
            message=message,
            recipient_ids=(recipient_id, uuid7()),
            attachments=attachments,
            **context,
        )
    elif event_kind == "rejected":
        events = (
            factory.create_message_rejected(
                target_user_id=sender_id,
                client_message_id=message.client_message_id.value,
                dialog_id=dialog_id,
                code="message.send_conflict",
                **context,
            ),
        )
    else:
        events = (
            factory.create_receipt_watermark_advanced(
                dialog_id=dialog_id,
                target_user_id=sender_id,
                kind="READ",
                through_message_id=message.id,
                through_message_time=NOW,
                status_version=1,
                **context,
            ),
        )

    for event in events:
        schema = next(s for s in schemas if s.get("title") == event.type)
        Draft202012Validator(
            schema, registry=registry, format_checker=FormatChecker()
        ).validate(event.payload)
        assert event.topic == "messaging.events.v1"
        assert event.key == event.payload["payload"]["targetUserId"]
        assert event.id == UUID(event.payload["eventId"])
        if causation_id is None:
            assert "causationId" not in event.payload
        else:
            assert event.payload["causationId"] == str(causation_id)
        restored = OutboxMessage.model_validate_json(event.model_dump_json())
        assert restored.id == event.id
        assert restored.payload == event.payload
    assert len({event.id for event in events}) == len(events)
