import sys
sys.path.insert(0, "d:/trae-bz/TraeProjects/12382")

from app.database import SessionLocal
from app.models import NotificationRule

db = SessionLocal()

all_rules = db.query(NotificationRule).order_by(NotificationRule.id).all()
for r in all_rules:
    print(f"id={r.id}, event={r.event_type.value}, enabled={r.enabled}, enabled_type={type(r.enabled)}, roles_json={r.roles_json}, updated_at={r.updated_at}")

db.close()
