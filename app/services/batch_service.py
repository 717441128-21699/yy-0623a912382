from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.enums import (
    StatusNodeEnum,
    STATUS_FLOW_RULES,
    STATUS_LABEL_MAP,
    ROLE_LABEL_MAP,
    ROLE_STATUS_PERMISSIONS,
    STATUS_RESPONSIBLE_ROLE,
    RoleEnum,
)
from app.models import MaterialBatch, Attachment, StatusRecord, User, Notification, PushChannel, DeliveryRecord
from app.schemas import (
    BatchRegisterRequest,
    StatusUpdateRequest,
    BatchListQuery,
    BatchDetailResponse,
    NextNodeInfo,
    NotificationListQuery,
    NotificationHandleRequest,
    PushChannelCreate,
    PushChannelUpdate,
    DeliveryRecordListQuery,
    DashboardResponse,
    StatusCountItem,
)
from app.enums import StatusNodeEnum
from app.utils import generate_batch_no
from app.services.notification_service import (
    check_and_notify_status,
    compute_reinspection_deadline,
)


def _build_next_nodes(current_status: StatusNodeEnum) -> List[NextNodeInfo]:
    allowed = STATUS_FLOW_RULES.get(current_status, [])
    result = []
    for node in allowed:
        allowed_roles = [
            role for role, nodes in ROLE_STATUS_PERMISSIONS.items()
            if node in nodes
        ]
        result.append(NextNodeInfo(
            node=node,
            label=STATUS_LABEL_MAP.get(node, str(node)),
            allowed_roles=allowed_roles,
            allowed_role_labels=[ROLE_LABEL_MAP.get(r, str(r)) for r in allowed_roles],
        ))
    return result


