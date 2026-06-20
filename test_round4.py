import requests, json, time

BASE = "http://127.0.0.1:8000/api/v1"

def pprint(label, data):
    print("\n===", label, "===")
    if isinstance(data, dict):
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        if len(text) > 2500:
            text = text[:2500] + "..."
        print(text)
    else:
        print(data)

# 种子用户
users = requests.get(f"{BASE}/users", params={"project_id": "PRJ-A"}).json()
materials = [u for u in users if u["role"] == "material_staff"]
quality = [u for u in users if u["role"] == "quality_inspector"]
pm = [u for u in users if u["role"] == "project_manager"]
gate = [u for u in users if u["role"] == "gate_staff"]
superv = [u for u in users if u["role"] == "supervisor"]
mat_id = materials[0]["id"]
qua_id = quality[0]["id"]
pm_id = pm[0]["id"]
gate_id = gate[0]["id"]
sup_id = superv[0]["id"]
print(f"种子用户 OK: material={mat_id} quality={qua_id} pm={pm_id} gate={gate_id} supervisor={sup_id}")

# ============ 1. 通知规则 启用/停用 ============
print("\n===== [1] 通知规则 enabled + toggle =====")

# 先看默认
r = requests.get(f"{BASE}/notifications/rules", params={"project_id": "PRJ-A"})
rules = r.json()
missing_default = [x for x in rules["rules"] if x["event_type"] == "missing_docs"][0]
assert missing_default["enabled"] == True
assert missing_default["is_custom"] == False
print("[INFO] 默认规则 enabled=True，is_custom=False")

# 设置自定义
r = requests.post(f"{BASE}/notifications/rules",
    params={"created_by": pm_id},
    json={
        "project_id": "PRJ-A",
        "event_type": "missing_docs",
        "roles": ["material_staff", "project_manager"]
    })
assert r.status_code == 200
rules2 = r.json()
m2 = [x for x in rules2["rules"] if x["event_type"] == "missing_docs"][0]
assert m2["enabled"] == True
assert m2["is_custom"] == True
assert len(m2["roles"]) == 2
print("[OK] 设置自定义规则成功，enabled=True，roles=2")

# 停用
r = requests.post(f"{BASE}/notifications/rules/toggle",
    params={"operator_id": pm_id},
    json={"project_id": "PRJ-A", "event_type": "missing_docs", "enabled": False})
assert r.status_code == 200
rules3 = r.json()
m3 = [x for x in rules3["rules"] if x["event_type"] == "missing_docs"][0]
assert m3["enabled"] == False
assert m3["is_custom"] == True
assert len(m3["roles"]) == 0
print("[OK] 停用成功，enabled=False，roles=[]")

# 恢复启用
r = requests.post(f"{BASE}/notifications/rules/toggle",
    params={"operator_id": pm_id},
    json={"project_id": "PRJ-A", "event_type": "missing_docs", "enabled": True})
assert r.status_code == 200
m4 = [x for x in r.json()["rules"] if x["event_type"] == "missing_docs"][0]
assert m4["enabled"] == True
assert len(m4["roles"]) == 2
print("[OK] 恢复启用成功，enabled=True，roles=2")

# 非项目经理不能操作
r = requests.post(f"{BASE}/notifications/rules/toggle",
    params={"operator_id": mat_id},
    json={"project_id": "PRJ-A", "event_type": "missing_docs", "enabled": False})
assert r.status_code == 403
print("[OK] 非项目经理操作返回 403")

# ============ 2. 投递记录：duration_ms + 升序 + 最终闭环 ============
print("\n===== [2] 投递记录增强 =====")

# 创建批次
batch1 = requests.post(f"{BASE}/batches/register", json={
    "project_id": "PRJ-A", "registered_by": mat_id,
    "supplier": "南方水泥", "material_category": "水泥", "specification": "P.O 42.5",
    "quantity": 100, "unit": "吨", "contract_no": "HT-2025-009",
    "attachments": []
}).json()
batch_no1 = batch1["batch_no"]
print("批次:", batch_no1)

# 走流程触发通知
for op_id, to_status, extra in [
    (gate_id, "arrived", {}),
    (mat_id, "unloaded", {}),
    (qua_id, "accepted", {"docs_complete": False}),
]:
    r = requests.post(f"{BASE}/status/update", json={
        "batch_no": batch_no1, "to_status": to_status,
        "operator_id": op_id, "remark": f"test-{to_status}", **extra
    })
    assert r.status_code == 200
