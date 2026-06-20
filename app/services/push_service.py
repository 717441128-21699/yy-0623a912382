import json
import hashlib
import hmac
import logging
from datetime import datetime
from typing import List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.models import PushChannel, DeliveryRecord, Notification, MaterialBatch, NotificationRule
from app.enums import NotificationTypeEnum, RoleEnum

logger = logging.getLogger(__name__)


def build_push_payload(notification: Notification, batch: Optional[MaterialBatch] = None) -> dict:
    payload = {
        "notification_id": notification.id,
        "type": notification.type.value if notification.type else None,
        "title": notification.title,
        "content": notification.content,
        "recipient_id": notification.recipient_id,
        "recipient_role": notification.recipient_role.value if notification.recipient_role else None,
        "is_read": notification.is_read,
        "is_handled": notification.is_handled,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }
    if batch:
        payload["batch_no"] = batch.batch_no
        payload["project_id"] = batch.project_id
        payload["supplier"] = batch.supplier
        payload["material_category"] = batch.material_category
        payload["current_status"] = batch.current_status.value if batch.current_status else None
    return payload


def sign_payload(payload: dict, secret: str) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()


def _one_attempt(
    db: Session,
    notification: Notification,
    channel: PushChannel,
    payload: dict,
    payload_json: str,
    headers: dict,
    attempt_no: int,
    timeout: float,
    trigger: str = "auto",
) -> DeliveryRecord:
    record = DeliveryRecord(
        notification_id=notification.id,
        channel_id=channel.id,
        status="pending",
        attempt_no=attempt_no,
        trigger=trigger,
        request_body=payload_json,
        retry_count=attempt_no - 1,
    )
    db.add(record)
    db.flush()

    try:
        resp = httpx.post(
            channel.callback_url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        record.response_code = resp.status_code
        record.response_body = resp.text[:2000] if resp.text else None
        if 200 <= resp.status_code < 300:
            record.status = "success"
            record.delivered_at = datetime.utcnow()
        else:
            record.status = "failed"
            record.error_message = f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        record.status = "failed"
        record.error_message = "请求超时"
    except httpx.RequestError as e:
        record.status = "failed"
        record.error_message = str(e)[:500]
    except Exception as e:
        record.status = "failed"
        record.error_message = f"未知异常: {str(e)[:500]}"

    db.commit()
    db.refresh(record)
    return record


def deliver_to_channel(
    db: Session,
    notification: Notification,
    channel: PushChannel,
    trigger: str = "auto",
) -> List[DeliveryRecord]:
    batch = notification.batch
    payload = build_push_payload(notification, batch)
    payload_json = json.dumps(payload, ensure_ascii=False)

    headers = {"Content-Type": "application/json"}
    if channel.headers_json:
        try:
            extra = json.loads(channel.headers_json)
            if isinstance(extra, dict):
                headers.update(extra)
        except json.JSONDecodeError:
            pass

    if channel.secret:
        sig = sign_payload(payload, channel.secret)
        headers["X-Signature"] = sig

    max_retries = channel.max_retries or 0
    timeout = channel.timeout_seconds or 5.0
    total_attempts = max_retries + 1

    records: List[DeliveryRecord] = []
    for attempt_no in range(1, total_attempts + 1):
        rec = _one_attempt(db, notification, channel, payload, payload_json, headers, attempt_no, timeout, trigger)
        records.append(rec)
        if rec.status == "success":
            break
        if attempt_no < total_attempts:
            logger.info(
                "投递失败，准备重试: notif_id=%s channel_id=%s attempt=%s/%s",
                notification.id, channel.id, attempt_no, total_attempts,
            )

    return records


def auto_deliver_notification(db: Session, notification: Notification) -> List[DeliveryRecord]:
    batch = notification.batch
    project_id = batch.project_id if batch else None
    if not project_id:
        return []

    channels = (
        db.query(PushChannel)
        .filter(PushChannel.project_id == project_id, PushChannel.enabled == True)
        .all()
    )

    all_records: List[DeliveryRecord] = []
    for channel in channels:
        try:
            records = deliver_to_channel(db, notification, channel, trigger="auto")
            all_records.extend(records)
        except Exception as e:
            logger.error("自动投递异常: notif_id=%s channel_id=%s err=%s", notification.id, channel.id, e)
    return all_records


def manual_deliver(
    db: Session,
    notification_id: int,
    channel_id: int,
) -> Tuple[Optional[List[DeliveryRecord]], Optional[str]]:
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        return None, "通知不存在"

    channel = db.query(PushChannel).filter(PushChannel.id == channel_id).first()
    if not channel:
        return None, "推送通道不存在"

    existing_success = (
        db.query(DeliveryRecord)
        .filter(
            DeliveryRecord.notification_id == notification_id,
            DeliveryRecord.channel_id == channel_id,
            DeliveryRecord.status == "success",
            DeliveryRecord.trigger.in_(["auto", "manual"]),
        )
        .first()
    )
    if existing_success:
        prev_records = (
            db.query(DeliveryRecord)
            .filter(
                DeliveryRecord.notification_id == notification_id,
                DeliveryRecord.channel_id == channel_id,
            )
            .order_by(DeliveryRecord.created_at)
            .all()
        )
        return prev_records, "该通知已通过此通道成功投递，可在历史记录中查看"

    records = deliver_to_channel(db, notification, channel, trigger="manual")
    return records, None


DEFAULT_NOTIFY_ROLES = {
    NotificationTypeEnum.MISSING_DOCS: [
        RoleEnum.MATERIAL_STAFF,
        RoleEnum.QUALITY_INSPECTOR,
        RoleEnum.PROJECT_MANAGER,
    ],
    NotificationTypeEnum.SUPERVISOR_REJECT: [
        RoleEnum.MATERIAL_STAFF,
        RoleEnum.QUALITY_INSPECTOR,
        RoleEnum.PROJECT_MANAGER,
    ],
    NotificationTypeEnum.REINSPECTION_OVERDUE: [
        RoleEnum.MATERIAL_STAFF,
        RoleEnum.QUALITY_INSPECTOR,
        RoleEnum.PROJECT_MANAGER,
    ],
}


def get_notify_roles(db: Session, project_id: str, event_type: NotificationTypeEnum) -> List[RoleEnum]:
    rule = (
        db.query(NotificationRule)
        .filter(
            NotificationRule.project_id == project_id,
            NotificationRule.event_type == event_type,
            NotificationRule.enabled == True,
        )
        .order_by(NotificationRule.updated_at.desc())
        .first()
    )
    if rule:
        try:
            role_values = json.loads(rule.roles_json)
            return [RoleEnum(rv) for rv in role_values if rv in RoleEnum._value2member_map_]
        except (json.JSONDecodeError, ValueError):
            pass
    return list(DEFAULT_NOTIFY_ROLES.get(event_type, []))


def set_notify_roles(
    db: Session,
    project_id: str,
    event_type: NotificationTypeEnum,
    roles: List[RoleEnum],
    created_by: int,
) -> NotificationRule:
    old_rules = (
        db.query(NotificationRule)
        .filter(
            NotificationRule.project_id == project_id,
            NotificationRule.event_type == event_type,
        )
        .all()
    )
    for r in old_rules:
        r.enabled = False

    rule = NotificationRule(
        project_id=project_id,
        event_type=event_type,
        roles_json=json.dumps([r.value for r in roles], ensure_ascii=False),
        enabled=True,
        created_by=created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def list_notify_rules(db: Session, project_id: str) -> List[dict]:
    configured = (
        db.query(NotificationRule)
        .filter(
            NotificationRule.project_id == project_id,
            NotificationRule.enabled == True,
        )
        .all()
    )
    configured_map = {r.event_type: r for r in configured}

    result = []
    for et, default_roles in DEFAULT_NOTIFY_ROLES.items():
        rule = configured_map.get(et)
        if rule:
            try:
                roles = [RoleEnum(rv) for rv in json.loads(rule.roles_json) if rv in RoleEnum._value2member_map_]
            except (json.JSONDecodeError, ValueError):
                roles = default_roles
            from app.enums import NOTIFICATION_LABEL_MAP
            result.append({
                "event_type": et.value,
                "event_label": NOTIFICATION_LABEL_MAP.get(et, str(et)),
                "roles": [r.value for r in roles],
                "role_labels": [ROLE_LABEL_MAP_FALLBACK(r) for r in roles],
                "is_custom": True,
                "rule_id": rule.id,
                "updated_at": rule.updated_at,
            })
        else:
            from app.enums import NOTIFICATION_LABEL_MAP
            result.append({
                "event_type": et.value,
                "event_label": NOTIFICATION_LABEL_MAP.get(et, str(et)),
                "roles": [r.value for r in default_roles],
                "role_labels": [ROLE_LABEL_MAP_FALLBACK(r) for r in default_roles],
                "is_custom": False,
                "rule_id": None,
                "updated_at": None,
            })
    return result


def ROLE_LABEL_MAP_FALLBACK(role: RoleEnum) -> str:
    from app.enums import ROLE_LABEL_MAP
    return ROLE_LABEL_MAP.get(role, str(role))
