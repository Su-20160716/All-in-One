# -*- coding: utf-8 -*-
"""knowledgegraph 冒烟脚本（进程内走 DRF 路由栈，不需要先起 8000 端口）。

用途：跑一遍「建模 → 录实体 → 建关系 → 图查询 → 保存查询
→ 抽取 → 快照 → 统计 → 清理」的主链路，用于发布前确认接口可用。

运行方式（必须显式执行，不参与 CI，也不会被单元测试收集）：
    venv/Scripts/python.exe knowledgegraph_smoke_test.py

环境变量：
    KG_USERNAME  登录用户名（与 KG_PASSWORD 一起使用时自动换 access token）
    KG_PASSWORD  登录密码
    KG_TOKEN     也可直接给 JWT access token，跳过登录
    都未提供时自动登录 admin/admin123，失败再回退注册新账号。

退出码：0 = 全链路通过；1 = 任一步失败（打印失败步骤与响应体）。
"""
import json
import sys

from smoke_inproc import init, request_json

API = "/api/knowledgegraph"

CLIENT, TOKEN = init("kg", token_env="KG_TOKEN",
                     username_env="KG_USERNAME", password_env="KG_PASSWORD")

failures = []


def call(method, path, payload=None, auth=True):
    """发一次进程内请求并返回 (status, body)；错误响应也解析响应体。"""
    url = path if path.startswith("/api/") else f"{API}{path}"
    return request_json(CLIENT, method, url, payload=payload, auth=auth)


def step(name, method, path, payload=None, expect=200, auth=True):
    """执行一个步骤，返回 data；失败则记录并返回 None（后续步骤尽量继续）。"""
    status, body = call(method, path, payload, auth=auth)
    ok_flag = status == expect and (body.get("ok") is not False)
    mark = "OK " if ok_flag else "FAIL"
    print(f"[{mark}] {name:<28} {method} {path} -> {status}")
    if not ok_flag:
        failures.append({"step": name, "status": status, "body": body})
        print(f"       {json.dumps(body, ensure_ascii=False)[:400]}")
        return None
    return body.get("data")


def login():
    """认证已由 smoke_inproc.init 完成（KG_TOKEN / 账号密码 / admin 回退）。"""
    print("[OK ] 登录成功")
    return True


def main():
    if not login():
        return 1

    catalog = step("目录与限制", "GET", "/")
    if catalog:
        print(f"       接口数={len(catalog.get('endpoints', []))} "
              f"模型数={catalog.get('model_count')}")

    ontology = step("创建本体", "POST", "/ontologies/create/",
                    {"name": "冒烟图谱", "description": "smoke test"})
    if not ontology:
        return 1
    ontology_id = ontology["id"]

    org = step("创建实体类型-组织", "POST", "/entity-types/create/",
               {"ontology_id": ontology_id, "name": "组织", "code": "org"})
    place = step("创建实体类型-地点", "POST", "/entity-types/create/",
                 {"ontology_id": ontology_id, "name": "地点", "code": "place"})
    belongs = step("创建关系类型-属于", "POST", "/relation-types/create/",
                   {"ontology_id": ontology_id, "name": "属于",
                    "code": "belongs_to"})
    if not (org and place and belongs):
        return 1

    tencent = step("创建实体-腾讯", "POST", "/entities/create/",
                   {"ontology_id": ontology_id, "entity_type_id": org["id"],
                    "name": "腾讯", "description": "互联网公司"})
    shenzhen = step("创建实体-深圳", "POST", "/entities/create/",
                    {"ontology_id": ontology_id, "entity_type_id": place["id"],
                     "name": "深圳", "description": "城市"})
    if not (tencent and shenzhen):
        return 1

    step("创建别名", "POST", "/aliases/create/",
         {"entity_id": tencent["id"], "alias": "Tencent", "lang": "en"})
    step("创建标签", "POST", "/tags/create/",
         {"entity_id": tencent["id"], "tag": "互联网", "weight": 2})
    relation = step("创建关系", "POST", "/relations/create/",
                    {"ontology_id": ontology_id,
                     "relation_type_id": belongs["id"],
                     "source_entity_id": tencent["id"],
                     "target_entity_id": shenzhen["id"],
                     "weight": 2})
    if not relation:
        return 1

    step("实体搜索", "GET", "/entities/search/?q=腾讯")
    step("重复实体建议", "GET", f"/entities/duplicates/?ontology_id={ontology_id}")
    neighbors = step("邻居查询", "GET",
                     f"/graph/neighbors/?entity_id={tencent['id']}&depth=1")
    if neighbors:
        print(f"       邻居节点数={neighbors.get('node_count')}")
    path = step("最短路径", "GET",
                f"/graph/path/?start_id={tencent['id']}"
                f"&end_id={shenzhen['id']}")
    if path:
        print(f"       路径={path.get('path')} found={path.get('found')}")
    step("K 条备选路径", "GET",
         f"/graph/k-paths/?start_id={tencent['id']}"
         f"&end_id={shenzhen['id']}&k=2")
    step("环路检测", "GET", f"/graph/cycles/?ontology_id={ontology_id}")
    step("DSL 预览", "POST", "/graph/dsl/preview/",
         {"dsl": f"neighbors(entity_id={tencent['id']}, depth=1)"})
    step("DSL 执行", "POST", "/graph/dsl/execute/",
         {"dsl": f"path(start={tencent['id']}, end={shenzhen['id']})"})

    query = step("保存查询", "POST", "/queries/create/",
                 {"name": "冒烟邻居", "kind": "neighbors",
                  "params": {"entity_id": tencent["id"], "depth": 1},
                  "ontology_id": ontology_id})
    if query:
        step("执行保存查询", "POST", f"/queries/{query['id']}/run/")
        step("执行历史", "GET", f"/queries/{query['id']}/runs/")

    source = step("创建来源", "POST", "/sources/create/",
                  {"name": "冒烟文本", "type": "document",
                   "config": {"text": "腾讯属于深圳。华为位于深圳。"}})
    if source:
        job = step("创建抽取任务", "POST", "/extraction/jobs/create/",
                   {"source_id": source["id"], "ontology_id": ontology_id})
        if job:
            step("执行抽取", "POST", f"/extraction/jobs/{job['id']}/run/")
            candidates = step("查看候选", "GET",
                              f"/extraction/jobs/{job['id']}/candidates/")
            if candidates:
                print(f"       候选数={candidates.get('count')}")

    snapshot = step("创建快照", "POST", "/snapshots/create/",
                    {"ontology_id": ontology_id, "name": "冒烟基线"})
    step("图谱概览", "GET", "/stats/overview/")
    step("PageRank", "GET", f"/stats/pagerank/?ontology_id={ontology_id}")
    step("k-core", "GET", f"/stats/kcore/?ontology_id={ontology_id}")
    step("图密度", "GET", f"/stats/density/?ontology_id={ontology_id}")

    if snapshot:
        step("删除快照", "POST", f"/snapshots/{snapshot['id']}/delete/")
    step("删除本体（force）", "POST", f"/ontologies/{ontology_id}/delete/",
         {"force": True})

    print("-" * 60)
    if failures:
        print(f"冒烟失败：{len(failures)} 个步骤未通过")
        for row in failures:
            print(f"  - {row['step']} ({row['status']}): "
                  f"{json.dumps(row['body'], ensure_ascii=False)[:300]}")
        return 1
    print("冒烟通过：主链路全部正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
