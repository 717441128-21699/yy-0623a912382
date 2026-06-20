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
)
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
        filters = []
        if query.notification_id:
            filters.append(DeliveryRecord.notification_id == query.notification_id)
        if query.channel_id:
            filters.append(DeliveryRecord.channel_id == query.channel_id)
        if query.status:
            filters.append(DeliveryRecord.status == query.status)
        if filters:
            q = q.filter(and_(*filters))
        total = q.count()
        items = q.order_by(DeliveryRecord.created_at.desc()).offset(skip).limit(limit).all()
        return total, items

    def manual_push(self, notification_id: int, channel_id: int) -> Tuple[Optional[DeliveryRecord], Optional[str]]:
        from app.services.push_service import manual_deliver
        return manual_deliver(self.db, notification_id, channel_id)