class BatchService:
    def __init__(self, db: Session):
        self.db = db

    def _get_user(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def _get_batch_by_no(self, batch_no: str) -> Optional[MaterialBatch]:
        return self.db.query(MaterialBatch).filter(MaterialBatch.batch_no == batch_no).first()

    def register_batch(self, req: BatchRegisterRequest) -> Tuple[Optional[MaterialBatch], Optional[str]]:
        user = self._get_user(req.registered_by)
        if not user:
            return None, "登记人不存在"

        batch_no = generate_batch_no(req.project_id)
        while self._get_batch_by_no(batch_no):
            batch_no = generate_batch_no(req.project_id)

        batch = MaterialBatch(
            batch_no=batch_no,
            project_id=req.project_id,
            supplier=req.supplier,
            material_category=req.material_category,
            specification=req.specification,
            quantity=req.quantity,
            unit=req.unit or "件",
            contract_no=req.contract_no,
            registered_by=req.registered_by,
            remark=req.remark,
        )
        self.db.add(batch)
        self.db.flush()

        if req.attachments:
            for att in req.attachments:
                attachment = Attachment(
                    batch_id=batch.id,
                    file_name=att.file_name,
                    file_path=att.file_path,
                    file_type=att.file_type,
                    file_size=att.file_size,
                )
                self.db.add(attachment)

        init_record = StatusRecord(
            batch_id=batch.id,
            from_status=None,
            to_status=StatusNodeEnum.REGISTERED,
            operator_id=req.registered_by,
            remark="批次初始登记",
            docs_complete=True,
            has_reinspection=False,
        )
        self.db.add(init_record)
        self.db.commit()
        self.db.refresh(batch)
        return batch, None

    def update_status(self, req: StatusUpdateRequest) -> Tuple[Optional[StatusRecord], Optional[str]]:
        batch = self._get_batch_by_no(req.batch_no)
        if not batch:
            return None, "批次不存在"

        operator = self._get_user(req.operator_id)
        if not operator:
            return None, "操作人不存在"

        current_status = batch.current_status
        allowed_next = STATUS_FLOW_RULES.get(current_status, [])
        if req.to_status not in allowed_next:
            current_label = STATUS_LABEL_MAP.get(current_status, str(current_status))
            target_label = STATUS_LABEL_MAP.get(req.to_status, str(req.to_status))
            allowed_labels = [STATUS_LABEL_MAP.get(s, str(s)) for s in allowed_next]
            return None, (
                f"状态流转不合法：当前状态【{current_label}】不能流转到【{target_label}】，"
                f"当前可流转节点：{'、'.join(allowed_labels) if allowed_labels else '无（已终结）'}"
            )

        permitted_nodes = ROLE_STATUS_PERMISSIONS.get(operator.role, [])
        if req.to_status not in permitted_nodes:
            operator_role_label = ROLE_LABEL_MAP.get(operator.role, str(operator.role))
            target_label = STATUS_LABEL_MAP.get(req.to_status, str(req.to_status))
            return None, (
                f"角色无权限：{operator_role_label}（{operator.full_name}）无权操作【{target_label}】节点，"
                f"请联系对应角色人员处理"
            )

        reinspection_deadline = None
        if req.to_status == StatusNodeEnum.REINSPECTION_PENDING:
            reinspection_deadline = compute_reinspection_deadline()

        record = StatusRecord(
            batch_id=batch.id,
            from_status=current_status,
            to_status=req.to_status,
            operator_id=req.operator_id,
            remark=req.remark,
            docs_complete=req.docs_complete if req.docs_complete is not None else True,
            has_reinspection=req.has_reinspection if req.has_reinspection is not None else False,
            reinspection_deadline=reinspection_deadline,
        )
        self.db.add(record)

        batch.current_status = req.to_status
        self.db.flush()

        check_and_notify_status(self.db, batch, record)

        self.db.commit()
        self.db.refresh(record)
        return record, None

    def get_batch_detail(self, batch_no: str) -> Optional[dict]:
        batch = self._get_batch_by_no(batch_no)
        if not batch:
            return None

        resp = BatchDetailResponse.model_validate(batch)
        responsible_role = STATUS_RESPONSIBLE_ROLE.get(batch.current_status)
        resp.current_responsible_role = responsible_role
        resp.current_responsible_role_label = ROLE_LABEL_MAP.get(responsible_role) if responsible_role else None
        resp.next_available_nodes = _build_next_nodes(batch.current_status)
        resp.timeline = _build_timeline(self.db, batch)
        return resp

    def list_batches(self, query: BatchListQuery, skip: int = 0, limit: int = 50) -> Tuple[int, List[MaterialBatch]]:
        q = self.db.query(MaterialBatch)
        filters = []
        if query.project_id:
            filters.append(MaterialBatch.project_id == query.project_id)
        if query.current_status:
            filters.append(MaterialBatch.current_status == query.current_status)
        if query.supplier:
            filters.append(MaterialBatch.supplier.contains(query.supplier))
        if query.material_category:
            filters.append(MaterialBatch.material_category.contains(query.material_category))
        if query.contract_no:
            filters.append(MaterialBatch.contract_no.contains(query.contract_no))
        if filters:
            q = q.filter(and_(*filters))

        total = q.count()
        items = q.order_by(MaterialBatch.created_at.desc()).offset(skip).limit(limit).all()
        return total, items


class NotificationService:
    def __init__(self, db: Session):
        self.db = db

    def list_notifications(
        self,
        query: NotificationListQuery,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[int, List[Notification]]:
        q = self.db.query(Notification)
        filters = []
        if query.recipient_id:
            filters.append(Notification.recipient_id == query.recipient_id)
        if query.recipient_role:
            filters.append(Notification.recipient_role == query.recipient_role)
        if query.is_handled is not None:
            filters.append(Notification.is_handled == query.is_handled)
        if query.type:
            filters.append(Notification.type == query.type)
        if filters:
            q = q.filter(and_(*filters))

        total = q.count()
        items = q.order_by(Notification.created_at.desc()).offset(skip).limit(limit).all()
        return total, items

    def mark_read(self, notif_id: int, user_id: int) -> Tuple[Optional[Notification], Optional[str]]:
        notif = self.db.query(Notification).filter(Notification.id == notif_id).first()
        if not notif:
            return None, "通知不存在"
        if notif.recipient_id != user_id:
            return None, "无权限操作该通知"
        notif.is_read = True
        self.db.commit()
        self.db.refresh(notif)
        return notif, None

    def handle_notification(
        self,
        notif_id: int,
        user_id: int,
        req: NotificationHandleRequest,
    ) -> Tuple[Optional[Notification], Optional[str]]:
        notif = self.db.query(Notification).filter(Notification.id == notif_id).first()
        if not notif:
            return None, "通知不存在"
        if notif.recipient_id != user_id:
            return None, "无权限操作该通知"
        from datetime import datetime
        notif.is_handled = req.is_handled
        notif.handle_remark = req.handle_remark
        if req.is_handled:
            notif.handled_at = datetime.utcnow()
        notif.is_read = True
        self.db.commit()
        self.db.refresh(notif)
        return notif, None


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def create_user(self, username: str, full_name: str, role, phone: Optional[str] = None, project_id: Optional[str] = None):
        existing = self.db.query(User).filter(User.username == username).first()
        if existing:
            return existing, False
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            phone=phone,
            project_id=project_id,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user, True

    def get_user(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def list_users(self, project_id: Optional[str] = None, role=None) -> List[User]:
        q = self.db.query(User)
        if project_id:
            q = q.filter(User.project_id == project_id)
        if role:
            q = q.filter(User.role == role)
        return q.all()


class PushChannelService:
    def __init__(self, db: Session):
        self.db = db

    def create_channel(self, req: PushChannelCreate) -> PushChannel:
        channel = PushChannel(
            name=req.name,
            project_id=req.project_id,
            callback_url=req.callback_url,
            secret=req.secret,
            headers_json=req.headers_json,
            enabled=req.enabled if req.enabled is not None else True,
            max_retries=req.max_retries or 3,
            timeout_seconds=req.timeout_seconds or 5.0,
        )
        self.db.add(channel)
        self.db.commit()
        self.db.refresh(channel)
        return channel

    def update_channel(self, channel_id: int, req: PushChannelUpdate) -> Tuple[Optional[PushChannel], Optional[str]]:
        channel = self.db.query(PushChannel).filter(PushChannel.id == channel_id).first()
        if not channel:
            return None, "推送通道不存在"
        update_data = req.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(channel, key, value)
        self.db.commit()
        self.db.refresh(channel)
        return channel, None

    def delete_channel(self, channel_id: int) -> Tuple[bool, Optional[str]]:
        channel = self.db.query(PushChannel).filter(PushChannel.id == channel_id).first()
        if not channel:
            return False, "推送通道不存在"
        self.db.delete(channel)
        self.db.commit()
        return True, None

    def get_channel(self, channel_id: int) -> Optional[PushChannel]:
        return self.db.query(PushChannel).filter(PushChannel.id == channel_id).first()

    def list_channels(self, project_id: Optional[str] = None, enabled: Optional[bool] = None) -> List[PushChannel]:
        q = self.db.query(PushChannel)
        if project_id:
            q = q.filter(PushChannel.project_id == project_id)
        if enabled is not None:
            q = q.filter(PushChannel.enabled == enabled)
        return q.order_by(PushChannel.created_at.desc()).all()


class DeliveryService:
    def __init__(self, db: Session):
        self.db = db

    def list_records(self, query: DeliveryRecordListQuery, skip: int = 0, limit: int = 50) -> Tuple[int, List[DeliveryRecord]]:
        q = self.db.query(DeliveryRecord)
        q = q.join(Notification, Notification.id == DeliveryRecord.notification_id)
        q = q.join(MaterialBatch, MaterialBatch.id == Notification.batch_id)
        filters = []
        if query.notification_id:
            filters.append(DeliveryRecord.notification_id == query.notification_id)
        if query.channel_id:
            filters.append(DeliveryRecord.channel_id == query.channel_id)
        if query.status:
            filters.append(DeliveryRecord.status == query.status)
        if query.batch_no:
            filters.append(MaterialBatch.batch_no == query.batch_no)
        if query.recipient_id:
            filters.append(Notification.recipient_id == query.recipient_id)
        if query.recipient_role:
            filters.append(Notification.recipient_role == query.recipient_role)
        if query.project_id:
            filters.append(MaterialBatch.project_id == query.project_id)
        if filters:
            q = q.filter(and_(*filters))
        total = q.count()
        items = q.order_by(DeliveryRecord.attempt_no.asc()).offset(skip).limit(limit).all()
        return total, items

    def manual_push(
        self, notification_id: int, channel_id: int
    ) -> Tuple[Optional[List[DeliveryRecord]], Optional[str]]:
        from app.services.push_service import manual_deliver
        return manual_deliver(self.db, notification_id, channel_id)


class DashboardService:
    def __init__(self, db: Session):
        self.db = db

    def get_project_dashboard(self, project_id: str) -> DashboardResponse:
        from datetime import datetime
        from sqlalchemy import func

        batches_q = self.db.query(MaterialBatch).filter(MaterialBatch.project_id == project_id)
        total_batches = batches_q.count()

        status_counts = []
        for status_node in StatusNodeEnum:
            cnt = batches_q.filter(MaterialBatch.current_status == status_node).count()
            if cnt > 0:
                status_counts.append(StatusCountItem(
                    status=status_node,
                    status_label=STATUS_LABEL_MAP.get(status_node, str(status_node)),
                    count=cnt,
                ))

        now = datetime.utcnow()
        from app.models import StatusRecord as SR

        overdue_subq = (
            self.db.query(SR.batch_id, func.max(SR.id).label("latest_id"))
            .filter(SR.to_status == StatusNodeEnum.REINSPECTION_PENDING, SR.reinspection_deadline.isnot(None))
            .group_by(SR.batch_id)
            .subquery()
        )
        overdue_count = (
            self.db.query(MaterialBatch)
            .join(overdue_subq, overdue_subq.c.batch_id == MaterialBatch.id)
            .join(SR, SR.id == overdue_subq.c.latest_id)
            .filter(
                MaterialBatch.project_id == project_id,
                MaterialBatch.current_status == StatusNodeEnum.REINSPECTION_PENDING,
                SR.reinspection_deadline < now,
            )
            .count()
        )

        pending_material = batches_q.filter(
            MaterialBatch.current_status.in_([StatusNodeEnum.ARRIVED])
        ).count()

        pending_quality = batches_q.filter(
            MaterialBatch.current_status.in_([
                StatusNodeEnum.UNLOADED,
                StatusNodeEnum.ACCEPTED,
                StatusNodeEnum.REINSPECTION_PENDING,
                StatusNodeEnum.SUPERVISOR_REJECTED,
            ])
        ).count()

        return DashboardResponse(
            project_id=project_id,
            total_batches=total_batches,
            status_counts=status_counts,
            overdue_reinspection_count=overdue_count,
            pending_material_staff_count=pending_material,
            pending_quality_inspector_count=pending_quality,
        )


def _build_timeline(db: Session, batch: MaterialBatch) -> List[dict]:
    events: List[dict] = []

    for sr in batch.status_records:
        events.append({
            "type": "status",
            "event_type_label": "状态流转",
            "time": sr.created_at,
            "from_status": sr.from_status.value if sr.from_status else None,
            "from_status_label": STATUS_LABEL_MAP.get(sr.from_status) if sr.from_status else None,
            "to_status": sr.to_status.value,
            "to_status_label": STATUS_LABEL_MAP.get(sr.to_status, str(sr.to_status)),
            "operator_name": sr.operator.full_name if sr.operator else None,
            "operator_role": sr.operator.role.value if sr.operator and sr.operator.role else None,
            "operator_role_label": ROLE_LABEL_MAP.get(sr.operator.role) if sr.operator and sr.operator.role else None,
            "remark": sr.remark,
            "docs_complete": sr.docs_complete,
            "reinspection_deadline": sr.reinspection_deadline,
        })

    for n in batch.notifications:
        events.append({
            "type": "notification",
            "event_type_label": "通知生成",
            "time": n.created_at,
            "notification_id": n.id,
            "notification_type": n.type.value if n.type else None,
            "notification_type_label": _notification_label(n.type),
            "title": n.title,
            "recipient_name": n.recipient.full_name if n.recipient else None,
            "recipient_role": n.recipient_role.value if n.recipient_role else None,
            "recipient_role_label": ROLE_LABEL_MAP.get(n.recipient_role) if n.recipient_role else None,
            "is_read": n.is_read,
            "is_handled": n.is_handled,
            "sender_name": n.sender.full_name if n.sender else None,
        })

    for n in batch.notifications:
        for dr in n.delivery_records:
            events.append({
                "type": "delivery",
                "event_type_label": "外部推送",
                "time": dr.created_at,
                "notification_id": n.id,
                "delivery_id": dr.id,
                "notification_type": n.type.value if n.type else None,
                "notification_type_label": _notification_label(n.type),
                "recipient_role": n.recipient_role.value if n.recipient_role else None,
                "recipient_role_label": ROLE_LABEL_MAP.get(n.recipient_role) if n.recipient_role else None,
                "channel_name": dr.channel.name if dr.channel else None,
                "status": dr.status,
                "attempt_no": dr.attempt_no,
                "trigger": dr.trigger,
                "response_code": dr.response_code,
                "error_message": dr.error_message,
                "delivered_at": dr.delivered_at,
            })

    events.sort(key=lambda e: (e["time"] if e["time"] else datetime.min))
    return events


def _notification_label(nt) -> str:
    from app.enums import NOTIFICATION_LABEL_MAP
    return NOTIFICATION_LABEL_MAP.get(nt, str(nt)) if nt else ""


ROLE_TODO_STATUS_MAP = {
    RoleEnum.GATE_STAFF: [StatusNodeEnum.REGISTERED],
    RoleEnum.MATERIAL_STAFF: [StatusNodeEnum.ARRIVED],
    RoleEnum.QUALITY_INSPECTOR: [
        StatusNodeEnum.UNLOADED,
        StatusNodeEnum.ACCEPTED,
        StatusNodeEnum.REINSPECTION_PENDING,
        StatusNodeEnum.SUPERVISOR_REJECTED,
    ],
    RoleEnum.SUPERVISOR: [StatusNodeEnum.REINSPECTION_DONE],
}

PROJECT_MANAGER_WATCH_STATUS = [
    StatusNodeEnum.REINSPECTION_PENDING,
    StatusNodeEnum.SUPERVISOR_REJECTED,
]


class TodolistService:
    def __init__(self, db: Session):
        self.db = db

    def _batch_to_todo(self, batch: MaterialBatch, responsible_role: Optional[RoleEnum] = None, is_exception: bool = False) -> dict:
        role = responsible_role or STATUS_RESPONSIBLE_ROLE.get(batch.current_status)
        notif_ids = [n.id for n in batch.notifications]
        return {
            "batch_no": batch.batch_no,
            "batch_id": batch.id,
            "project_id": batch.project_id,
            "supplier": batch.supplier,
            "material_category": batch.material_category,
            "specification": batch.specification,
            "quantity": batch.quantity,
            "unit": batch.unit,
            "current_status": batch.current_status,
            "current_status_label": STATUS_LABEL_MAP.get(batch.current_status, str(batch.current_status)),
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
            "responsible_role": role.value if role else None,
            "responsible_role_label": ROLE_LABEL_MAP.get(role) if role else None,
            "related_notification_ids": notif_ids,
            "is_exception": is_exception,
        }

    def _build_project_overview(self, project_id: str) -> dict:
        from app.models import StatusRecord as SR
        from sqlalchemy import func

        role_stats = []
        total_pending = 0
        for role, statuses in ROLE_TODO_STATUS_MAP.items():
            cnt = (
                self.db.query(MaterialBatch)
                .filter(
                    MaterialBatch.project_id == project_id,
                    MaterialBatch.current_status.in_(statuses),
                )
                .count()
            )
            total_pending += cnt
            role_stats.append({
                "role": role,
                "role_label": ROLE_LABEL_MAP.get(role, str(role)),
                "pending_count": cnt,
            })

        now = datetime.utcnow()
        overdue_subq = (
            self.db.query(SR.batch_id, func.max(SR.id).label("latest_id"))
            .filter(
                SR.to_status == StatusNodeEnum.REINSPECTION_PENDING,
                SR.reinspection_deadline.isnot(None),
            )
            .group_by(SR.batch_id)
            .subquery()
        )
        overdue_count = (
            self.db.query(MaterialBatch)
            .join(overdue_subq, overdue_subq.c.batch_id == MaterialBatch.id)
            .join(SR, SR.id == overdue_subq.c.latest_id)
            .filter(
                MaterialBatch.project_id == project_id,
                MaterialBatch.current_status == StatusNodeEnum.REINSPECTION_PENDING,
                SR.reinspection_deadline < now,
            )
            .count()
        )
        reject_count = (
            self.db.query(MaterialBatch)
            .filter(
                MaterialBatch.project_id == project_id,
                MaterialBatch.current_status == StatusNodeEnum.SUPERVISOR_REJECTED,
            )
            .count()
        )
        exception_count = overdue_count + reject_count

        latest_sr = (
            self.db.query(SR)
            .join(MaterialBatch, MaterialBatch.id == SR.batch_id)
            .filter(MaterialBatch.project_id == project_id)
            .order_by(SR.created_at.desc())
            .first()
        )

        return {
            "project_id": project_id,
            "total_pending_batches": total_pending,
            "exception_count": exception_count,
            "latest_status_updated_at": latest_sr.created_at if latest_sr else None,
            "role_stats": role_stats,
        }

    def get_todolist(self, user_id: int):
        from app.models import StatusRecord as SR
        from sqlalchemy import func
        from datetime import datetime

        user_svc = UserService(self.db)
        user = user_svc.get_user(user_id)
        if not user:
            return None, "用户不存在"

        project_id = user.project_id
        role = user.role

        todo_batches: List[MaterialBatch] = []
        groups = []

        todo_statuses = ROLE_TODO_STATUS_MAP.get(role, [])
        if todo_statuses:
            todos = (
                self.db.query(MaterialBatch)
                .filter(
                    MaterialBatch.project_id == project_id,
                    MaterialBatch.current_status.in_(todo_statuses),
                )
                .order_by(MaterialBatch.updated_at.desc())
                .all()
            )
            todo_batches.extend(todos)
            for s in todo_statuses:
                cnt = sum(1 for b in todos if b.current_status == s)
                if cnt > 0:
                    groups.append({
                        "group_type": "status",
                        "status": s.value,
                        "label": STATUS_LABEL_MAP.get(s, str(s)),
                        "count": cnt,
                    })

        notif_q = NotificationListQuery(recipient_id=user_id, is_handled=False)
        notif_svc = NotificationService(self.db)
        _, unhandled_notifs = notif_svc.list_notifications(notif_q, skip=0, limit=200)
        notif_batch_ids = list({n.batch_id for n in unhandled_notifs})
        for bid in notif_batch_ids:
            if bid not in [b.id for b in todo_batches]:
                b = self.db.query(MaterialBatch).filter(MaterialBatch.id == bid).first()
                if b:
                    todo_batches.append(b)
        if unhandled_notifs:
            groups.append({
                "group_type": "notification",
                "status": None,
                "label": "待处理通知",
                "count": len(unhandled_notifs),
            })

        exception_batches_data = []
        if role == RoleEnum.PROJECT_MANAGER:
            now = datetime.utcnow()
            overdue_subq = (
                self.db.query(SR.batch_id, func.max(SR.id).label("latest_id"))
                .filter(
                    SR.to_status == StatusNodeEnum.REINSPECTION_PENDING,
                    SR.reinspection_deadline.isnot(None),
                )
                .group_by(SR.batch_id)
                .subquery()
            )
            overs = (
                self.db.query(MaterialBatch)
                .join(overdue_subq, overdue_subq.c.batch_id == MaterialBatch.id)
                .join(SR, SR.id == overdue_subq.c.latest_id)
                .filter(
                    MaterialBatch.project_id == project_id,
                    MaterialBatch.current_status == StatusNodeEnum.REINSPECTION_PENDING,
                    SR.reinspection_deadline < now,
                )
                .all()
            )
            rejects = (
                self.db.query(MaterialBatch)
                .filter(
                    MaterialBatch.project_id == project_id,
                    MaterialBatch.current_status == StatusNodeEnum.SUPERVISOR_REJECTED,
                )
                .all()
            )
            ex_batches = overs + rejects
            ex_ids = set()
            for b in ex_batches:
                if b.id not in ex_ids:
                    ex_ids.add(b.id)
                    exception_batches_data.append(self._batch_to_todo(b, is_exception=True))
                if b.id not in [x.id for x in todo_batches]:
                    todo_batches.append(b)
            if exception_batches_data:
                groups.append({
                    "group_type": "exception",
                    "status": None,
                    "label": "关注异常批次",
                    "count": len(exception_batches_data),
                })

        todo_batch_items = []
        todo_ids = set()
        for b in todo_batches:
            if b.id in todo_ids:
                continue
            todo_ids.add(b.id)
            is_ex = b.id in [x["batch_id"] for x in exception_batches_data]
            todo_batch_items.append(self._batch_to_todo(b, is_exception=is_ex))

        notif_items = []
        for n in unhandled_notifs:
            nd = n.__dict__.copy()
            nd["batch_no"] = n.batch.batch_no if n.batch else None
            notif_items.append(nd)

        project_overview = None
        if role == RoleEnum.PROJECT_MANAGER:
            project_overview = self._build_project_overview(project_id)

        total_count = len(todo_batch_items) + len(unhandled_notifs)

        return {
            "user_id": user.id,
            "user_role": role,
            "user_role_label": ROLE_LABEL_MAP.get(role, str(role)),
            "total_count": total_count,
            "groups": groups,
            "batches": todo_batch_items,
            "notifications": notif_items,
            "exception_batches": exception_batches_data,
            "project_overview": project_overview,
        }, None


class NotificationRuleService:
    def __init__(self, db: Session):
        self.db = db

    def list_rules(self, project_id: str):
        from app.services.push_service import list_notify_rules
        raw = list_notify_rules(self.db, project_id)
        result = []
        for r in raw:
            result.append({
                "event_type": r["event_type"],
                "event_label": r["event_label"],
                "roles": r["roles"],
                "role_labels": r["role_labels"],
                "is_custom": r["is_custom"],
                "enabled": r["enabled"],
                "rule_id": r["rule_id"],
                "updated_at": r["updated_at"],
            })
        return {
            "project_id": project_id,
            "rules": result,
        }

    def set_rule(self, project_id: str, event_type, roles, created_by: int):
        from app.services.push_service import set_notify_roles
        rule = set_notify_roles(self.db, project_id, event_type, roles, created_by)
        return self.list_rules(project_id), None

    def toggle_rule(self, project_id: str, event_type, enabled: bool, operator_id: int):
        from app.services.push_service import set_rule_enabled
        rule = set_rule_enabled(self.db, project_id, event_type, enabled)
        if not rule:
            return None, "该事件暂无自定义规则，无法切换启用状态"
        return self.list_rules(project_id), None

