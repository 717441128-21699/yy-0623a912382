import uuid
from datetime import datetime


def generate_batch_no(project_id: str) -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:8].upper()
    safe_project = (project_id or "PRJ").replace("-", "").replace("_", "")[:6].upper()
    return f"MAT-{safe_project}-{date_str}-{short_uuid}"
