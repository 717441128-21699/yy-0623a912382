from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import StatusUpdateRequest, StatusRecordResponse
from app.services.batch_service import BatchService

router = APIRouter(prefix="/status", tags=["状态流转"])


@router.post(
    "/update",
    response_model=StatusRecordResponse,
    summary="更新批次状态节点",
    description="门禁/现场端更新：已登记→到场→卸货→验收→待复检→复检完成→监理驳回/退场，记录责任人，自动触发通知",
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
