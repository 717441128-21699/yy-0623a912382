from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import StatusUpdateRequest, StatusRecordResponse
from app.services.batch_service import BatchService

router = APIRouter(prefix="/status", tags=["状态流转"])


@router.post(
    "/update",
    response_model=StatusRecordResponse,
    summary="更新批次状态节点（含角色权限校验）",
    description=(
        "按角色限定操作：门禁→到场/退场，材料员→卸货/退场，质检员→验收/待复检/复检完成/退场，"
        "监理→驳回/退场，项目经理→退场。非法角色或非法流转均返回 400 业务提示"
    ),
)
def update_status(
    req: StatusUpdateRequest,
    db: Session = Depends(get_db),
):
    svc = BatchService(db)
    record, err = svc.update_status(req)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return record
