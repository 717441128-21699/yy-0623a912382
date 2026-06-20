import requests, json

BASE = "http://127.0.0.1:8000/api/v1"

def pprint(label, data):
    print("\n===", label, "===")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))

# ========= 准备：查已有种子用户 =========
users = requests.get(f"{BASE}/users", params={"project_id": "PRJ-A"}).json()
pprint("种子用户(PRJ-A)", users)
materials = [u for u in users if u["role"] == "material_staff"]
quality = [u for u in users if u["role"] == "quality_inspector"]
pm = [u for u in users if u["role"] == "project_manager"]
mat_id = materials[0]["id"] if materials else None
qua_id = quality[0]["id"] if quality else None
pm_id = pm[0]["id"] if pm else None
print("材料员:", mat_id, "质检员:", qua_id, "项目经理:", pm_id)

# ========= 1. 创建批次 + 走完流程 =========
batch1 = requests.post(f"{BASE}/batches/register", json={
    "project_id": "PRJ-A", "registered_by": mat_id,
    "supplier": "南方水泥", "material_category": "水泥", "specification": "P.O 42.5",
    "quantity": 100, "unit": "吨", "contract_no": "HT-2025-007",
    "attachments": []
}).json()
batch_no1 = batch1["batch_no"]
print("批次1:", batch_no1)

# 走几步：到场(门禁5)、卸货(材料员1)、验收(质检员3、docs_complete=false触发资料缺失通知)
from datetime import datetime, timedelta
def to_iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
gate_id = [u for u in users if u["role"] == "gate_staff"][0]["id"]

for op_id, to_status, extra in [
    (gate_id, "arrived", {}),
    (mat_id, "unloaded", {}),
    (qua_id, "accepted", {"docs_complete": False, "has_reinspection": True,
     "reinspection_deadline": to_iso(datetime.utcnow() + timedelta(days=7))}),
]:
    r = requests.post(f"{BASE}/status/update", json={
        "batch_no": batch_no1,
        "to_status": to_status, "operator_id": op_id,
        "remark": f"测试{to_status}", **extra
    })
    print(f"  -> {to_status}: {r.status_code} {r.text[:200]}")

# ========= 2. 配置通知规则：资料缺失只推 [material_staff, project_manager] =========
print("\n--- 先看默认规则 ---")
r = requests.get(f"{BASE}/notifications/rules", params={"project_id": "PRJ-A"})
pprint("PRJ-A 默认规则", r.json())

r = requests.post(f"{BASE}/notifications/rules",
    params={"created_by": pm_id},
    json={
        "project_id": "PRJ-A",
        "event_type": "missing_docs",
        "roles": ["material_staff", "project_manager"]  # 去掉 quality_inspector
    })
print("设置自定义规则:", r.status_code, r.text[:300])

# ========= 3. 配置推送通道(坏URL，max_retries=2) =========
r = requests.post(f"{BASE}/push/channels", json={
    "project_id": "PRJ-A", "name": "坏通道-测试重试",
    "channel_type": "callback", "callback_url": "http://127.0.0.1:19999/bad-url",
    "max_retries": 2, "hmac_secret": "test-secret",
    "headers": {"X-Source": "test", "X-Bad": "true"}
})
print("创建通道:", r.status_code, r.text[:200])
chan_id = r.json()["id"]

# 触发一次 资料缺失（手动生成通知？或者上面 docs_complete=false 已经触发。查通知列表：）
r = requests.post(f"{BASE}/notifications/list", json={"project_id": "PRJ-A"},
                  params={"skip": 0, "limit": 20})
notifs = r.json()["items"]
pprint(f"当前共 {r.json()['total']} 条通知", notifs)

# 调触发通道推送（把现有通知推送出去）
# 方式：遍历每条通知，手动push = 会走 auto 流程
for n in notifs:
    r = requests.post(f"{BASE}/push/manual", json={"notification_id": n["id"], "channel_id": chan_id})
    print(f"手动触发推 通知{n['id']}: {r.status_code}")
    resp = r.json()
    pprint(f"  投递记录数={resp['total']}", resp["items"])

# ========= 4. 改通道为可连通URL，再手动补发 =========
r = requests.put(f"{BASE}/push/channels/{chan_id}", json={
    "callback_url": "http://httpbin.org/post",  # 能连通
})
print("改通道URL为httpbin:", r.status_code)

# 手动补发刚才其中一条通知
nid = notifs[0]["id"]
r = requests.post(f"{BASE}/push/manual", json={"notification_id": nid, "channel_id": chan_id})
print(f"再推 通知{nid}: {r.status_code}")
resp2 = r.json()
pprint(f"  投递记录数={resp2['total']}（应新增 trigger=manual 的 success）", resp2["items"])

# ========= 5. 查批次详情时间线 =========
r = requests.get(f"{BASE}/batches/{batch_no1}")
detail = r.json()
pprint(f"批次详情 timeline 长度={len(detail.get('timeline', []))}", detail.get("timeline", [])[:15])

# ========= 6. 待办聚合 =========
r = requests.get(f"{BASE}/batches/todolist/mine", params={"user_id": mat_id})
pprint(f"材料员(user_id={mat_id})待办", r.json())

r = requests.get(f"{BASE}/batches/todolist/mine", params={"user_id": qua_id})
pprint(f"质检员(user_id={qua_id})待办", r.json())

r = requests.get(f"{BASE}/batches/todolist/mine", params={"user_id": pm_id})
pprint(f"项目经理(user_id={pm_id})待办", r.json())

# ========= 7. 查投递记录列表（按通道+批次） =========
r = requests.post(f"{BASE}/push/deliveries/list",
    json={"project_id": "PRJ-A", "channel_id": chan_id},
    params={"skip": 0, "limit": 50})
pprint("按通道查投递（应按时间顺序）", r.json())
