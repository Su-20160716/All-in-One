# -*- coding: utf-8 -*-
"""knowledgegraph 测试：本体 / 类型 / 实体 / 关系 / 图算法 / 查询 / 抽取 / 合并 / 快照 / 统计与权限。

运行：
    venv/Scripts/python.exe manage.py test knowledgegraph -v 1

说明：
- 本应用的 migrations 包为空，测试库不会自动建表，因此每个 TestCase 在
  setUpClass 里按依赖顺序幂等补建本应用的表（只作用于测试库）；
- 仓库根目录的 backend/code 包会遮蔽标准库 code，导致 manage.py test 的
  pdb 导入失败；knowledgegraph/apps.py 在测试进程里给 code 包补了最小
  InteractiveConsole 占位（仅在 test 参数下生效），因此常规命令即可运行；
- 测试全程使用内存 sqlite，不访问网络，也不调用任何外部模型。
"""
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from knowledgegraph import analytics, services
from knowledgegraph.models import (Entity, EntityAlias, EntityTag, EntityType,
                                   ExtractionCandidate, ExtractionJob,
                                   GraphAudit, GraphSnapshot, MergeLog,
                                   MergeRequest, Ontology, Relation,
                                   RelationType, Source)
from knowledgegraph.urls import urlpatterns

User = get_user_model()

BASE = "/api/knowledgegraph/"


def ensure_knowledgegraph_tables():
    """测试库补建 knowledgegraph 表（幂等，只影响测试库）。

    空的 migrations 包会让 Django 认为应用「已迁移但无迁移」，测试库不会
    sync 建表。这里按外键依赖顺序建表：先建无本应用外键的表，再建引用
    它们的表；自引用外键（EntityType.parent）不阻塞建表顺序。
    """
    existing = set(connection.introspection.table_names())
    pending = [model for model in apps.get_app_config("knowledgegraph").get_models()
               if model._meta.db_table not in existing]
    ordered = []
    while pending:
        progressed = False
        for model in list(pending):
            deps = []
            for field in model._meta.get_fields():
                if not getattr(field, "is_relation", False):
                    continue
                # 只统计本表真实持有的外键；反向关联（related_name 描述符）
                # 的 auto_created 为 True，把它们算作依赖会造出假的依赖环。
                if getattr(field, "auto_created", False) or not field.concrete:
                    continue
                related = getattr(field, "related_model", None)
                if related is None:
                    continue
                if related is model:
                    continue
                if related._meta.app_label != "knowledgegraph":
                    continue
                deps.append(related)
            if all(dep._meta.db_table in existing or dep in ordered for dep in deps):
                ordered.append(model)
                pending.remove(model)
                progressed = True
        if not progressed:  # pragma: no cover —— 依赖环兜底
            raise RuntimeError("knowledgegraph 模型依赖存在环，无法补建测试表")
    with connection.schema_editor() as editor:
        for model in ordered:
            editor.create_model(model)


class KGBase(TestCase):
    """公共夹具：两个用户、认证客户端、统一断言助手。"""

    @classmethod
    def setUpClass(cls):
        ensure_knowledgegraph_tables()
        super().setUpClass()

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="pass1234",
                                              nickname="爱丽丝")
        self.bob = User.objects.create_user(username="bob", password="pass1234",
                                            nickname="鲍勃")
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    # ---- 请求 ----
    def as_user(self, user):
        self.client.force_authenticate(user)

    def get(self, path, params=None):
        return self.client.get(f"{BASE}{path}", params or {})

    def post(self, path, payload=None):
        return self.client.post(f"{BASE}{path}", payload or {}, format="json")

    # ---- 断言 ----
    def ok(self, response):
        self.assertEqual(response.status_code, 200,
                         getattr(response, "data", response.content))
        body = response.json()
        self.assertTrue(body.get("ok"), body)
        return body.get("data")

    def bad(self, response, contains=""):
        self.assertEqual(response.status_code, 400,
                         getattr(response, "data", response.content))
        body = response.json()
        self.assertFalse(body.get("ok"))
        if contains:
            self.assertIn(contains, body.get("error", ""))

    # ---- 业务夹具 ----
    def seed(self):
        """一张小图：腾讯(组织) 属于 深圳(地点)；华为(组织) 位于 深圳；
        腾讯 与 华为 合作；深圳 包含 腾讯。"""
        ont = Ontology.objects.create(owner=self.alice, name="企业图谱",
                                      namespace="enterprise", status="published")
        org = EntityType.objects.create(owner=self.alice, ontology=ont,
                                        name="组织", code="org")
        place = EntityType.objects.create(owner=self.alice, ontology=ont,
                                          name="地点", code="place")
        belongs = RelationType.objects.create(owner=self.alice, ontology=ont,
                                              name="属于", code="belongs_to")
        located = RelationType.objects.create(owner=self.alice, ontology=ont,
                                              name="位于", code="located_in",
                                              directed=False)
        self.tencent = Entity.objects.create(
            owner=self.alice, ontology=ont, entity_type=org, name="腾讯",
            canonical_name="腾讯", created_by=self.alice)
        self.huawei = Entity.objects.create(
            owner=self.alice, ontology=ont, entity_type=org, name="华为",
            canonical_name="华为", created_by=self.alice)
        self.shenzhen = Entity.objects.create(
            owner=self.alice, ontology=ont, entity_type=place, name="深圳",
            canonical_name="深圳", created_by=self.alice)
        self.r1 = Relation.objects.create(
            owner=self.alice, ontology=ont, relation_type=belongs,
            source_entity=self.tencent, target_entity=self.shenzhen)
        self.r2 = Relation.objects.create(
            owner=self.alice, ontology=ont, relation_type=located,
            source_entity=self.huawei, target_entity=self.shenzhen)
        self.r3 = Relation.objects.create(
            owner=self.alice, ontology=ont, relation_type=belongs,
            source_entity=self.tencent, target_entity=self.huawei)
        self.ont, self.org, self.place = ont, org, place
        self.belongs, self.located = belongs, located
        return ont


# ---------------------------------------------------------------------------
# 目录 + 本体 + 类型
# ---------------------------------------------------------------------------


