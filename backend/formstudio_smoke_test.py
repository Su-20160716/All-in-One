# -*- coding: utf-8 -*-
"""formstudio 冒烟测试：真实 HTTP 调用，覆盖目录、设计、发布、提交、统计、
导出、分享链接、Webhook、模板、审核与评论的端到端链路。

运行（backend 目录）：venv/Scripts/python.exe formstudio_smoke_test.py
"""
import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient  # noqa: E402

BASE = "/api/formstudio/"
passed, failed = [], []


def check(name, cond, extra=""):
    """记录一条断言结果，失败时打印附加信息。"""
    (passed if cond else failed).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {extra}"))


def body(resp):
    """安全读取 JSON 响应体。"""
    try:
        return resp.json()
    except Exception:  # noqa: BLE001 - 冒烟脚本只关心可读的错误信息
        return {"raw": getattr(resp, "content", b"")[:200]}


def data_of(resp):
    """取统一响应包裹中的 data。"""
    return body(resp).get("data") or {}


def register(client, username, password="test12345"):
    """注册并返回带 Bearer Token 的客户端。"""
    resp = client.post(
        "/api/auth/register/",
        {"username": username, "password": password, "nickname": "表单冒烟"},
        format="json",
    )
    if resp.status_code not in (200, 201):
        raise SystemExit(f"注册失败: {resp.status_code} {body(resp)}")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


SCHEMA = {
    "sections": [{"key": "base", "title": "基本信息", "order": 0}],
    "fields": [
        {"key": "name", "label": "姓名", "type": "text", "required": True,
         "section": "base", "order": 0, "validation": {"min_length": 2, "max_length": 20}},
        {"key": "plan", "label": "套餐", "type": "select", "required": True,
         "section": "base", "order": 1,
         "options": [{"value": "basic", "label": "基础", "score": 1},
                     {"value": "pro", "label": "专业", "score": 5}]},
        {"key": "age", "label": "年龄", "type": "number", "section": "base", "order": 2,
         "validation": {"min": 18, "max": 120, "integer": True}},
        {"key": "email", "label": "邮箱", "type": "email", "section": "base", "order": 3},
        {"key": "agree", "label": "同意回访", "type": "boolean", "section": "base", "order": 4},
        {"key": "reason", "label": "回访原因", "type": "textarea", "section": "base", "order": 5,
         "condition": {"field": "agree", "op": "eq", "value": True}},
    ],
    "logic": [
        {"name": "同意后必填原因", "condition": {"field": "agree", "op": "eq", "value": True},
         "action": "require", "target_key": "reason", "priority": 10},
    ],
    "settings": {"scoring": {"pass_score": 3}},
}

ANSWERS = {"name": "张三", "plan": "pro", "age": 30, "email": "zhangsan@example.com", "agree": False}


