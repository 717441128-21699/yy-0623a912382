from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from app.enums import RoleEnum, StatusNodeEnum, NotificationTypeEnum, STATUS_LABEL_MAP, ROLE_LABEL_MAP


class UserBase(BaseModel):
    username: str
    full_name: str
    role: RoleEnum
    phone: Optional[str] = None
    project_id: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

    @property
    def role_label(self) -> str:
        return ROLE_LABEL_MAP.get(self.role, str(self.role))


class UserSimple(BaseModel):
    id: int
    full_name: str
    role: RoleEnum

    class Config:
        from_attributes = True

    @property
    def role_label(self) -> str:
        return ROLE_LABEL_MAP.get(self.role, str(self.role))


class AttachmentBase(BaseModel):
    file_name: str
    file_path: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None


class AttachmentCreate(AttachmentBase):
    pass


class AttachmentResponse(AttachmentBase):
    id: int
    uploaded_at: datetime

    class Config:
        from_attributes = True


class BatchRegisterRequest(BaseModel):
    project_id: str = Field(..., description="项目编号")
    supplier: str = Field(..., description="供应商名称", min_length=1)
    material_category: str = Field(..., description="材料类别", min_length=1)
    specification: str = Field(..., description="规格型号", min_length=1)
    quantity: int = Field(..., description="数量", gt=0)
    unit: Optional[str] = "件"
    contract_no: str = Field(..., description="合同编号", min_length=1)
    registered_by: int = Field(..., description="登记人ID（材料员）")
    remark: Optional[str] = None
    attachments: Optional[List[AttachmentCreate]] = Field(default_factory=list, description="附件列表")


class BatchRegisterResponse(BaseModel):
    batch_no: str = Field(..., description="唯一批次号")
    message: str = "批次登记成功"


class StatusRecordBase(BaseModel):
    pass


class StatusUpdateRequest(BaseModel):
    batch_no: str = Field(..., description="批次号")
    to_status: StatusNodeEnum = Field(..., description="目标状态节点")
    operator_id: int = Field(..., description="操作人ID")
    remark: Optional[str] = None
    docs_complete: Optional[bool] = True
    has_reinspection: Optional[bool] = False


class StatusRecordResponse(BaseModel):
    id: int
    from_status: Optional[StatusNodeEnum]
    to_status: StatusNodeEnum
    operator: UserSimple
    remark: Optional[str]
    docs_complete: bool
    has_reinspection: bool
    reinspection_deadline: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

    @property
    def from_status_label(self) -> Optional[str]:
        return STATUS_LABEL_MAP.get(self.from_status) if self.from_status else None

    @property
    def to_status_label(self) -> str:
        return STATUS_LABEL_MAP.get(self.to_status, str(self.to_status))


class BatchDetailResponse(BaseModel):
    id: int
    batch_no: str
    project_id: str
    supplier: str
    material_category: str
    specification: str
    quantity: int
    unit: str
    contract_no: str
    current_status: StatusNodeEnum
    registered_by: int
    remark: Optional[str]
    created_at: datetime
    updated_at: datetime
    attachments: List[AttachmentResponse] = Field(default_factory=list)
    status_records: List[StatusRecordResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True

    @property
    def current_status_label(self) -> str:
        return STATUS_LABEL_MAP.get(self.current_status, str(self.current_status))

    @property
    def current_operator(self) -> Optional[UserSimple]:
        if self.status_records:
            return self.status_records[-1].operator
        return None


class BatchListQuery(BaseModel):
    project_id: Optional[str] = None
    current_status: Optional[StatusNodeEnum] = None
    supplier: Optional[str] = None
    material_category: Optional[str] = None
    contract_no: Optional[str] = None


class BatchListItem(BaseModel):
    id: int
    batch_no: str
    project_id: str
    supplier: str
    material_category: str
    specification: str
    quantity: int
    unit: str
    contract_no: str
    current_status: StatusNodeEnum
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @property
    def current_status_label(self) -> str:
        return STATUS_LABEL_MAP.get(self.current_status, str(self.current_status))


class BatchListResponse(BaseModel):
    total: int
    items: List[BatchListItem]


class NotificationResponse(BaseModel):
    id: int
    batch_id: int
    batch_no: Optional[str] = None
    type: NotificationTypeEnum
    title: str
    content: str
    sender: Optional[UserSimple] = None
    recipient_id: int
    recipient_role: RoleEnum
    is_read: bool
    is_handled: bool
    handled_at: Optional[datetime] = None
    handle_remark: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @property
    def type_label(self) -> str:
        from app.enums import NOTIFICATION_LABEL_MAP
        return NOTIFICATION_LABEL_MAP.get(self.type, str(self.type))

    @property
    def recipient_role_label(self) -> str:
        return ROLE_LABEL_MAP.get(self.recipient_role, str(self.recipient_role))


class NotificationHandleRequest(BaseModel):
    is_handled: bool = True
    handle_remark: Optional[str] = None


class NotificationListQuery(BaseModel):
    recipient_id: Optional[int] = None
    recipient_role: Optional[RoleEnum] = None
    is_handled: Optional[bool] = None
    type: Optional[NotificationTypeEnum] = None


class NotificationListResponse(BaseModel):
    total: int
    items: List[NotificationResponse]