class CatalogOntologyTests(KGBase):
    def test_catalog_metadata(self):
        data = self.ok(self.get(""))
        self.assertEqual(data["app"], "knowledgegraph")
        self.assertEqual(len(data["endpoints"]), len(urlpatterns))
        self.assertGreaterEqual(len(data["endpoints"]), 52)
        self.assertEqual(data["limits"]["traversal_depth"], 5)
        self.assertEqual(data["limits"]["graph_nodes"], 500)
        kinds = {row["value"] for row in data["query_kinds"]}
        self.assertEqual(kinds, {"neighbors", "path", "subgraph", "search",
                                 "cypher_like"})
        self.assertIn("neighbors", data["dsl"]["functions"])
        self.assertEqual(data["model_count"], 18)
        self.assertEqual(data["counts"]["entities"], 0)

    def test_ontology_lifecycle(self):
        data = self.ok(self.post("ontologies/create/", {
            "name": "企业知识图谱", "description": "示例"}))
        ontology_id = data["id"]
        self.assertEqual(data["status"], "draft")
        self.assertTrue(data["namespace"])

        listing = self.ok(self.get("ontologies/"))
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["items"][0]["entity_count"], 0)

        found = self.ok(self.get("ontologies/", {"q": "知识图谱"}))
        self.assertEqual(found["count"], 1)
        empty = self.ok(self.get("ontologies/", {"q": "不存在的名字"}))
        self.assertEqual(empty["count"], 0)

        detail = self.ok(self.get(f"ontologies/{ontology_id}/"))
        self.assertEqual(detail["entity_count"], 0)
        self.assertEqual(detail["versions"], [])

        updated = self.ok(self.post(f"ontologies/{ontology_id}/update/", {
            "name": "企业知识图谱 V2", "description": "更新"}))
        self.assertEqual(updated["name"], "企业知识图谱 V2")

        published = self.ok(self.post(f"ontologies/{ontology_id}/publish/",
                                      {"allow_empty": True, "note": "首发"}))
        self.assertEqual(published["version"], "v2")
        versions = self.ok(self.get(f"ontologies/{ontology_id}/versions/"))
        self.assertEqual(versions["count"], 1)
        self.assertEqual(versions["current_version"], "v2")

        archived = self.ok(self.post(f"ontologies/{ontology_id}/archive/"))
        self.assertEqual(archived["status"], "archived")
        self.bad(self.post(f"ontologies/{ontology_id}/update/", {"name": "x"}),
                 "已归档")
        again = self.ok(self.post(f"ontologies/{ontology_id}/archive/"))
        self.assertTrue(again["already"])

    def test_ontology_validation_and_delete(self):
        first = self.ok(self.post("ontologies/create/", {
            "name": "图谱一", "namespace": "kg-one"}))
        self.bad(self.post("ontologies/create/", {
            "name": "图谱二", "namespace": "kg-one"}), "命名空间已存在")
        self.bad(self.post("ontologies/create/", {"name": "  "}))

        etype = EntityType.objects.create(owner=self.alice,
                                          ontology_id=first["id"],
                                          name="组织", code="org")
        Entity.objects.create(owner=self.alice, ontology_id=first["id"],
                              entity_type=etype, name="甲", canonical_name="甲")
        self.bad(self.post(f"ontologies/{first['id']}/delete/"), "force")
        deleted = self.ok(self.post(f"ontologies/{first['id']}/delete/",
                                    {"force": True}))
        self.assertTrue(deleted["deleted"])
        self.assertEqual(Ontology.objects.count(), 0)

    def test_entity_and_relation_types(self):
        ontology = self.ok(self.post("ontologies/create/", {"name": "类型图谱"}))
        ontology_id = ontology["id"]
        org = self.ok(self.post("entity-types/create/", {
            "ontology_id": ontology_id, "name": "组织", "code": "org",
            "color": "#123456"}))
        self.assertEqual(org["code"], "org")
        child = self.ok(self.post("entity-types/create/", {
            "ontology_id": ontology_id, "name": "子公司", "code": "sub_org",
            "parent_id": org["id"]}))
        self.assertEqual(child["parent_id"], org["id"])
        types = self.ok(self.get("entity-types/", {"ontology_id": ontology_id}))
        self.assertEqual(types["count"], 2)
        self.bad(self.post("entity-types/create/", {
            "ontology_id": ontology_id, "name": "重复", "code": "org"}),
            "类型标识已存在")
        self.bad(self.post(f"entity-types/{org['id']}/delete/"), "子类型")

        updated = self.ok(self.post(f"entity-types/{org['id']}/update/", {
            "color": "#abcdef", "icon": "office-building"}))
        self.assertEqual(updated["color"], "#abcdef")

        rtype = self.ok(self.post("relation-types/create/", {
            "ontology_id": ontology_id, "name": "属于", "code": "belongs_to",
            "source_type_id": child["id"]}))
        self.assertEqual(rtype["source_type_id"], child["id"])
        listing = self.ok(self.get("relation-types/",
                                   {"ontology_id": ontology_id}))
        self.assertEqual(listing["count"], 1)
        detail = self.ok(self.get(f"relation-types/{rtype['id']}/"))
        self.assertEqual(detail["relation_count"], 0)
        self.ok(self.post(f"relation-types/{rtype['id']}/update/", {
            "weight": 2.5}))
        self.ok(self.post(f"relation-types/{rtype['id']}/delete/"))
        self.ok(self.post(f"entity-types/{child['id']}/delete/"))
        self.ok(self.post(f"entity-types/{org['id']}/delete/"))


# ---------------------------------------------------------------------------
# 实体 / 别名
# ---------------------------------------------------------------------------


class EntityTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_entity_crud_and_search(self):
        created = self.ok(self.post("entities/create/", {
            "ontology_id": self.ont.id, "entity_type_id": self.org.id,
            "name": "字节跳动", "description": "互联网公司",
            "attrs": {"city": "北京"}, "confidence": 0.9}))
        entity_id = created["id"]
        self.assertEqual(created["canonical_name"], "字节跳动")
        self.assertEqual(created["entity_type"], "组织")
        self.bad(self.post("entities/create/", {
            "ontology_id": self.ont.id, "entity_type_id": self.org.id,
            "name": "字节跳动"}), "实体已存在")

        self.ok(self.post("aliases/create/", {
            "entity_id": entity_id, "alias": "ByteDance", "lang": "en"}))
        self.ok(self.post("tags/create/", {
            "entity_id": entity_id, "tag": "互联网", "weight": 2}))

        detail = self.ok(self.get(f"entities/{entity_id}/"))
        self.assertEqual(len(detail["aliases"]), 1)
        self.assertEqual(len(detail["tags"]), 1)
        self.assertEqual(detail["relation_count"], 0)

        updated = self.ok(self.post(f"entities/{entity_id}/update/", {
            "description": "全球化互联网公司", "confidence": 0.95}))
        self.assertEqual(updated["description"], "全球化互联网公司")

        searched = self.ok(self.get("entities/search/", {"q": "ByteDance"}))
        self.assertEqual(searched["count"], 1)
        self.assertEqual(searched["items"][0]["entity_id"], entity_id)
        searched2 = self.ok(self.get("entities/search/", {"q": "腾讯"}))
        self.assertGreaterEqual(searched2["count"], 1)

        listing = self.ok(self.get("entities/", {"ontology_id": self.ont.id}))
        self.assertEqual(listing["count"], 4)
        self.bad(self.get("entities/", {"page_size": 500}), "page_size")

        archived = self.ok(self.post(f"entities/{entity_id}/delete/"))
        self.assertEqual(archived["status"], "archived")
        again = self.ok(self.post(f"entities/{entity_id}/archive/"))
        self.assertTrue(again["already"])

    def test_bulk_import_and_duplicates(self):
        payload = {"ontology_id": self.ont.id, "rows": [
            {"name": "阿里巴巴", "entity_type_code": "org"},
            {"name": "腾讯", "entity_type_code": "org"},
            {"name": "杭州", "entity_type_code": "place"},
            {"name": "", "entity_type_code": "place"},
            {"name": "缺失类型"},
        ]}
        result = self.ok(self.post("entities/bulk-import/", payload))
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["error_count"], 2)
        self.assertEqual(Entity.objects.filter(name="阿里巴巴").count(), 1)

        Entity.objects.create(owner=self.alice, ontology=self.ont,
                              entity_type=self.org, name="腾讯科技有限公司",
                              canonical_name=services.normalize_name("腾讯科技有限公司"),
                              created_by=self.alice)
        suggestions = self.ok(self.get("entities/duplicates/",
                                       {"ontology_id": self.ont.id}))
        self.assertGreaterEqual(suggestions["count"], 1)
        pair = suggestions["items"][0]
        self.assertGreaterEqual(pair["score"], 0.8)

    def test_merge_migrates_dedupes_and_logs(self):
        # 追加一条 C -> 腾讯 的关系，合并后应迁移到 华为
        extra = Relation.objects.create(
            owner=self.alice, ontology=self.ont, relation_type=self.belongs,
            source_entity=self.shenzhen, target_entity=self.tencent)
        result = self.ok(self.post("entities/merge/", {
            "source_id": self.tencent.id, "target_id": self.huawei.id,
            "reason": "同一主体"}))
        self.assertEqual(result["moved_relations"], 1)  # 深圳 -> 腾讯
        self.assertEqual(result["deduped_relations"], 1)  # 腾讯 -> 深圳 与 华为 -> 深圳
        self.assertEqual(result["dropped_self_loops"], 1)  # 腾讯 -> 华为
        self.tencent.refresh_from_db()
        self.assertEqual(self.tencent.status, "merged")
        self.assertEqual(self.tencent.attrs["merged_into"], self.huawei.id)
        self.assertTrue(MergeLog.objects.filter(source_entity=self.tencent).exists())
        self.assertTrue(GraphAudit.objects.filter(action="entity.merge").exists())
        self.assertEqual(Relation.objects.filter(source_entity=self.shenzhen,
                                                 target_entity=self.huawei,
                                                 status="active").count(), 1)
        self.assertEqual(Relation.objects.filter(source_entity=self.huawei,
                                                 target_entity=self.huawei).count(), 0)
        extra.refresh_from_db()
        self.assertEqual(extra.target_entity_id, self.huawei.id)

        self.bad(self.post("entities/merge/", {
            "source_id": self.huawei.id, "target_id": self.huawei.id}),
            "自身")
        self.bad(self.post("entities/merge/", {
            "source_id": self.tencent.id, "target_id": self.huawei.id}),
            "生效状态")

    def test_split_moves_selected_relations(self):
        new_name = "腾讯云"
        result = self.ok(self.post(f"entities/{self.tencent.id}/split/", {
            "name": new_name, "relation_ids": [self.r3.id],
            "description": "拆分出的云业务"}))
        self.assertEqual(result["moved_relations"], 1)
        new_entity = Entity.objects.get(pk=result["entity_id"])
        self.assertEqual(new_entity.name, new_name)
        self.r3.refresh_from_db()
        self.assertEqual(self.r3.source_entity_id, new_entity.id)
        self.assertTrue(GraphAudit.objects.filter(action="entity.split").exists())
        self.bad(self.post(f"entities/{self.tencent.id}/split/", {
            "name": "空拆分"}), "至少需要选择")

    def test_alias_crud_and_batch(self):
        alias = self.ok(self.post("aliases/create/", {
            "entity_id": self.tencent.id, "alias": "Tencent"}))
        self.bad(self.post("aliases/create/", {
            "entity_id": self.tencent.id, "alias": "Tencent"}), "已存在")
        listing = self.ok(self.get("aliases/", {"entity_id": self.tencent.id}))
        self.assertEqual(listing["count"], 1)
        batch = self.ok(self.post("aliases/batch/", {
            "entity_id": self.tencent.id,
            "aliases": ["TCE", {"alias": "腾讯控股", "lang": "zh"},
                        "TCE"]}))
        self.assertEqual(batch["created"], 2)
        self.assertEqual(batch["skipped"], 1)
        updated = self.ok(self.post(f"aliases/{alias['id']}/update/", {
            "lang": "en", "confidence": 0.9}))
        self.assertEqual(updated["lang"], "en")
        self.ok(self.post(f"aliases/{alias['id']}/delete/"))
        self.assertEqual(EntityAlias.objects.filter(entity=self.tencent).count(), 2)
        self.assertFalse(EntityAlias.objects.filter(pk=alias["id"]).exists())


# ---------------------------------------------------------------------------
# 关系
# ---------------------------------------------------------------------------


class RelationTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.bob_entity = None

    def test_relation_crud(self):
        created = self.ok(self.post("relations/create/", {
            "ontology_id": self.ont.id, "relation_type_id": self.located.id,
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.shenzhen.id, "weight": 2,
            "attrs": {"since": 1998}}))
        relation_id = created["id"]
        self.assertEqual(created["weight"], 2)
        self.bad(self.post("relations/create/", {
            "ontology_id": self.ont.id, "relation_type_id": self.located.id,
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.shenzhen.id}), "已存在")
        # 无向关系类型的反向重复也应判重
        self.bad(self.post("relations/create/", {
            "ontology_id": self.ont.id, "relation_type_id": self.located.id,
            "source_entity_id": self.shenzhen.id,
            "target_entity_id": self.tencent.id}), "已存在")
        self.bad(self.post("relations/create/", {
            "ontology_id": self.ont.id, "relation_type_id": self.located.id,
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.tencent.id}), "不能相同")

        listing = self.ok(self.get("relations/", {"ontology_id": self.ont.id}))
        self.assertEqual(listing["count"], 4)
        filtered = self.ok(self.get("relations/", {
            "entity_id": self.tencent.id, "status": "active"}))
        self.assertGreaterEqual(filtered["count"], 2)

        detail = self.ok(self.get(f"relations/{relation_id}/"))
        self.assertEqual(detail["relation_type"], "位于")
        updated = self.ok(self.post(f"relations/{relation_id}/update/", {
            "weight": 3.5}))
        self.assertEqual(updated["weight"], 3.5)

        deleted = self.ok(self.post(f"relations/{relation_id}/delete/"))
        self.assertEqual(deleted["status"], "deleted")
        again = self.ok(self.post(f"relations/{relation_id}/delete/"))
        self.assertTrue(again["already"])
        self.bad(self.post(f"relations/{relation_id}/update/", {"weight": 1}),
                 "已删除")

    def test_relation_batch_and_type_delete_guard(self):
        new_entity = Entity.objects.create(
            owner=self.alice, ontology=self.ont, entity_type=self.org,
            name="大疆", canonical_name="大疆", created_by=self.alice)
        result = self.ok(self.post("relations/batch/", {
            "ontology_id": self.ont.id, "rows": [
                {"relation_type_id": self.belongs.id,
                 "source_entity_id": new_entity.id,
                 "target_entity_id": self.shenzhen.id},
                {"relation_type_id": self.belongs.id,
                 "source_entity_id": self.tencent.id,
                 "target_entity_id": self.shenzhen.id},
                {"relation_type_id": self.belongs.id,
                 "source_entity_id": new_entity.id,
                 "target_entity_id": self.shenzhen.id},
            ]}))
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 2)
        self.bad(self.post(f"relation-types/{self.belongs.id}/delete/"),
                 "仍有")
        self.ok(self.post("relations/batch/", {
            "ontology_id": self.ont.id, "rows": [
                {"relation_type_code": "missing",
                 "source_entity_id": new_entity.id,
                 "target_entity_id": self.shenzhen.id}]}))

    def test_entity_type_delete_guard_with_relations(self):
        self.bad(self.post(f"entity-types/{self.org.id}/delete/"), "实体")


# ---------------------------------------------------------------------------
# 图查询 / DSL / 保存查询
# ---------------------------------------------------------------------------


class GraphQueryTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_neighbors_path_subgraph(self):
        neighbors = self.ok(self.get("graph/neighbors/", {
            "entity_id": self.tencent.id, "direction": "out", "depth": 1}))
        self.assertEqual(neighbors["node_count"], 2)
        self.assertIn(self.shenzhen.id,
                      {node["id"] for node in neighbors["nodes"]})
        self.assertEqual(neighbors["center"]["name"], "腾讯")

        path = self.ok(self.get("graph/path/", {
            "start_id": self.tencent.id, "end_id": self.shenzhen.id,
            "direction": "out"}))
        self.assertTrue(path["found"])
        self.assertEqual(path["path"], [self.tencent.id, self.shenzhen.id])
        cached = self.ok(self.get("graph/path/", {
            "start_id": self.tencent.id, "end_id": self.shenzhen.id,
            "direction": "out"}))
        self.assertTrue(cached["cached"])

        weighted = self.ok(self.get("graph/path/", {
            "start_id": self.tencent.id, "end_id": self.shenzhen.id,
            "weighted": True}))
        self.assertTrue(weighted["found"])
        self.assertIsNotNone(weighted["cost"])

        isolated = Entity.objects.create(
            owner=self.alice, ontology=self.ont, entity_type=self.org,
            name="孤岛", canonical_name="孤岛", created_by=self.alice)
        missing = self.ok(self.get("graph/path/", {
            "start_id": isolated.id, "end_id": self.shenzhen.id}))
        self.assertEqual(missing["path"], [])
        self.assertFalse(missing["found"])

        sub = self.ok(self.get("graph/subgraph/", {
            "entity_id": self.tencent.id, "depth": 2}))
        self.assertGreaterEqual(sub["node_count"], 3)
        self.bad(self.get("graph/subgraph/", {
            "entity_id": self.tencent.id, "depth": 6}), "深度")

        self.bad(self.get("graph/neighbors/", {
            "entity_id": self.tencent.id, "direction": "sideways"}), "direction")

    def test_dsl_preview_and_execute(self):
        preview = self.ok(self.post("graph/dsl/preview/", {
            "dsl": f"neighbors(entity_id={self.tencent.id}, depth=1, "
                   "direction=out)"}))
        self.assertEqual(preview["kind"], "neighbors")
        self.assertEqual(preview["params"]["depth"], 1)
        self.bad(self.post("graph/dsl/preview/", {"dsl": "walk(x=1)"}), "仅支持")
        self.bad(self.post("graph/dsl/preview/", {"dsl": "path(start=1)"}),
                 "缺少必填参数")
        self.bad(self.post("graph/dsl/preview/", {"dsl": "neighbors(entity_id=1, bad=2)"}),
                 "不支持参数")

        executed = self.ok(self.post("graph/dsl/execute/", {
            "dsl": f"neighbors(entity_id={self.tencent.id}, direction=out)"}))
        self.assertEqual(executed["kind"], "neighbors")
        self.assertEqual(executed["node_count"], 2)
        self.assertTrue(all("name" in node for node in executed["nodes"]))

        path = self.ok(self.post("graph/dsl/execute/", {
            "dsl": f"path(start={self.tencent.id}, end={self.shenzhen.id}, "
                   "direction=out)"}))
        self.assertTrue(path["found"])
        self.assertEqual(path["nodes"][0]["name"], "腾讯")

        searched = self.ok(self.post("graph/dsl/execute/", {
            "dsl": 'search(q="腾讯", limit=5)'}))
        self.assertEqual(searched["count"], 1)

    def test_saved_query_lifecycle_and_history(self):
        created = self.ok(self.post("queries/create/", {
            "name": "腾讯的邻居", "kind": "neighbors",
            "params": {"entity_id": self.tencent.id, "depth": 1},
            "ontology_id": self.ont.id}))
        query_id = created["id"]
        listing = self.ok(self.get("queries/", {"kind": "neighbors"}))
        self.assertEqual(listing["count"], 1)
        detail = self.ok(self.get(f"queries/{query_id}/"))
        self.assertEqual(detail["name"], "腾讯的邻居")

        updated = self.ok(self.post(f"queries/{query_id}/update/", {
            "description": "常用"}))
        self.assertEqual(updated["id"], query_id)

        result = self.ok(self.post(f"queries/{query_id}/run/"))
        self.assertGreaterEqual(result["node_count"], 2)
        runs = self.ok(self.get(f"queries/{query_id}/runs/"))
        self.assertEqual(runs["count"], 1)
        history = self.ok(self.get("queries/history/", {"status": "success"}))
        self.assertEqual(history["count"], 1)

        # 用表达式覆盖出非法 DSL，执行应记录 failed 并返回 400
        self.bad(self.post(f"queries/{query_id}/run/",
                           {"dsl": "path(start=)"}), "语法")
        failed = self.ok(self.get("queries/history/", {"status": "failed"}))
        self.assertEqual(failed["count"], 1)
        self.assertIn("DSL", failed["items"][0]["error"])

        self.ok(self.post(f"queries/{query_id}/delete/"))
        self.assertEqual(self.ok(self.get("queries/"))["count"], 0)

    def test_query_validation(self):
        self.bad(self.post("queries/create/", {
            "name": "坏查询", "kind": "path", "params": {"start": 1}}),
            "缺少必填参数")
        self.bad(self.post("queries/create/", {
            "name": "空 DSL", "kind": "cypher_like"}), "dsl")
        self.bad(self.post("queries/create/", {
            "name": "x", "kind": "unknown"}), "仅支持")
        saved = self.ok(self.post("queries/create/", {
            "name": "DSL 查询", "kind": "cypher_like",
            "dsl": f"neighbors(entity_id={self.tencent.id})"}))
        self.assertEqual(saved["kind"], "cypher_like")

    def test_tags(self):
        tag = self.ok(self.post("tags/create/", {
            "entity_id": self.tencent.id, "tag": "互联网", "weight": 2}))
        self.assertTrue(tag["created"])
        again = self.ok(self.post("tags/create/", {
            "entity_id": self.tencent.id, "tag": "互联网", "weight": 1}))
        self.assertFalse(again["created"])
        self.assertEqual(again["weight"], 3)
        listing = self.ok(self.get("tags/", {"entity_id": self.tencent.id}))
        self.assertEqual(listing["count"], 1)
        updated = self.ok(self.post(f"tags/{tag['id']}/update/", {"weight": 5}))
        self.assertEqual(updated["weight"], 5)
        self.ok(self.post(f"tags/{tag['id']}/delete/"))
        self.assertEqual(EntityTag.objects.count(), 0)


# ---------------------------------------------------------------------------
# 来源 / 抽取 / 合并申请 / 快照
# ---------------------------------------------------------------------------


class ExtractionTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_source_crud(self):
        source = self.ok(self.post("sources/create/", {
            "name": "公司简介", "type": "document",
            "config": {"text": "腾讯属于深圳。华为位于深圳。腾讯的负责人是马化腾。"}}))
        source_id = source["id"]
        listing = self.ok(self.get("sources/", {"type": "document"}))
        self.assertEqual(listing["count"], 1)
        detail = self.ok(self.get(f"sources/{source_id}/"))
        self.assertEqual(detail["job_count"], 0)
        updated = self.ok(self.post(f"sources/{source_id}/update/", {
            "description": "简介文档"}))
        self.assertEqual(updated["description"], "简介文档")
        self.ok(self.post(f"sources/{source_id}/delete/"))

    def test_extraction_job_and_candidates(self):
        source = Source.objects.create(
            owner=self.alice, name="简介", type="document",
            config={"text": "腾讯属于深圳。华为位于深圳。腾讯的负责人是马化腾。"})
        job = self.ok(self.post("extraction/jobs/create/", {
            "source_id": source.id, "ontology_id": self.ont.id,
            "rules": {"dictionary": [{"name": "腾讯", "type": "org"},
                                     {"name": "华为", "type": "org"}]}}))
        job_id = job["id"]
        self.assertEqual(job["status"], "queued")
        listing = self.ok(self.get("extraction/jobs/", {"status": "queued"}))
        self.assertEqual(listing["count"], 1)

        updated = self.ok(self.post(f"extraction/jobs/{job_id}/update/", {
            "rules": {"dictionary": ["腾讯", "深圳"]}}))
        self.assertEqual(updated["status"], "queued")

        ran = self.ok(self.post(f"extraction/jobs/{job_id}/run/"))
        self.assertEqual(ran["status"], "done")
        self.assertGreaterEqual(ran["entity_count"], 2)
        self.assertGreaterEqual(ran["relation_count"], 2)

        detail = self.ok(self.get(f"extraction/jobs/{job_id}/"))
        self.assertGreaterEqual(detail["pending_count"], 2)
        candidates = self.ok(self.get("extraction/candidates/", {
            "job_id": job_id, "status": "pending"}))
        self.assertGreaterEqual(candidates["count"], 3)
        job_candidates = self.ok(self.get(
            f"extraction/jobs/{job_id}/candidates/"))
        self.assertEqual(job_candidates["count"], candidates["count"])

        entity_candidate = next(c for c in candidates["items"]
                                if c["kind"] == "entity")
        accepted = self.ok(self.post(
            f"extraction/candidates/{entity_candidate['id']}/accept/"))
        self.assertEqual(accepted["status"], "accepted")
        self.assertTrue(Entity.objects.filter(
            name=entity_candidate["name"], status="active").exists())
        self.bad(self.post(
            f"extraction/candidates/{entity_candidate['id']}/accept/"), "状态")

        relation_candidate = next(c for c in candidates["items"]
                                  if c["kind"] == "relation"
                                  and c["status"] == "pending")
        accepted_relation = self.ok(self.post(
            f"extraction/candidates/{relation_candidate['id']}/accept/"))
        self.assertEqual(accepted_relation["status"], "accepted")
        self.assertIsNotNone(accepted_relation["relation_id"])
        self.assertTrue(Relation.objects.filter(
            pk=accepted_relation["relation_id"]).exists())

        reject_candidate = next(c for c in candidates["items"]
                                if c["kind"] == "relation"
                                and c["id"] != relation_candidate["id"])
        rejected = self.ok(self.post(
            f"extraction/candidates/{reject_candidate['id']}/reject/",
            {"reason": "证据不足"}))
        self.assertEqual(rejected["status"], "rejected")

        # 重复执行会重建待处理候选（已处理的不动）
        rerun = self.ok(self.post(f"extraction/jobs/{job_id}/run/"))
        self.assertEqual(rerun["status"], "done")
        self.assertEqual(ExtractionCandidate.objects.filter(
            job_id=job_id, status="accepted").count(), 2)

        self.ok(self.post(f"extraction/jobs/{job_id}/delete/"))
        self.assertEqual(ExtractionJob.objects.count(), 0)

    def test_extraction_job_validation(self):
        source = Source.objects.create(owner=self.alice, name="空来源")
        job = self.ok(self.post("extraction/jobs/create/", {
            "source_id": source.id, "ontology_id": self.ont.id}))
        self.bad(self.post(f"extraction/jobs/{job['id']}/run/"), "文本为空")


class MergeRequestTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_merge_request_approve(self):
        request_row = self.ok(self.post("merge-requests/create/", {
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.huawei.id, "reason": "同一主体"}))
        request_id = request_row["id"]
        listing = self.ok(self.get("merge-requests/", {"status": "pending"}))
        self.assertEqual(listing["count"], 1)
        detail = self.ok(self.get(f"merge-requests/{request_id}/"))
        self.assertIn("preview", detail)
        self.assertEqual(detail["preview"]["relation_count"], 2)

        approved = self.ok(self.post(f"merge-requests/{request_id}/approve/"))
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(MergeRequest.objects.get(pk=request_id).status,
                         "approved")
        self.assertTrue(MergeLog.objects.filter(request_id=request_id).exists())
        self.bad(self.post(f"merge-requests/{request_id}/approve/"), "不可审批")

    def test_merge_request_validation_and_reject(self):
        self.bad(self.post("merge-requests/create/", {
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.tencent.id}), "自身")
        request_row = self.ok(self.post("merge-requests/create/", {
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.huawei.id}))
        self.bad(self.post("merge-requests/create/", {
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.huawei.id}), "已存在")
        rejected = self.ok(self.post(
            f"merge-requests/{request_row['id']}/reject/", {"reason": "证据不足"}))
        self.assertEqual(rejected["status"], "rejected")
        self.assertIn("驳回", MergeRequest.objects.get(
            pk=request_row["id"]).reason)


class SnapshotTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_snapshot_create_diff(self):
        first = self.ok(self.post("snapshots/create/", {
            "ontology_id": self.ont.id, "name": "基线"}))
        self.assertEqual(first["node_count"], 3)
        self.assertEqual(first["edge_count"], 3)
        self.assertIn("type_distribution", first["stats"])

        Entity.objects.create(owner=self.alice, ontology=self.ont,
                              entity_type=self.place, name="北京",
                              canonical_name="北京", created_by=self.alice)
        second = self.ok(self.post("snapshots/generate/", {
            "ontology_id": self.ont.id}))
        self.assertEqual(second["node_count"], 4)

        listing = self.ok(self.get("snapshots/", {"ontology_id": self.ont.id}))
        self.assertEqual(listing["count"], 2)
        detail = self.ok(self.get(f"snapshots/{first['id']}/"))
        self.assertEqual(detail["name"], "基线")

        diff = self.ok(self.get("snapshots/diff/", {
            "a": first["id"], "b": second["id"]}))
        self.assertEqual(diff["node_delta"], 1)
        self.assertEqual(diff["deltas"]["edge_count"]["delta"], 0)
        self.bad(self.get("snapshots/diff/", {"a": first["id"], "b": first["id"]}),
                 "不能相同")

        self.ok(self.post(f"snapshots/{first['id']}/delete/"))
        self.assertEqual(GraphSnapshot.objects.count(), 1)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


class StatsTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_overview_and_growth(self):
        overview = self.ok(self.get("stats/overview/"))
        self.assertEqual(overview["entities"], 3)
        self.assertEqual(overview["relations"], 3)
        self.assertEqual(overview["ontologies"], 1)
        self.assertEqual(overview["pending_merges"], 0)

        growth = self.ok(self.get("stats/growth/", {"days": 7}))
        self.assertEqual(len(growth["entities"]["items"]), 7)
        self.assertEqual(growth["entities"]["items"][-1]["created"], 3)
        self.assertEqual(growth["relations"]["items"][-1]["created"], 3)
        self.bad(self.get("stats/growth/", {"days": 0}), "days")

    def test_graph_statistics(self):
        degree = self.ok(self.get("stats/degree/", {"ontology_id": self.ont.id}))
        self.assertEqual(degree["entity_count"], 3)
        self.assertEqual(degree["relation_count"], 3)
        # 三个节点各 2 度，同分排序不稳定，断言度最高的节点集合
        self.assertEqual({row["name"] for row in degree["top"][:3]},
                         {"深圳", "腾讯", "华为"})

        components = self.ok(self.get("stats/components/",
                                      {"ontology_id": self.ont.id}))
        self.assertEqual(components["component_count"], 1)
        self.assertEqual(components["largest_size"], 3)

        communities = self.ok(self.get("stats/communities/",
                                       {"ontology_id": self.ont.id}))
        self.assertGreaterEqual(communities["community_count"], 1)
        self.assertLessEqual(communities["iterations"], 20)

        centrality = self.ok(self.get("stats/centrality/",
                                      {"ontology_id": self.ont.id,
                                       "method": "both"}))
        self.assertIn("degree", centrality)
        self.assertIn("betweenness", centrality)
        self.assertGreaterEqual(centrality["degree"]["count"], 1)
        self.bad(self.get("stats/centrality/", {"method": "pagerank"}),
                 "method")

        types = self.ok(self.get("stats/types/", {"ontology_id": self.ont.id}))
        self.assertEqual(types["entity_count"], 3)
        self.assertEqual(types["entity_types"]["count"], 3)
        self.assertEqual(types["relation_types"]["count"], 3)

    def test_advanced_statistics(self):
        pagerank = self.ok(self.get("stats/pagerank/",
                                    {"ontology_id": self.ont.id}))
        self.assertEqual(pagerank["entity_count"], 3)
        self.assertEqual(pagerank["count"], 3)
        # PageRank 权重总和必须为 1，否则悬挂节点分摊有问题
        self.assertAlmostEqual(sum(row["score"] for row in pagerank["items"]),
                               1.0, places=4)
        closeness = self.ok(self.get("stats/closeness/",
                                     {"ontology_id": self.ont.id}))
        self.assertEqual(closeness["count"], 3)
        self.assertTrue(all(row["reachable"] >= 1 for row in closeness["items"]))

        kcore = self.ok(self.get("stats/kcore/", {"ontology_id": self.ont.id}))
        # 腾讯-华为-深圳构成三角形，核数为 2
        self.assertEqual(kcore["max_core"], 2)
        self.assertEqual(kcore["distribution"]["2"], 3)

        clustering = self.ok(self.get("stats/clustering/",
                                      {"ontology_id": self.ont.id}))
        self.assertGreater(clustering["average"], 0)
        self.assertEqual(clustering["triangles"], 1)

        density = self.ok(self.get("stats/density/",
                                   {"ontology_id": self.ont.id}))
        self.assertEqual(density["entity_count"], 3)
        self.assertEqual(density["relation_count"], 3)
        self.assertEqual(density["self_loops"], 0)
        self.assertGreater(density["density"], 0)

        clusters = self.ok(self.get("stats/similarity-clusters/",
                                    {"ontology_id": self.ont.id}))
        self.assertEqual(clusters["count"], 0)

    def test_cycles_and_k_paths(self):
        # 补一条 华为 -> 腾讯，形成 腾讯 ↔ 华为 的二节点环
        Relation.objects.create(owner=self.alice, ontology=self.ont,
                                relation_type=self.belongs,
                                source_entity=self.huawei,
                                target_entity=self.tencent)
        cycles = self.ok(self.get("graph/cycles/",
                                  {"ontology_id": self.ont.id}))
        self.assertGreaterEqual(cycles["count"], 1)
        self.assertEqual(cycles["items"][0]["length"], 2)
        self.assertEqual(len(cycles["items"][0]["nodes_detail"]), 2)

        paths = self.ok(self.get("graph/k-paths/", {
            "start_id": self.tencent.id, "end_id": self.shenzhen.id, "k": 2}))
        self.assertGreaterEqual(paths["count"], 1)
        first = paths["items"][0]
        self.assertEqual(first["path"][0], self.tencent.id)
        self.assertEqual(first["path"][-1], self.shenzhen.id)
        self.assertEqual(len(first["nodes"]), len(first["path"]))
        self.assertGreater(paths["items"][0]["cost"], 0)


# ---------------------------------------------------------------------------
# 行级权限隔离
# ---------------------------------------------------------------------------