def main():
    ts = int(time.time())
    owner = register(APIClient(), f"fs_smoke_{ts}")
    other = register(APIClient(), f"fs_smoke_fill_{ts}")

    print("\n— 一、目录与设计 —")
    cat = other.get(BASE + "catalog/")
    check("目录可访问", cat.status_code == 200, body(cat))
    info = data_of(cat)
    check("接口数量不少于 48", info.get("endpoint_count", 0) >= 48, info.get("endpoint_count"))
    check("字段类型不少于 16", len(info.get("field_types") or []) >= 16)
    check("未登录被拦截", APIClient().get(BASE + "catalog/").status_code in (401, 403))

    created = owner.post(
        BASE + "forms/",
        {"name": f"冒烟表单 {ts}", "form_type": "survey", "allow_multiple": True,
         "allow_anonymous": True},
        format="json",
    )
    check("创建表单", created.status_code == 200, body(created))
    form = data_of(created)
    form_id = form.get("id")

    saved = owner.post(f"{BASE}forms/{form_id}/schema/", {"schema": SCHEMA}, format="json")
    check("保存 schema", saved.status_code == 200, body(saved))
    bad = dict(SCHEMA)
    bad["fields"] = [dict(SCHEMA["fields"][0]), dict(SCHEMA["fields"][0])]
    dup = owner.post(f"{BASE}forms/{form_id}/schema/", {"schema": bad}, format="json")
    check("重复字段键被拒绝", dup.status_code == 400, body(dup))

    schema_detail = owner.get(f"{BASE}forms/{form_id}/schema/")
    check("读取 schema", schema_detail.status_code == 200 and
          len(data_of(schema_detail).get("fields") or []) == 6, body(schema_detail))

    print("\n— 二、发布与提交 —")
    published = owner.post(f"{BASE}forms/{form_id}/publish/", {}, format="json")
    check("发布表单", published.status_code == 200, body(published))
    check("生成版本号 1", data_of(published).get("version_no") == 1)

    missing = other.post(f"{BASE}submissions/public/", {"code": form.get("code"), "answers": {}},
                         format="json")
    check("缺必填被拒绝", missing.status_code == 400 and body(missing).get("errors"), body(missing))

    submitted = other.post(
        BASE + "submissions/public/",
        {"code": form.get("code"), "answers": ANSWERS, "duration_seconds": 42},
        format="json",
    )
    check("公开提交成功", submitted.status_code == 200, body(submitted))
    submission = data_of(submitted).get("submission") or {}
    check("冻结版本号", submission.get("version_no") == 1)
    check("按选项计分", submission.get("score") == 5, submission.get("score"))
    check("记录填报人", (submission.get("submitted_by") or {}).get("id") is not None)

    anonymous = other.post(
        BASE + "submissions/public/",
        {"code": form.get("code"), "answers": dict(ANSWERS, name="匿名"), "anonymous": True},
        format="json",
    )
    check("匿名提交不记填报人",
          anonymous.status_code == 200 and
          data_of(anonymous).get("submission", {}).get("submitted_by") is None,
          body(anonymous))

    mine = other.get(BASE + "submissions/mine/")
    check("我的提交列表", mine.status_code == 200 and data_of(mine).get("count", 0) >= 2,
          body(mine))

    print("\n— 三、统计与导出 —")
    stats = owner.get(f"{BASE}forms/{form_id}/stats/")
    check("统计可读", stats.status_code == 200, body(stats))
    overview = data_of(stats)
    check("提交计数为 2", overview.get("total") == 2, overview.get("total"))
    check("平均分已计算", (overview.get("avg_score") or 0) > 0, overview.get("avg_score"))

    dist = owner.get(f"{BASE}forms/{form_id}/stats/fields/", {"field": "plan"})
    check("字段分布可读", dist.status_code == 200, body(dist))

    trend = owner.get(f"{BASE}forms/{form_id}/stats/trend/", {"days": 7})
    check("趋势可读", trend.status_code == 200 and len(data_of(trend).get("items") or []) == 7,
          body(trend))

    exported = owner.get(f"{BASE}forms/{form_id}/export/")
    export_data = data_of(exported)
    check("CSV 导出", exported.status_code == 200 and
          str(export_data.get("filename", "")).endswith(".csv"), body(exported))
    check("CSV 含表头与数据", "姓名" in str(export_data.get("content", "")) and
          export_data.get("row_count") == 2, export_data.get("row_count"))

    print("\n— 四、分享链接 —")
    link_resp = owner.post(f"{BASE}forms/{form_id}/share-links/",
                           {"label": "冒烟链接", "password": "abcd", "max_uses": 5}, format="json")
    check("创建分享链接", link_resp.status_code == 200, body(link_resp))
    link = data_of(link_resp)
    token = link.get("token")
    check("令牌长度 40", len(token or "") == 40, len(token or ""))

    denied = other.post(BASE + "share-links/verify/", {"token": token, "password": "wrong"},
                        format="json")
    check("错误密码被拒绝", denied.status_code == 400, body(denied))
    verified = other.post(BASE + "share-links/verify/", {"token": token, "password": "abcd"},
                          format="json")
    check("密码核验通过", verified.status_code == 200, body(verified))

    print("\n— 五、Webhook —")
    hook = owner.post(
        BASE + "webhooks/",
        {"url": "https://hooks.example.com/formstudio", "events": ["submission.created"]},
        format="json",
    )
    check("创建 Webhook", hook.status_code == 200, body(hook))
    hook_id = data_of(hook).get("id")
    tested = owner.post(f"{BASE}webhooks/{hook_id}/test/", {}, format="json")
    check("模拟投递成功", tested.status_code == 200 and
          data_of(tested).get("delivery", {}).get("status") == "success", body(tested))
    bad_hook = owner.post(BASE + "webhooks/", {"url": "ftp://invalid"}, format="json")
    check("非法地址被拒绝", bad_hook.status_code == 400, body(bad_hook))

    print("\n— 六、模板、审核与评论 —")
    templates = owner.get(BASE + "templates/")
    check("模板目录可读", templates.status_code == 200 and
          data_of(templates).get("count", 0) >= 6, body(templates))
    template_id = (data_of(templates).get("items") or [{}])[0].get("id")
    instantiated = owner.post(f"{BASE}templates/{template_id}/instantiate/",
                              {"name": f"模板实例 {ts}"}, format="json")
    check("模板实例化", instantiated.status_code == 200, body(instantiated))

    approval = owner.post(
        BASE + "forms/",
        {"name": f"审批表单 {ts}", "form_type": "approval", "allow_multiple": True},
        format="json",
    )
    approval_id = (data_of(approval) or {}).get("id")
    owner.post(f"{BASE}forms/{approval_id}/schema/",
               {"schema": {"fields": [{"key": "title", "label": "事项", "type": "text",
                                       "required": True}]}}, format="json")
    owner.post(f"{BASE}forms/{approval_id}/publish/", {}, format="json")
    approval_sub = other.post(
        BASE + "submissions/public/",
        {"code": (data_of(approval) or {}).get("code"), "answers": {"title": "申请用印"}},
        format="json",
    )
    check("审批提交成功", approval_sub.status_code == 200, body(approval_sub))
    approval_sub_id = (data_of(approval_sub).get("submission") or {}).get("id")
    decided = owner.post(f"{BASE}submissions/{approval_sub_id}/approve/",
                         {"conclusion": "同意"}, format="json")
    check("审批通过", decided.status_code == 200, body(decided))

    commented = other.post(f"{BASE}forms/{form_id}/comments/",
                           {"body": "希望增加一列备注"}, format="json")
    check("提交人可评论", commented.status_code == 200, body(commented))
    comment_id = (data_of(commented) or {}).get("id")
    resolved = owner.post(f"{BASE}comments/{comment_id}/resolve/", {"resolved": True}, format="json")
    check("创建者可解决评论", resolved.status_code == 200, body(resolved))

    print("\n— 七、权限边界 —")
    stolen = other.patch(f"{BASE}forms/{form_id}/", {"name": "越权改名"}, format="json")
    check("非创建者不可改表单", stolen.status_code in (400, 403, 404), body(stolen))
    hidden = other.get(f"{BASE}submissions/{submission.get('id')}/")
    check("他人提交不可越权查看", hidden.status_code == 400, body(hidden))
    deleted = owner.delete(f"{BASE}forms/{form_id}/", {}, format="json")
    check("有关联数据时删除被拒绝", deleted.status_code == 400, body(deleted))

    print(f"\n通过 {len(passed)} 项，失败 {len(failed)} 项")
    if failed:
        print("失败项：")
        for name in failed:
            print("  - " + name)
        raise SystemExit(1)
    print("formstudio 冒烟测试全部通过")


if __name__ == "__main__":
    main()
