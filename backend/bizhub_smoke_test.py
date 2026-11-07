# -*- coding: utf-8 -*-
"""bizhub 冒烟测试：对全部业务模块逐一跑通完整业务链路。

覆盖：模块目录/详情 → 记录的增删改查 → 收藏/评论/时间线/复制/归档/恢复 →
批量 → 保存视图 → 合并 → 导入（含错误行）→ 订阅 → 越权拒绝（普通用户 vs 管理员）。

运行：venv/Scripts/python.exe bizhub_smoke_test.py
串行执行，结束时不清库（便于复现问题）。
"""
import os
import sys
import time
from datetime import date, timedelta

import django

# Windows 控制台默认 GBK，输出 ✓/✗ 会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# 154 个模块一轮跑下来约 5000 次请求，会撞线上 1000/min 限流；
# 这里仅在测试进程内放宽，避免 429 掩盖真实业务失败（不影响线上配置）。
from django.conf import settings as dj_settings  # noqa: E402
from rest_framework.settings import api_settings  # noqa: E402

dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update({"user": "1000000/min", "anon": "1000000/min"})
api_settings.DEFAULT_THROTTLE_RATES.update(dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])

from rest_framework.test import APIClient  # noqa: E402

from bizhub.modules import FEATURE_TOTAL, GROUP_ORDER, MODULE_INDEX  # noqa: E402

BASE = "/api/biz/"
MODULE_COUNT = len(MODULE_INDEX)
passed, failed = [], []


def check(name, cond, extra=""):
    if cond:
        passed.append(name)
    else:
        failed.append(name)
        print(f"  ✗ {name} {extra}")


def brief(resp, limit=180):
    try:
        body = resp.data
    except Exception:  # noqa: BLE001
        body = ""
    return f"[{resp.status_code}] {str(body)[:limit]}"


def register(client, username, password="test12345"):
    return client.post(
        "/api/auth/register/", {"username": username, "password": password}, format="json"
    )


def auth_client(token):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def ok_data(resp):
    """取出统一响应里的 data（失败返回 {}；data 可能是对象或数组）。"""
    try:
        if resp.data.get("ok"):
            data = resp.data.get("data")
            if isinstance(data, (dict, list)):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def payload_for(mod, seq, ts, title_prefix=""):
    """按模块 schema 生成一份合法入参（含所有自定义字段）。"""
    title = f"{title_prefix}{mod['name']}冒烟{ts}-{seq}"
    payload = {
        "title": title,
        "status": mod["statuses"][0]["key"] if mod["statuses"] else "",
        "category": mod["categories"][0] if mod["categories"] else "",
        "priority": "high",
        "due_date": (date.today() - timedelta(days=2)).isoformat(),
        "tags": ["smoke", "auto"],
        "data": {},
    }
    for f in mod["fields"]:
        t = f["type"]
        if t == "number":
            v = 42
        elif t == "date":
            v = "2026-01-15"
        elif t == "select":
            if not f["options"]:
                continue
            v = f["options"][0]
        elif t == "bool":
            v = True
        elif t == "textarea":
            v = "冒烟测试说明"
        else:
            v = f"值{seq}"
        payload["data"][f["key"]] = v
    return payload