class PermissionTests(KGBase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_read_isolation(self):
        self.as_user(self.bob)
        self.assertEqual(self.ok(self.get("entities/"))["count"], 0)
        self.assertEqual(self.ok(self.get("ontologies/"))["count"], 0)
        self.bad(self.get(f"ontologies/{self.ont.id}/"), "无权")
        self.bad(self.get(f"entities/{self.tencent.id}/"), "无权")
        self.assertEqual(self.ok(self.get("queries/"))["count"], 0)
        catalog = self.ok(self.get(""))
        self.assertEqual(catalog["counts"]["entities"], 0)
        self.assertEqual(catalog["counts"]["ontologies"], 0)

    def test_write_isolation(self):
        self.as_user(self.bob)
        self.bad(self.post("entities/create/", {
            "ontology_id": self.ont.id, "entity_type_id": self.org.id,
            "name": "越权实体"}), "无权")
        self.bad(self.post("aliases/create/", {
            "entity_id": self.tencent.id, "alias": "x"}), "无权")
        self.bad(self.post(f"entities/{self.tencent.id}/update/", {
            "description": "hack"}), "无权")
        self.bad(self.post("entities/merge/", {
            "source_id": self.tencent.id, "target_id": self.huawei.id}), "无权")
        self.bad(self.post("relations/create/", {
            "ontology_id": self.ont.id, "relation_type_id": self.belongs.id,
            "source_entity_id": self.tencent.id,
            "target_entity_id": self.huawei.id}), "无权")
        self.bad(self.post("snapshots/create/", {
            "ontology_id": self.ont.id, "name": "越权快照"}), "无权")
        self.tencent.refresh_from_db()
        self.assertEqual(self.tencent.description, "")


# ---------------------------------------------------------------------------
# 服务层纯函数
# ---------------------------------------------------------------------------


class ServiceUnitTests(TestCase):
    def test_normalize_and_similarity(self):
        # 法人后缀（有限公司）会被剔除，行业词（科技）属于名称主体，保留
        self.assertEqual(services.normalize_name("腾讯科技有限公司"), "腾讯科技")
        self.assertEqual(services.normalize_name("ＡＢＣ  公司"), "abc")
        self.assertEqual(services.normalize_name("  "), "")
        self.assertGreater(services.similarity("腾讯", "腾讯科技"), 0.5)
        self.assertEqual(services.similarity("腾讯", "腾讯有限公司"), 1.0)
        self.assertLess(services.similarity("腾讯", "华为"), 0.4)
        self.assertEqual(services.levenshtein("kitten", "sitting"), 3)
        self.assertGreater(services.jaccard({"a", "b"}, {"b", "c"}), 0)

    def test_graph_algorithms(self):
        relations = [
            {"id": 1, "src": 1, "dst": 2, "type_id": 1, "weight": 1.0,
             "confidence": 1.0},
            {"id": 2, "src": 2, "dst": 3, "type_id": 1, "weight": 4.0,
             "confidence": 0.9},
            {"id": 3, "src": 1, "dst": 3, "type_id": 2, "weight": 0.2,
             "confidence": 0.5},
        ]
        adjacency = services.build_adjacency(relations)
        path = services.shortest_path(1, 3, adjacency, direction="out")
        self.assertEqual(path, [1, 3])
        weighted, cost = services.shortest_path_weighted(
            1, 3, adjacency, direction="out")
        self.assertEqual(weighted, [1, 2, 3])
        self.assertGreater(cost, 1)
        self.assertEqual(services.shortest_path(3, 1, adjacency,
                                                direction="out"), [])
        filtered = services.shortest_path(1, 3, adjacency, direction="out",
                                          type_ids=[1])
        self.assertEqual(filtered, [1, 2, 3])
        sub = services.subgraph(1, adjacency, depth=2, direction="both")
        self.assertEqual(sub["node_count"], 3)
        with self.assertRaises(ValueError):
            services.subgraph(1, adjacency, depth=6, direction="both")

    def test_dsl_and_extraction(self):
        parsed = services.parse_dsl("neighbors(entity_id=1, depth=2, "
                                    "types=[1,2], direction=out)")
        self.assertEqual(parsed["kind"], "neighbors")
        self.assertEqual(parsed["params"]["types"], [1, 2])
        with self.assertRaises(ValueError):
            services.parse_dsl("path(start=1)")
        with self.assertRaises(ValueError):
            services.parse_dsl("nope()")
        normalized = services.validate_dsl_params("search", {"q": " 腾讯 "})
        self.assertEqual(normalized["q"], "腾讯")

        text = "腾讯属于深圳。华为位于深圳。腾讯的负责人是马化腾。"
        candidates = services.extract_candidates(
            text, dictionary=[{"name": "腾讯", "type": "org"}])
        kinds = {item["kind"] for item in candidates}
        self.assertEqual(kinds, {"entity", "relation"})
        relation_codes = {item["payload"].get("relation_code")
                          for item in candidates if item["kind"] == "relation"}
        self.assertIn("belongs_to", relation_codes)
        self.assertIn("located_in", relation_codes)
        self.assertIn("owner_of", relation_codes)
        summary = services.summarize_candidates(candidates)
        self.assertEqual(summary["total"], len(candidates))

    def test_statistics_and_diff(self):
        entities = [{"id": 1, "name": "A", "entity_type_id": 1},
                    {"id": 2, "name": "B", "entity_type_id": 1},
                    {"id": 3, "name": "C", "entity_type_id": 2},
                    {"id": 4, "name": "D", "entity_type_id": 2}]
        relations = [
            {"id": 1, "src": 1, "dst": 2, "type_id": 1, "weight": 1.0,
             "confidence": 1.0},
            {"id": 2, "src": 3, "dst": 4, "type_id": 1, "weight": 1.0,
             "confidence": 1.0},
        ]
        degree = services.degree_distribution(entities, relations)
        self.assertEqual(degree["entity_count"], 4)
        self.assertEqual(degree["avg_degree"], 1.0)
        components = services.connected_components(entities, relations)
        self.assertEqual(components["component_count"], 2)
        communities = services.label_propagation(entities, relations)
        self.assertEqual(communities["community_count"], 2)
        stats = services.snapshot_stats(entities, relations, {1: "组织", 2: "地点"})
        self.assertEqual(stats["node_count"], 4)
        self.assertEqual(stats["type_distribution"]["1"], 2)
        diff = services.diff_stats(stats, {**stats, "node_count": 6})
        self.assertEqual(diff["node_delta"], 2)
        trend = services.growth_trend([], days=3)
        self.assertEqual(len(trend["items"]), 3)

    def test_analytics_algorithms(self):
        entities = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"},
                    {"id": 3, "name": "C"}]
        relations = [
            {"id": 1, "src": 1, "dst": 2, "type_id": 1, "weight": 1.0,
             "confidence": 1.0},
            {"id": 2, "src": 2, "dst": 3, "type_id": 1, "weight": 1.0,
             "confidence": 1.0},
            {"id": 3, "src": 1, "dst": 3, "type_id": 1, "weight": 1.0,
             "confidence": 1.0},
            {"id": 4, "src": 3, "dst": 1, "type_id": 1, "weight": 1.0,
             "confidence": 1.0},
        ]
        ranks = analytics.pagerank(entities, relations)
        self.assertAlmostEqual(sum(row["score"] for row in ranks["items"]),
                               1.0, places=4)
        cores = analytics.k_core(entities, relations)
        self.assertEqual(cores["max_core"], 2)
        clustering = analytics.clustering_coefficient(entities, relations)
        self.assertEqual(clustering["triangles"], 1)
        self.assertGreater(clustering["average"], 0)
        closeness = analytics.closeness_centrality(entities, relations)
        self.assertEqual(closeness["count"], 3)
        density = analytics.graph_density(entities, relations)
        self.assertEqual(density["density"], round(4 / 6, 6))
        cycles = analytics.find_cycles(entities, relations, max_cycles=5,
                                       max_length=5)
        self.assertGreaterEqual(cycles["count"], 1)
        self.assertIn(3, [row["length"] for row in cycles["items"]])
        adjacency = services.build_adjacency(relations)
        paths = analytics.k_shortest_paths(adjacency, 1, 3, k=2,
                                           weighted=False)
        self.assertGreaterEqual(paths["count"], 1)
        self.assertEqual(paths["items"][0]["path"], [1, 3])
        clusters = analytics.similarity_clusters(
            [{"id": 1, "name": "腾讯", "canonical_name": "腾讯"},
             {"id": 2, "name": "腾讯科技", "canonical_name": "腾讯科技"},
             {"id": 3, "name": "华为", "canonical_name": "华为"}],
            threshold=0.8)
        self.assertEqual(clusters["count"], 1)
        self.assertEqual(clusters["items"][0]["entity_ids"], [1, 2])