print("[OK] 状态流转 OK")

# 创建 httpbin 通道
r = requests.post(f"{BASE}/push/channels", json={
    "project_id": "PRJ-A", "name": "test-httpbin",
    "channel_type": "callback", "callback_url": "http://httpbin.org/post",
    "max_retries": 1, "timeout_seconds": 10,
})
chan_id = r.json()["id"]
print("通道 id=", chan_id)

# 拿一条通知手动推
notifs = requests.post(f"{BASE}/notifications/list",
    json={"project_id": "PRJ-A"}, params={"limit": 5}).json()["items"]
nid = notifs[0]["id"]
print(f"通知 {nid} 手动推送...")

r = requests.post(f"{BASE}/push/manual", json={"notification_id": nid, "channel_id": chan_id})
result = r.json()

print(f"  总记录数: {result['total']}")
print(f"  final_closed: {result['final_closed']}")
print(f"  success_attempts: {result['success_attempts']}")
print(f"  failed_attempts: {result['failed_attempts']}")
print(f"  last_attempt_at: {result['last_attempt_at']}")
assert result["final_closed"] == True
assert result["success_attempts"] >= 1

# 检查每条记录都有 duration_ms，且 attempt_no 连续
prev = 0
for item in result["items"]:
    assert item["duration_ms"] is not None and item["duration_ms"] >= 0
    assert item["attempt_no"] == prev + 1
    prev = item["attempt_no"]
print(f"[OK] {prev} 条记录，attempt_no 连续，每条都有 duration_ms")

# 再推一次（已成功，应返回历史且 final_closed=true
r = requests.post(f"{BASE}/push/manual", json={"notification_id": nid, "channel_id": chan_id})
result2 = r.json()
assert result2["final_closed"] == True
print(f"[OK] 已成功再推送返回历史记录，final_closed={result2['final_closed']}")

# 查询投递列表按批次查
r = requests.post(f"{BASE}/push/deliveries",
    json={"project_id": "PRJ-A", "channel_id": chan_id},
    params={"limit": 50})
list_result = r.json()
assert list_result["final_closed"] == True
print(f"[OK] 列表查询也返回 final_closed summary 正确")

# ============ 3. 待办聚合 + 项目概览 + 总数正确 ============
print("\n===== [3] 待办聚合 + 项目概览 =====")

# 材料员
r = requests.get(f"{BASE}/batches/todolist/mine", params={"user_id": mat_id})
mat_todo = r.json()
print(f"材料员: total={mat_todo['total_count']}, batches={len(mat_todo['batches'])}, notifs={len(mat_todo['notifications'])}, groups={len(mat_todo['groups'])}")
assert mat_todo["project_overview"] is None
print("[OK] 材料员无 project_overview")

# 质检员
r = requests.get(f"{BASE}/batches/todolist/mine", params={"user_id": qua_id})
qua_todo = r.json()
print(f"质检员: total={qua_todo['total_count']}, batches={len(qua_todo['batches'])}, notifs={len(qua_todo['notifications'])}")

# 项目经理
r = requests.get(f"{BASE}/batches/todolist/mine", params={"user_id": pm_id})
pm_todo = r.json()
print(f"项目经理: total={pm_todo['total_count']}, batches={len(pm_todo['batches'])}, notifs={len(pm_todo['notifications'])}, exceptions={len(pm_todo['exception_batches'])}")

# 验证项目概览
ov = pm_todo["project_overview"]
assert ov is not None
print(f"  project_overview: total_pending={ov['total_pending_batches']}, exception={ov['exception_count']}, roles={len(ov['role_stats'])}")
assert len(ov["role_stats"]) >= 4
assert ov["latest_status_updated_at"] is not None
print("[OK] 项目经理有 project_overview，含各角色待办数、异常数、最近更新时间")

# 验证总数 = batches + notifications
expected = len(pm_todo["batches"]) + len(pm_todo["notifications"])
assert pm_todo["total_count"] == expected
print(f"[OK] 待办总数正确: {pm_todo['total_count']} = {len(pm_todo['batches'])} 批次 + {len(pm_todo['notifications'])} 通知")

# 验证 groups 结构化
for g in pm_todo["groups"]:
    assert "group_type" in g
    assert "label" in g
    assert "count" in g
print("[OK] groups 是结构化的 TodoGroupItem")

print("\n===== ALL TESTS PASSED =====")