def main():
    ts = int(time.time())
    user_a = f"biz{ts}a"
    user_b = f"biz{ts}b"

    c1 = APIClient()
    r = register(c1, user_a)
    check("注册用户A", r.status_code == 201, brief(r))
    c1 = auth_client(r.data["access"])

    c2 = APIClient()
    r = register(c2, user_b)
    check("注册用户B", r.status_code == 201, brief(r))
    c2 = auth_client(r.data["access"])

    cadmin = APIClient()
    r = cadmin.post("/api/auth/login/", {"username": "admin", "password": "admin123"}, format="json")
    check("管理员登录", r.status_code == 200, brief(r))
    if r.status_code == 200:
        cadmin = auth_client(r.data["access"])

    # ---------- 1. 模块目录 ----------
    r = c1.get(BASE + "modules/")
    catalog = ok_data(r)
    mods = catalog.get("modules") or []
    check("模块目录接口", r.status_code == 200 and catalog.get("module_count") == MODULE_COUNT, brief(r))
    check(f"模块数={MODULE_COUNT}", len(mods) == MODULE_COUNT, str(len(mods)))
    check(f"功能总数={FEATURE_TOTAL}", catalog.get("feature_count") == FEATURE_TOTAL, str(catalog.get("feature_count")))
    check(f"目录分组={len(GROUP_ORDER)}", len(catalog.get("groups") or []) == len(GROUP_ORDER))

    r = c1.get(BASE + "modules/crm-leads/")
    d = ok_data(r)
    check("模块详情(29 项)", r.status_code == 200 and d.get("feature_count") == 29, brief(r))
    r = c1.get(BASE + "modules/crm-opportunities/")
    d = ok_data(r)
    check("模块详情(30 项)", r.status_code == 200 and d.get("feature_count") == 30, brief(r))
    r = c1.get(BASE + "modules/not-a-module/")
    check("未知模块 404", r.status_code == 404)

    # ---------- 2. 概览 / 成员 ----------
    r = c1.get(BASE + "overview/")
    d = ok_data(r)
    check(
        "概览",
        r.status_code == 200 and d.get("module_count") == MODULE_COUNT and "by_group" in d,
        brief(r),
    )
    r = c1.get(BASE + "members/")
    members = ok_data(r)
    r2 = cadmin.get(BASE + "members/")
    check(
        "成员列表",
        r.status_code == 200 and isinstance(members, list) and len(members) >= 1,
        brief(r),
    )
    check("管理员成员列表", r2.status_code == 200 and len(ok_data(r2)) >= 2, brief(r2))

    # ---------- 3. 全部模块全链路 ----------
    keep_id = None
    keep_slug = None
    for seq, mod in enumerate(mods, start=1):
        slug = mod["slug"]
        schema = MODULE_INDEX[slug]
        mod_base = f"{BASE}{slug}/"
        payload = payload_for(schema, seq, ts)
        statuses = [s["key"] for s in schema["statuses"]]

        # create
        r = c1.post(mod_base + "records/", payload, format="json")
        rec = ok_data(r)
        rec_id = rec.get("id")
        check(f"{slug} 新建", r.status_code == 200 and bool(rec_id), brief(r))

        # list + 搜索命中
        r = c1.get(mod_base + "records/", {"q": payload["title"], "page_size": 50})
        d = ok_data(r)
        hit = [x for x in d.get("results", []) if x.get("id") == rec_id]
        check(
            f"{slug} 列表搜索",
            r.status_code == 200 and bool(hit) and d.get("summary", {}).get("total", 0) >= 1,
            brief(r),
        )

        # detail
        r = c1.get(f"{mod_base}records/{rec_id}/")
        check(f"{slug} 详情", r.status_code == 200 and ok_data(r).get("id") == rec_id, brief(r))

        # patch
        r = c1.patch(f"{mod_base}records/{rec_id}/", {"priority": "low", "tags": ["smoke", "patched"]}, format="json")
        d = ok_data(r)
        check(
            f"{slug} 更新",
            r.status_code == 200 and d.get("priority") == "low" and "patched" in d.get("tags", []),
            brief(r),
        )

        # stats / trend / distribution / quality
        r = c1.get(mod_base + "stats/")
        d = ok_data(r)
        check(
            f"{slug} 统计",
            r.status_code == 200 and d.get("total", 0) >= 1 and "by_status" in d,
            brief(r),
        )
        r = c1.get(mod_base + "trend/", {"days": 7})
        d = ok_data(r)
        check(
            f"{slug} 趋势",
            r.status_code == 200 and d.get("days") == 7 and len(d.get("items", [])) == 7,
            brief(r),
        )
        r = c1.get(mod_base + "distribution/", {"field": "status"})
        d = ok_data(r)
        check(
            f"{slug} 分布",
            r.status_code == 200 and len(d.get("items", [])) == len(statuses),
            brief(r),
        )
        r = c1.get(mod_base + "quality/")
        d = ok_data(r)
        check(
            f"{slug} 质量检查",
            r.status_code == 200 and isinstance(d.get("score"), (int, float)) and len(d.get("issues", [])) == 5,
            brief(r),
        )

        # export
        r = c1.get(mod_base + "export/", {"fmt": "csv"})
        check(
            f"{slug} 导出CSV",
            r.status_code == 200
            and r["Content-Type"].startswith("text/csv")
            and r.content.startswith(b"\xef\xbb\xbf"),
            f"[{r.status_code}] {r['Content-Type']}",
        )

        # favorite
        r = c1.post(f"{mod_base}records/{rec_id}/favorite/", {}, format="json")
        d = ok_data(r)
        check(f"{slug} 收藏", r.status_code == 200 and d.get("favorite") is True and d.get("count", 0) >= 1, brief(r))

        # comment
        r = c1.post(f"{mod_base}records/{rec_id}/comments/", {"content": "冒烟评论"}, format="json")
        check(f"{slug} 评论", r.status_code == 200 and ok_data(r).get("id"), brief(r))
        r = c1.get(f"{mod_base}records/{rec_id}/comments/")
        d = ok_data(r)
        check(f"{slug} 评论列表", r.status_code == 200 and d.get("total", 0) >= 1, brief(r))

        # timeline
        r = c1.get(f"{mod_base}records/{rec_id}/timeline/")
        items = ok_data(r).get("items") or []
        kinds = {x.get("kind") for x in items}
        check(
            f"{slug} 时间线",
            r.status_code == 200 and len(items) >= 2 and kinds == {"activity", "comment"},
            brief(r),
        )

        # duplicate
        r = c1.post(f"{mod_base}records/{rec_id}/duplicate/", {}, format="json")
        dup = ok_data(r)
        check(
            f"{slug} 复制",
            r.status_code == 200 and dup.get("id") and "副本" in dup.get("title", ""),
            brief(r),
        )
        dup_id = dup.get("id")

        # archive / unarchive
        r = c1.post(f"{mod_base}records/{rec_id}/archive/", {}, format="json")
        check(f"{slug} 归档", r.status_code == 200 and ok_data(r).get("archived") is True, brief(r))
        r = c1.post(f"{mod_base}records/{rec_id}/unarchive/", {}, format="json")
        check(f"{slug} 取消归档", r.status_code == 200 and ok_data(r).get("archived") is False, brief(r))

        # delete / restore
        r = c1.delete(f"{mod_base}records/{rec_id}/")
        check(f"{slug} 删除", r.status_code == 200 and ok_data(r).get("is_deleted") is True, brief(r))
        r = c1.post(f"{mod_base}records/{rec_id}/restore/", {}, format="json")
        check(f"{slug} 恢复", r.status_code == 200 and ok_data(r).get("is_deleted") is False, brief(r))

        # bulk status
        target_status = statuses[1] if len(statuses) > 1 else statuses[0]
        r = c1.post(mod_base + "bulk/", {"action": "status", "ids": [rec_id], "status": target_status}, format="json")
        d = ok_data(r)
        check(f"{slug} 批量改状态", r.status_code == 200 and d.get("updated") == 1, brief(r))

        # saved view
        view_name = f"视图{ts}"
        r = c1.post(mod_base + "saved-views/", {"name": view_name, "params": {"q": ""}, "shared": True}, format="json")
        vid = ok_data(r).get("id")
        check(f"{slug} 保存视图", r.status_code == 200 and bool(vid), brief(r))
        r = c1.get(mod_base + "saved-views/")
        d = ok_data(r)
        check(
            f"{slug} 读取视图",
            r.status_code == 200 and any(x.get("id") == vid for x in d.get("items", [])),
            brief(r),
        )

        # merge 两条记录
        payload2 = payload_for(schema, seq + 100, ts, title_prefix="合并")
        r = c1.post(mod_base + "records/", payload2, format="json")
        second_id = ok_data(r).get("id")
        r = c1.post(mod_base + "merge/", {"ids": [rec_id, second_id], "primary_id": rec_id}, format="json")
        d = ok_data(r)
        check(
            f"{slug} 合并",
            r.status_code == 200
            and d.get("id") == rec_id
            and second_id in (d.get("data") or {}).get("merged_ids", []),
            brief(r),
        )

        # 顺带清理复制出来的副本，避免后续列表/统计噪声（软删）
        if dup_id:
            c1.delete(f"{mod_base}records/{dup_id}/")

        keep_id, keep_slug = rec_id, slug
        print(f"  ✓ 模块 {slug}（{seq}/{MODULE_COUNT}）")

    # ---------- 4. 导入 ----------
    import_rows = [
        {"title": f"导入A{ts}", "status": "potential", "priority": "low", "tags": "a,b", "level": "A", "phone": "123"},
        {"title": f"导入B{ts}", "status": "following", "category": "直客", "owner": user_a},
        {"title": f"导入C{ts}", "status": "不存在的状态"},
    ]
    r = c1.post(f"{BASE}crm-accounts/import/", {"rows": import_rows}, format="json")
    d = ok_data(r)
    check(
        "导入三行(2 成功 1 失败)",
        r.status_code == 200 and d.get("created") == 2 and len(d.get("errors") or []) == 1,
        brief(r),
    )
    r = c1.post(
        f"{BASE}crm-accounts/import/",
        {"csv": f"title,status,priority,level\nCSV导入{ts},potential,high,B\n"},
        format="json",
    )
    d = ok_data(r)
    check("导入CSV", r.status_code == 200 and d.get("created") == 1, brief(r))

    # ---------- 5. 订阅 ----------
    r = c1.get(f"{BASE}crm-accounts/subscription/")
    d = ok_data(r)
    check(
        "订阅默认值",
        r.status_code == 200 and d.get("enabled") is False and d.get("frequency") == "daily",
        brief(r),
    )
    r = c1.post(f"{BASE}crm-accounts/subscription/", {"enabled": True, "frequency": "weekly"}, format="json")
    d = ok_data(r)
    check(
        "订阅开启",
        r.status_code == 200 and d.get("enabled") is True and d.get("frequency") == "weekly",
        brief(r),
    )
    r = c1.get(f"{BASE}crm-leads/subscription/")
    check("非订阅模块 400", r.status_code == 400, brief(r))

    # ---------- 6. 越权 ----------
    mod_base = f"{BASE}{keep_slug}/"
    r = c2.patch(f"{mod_base}records/{keep_id}/", {"priority": "urgent"}, format="json")
    check("他人记录不可编辑", r.status_code in (403, 404), brief(r))
    r = c2.get(f"{mod_base}records/{keep_id}/")
    check("他人记录不可见", r.status_code == 404, brief(r))
    r = cadmin.patch(f"{mod_base}records/{keep_id}/", {"priority": "urgent"}, format="json")
    check("管理员可编辑他人记录", r.status_code == 200 and ok_data(r).get("priority") == "urgent", brief(r))

    # ---------- 7. 收尾 ----------
    r = c1.get(f"{BASE}{keep_slug}/overdue/")
    d = ok_data(r)
    check("逾期清单", r.status_code == 200 and "count" in d, brief(r))
    r = c1.get(f"{BASE}{keep_slug}/records/", {"deleted": 1})
    d = ok_data(r)
    check("回收站列表", r.status_code == 200 and all(x.get("is_deleted") for x in d.get("results", [])), brief(r))
    r = c1.get(f"{BASE}{keep_slug}/records/", {"favorite": 1})
    d = ok_data(r)
    check("收藏筛选", r.status_code == 200 and all(x.get("favorite") for x in d.get("results", [])), brief(r))

    total = len(passed) + len(failed)
    print(f"\nbizhub 冒烟：通过 {len(passed)} / 失败 {len(failed)}（共 {total} 项）")
    if failed:
        print("失败项：")
        for name in failed:
            print("  -", name)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
