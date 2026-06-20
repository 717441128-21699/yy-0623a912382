import sys
sys.path.insert(0, "d:/trae-bz/TraeProjects/12382")

from app.database import SessionLocal
from app.services.push_service import list_notify_rules, set_rule_enabled, set_notify_roles
from app.enums import NotificationTypeEnum, RoleEnum

db = SessionLocal()

print("=== 当前数据库中的规则 ===")
from app.models import NotificationRule
rules_in_db = db.query(NotificationRule).all()
for r in rules_in_db:
    print(f"  id={r.id}, event={r.event_type}, enabled={r.enabled} (type={type(r.enabled)}), roles_json={r.roles_json}")

print("\n=== list_notify_rules 输出 ===")
result = list_notify_rules(db, "PRJ-A")
for r in result:
    print(f"  {r['event_type']}: enabled={r['enabled']}, is_custom={r['is_custom']}, roles={r['roles']}, rule_id={r['rule_id']}")

print("\n=== 测试 set_rule_enabled (False) ===")
rule = set_rule_enabled(db, "PRJ-A", NotificationTypeEnum.MISSING_DOCS, False)
print(f"  返回: id={rule.id}, enabled={rule.enabled}")

print("\n=== 再查 list_notify_rules ===")
result = list_notify_rules(db, "PRJ-A")
for r in result:
    print(f"  {r['event_type']}: enabled={r['enabled']}, is_custom={r['is_custom']}, roles_count={len(r['roles'])}")

db.close()
