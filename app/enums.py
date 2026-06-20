from enum import Enum


class RoleEnum(str, Enum):
    MATERIAL_STAFF = "material_staff"
    QUALITY_INSPECTOR = "quality_inspector"
    PROJECT_MANAGER = "project_manager"
    SUPERVISOR = "supervisor"
    GATE_STAFF = "gate_staff"


ROLE_LABEL_MAP = {
    RoleEnum.MATERIAL_STAFF: "材料员",
    RoleEnum.QUALITY_INSPECTOR: "质检员",
    RoleEnum.PROJECT_MANAGER: "项目经理",
    RoleEnum.SUPERVISOR: "监理",
    RoleEnum.GATE_STAFF: "门禁人员",
}


class StatusNodeEnum(str, Enum):
    REGISTERED = "registered"
    ARRIVED = "arrived"
    UNLOADED = "unloaded"
    ACCEPTED = "accepted"
    REINSPECTION_PENDING = "reinspection_pending"
    REINSPECTION_DONE = "reinspection_done"
    SUPERVISOR_REJECTED = "supervisor_rejected"
    EXITED = "exited"


STATUS_LABEL_MAP = {
    StatusNodeEnum.REGISTERED: "已登记",
    StatusNodeEnum.ARRIVED: "已到场",
    StatusNodeEnum.UNLOADED: "已卸货",
    StatusNodeEnum.ACCEPTED: "已验收",
    StatusNodeEnum.REINSPECTION_PENDING: "待复检",
    StatusNodeEnum.REINSPECTION_DONE: "复检完成",
    StatusNodeEnum.SUPERVISOR_REJECTED: "监理驳回",
    StatusNodeEnum.EXITED: "已退场",
}


STATUS_FLOW_RULES = {
    StatusNodeEnum.REGISTERED: [StatusNodeEnum.ARRIVED, StatusNodeEnum.EXITED],
    StatusNodeEnum.ARRIVED: [StatusNodeEnum.UNLOADED, StatusNodeEnum.EXITED],
    StatusNodeEnum.UNLOADED: [StatusNodeEnum.ACCEPTED, StatusNodeEnum.REINSPECTION_PENDING, StatusNodeEnum.EXITED],
    StatusNodeEnum.ACCEPTED: [StatusNodeEnum.REINSPECTION_PENDING, StatusNodeEnum.EXITED],
    StatusNodeEnum.REINSPECTION_PENDING: [StatusNodeEnum.REINSPECTION_DONE, StatusNodeEnum.SUPERVISOR_REJECTED, StatusNodeEnum.EXITED],
    StatusNodeEnum.REINSPECTION_DONE: [StatusNodeEnum.SUPERVISOR_REJECTED, StatusNodeEnum.EXITED],
    StatusNodeEnum.SUPERVISOR_REJECTED: [StatusNodeEnum.REINSPECTION_PENDING, StatusNodeEnum.EXITED],
    StatusNodeEnum.EXITED: [],
}


ROLE_STATUS_PERMISSIONS = {
    RoleEnum.GATE_STAFF: [StatusNodeEnum.ARRIVED, StatusNodeEnum.EXITED],
    RoleEnum.MATERIAL_STAFF: [StatusNodeEnum.UNLOADED, StatusNodeEnum.EXITED],
    RoleEnum.QUALITY_INSPECTOR: [StatusNodeEnum.ACCEPTED, StatusNodeEnum.REINSPECTION_PENDING, StatusNodeEnum.REINSPECTION_DONE, StatusNodeEnum.EXITED],
    RoleEnum.SUPERVISOR: [StatusNodeEnum.SUPERVISOR_REJECTED, StatusNodeEnum.EXITED],
    RoleEnum.PROJECT_MANAGER: [StatusNodeEnum.EXITED],
}


STATUS_RESPONSIBLE_ROLE = {
    StatusNodeEnum.REGISTERED: RoleEnum.MATERIAL_STAFF,
    StatusNodeEnum.ARRIVED: RoleEnum.MATERIAL_STAFF,
    StatusNodeEnum.UNLOADED: RoleEnum.QUALITY_INSPECTOR,
    StatusNodeEnum.ACCEPTED: RoleEnum.QUALITY_INSPECTOR,
    StatusNodeEnum.REINSPECTION_PENDING: RoleEnum.QUALITY_INSPECTOR,
    StatusNodeEnum.REINSPECTION_DONE: RoleEnum.SUPERVISOR,
    StatusNodeEnum.SUPERVISOR_REJECTED: RoleEnum.QUALITY_INSPECTOR,
    StatusNodeEnum.EXITED: None,
}


class NotificationTypeEnum(str, Enum):
    MISSING_DOCS = "missing_docs"
    REINSPECTION_OVERDUE = "reinspection_overdue"
    SUPERVISOR_REJECT = "supervisor_reject"


NOTIFICATION_LABEL_MAP = {
    NotificationTypeEnum.MISSING_DOCS: "资料缺失",
    NotificationTypeEnum.REINSPECTION_OVERDUE: "复检逾期",
    NotificationTypeEnum.SUPERVISOR_REJECT: "监理驳回",
}
