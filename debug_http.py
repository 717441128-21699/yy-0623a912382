import requests, json

BASE = "http://127.0.0.1:8000/api/v1"

# 先看规则
r = requests.get(f"{BASE}/notifications/rules", params={"project_id": "PRJ-A"})
m0 = [x for x in r.json()["rules"] if x["event_type"] == "missing_docs"][0]
print("初始:", m0)

# 设置自定义
r = requests.post(f"{BASE}/notifications/rules",
    params={"created_by": 3},
    json={"project_id": "PRJ-A", "event_type": "missing_docs", "roles": ["material_staff", "project_manager"]})
m = [x for x in r.json()["rules"] if x["event_type"] == "missing_docs"][0]
print("set后:", m)

# toggle 停用
r = requests.post(f"{BASE}/notifications/rules/toggle",
    params={"operator_id": 3},
    json={"project_id": "PRJ-A", "event_type": "missing_docs", "enabled": False})
print(f"toggle status: {r.status_code}")
if r.status_code == 200:
    m3 = [x for x in r.json()["rules"] if x["event_type"] == "missing_docs"][0]
    print("toggle后:", m3)
else:
    print("错误:", r.text)

# 再查一次
r = requests.get(f"{BASE}/notifications/rules", params={"project_id": "PRJ-A"})
m4 = [x for x in r.json()["rules"] if x["event_type"] == "missing_docs"][0]
print("再查:", m4)
