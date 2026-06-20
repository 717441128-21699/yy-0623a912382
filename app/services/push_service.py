import json
import hashlib
import hmac
import logging
from datetime import datetime
from typing import List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.models import PushChannel, DeliveryRecord, Notification, MaterialBatch
from app.enums import NotificationTypeEnum

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


def deliver_to_channel(
    db: Session,
    notification: Notification,
    channel: PushChannel,
) -> DeliveryRecord:
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

    record = DeliveryRecord(
        notification_id=notification.id,
        channel_id=channel.id,
        status="pending",
        request_body=payload_json,
        retry_count=0,
    )
    db.add(record)
    db.flush()

    max_retries = channel.max_retries or 3
    timeout = channel.timeout_seconds or 5.0

    for attempt in range(max_retries + 1):
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
                break
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

        record.retry_count = attempt + 1
        if attempt < max_retries and record.status == "failed":
            logger.info(
                "投递失败，准备重试: notif_id=%s channel_id=%s attempt=%s",
                notification.id, channel.id, attempt + 1,
            )

    db.commit()
    db.refresh(record)
    return record


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

    results = []
    for channel in channels:
        try:
            record = deliver_to_channel(db, notification, channel)
            results.append(record)
        except Exception as e:
            logger.error("自动投递异常: notif_id=%s channel_id=%s err=%s", notification.id, channel.id, e)
    return results


def manual_deliver(db: Session, notification_id: int, channel_id: int) -> Tuple[Optional[DeliveryRecord], Optional[str]]:
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        return None, "通知不存在"

    channel = db.query(PushChannel).filter(PushChannel.id == channel_id).first()
    if not channel:
        return None, "推送通道不存在"

    existing = (
        db.query(DeliveryRecord)
        .filter(
            DeliveryRecord.notification_id == notification_id,
            DeliveryRecord.channel_id == channel_id,
            DeliveryRecord.status == "success",
        )
        .first()
    )
    if existing:
        return existing, "该通知已通过此通道成功投递，无需重复推送"

    record = deliver_to_channel(db, notification, channel)
    return record, None
