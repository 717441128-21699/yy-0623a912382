from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, SessionLocal
from app.services.batch_service import UserService
from app.enums import RoleEnum
from app.config import settings as app_settings

from app.routers import batches, status, notifications, users, push


def seed_initial_data():
    db = SessionLocal()
    try:
        svc = UserService(db)
        seed_users = [
            ("mat001", "张三（材料员）", RoleEnum.MATERIAL_STAFF, "13800000001", "PRJ-A"),
            ("qi001", "李四（质检员）", RoleEnum.QUALITY_INSPECTOR, "13800000002", "PRJ-A"),
            ("pm001", "王五（项目经理）", RoleEnum.PROJECT_MANAGER, "13800000003", "PRJ-A"),
            ("sup001", "赵六（监理）", RoleEnum.SUPERVISOR, "13800000004", "PRJ-A"),
            ("gate001", "孙七（门禁）", RoleEnum.GATE_STAFF, "13800000005", "PRJ-A"),
            ("mat002", "周八（材料员）", RoleEnum.MATERIAL_STAFF, "13800000006", "PRJ-B"),
            ("qi002", "吴九（质检员）", RoleEnum.QUALITY_INSPECTOR, "13800000007", "PRJ-B"),
            ("pm002", "郑十（项目经理）", RoleEnum.PROJECT_MANAGER, "13800000008", "PRJ-B"),
        ]
        for username, full_name, role, phone, project_id in seed_users:
            svc.create_user(username, full_name, role, phone, project_id)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_initial_data()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "材料进场验收后端服务，面向集团型施工企业，统一对接：\n"
        "- 项目管理 App（批次登记）\n"
        "- 门禁系统 / 现场端（状态更新）\n"
        "- 监理审批端（复检 / 驳回）\n"
        "核心能力：批次登记、验收状态流转、通知待办推送。"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["系统"])
def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "api_prefix": settings.API_V1_PREFIX,
    }


@app.get("/health", tags=["系统"])
def health_check():
    return {"status": "ok", "reinspection_days": app_settings.REINSPECTION_DAYS}


api_prefix = settings.API_V1_PREFIX
app.include_router(users.router, prefix=api_prefix)
app.include_router(batches.router, prefix=api_prefix)
app.include_router(status.router, prefix=api_prefix)
app.include_router(notifications.router, prefix=api_prefix)
app.include_router(push.router, prefix=api_prefix)
