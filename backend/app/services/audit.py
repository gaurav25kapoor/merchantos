from datetime import datetime
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import AuditEvent


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def log_event(
        self,
        merchant_id: UUID,
        event_type: str,
        entity_type: str,
        entity_id: object | None = None,
        actor_type: str = "system",
        actor_id: object | None = None,
        metadata: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            merchant_id=merchant_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            metadata_json=jsonable_encoder(metadata or {}),
        )
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(
        self,
        merchant_id: UUID,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEvent], int]:
        query = self.db.query(AuditEvent).filter(AuditEvent.merchant_id == merchant_id)
        if event_type:
            query = query.filter(AuditEvent.event_type == event_type)
        if entity_type:
            query = query.filter(AuditEvent.entity_type == entity_type)
        if entity_id:
            query = query.filter(AuditEvent.entity_id == entity_id)
        if start_date:
            query = query.filter(AuditEvent.created_at >= start_date)
        if end_date:
            query = query.filter(AuditEvent.created_at <= end_date)
        total = query.count()
        events = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit).all()
        return events, total


def log_audit_event(
    db: Session,
    merchant_id: UUID,
    event_type: str,
    entity_type: str,
    entity_id: object | None = None,
    actor_type: str = "system",
    actor_id: object | None = None,
    metadata: dict | None = None,
) -> AuditEvent | None:
    try:
        return AuditService(db).log_event(merchant_id, event_type, entity_type, entity_id, actor_type, actor_id, metadata)
    except Exception:
        return None
