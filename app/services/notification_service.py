from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MaterialBatch, StatusRecord, Notification, User
from app.enums import (
    StatusNodeEnum,
    NotificationTypeEnum,
    RoleEnum,
    STATUS_LABEL_MAP,
)


NOTIFY_ROLES = [
    RoleEnum.MATERIAL_STAFF,
    RoleEnum.QUALITY_INSPECTOR,
    RoleEnum.PROJECT_MANAGER,
]


def _get_project_users(db: Session, project_id: str, roles: List[RoleEnum]) -> List[User]:
    return (
        db.query(User)
        .filter(
            User.project_id == project_id,
            User.role.in_(roles),
        )
        .all()
    )


def _create_notification(
    db: Session,
    batch: MaterialBatch,
    notif_type: NotificationTypeEnum,
    title: str,
    content: str,
    recipient: User,
    sender_id: Optional[int] = None,
    auto_push: bool = True,
) -> Notification:
    notif = Notification(
        batch_id=batch.id,
        type=notif_type,
        title=title,
        content=content,
        sender_id=sender_id,
        recipient_id=recipient.id,
        recipient_role=recipient.role,
    )
    db.add(notif)
    db.flush()

    if auto_push:
        try:
            from app.services.push_service import auto_deliver_notification
            auto_deliver_notification(db, notif)
        except Exception:
            pass

    return notif


def notify_missing_docs(
    db: Session,
    batch: MaterialBatch,
    status_record: StatusRecord,
) -> List[Notification]:
    title = f"[资料缺失] 批次 {batch.batch_no} 验收资料不完整"
    content = (
        f"批次【{batch.batch_no}】在【{STATUS_LABEL_MAP.get(status_record.to_status)}】节点验收时，"
        f"资料不完整。材料类别：{batch.material_category}，规格：{batch.specification}，"
        f"数量：{batch.quantity}{batch.unit}，供应商：{batch.supplier}。"
        f"请材料员尽快补齐相关资料。备注：{status_record.remark or '无'}"
    )
    users = _get_project_users(db, batch.project_id, NOTIFY_ROLES)
    results = []
    for user in users:
        results.append(
            _create_notification(
                db, batch, NotificationTypeEnum.MISSING_DOCS,
                title, content, user, sender_id=status_record.operator_id,
            )
        )
    db.commit()
    return results


def notify_supervisor_reject(
    db: Session,
    batch: MaterialBatch,
    status_record: StatusRecord,
) -> List[Notification]:
    title = f"[监理驳回] 批次 {batch.batch_no} 复检结果未通过"
    content = (
        f"批次【{batch.batch_no}】被监理驳回。材料类别：{batch.material_category}，"
        f"规格：{batch.specification}，数量：{batch.quantity}{batch.unit}，供应商：{batch.supplier}。"
        f"请相关人员立即处理，处理建议：重新送检或联系供应商。"
        f"驳回原因：{status_record.remark or '未填写'}"
    )
    users = _get_project_users(db, batch.project_id, NOTIFY_ROLES)
    results = []
    for user in users:
        results.append(
            _create_notification(
                db, batch, NotificationTypeEnum.SUPERVISOR_REJECT,
                title, content, user, sender_id=status_record.operator_id,
            )
        )
    db.commit()
    return results


def notify_reinspection_overdue(db: Session, batch: MaterialBatch) -> List[Notification]:
    title = f"[复检逾期] 批次 {batch.batch_no} 复检已超过期限"
    content = (
        f"批次【{batch.batch_no}】当前处于【待复检】状态，复检期限已过。"
        f"材料类别：{batch.material_category}，规格：{batch.specification}，"
        f"数量：{batch.quantity}{batch.unit}，供应商：{batch.supplier}。"
        f"请质检员立即安排复检，项目经理督促跟进。"
    )
    users = _get_project_users(db, batch.project_id, NOTIFY_ROLES)
    results = []
    for user in users:
        results.append(
            _create_notification(
                db, batch, NotificationTypeEnum.REINSPECTION_OVERDUE,
                title, content, user,
            )
        )
    db.commit()
    return results


def check_and_notify_status(
    db: Session,
    batch: MaterialBatch,
    status_record: StatusRecord,
) -> List[Notification]:
    all_notifs = []

    if not status_record.docs_complete:
        all_notifs.extend(notify_missing_docs(db, batch, status_record))

    if status_record.to_status == StatusNodeEnum.SUPERVISOR_REJECTED:
        all_notifs.extend(notify_supervisor_reject(db, batch, status_record))

    return all_notifs


def scan_and_notify_overdue(db: Session) -> dict:
    from sqlalchemy import func

    now = datetime.utcnow()

    subq = (
        db.query(
            StatusRecord.batch_id,
            func.max(StatusRecord.id).label("latest_id"),
        )
        .filter(
            StatusRecord.to_status == StatusNodeEnum.REINSPECTION_PENDING,
            StatusRecord.reinspection_deadline.isnot(None),
        )
        .group_by(StatusRecord.batch_id)
        .subquery()
    )

    overdue_batches = (
        db.query(MaterialBatch)
        .join(subq, subq.c.batch_id == MaterialBatch.id)
        .join(StatusRecord, StatusRecord.id == subq.c.latest_id)
        .filter(
            MaterialBatch.current_status == StatusNodeEnum.REINSPECTION_PENDING,
            StatusRecord.reinspection_deadline < now,
        )
        .all()
    )

    count = 0
    for batch in overdue_batches:
        existing = (
            db.query(Notification)
            .filter(
                Notification.batch_id == batch.id,
                Notification.type == NotificationTypeEnum.REINSPECTION_OVERDUE,
                Notification.is_handled == False,
            )
            .first()
        )
        if not existing:
            notify_reinspection_overdue(db, batch)
            count += 1

    return {"scanned": len(overdue_batches), "notified": count}


def compute_reinspection_deadline(base_time: Optional[datetime] = None) -> datetime:
    base = base_time or datetime.utcnow()
    return base + timedelta(days=settings.REINSPECTION_DAYS)
