from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum as SAEnum, Boolean, Float
from sqlalchemy.orm import relationship, declarative_base

from app.enums import RoleEnum, StatusNodeEnum, NotificationTypeEnum

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(SAEnum(RoleEnum), nullable=False)
    phone = Column(String(20))
    project_id = Column(String(50), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    status_records = relationship("StatusRecord", back_populates="operator")
    sent_notifications = relationship(
        "Notification",
        back_populates="sender",
        foreign_keys="Notification.sender_id",
    )
    received_notifications = relationship(
        "Notification",
        back_populates="recipient",
        foreign_keys="Notification.recipient_id",
    )


class MaterialBatch(Base):
    __tablename__ = "material_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_no = Column(String(32), unique=True, index=True, nullable=False)
    project_id = Column(String(50), index=True, nullable=False)
    supplier = Column(String(200), nullable=False)
    material_category = Column(String(100), nullable=False)
    specification = Column(String(200), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit = Column(String(20), default="件")
    contract_no = Column(String(100), nullable=False)
    current_status = Column(SAEnum(StatusNodeEnum), default=StatusNodeEnum.REGISTERED, nullable=False)
    registered_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    attachments = relationship("Attachment", back_populates="batch", cascade="all, delete-orphan")
    status_records = relationship("StatusRecord", back_populates="batch", cascade="all, delete-orphan", order_by="StatusRecord.created_at")
    notifications = relationship("Notification", back_populates="batch", cascade="all, delete-orphan")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("material_batches.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50))
    file_size = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("MaterialBatch", back_populates="attachments")


class StatusRecord(Base):
    __tablename__ = "status_records"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("material_batches.id"), nullable=False)
    from_status = Column(SAEnum(StatusNodeEnum))
    to_status = Column(SAEnum(StatusNodeEnum), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    remark = Column(Text)
    docs_complete = Column(Boolean, default=True)
    has_reinspection = Column(Boolean, default=False)
    reinspection_deadline = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("MaterialBatch", back_populates="status_records")
    operator = relationship("User", back_populates="status_records")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("material_batches.id"), nullable=False)
    type = Column(SAEnum(NotificationTypeEnum), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"))
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_role = Column(SAEnum(RoleEnum), nullable=False)
    is_read = Column(Boolean, default=False)
    is_handled = Column(Boolean, default=False)
    handled_at = Column(DateTime)
    handle_remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("MaterialBatch", back_populates="notifications")
    sender = relationship("User", back_populates="sent_notifications", foreign_keys=[sender_id])
    recipient = relationship("User", back_populates="received_notifications", foreign_keys=[recipient_id])
    delivery_records = relationship("DeliveryRecord", back_populates="notification", cascade="all, delete-orphan")


class PushChannel(Base):
    __tablename__ = "push_channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    project_id = Column(String(50), index=True, nullable=False)
    callback_url = Column(String(500), nullable=False)
    secret = Column(String(200))
    headers_json = Column(Text)
    enabled = Column(Boolean, default=True)
    max_retries = Column(Integer, default=3)
    timeout_seconds = Column(Float, default=5.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    delivery_records = relationship("DeliveryRecord", back_populates="channel", cascade="all, delete-orphan")


class DeliveryRecord(Base):
    __tablename__ = "delivery_records"

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("notifications.id"), nullable=False)
    channel_id = Column(Integer, ForeignKey("push_channels.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    request_body = Column(Text)
    response_code = Column(Integer)
    response_body = Column(Text)
    retry_count = Column(Integer, default=0)
    error_message = Column(Text)
    delivered_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    notification = relationship("Notification", back_populates="delivery_records")
    channel = relationship("PushChannel", back_populates="delivery_records")
