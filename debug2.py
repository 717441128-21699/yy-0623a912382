import sys
sys.path.insert(0, "d:/trae-bz/TraeProjects/12382")

from app.database import SessionLocal
from app.services.push_service import list_notify_rules, set_rule_enabled, set_notify_roles
from app.enums import NotificationTypeEnum, RoleEnum

db = SessionLocal()

print("=== 初始状态 ===")
for r in list_notify_rules(db, "PRJ-A"):
    print(f"  {r['event_type']}: custom={r['is_custom']}, enabled={r['enabled']}, roles={r['roles']}")

print("\n=== 设置自定义规则 ===")
rule = set_notify_roles(db, "PRJ-A", NotificationTypeEnum.MISSING_DOCS, [RoleEnum.MATERIAL_STAFF, RoleEnum.PROJECT_MANAGER], 3)
print(f"  新规则: id={rule.id}, enabled={rule.enabled}, roles_json={rule.roles_json}")

print("\n=== 设置后 list ===")
for r in list_notify_rules(db, "PRJ-A"):
    if r["event_type"] == "missing_docs":
        print(f"  missing_docs: custom={r['is_custom']}, enabled={r['enabled']}, roles={r['roles']}, rule_id={r['rule_id']}")

print("\n=== 设为禁用 ===")
rule2 = set_rule_enabled(db, "PRJ-A", NotificationTypeEnum.MISSING_DOCS, False)
print(f"  返回规则: id={rule2.id}, enabled={rule2.enabled}")

print("\n=== 禁用后 list ===")
for r in list_notify_rules(db, "PRJ-A"):
    if r["event_type"] == "missing_docs":
        print(f"  missing_docs: custom={r['is_custom']}, enabled={r['enabled']}, roles={r['roles']}, rule_id={r['rule_id']}")

print("\n=== 直接查数据库所有规则 ===")
from app.models import NotificationRule
all_rules = db.query(NotificationRule).order_by(NotificationRule.id).all()
for r in all_rules:
    print(f"  id={r.id}, event={r.event_type}, enabled={r.enabled}, updated_at={r.updated_at}, roles={r.roles_json}")

db.close()
