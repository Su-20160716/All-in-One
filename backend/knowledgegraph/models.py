# -*- coding: utf-8 -*-
"""知识图谱 · 数据模型（18 张表：本体 / 类型 / 实体 / 关系 / 查询 / 抽取 / 合并 / 快照）。

设计约定（与平台其他应用保持一致）：
- 每张表都挂 owner 外键，行级权限统一由 core.scoping 收口，模型层不再自造
  权限字段；「读范围」与「写权限」的区分留在视图层显式调用 scope_queryset /
  can_write，避免把部门可见误当成可改；
- 每张表都带 created_at / updated_at：图谱是审计对象，实体合并、关系迁移都
  必须可回放，缺时间戳就无法解释「这条边是哪次合并产生的」；
- related_name 全部手工命名并统一 kg_ 前缀：一个用户会同时拥有本体、实体、
  关系、快照等十几类对象，默认的 %(class)s_set 在跨应用聚合时极易撞名；
- 结构化的扩展信息（属性 schema、实体属性、抽取规则、统计快照）统一放
  JSONField，避免为每种实体类型加列；但**状态机字段一律 CharField + 显式
  枚举**，保证非法流转（如已合并实体再生效）在服务层能被拦截；
- 置信度 / 权重统一用 FloatField 并限制 0–1，服务层再做一次夹取，
  防止外部批量导入写入 99 这种「看起来像百分数」的脏值；
- 唯一约束尽量下沉到数据库（别名去重、标签去重、路径缓存键），
  并发场景下「先查再写」必然有竞态，只有唯一键才能真正兜住幂等。

模型清单（18）：
1. Ontology          本体（命名空间 + 版本 + 发布状态）
2. OntologyVersion   本体版本（每次发布留痕，供回滚与对比）
3. EntityType        实体类型（颜色 / 图标 / 属性 schema / 继承）
4. RelationType      关系类型（源类型 / 目标类型 / 方向 / 权重）
5. Entity            实体（规范名 / 属性 / 来源 / 置信度 / 生命周期状态）
6. EntityAlias       实体别名（语言 / 来源 / 置信度）
7. Relation          关系边（属性 / 权重 / 置信度 / 软删除状态）
8. GraphQuery        保存的图查询（DSL / 参数）
9. QueryRun          查询执行历史（耗时 / 节点数 / 边数 / 错误）
10. EntityTag        实体标签（带权重，用于加权检索与聚类提示）
11. Source           知识来源（文档 / 笔记 / 上传 / 手工）
12. ExtractionJob    抽取任务（规则 / 计数 / 状态机）
13. ExtractionCandidate 抽取候选（待人工接受 / 拒绝）
14. MergeRequest     合并申请（审批流）
15. MergeLog         合并日志（迁移关系数 / 操作者）
16. GraphSnapshot    图谱快照（节点数 / 边数 / 统计 JSON）
17. PathCache        路径缓存（起终点 + 深度键）
18. GraphAudit       图谱审计（导入 / 合并 / 拆分 / 删除等操作留痕）
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# 枚举常量：视图、服务与前端目录共用，集中定义避免字符串各写各的
# ---------------------------------------------------------------------------

ONTOLOGY_STATUSES = ("draft", "published", "archived")
ONTOLOGY_STATUS_LABELS = {
    "draft": "草稿",
    "published": "已发布",
    "archived": "已归档",
}

ENTITY_STATUSES = ("active", "merged", "archived")
ENTITY_STATUS_LABELS = {
    "active": "生效",
    "merged": "已合并",
    "archived": "已归档",
}

RELATION_STATUSES = ("active", "deleted")
RELATION_STATUS_LABELS = {
    "active": "生效",
    "deleted": "已删除",
}

DIRECTIONS = ("out", "in", "both")
DIRECTION_LABELS = {"out": "出边", "in": "入边", "both": "双向"}

QUERY_KINDS = ("neighbors", "path", "subgraph", "search", "cypher_like")
QUERY_KIND_LABELS = {
    "neighbors": "邻居查询",
    "path": "路径查询",
    "subgraph": "子图查询",
    "search": "实体搜索",
    "cypher_like": "DSL 查询",
}

JOB_STATUSES = ("queued", "running", "done", "failed")
JOB_STATUS_LABELS = {
    "queued": "排队中",
    "running": "执行中",
    "done": "已完成",
    "failed": "失败",
}

CANDIDATE_STATUSES = ("pending", "accepted", "rejected")
CANDIDATE_STATUS_LABELS = {
    "pending": "待处理",
    "accepted": "已接受",
    "rejected": "已拒绝",
}

CANDIDATE_KINDS = ("entity", "relation")
CANDIDATE_KIND_LABELS = {"entity": "实体", "relation": "关系"}

MERGE_STATUSES = ("pending", "approved", "rejected")
MERGE_STATUS_LABELS = {
    "pending": "待审批",
    "approved": "已通过",
    "rejected": "已拒绝",
}

SOURCE_TYPES = ("document", "note", "upload", "manual")
SOURCE_TYPE_LABELS = {
    "document": "文档",
    "note": "笔记",
    "upload": "上传文件",
    "manual": "手工录入",
}

QUERY_RUN_STATUSES = ("success", "failed")

# 遍历与返回规模上限：图算法是 O(V+E) 甚至 O(V*E)，不设上限时一次
# 「查一下某个实体的 3 跳邻居」就可能把内存打满，因此统一在服务层收口。
MAX_TRAVERSAL_DEPTH = 5
MAX_GRAPH_NODES = 500
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20

# 名称规范化时要剔除的常见企业后缀：实体解析的关键是「同义不同写」，
# 这些后缀几乎不携带区分信息，保留它们会让「腾讯」与「腾讯科技有限公司」
# 的相似度被无谓拉低。
NAME_SUFFIX_NOISE = (
    "股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "集团",
    "分公司", "公司", "co.,ltd", "co.ltd", "co ltd", "ltd", "inc", "corp",
    "corporation", "company", "limited",
)

# 全角 → 半角的补充映射：unicodedata.normalize("NFKC") 已处理大部分，
# 但中文语境里常见的「（）」「·」「—」仍会残留，统一在这里收口。
PUNCTUATION_CHARS = "，。、；：！？·•,.;:!?()（）[]【】{}<>《》\"'“”‘’-_/\\|@#￥$%^&*+=~`"


def clamp_confidence(value, default=0.8):
    """把置信度夹取到 [0, 1]；非法输入回落默认值。

    外部批量导入 / 抽取规则可能写入 99、-1 这类值，一旦进入加权计算
    就会让排序完全失真，所以在模型层提供统一夹取函数供服务层复用。
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return float(default)
    if num != num:  # NaN 与任何数比较都是 False，单独拦截
        return float(default)
    return round(min(1.0, max(0.0, num)), 4)


# ---------------------------------------------------------------------------
# 1. 本体
# ---------------------------------------------------------------------------


class Ontology(models.Model):
    """知识本体：一个独立的图谱命名空间。

    命名空间在「同一所有者」范围内唯一：不同用户可以有同名的 ``default``
    本体（各自的知识域），但同一个人重复建同名本体一定是误操作。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_ontologies", verbose_name="所有者")
    name = models.CharField("名称", max_length=120)
    namespace = models.CharField("命名空间", max_length=80, db_index=True)
    description = models.TextField("描述", blank=True, default="")
    version = models.CharField("版本", max_length=20, default="v1")
    status = models.CharField("状态", max_length=20, default="draft", db_index=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "知识本体"
        verbose_name_plural = "知识本体"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "namespace"],
                                    name="kg_ontology_owner_ns_uniq"),
        ]
        indexes = [
            models.Index(fields=["owner", "status"], name="kg_ont_owner_status_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.namespace}@{self.version})"


class OntologyVersion(models.Model):
    """本体版本记录：每次 publish 追加一条，保留当时的规模统计。

    版本号本身存在 Ontology.version，这里额外留一份快照，
    是为了「发布后实体被改动」时还能解释版本发布那一刻的图谱形态。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_ontology_versions", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="versions", verbose_name="本体")
    version = models.CharField("版本号", max_length=20)
    note = models.TextField("发布说明", blank=True, default="")
    stats = models.JSONField("发布时统计", default=dict, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name="kg_ontology_publishes", verbose_name="发布人")
    created_at = models.DateTimeField("发布时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "本体版本"
        verbose_name_plural = "本体版本"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ontology", "version"], name="kg_ontver_ont_ver_idx"),
        ]

    def __str__(self):
        return f"{self.ontology_id}:{self.version}"


# ---------------------------------------------------------------------------
# 2. 类型
# ---------------------------------------------------------------------------


class EntityType(models.Model):
    """实体类型：定义一类实体的展示形态与属性 schema。

    parent 允许类型继承（如「子公司」继承「组织」），服务层在读取属性
    schema 时会沿继承链合并，保证子类型天然拥有父类型字段。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_entity_types", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="entity_types", verbose_name="本体")
    name = models.CharField("类型名称", max_length=80)
    code = models.CharField("类型标识", max_length=80, db_index=True)
    color = models.CharField("颜色", max_length=20, default="#409eff")
    icon = models.CharField("图标", max_length=40, blank=True, default="")
    attr_schema = models.JSONField("属性 schema", default=dict, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="children", verbose_name="继承类型")
    enabled = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "实体类型"
        verbose_name_plural = "实体类型"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["ontology", "code"],
                                    name="kg_entitytype_ont_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["ontology", "enabled"], name="kg_etype_ont_enabled_idx"),
        ]

    def __str__(self):
        return f"{self.name}[{self.code}]"


class RelationType(models.Model):
    """关系类型：约束关系的两端类型、方向与默认权重。

    source_type / target_type 为空表示「不限类型」；服务层在建边时会做校验，
    但不做数据库外键强约束之外的类型转换，避免「先建类型再建边」的顺序死锁。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_relation_types", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="relation_types", verbose_name="本体")
    name = models.CharField("关系名称", max_length=80)
    code = models.CharField("关系标识", max_length=80, db_index=True)
    source_type = models.ForeignKey(EntityType, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name="out_relation_types", verbose_name="源类型")
    target_type = models.ForeignKey(EntityType, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name="in_relation_types", verbose_name="目标类型")
    directed = models.BooleanField("有方向", default=True)
    attr_schema = models.JSONField("属性 schema", default=dict, blank=True)
    weight = models.FloatField("默认权重", default=1.0)
    enabled = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "关系类型"
        verbose_name_plural = "关系类型"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["ontology", "code"],
                                    name="kg_reltype_ont_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["ontology", "enabled"], name="kg_rtype_ont_enabled_idx"),
        ]

    def __str__(self):
        return f"{self.name}[{self.code}]"


# ---------------------------------------------------------------------------
# 3. 实体与关系
# ---------------------------------------------------------------------------


class Source(models.Model):
    """知识来源：抽取任务的输入载体。

    type 只是粗分类（文档 / 笔记 / 上传 / 手工），真正的定位信息放 config
    （文件 id、笔记 id、URL、正文片段），避免为每种来源加外键。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_sources", verbose_name="所有者")
    name = models.CharField("来源名称", max_length=200)
    type = models.CharField("来源类型", max_length=20, default="manual", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    config = models.JSONField("配置", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "知识来源"
        verbose_name_plural = "知识来源"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "type"], name="kg_source_owner_type_idx"),
        ]

    def __str__(self):
        return self.name[:60]


class Entity(models.Model):
    """图谱实体：本体内的一条知识节点。

    canonical_name 是去重与检索的「主键」：展示用 name（保留原始写法），
    比较用 canonical_name（大小写 / 全半角 / 标点 / 后缀都被规范化）。
    合并时源实体不物理删除，而是 status=merged 并记录 merged_into，
    这样历史关系与引用不会变成悬空指针，也方便回放。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_entities", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="entities", verbose_name="本体")
    entity_type = models.ForeignKey(EntityType, on_delete=models.PROTECT,
                                    related_name="entities", verbose_name="实体类型")
    name = models.CharField("名称", max_length=200, db_index=True)
    canonical_name = models.CharField("规范名", max_length=200, db_index=True)
    description = models.TextField("描述", blank=True, default="")
    attrs = models.JSONField("属性", default=dict, blank=True)
    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="entities", verbose_name="来源")
    confidence = models.FloatField("置信度", default=0.8)
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="kg_entities_created", verbose_name="创建人")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "图谱实体"
        verbose_name_plural = "图谱实体"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ontology", "status"], name="kg_entity_ont_status_idx"),
            models.Index(fields=["ontology", "canonical_name"], name="kg_entity_canon_idx"),
            models.Index(fields=["entity_type", "status"], name="kg_entity_type_status_idx"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.name}"


class EntityAlias(models.Model):
    """实体别名：同一实体的其他写法 / 简称 / 外文名。

    (entity, alias) 唯一：同一别名重复录入只会让搜索结果出现多条重复命中，
    没有业务价值，直接由数据库兜底。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_entity_aliases", verbose_name="所有者")
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                               related_name="aliases", verbose_name="实体")
    alias = models.CharField("别名", max_length=200, db_index=True)
    lang = models.CharField("语言", max_length=20, default="zh")
    source = models.CharField("来源", max_length=40, default="manual")
    confidence = models.FloatField("置信度", default=1.0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "实体别名"
        verbose_name_plural = "实体别名"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["entity", "alias"],
                                    name="kg_alias_entity_alias_uniq"),
        ]
        indexes = [
            models.Index(fields=["alias"], name="kg_alias_text_idx"),
        ]

    def __str__(self):
        return f"{self.alias} -> {self.entity_id}"


class Relation(models.Model):
    """关系边：两个实体之间的一条有向边。

    软删除（status=deleted）而不是物理删除：合并 / 拆分需要回放「哪些边被
    迁移过」，物理删除会让 MergeLog 的 moved_relations 失去对账依据。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_relations", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="relations", verbose_name="本体")
    relation_type = models.ForeignKey(RelationType, on_delete=models.PROTECT,
                                      related_name="relations", verbose_name="关系类型")
    source_entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                                      related_name="out_relations", verbose_name="源实体")
    target_entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                                      related_name="in_relations", verbose_name="目标实体")
    attrs = models.JSONField("属性", default=dict, blank=True)
    weight = models.FloatField("权重", default=1.0)
    confidence = models.FloatField("置信度", default=0.8)
    source = models.CharField("来源", max_length=40, default="manual")
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "图谱关系"
        verbose_name_plural = "图谱关系"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ontology", "status"], name="kg_rel_ont_status_idx"),
            models.Index(fields=["source_entity", "status"], name="kg_rel_src_status_idx"),
            models.Index(fields=["target_entity", "status"], name="kg_rel_tgt_status_idx"),
            models.Index(fields=["relation_type"], name="kg_rel_type_idx"),
        ]

    def __str__(self):
        return f"{self.source_entity_id} -{self.relation_type_id}-> {self.target_entity_id}"


# ---------------------------------------------------------------------------
# 4. 查询与执行历史
# ---------------------------------------------------------------------------


class GraphQuery(models.Model):
    """保存的图查询：kind 决定参数语义，dsl 保存原始 DSL 供回放。

    params 与 dsl 同时保留：前端可视化编辑器改的是 params，命令行 / 高级
    用户写的是 dsl；执行时以 dsl 为准（若存在），params 作为兜底。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_queries", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, null=True, blank=True,
                                 on_delete=models.CASCADE,
                                 related_name="queries", verbose_name="本体")
    name = models.CharField("名称", max_length=120)
    kind = models.CharField("查询类型", max_length=20, default="neighbors", db_index=True)
    dsl = models.TextField("DSL", blank=True, default="")
    params = models.JSONField("参数", default=dict, blank=True)
    description = models.TextField("描述", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "保存的图查询"
        verbose_name_plural = "保存的图查询"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "kind"], name="kg_query_owner_kind_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.kind})"


class QueryRun(models.Model):
    """查询执行历史：每次运行落一条，失败也保留（错误信息是排查依据）。

    刻意不存完整结果：结果集最大可能上千节点，存历史表会让库迅速膨胀；
    只存规模与耗时，具体结果由前端缓存或重新执行获取。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_query_runs", verbose_name="执行人")
    query = models.ForeignKey(GraphQuery, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="runs", verbose_name="查询")
    kind = models.CharField("查询类型", max_length=20, default="neighbors")
    params = models.JSONField("参数", default=dict, blank=True)
    elapsed_ms = models.IntegerField("耗时(ms)", default=0)
    node_count = models.IntegerField("节点数", default=0)
    edge_count = models.IntegerField("边数", default=0)
    status = models.CharField("状态", max_length=20, default="success")
    error = models.TextField("错误", blank=True, default="")
    created_at = models.DateTimeField("执行时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "查询执行记录"
        verbose_name_plural = "查询执行记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"], name="kg_run_owner_status_idx"),
        ]

    def __str__(self):
        return f"run#{self.pk} {self.kind} {self.status}"


class EntityTag(models.Model):
    """实体标签：带权重的自由标签，用于加权检索与社区提示。

    (entity, tag) 唯一；weight 允许后续被调大（人工确认）或调小（噪声），
    但同一标签不重复建行，避免统计时把同一标签算多次。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_entity_tags", verbose_name="所有者")
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                               related_name="tags", verbose_name="实体")
    tag = models.CharField("标签", max_length=60, db_index=True)
    weight = models.FloatField("权重", default=1.0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "实体标签"
        verbose_name_plural = "实体标签"
        ordering = ["-weight", "id"]
        constraints = [
            models.UniqueConstraint(fields=["entity", "tag"], name="kg_tag_entity_tag_uniq"),
        ]
        indexes = [
            models.Index(fields=["tag"], name="kg_tag_text_idx"),
        ]

    def __str__(self):
        return f"{self.entity_id}:{self.tag}"


# ---------------------------------------------------------------------------
# 5. 抽取
# ---------------------------------------------------------------------------


class ExtractionJob(models.Model):
    """抽取任务：把某个来源的文本按规则转成候选实体 / 关系。

    规则存 JSON（词典 + 模式），而不是代码引用：抽取规则属于业务配置，
    由使用者调整，不能要求每次改词表都发版。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_extraction_jobs", verbose_name="所有者")
    source = models.ForeignKey(Source, on_delete=models.CASCADE,
                               related_name="extraction_jobs", verbose_name="来源")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="extraction_jobs", verbose_name="本体")
    status = models.CharField("状态", max_length=20, default="queued", db_index=True)
    rules = models.JSONField("抽取规则", default=dict, blank=True)
    text = models.TextField("待抽取文本", blank=True, default="")
    entity_count = models.IntegerField("实体候选数", default=0)
    relation_count = models.IntegerField("关系候选数", default=0)
    error = models.TextField("错误", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "抽取任务"
        verbose_name_plural = "抽取任务"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"], name="kg_job_owner_status_idx"),
        ]

    def __str__(self):
        return f"job#{self.pk} {self.status}"


class ExtractionCandidate(models.Model):
    """抽取候选：待人工确认的实体或关系。

    接受前只是「建议」，不写图谱；接受后才落 Entity / Relation，
    这样规则误抽不会污染生产图谱（图谱的错误边比缺失边更难清理）。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_extraction_candidates", verbose_name="所有者")
    job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE,
                            related_name="candidates", verbose_name="任务")
    kind = models.CharField("候选类型", max_length=20, default="entity", db_index=True)
    name = models.CharField("名称", max_length=200)
    payload = models.JSONField("载荷", default=dict, blank=True)
    confidence = models.FloatField("置信度", default=0.6)
    status = models.CharField("状态", max_length=20, default="pending", db_index=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "抽取候选"
        verbose_name_plural = "抽取候选"
        ordering = ["-confidence", "id"]
        indexes = [
            models.Index(fields=["job", "status"], name="kg_cand_job_status_idx"),
        ]

    def __str__(self):
        return f"cand#{self.pk} {self.kind}:{self.name}"


# ---------------------------------------------------------------------------
# 6. 合并
# ---------------------------------------------------------------------------


class MergeRequest(models.Model):
    """合并申请：源实体并入目标实体前的审批凭据。

    与「直接合并」并存：低风险合并（相似度极高、同类型）可直接调合并接口，
    跨类型 / 关系多的合并走审批，避免误合并把两条业务线搅在一起。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_merge_requests", verbose_name="申请人")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="merge_requests", verbose_name="本体")
    source_entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                                      related_name="merge_requests_as_source", verbose_name="源实体")
    target_entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                                      related_name="merge_requests_as_target", verbose_name="目标实体")
    reason = models.TextField("理由", blank=True, default="")
    status = models.CharField("状态", max_length=20, default="pending", db_index=True)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="kg_merge_approvals", verbose_name="审批人")
    decided_at = models.DateTimeField("审批时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "合并申请"
        verbose_name_plural = "合并申请"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"], name="kg_merge_owner_status_idx"),
        ]

    def __str__(self):
        return f"merge#{self.pk} {self.source_entity_id}->{self.target_entity_id}"


class MergeLog(models.Model):
    """合并日志：一次实际合并的不可变凭据。

    source_entity / target_entity 用 SET_NULL：实体后来被归档甚至清理，
    日志仍要保留「当时合并了谁」的 id 文本（另外冗余在 detail JSON 里）。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_merge_logs", verbose_name="所有者")
    request = models.ForeignKey(MergeRequest, null=True, blank=True,
                                on_delete=models.SET_NULL,
                                related_name="logs", verbose_name="合并申请")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="merge_logs", verbose_name="本体")
    source_entity = models.ForeignKey(Entity, null=True, blank=True,
                                      on_delete=models.SET_NULL,
                                      related_name="merge_logs_as_source", verbose_name="源实体")
    target_entity = models.ForeignKey(Entity, null=True, blank=True,
                                      on_delete=models.SET_NULL,
                                      related_name="merge_logs_as_target", verbose_name="目标实体")
    moved_relations = models.IntegerField("迁移关系数", default=0)
    merged_aliases = models.IntegerField("迁移别名数", default=0)
    detail = models.JSONField("细节", default=dict, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="kg_merge_operations", verbose_name="操作者")
    created_at = models.DateTimeField("合并时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "合并日志"
        verbose_name_plural = "合并日志"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ontology"], name="kg_mergelog_ont_idx"),
        ]

    def __str__(self):
        return f"log#{self.pk} moved={self.moved_relations}"


# ---------------------------------------------------------------------------
# 7. 快照与路径缓存
# ---------------------------------------------------------------------------


class GraphSnapshot(models.Model):
    """图谱快照：某一时刻的规模与结构统计。

    只存统计而不是完整节点副本：图谱规模可能上万，完整快照会把库撑爆；
    「节点数 / 边数 / 度分布 / 类型分布」足够回答「这周图谱长了多少」。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_snapshots", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="snapshots", verbose_name="本体")
    name = models.CharField("快照名称", max_length=120)
    node_count = models.IntegerField("节点数", default=0)
    edge_count = models.IntegerField("边数", default=0)
    stats = models.JSONField("统计", default=dict, blank=True)
    note = models.TextField("备注", blank=True, default="")
    created_at = models.DateTimeField("生成时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "图谱快照"
        verbose_name_plural = "图谱快照"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ontology", "created_at"], name="kg_snap_ont_time_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.node_count}/{self.edge_count})"


class PathCache(models.Model):
    """路径缓存：按「起点 + 终点 + 最大深度」缓存最短路结果。

    图不变时最短路不变；缓存键必须包含深度上限，否则「先查 2 跳失败」
    会把「3 跳可达」的负结果缓存下来，造成幽灵 404。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_path_caches", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, on_delete=models.CASCADE,
                                 related_name="path_caches", verbose_name="本体")
    start_entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                                     related_name="path_caches_as_start", verbose_name="起点")
    end_entity = models.ForeignKey(Entity, on_delete=models.CASCADE,
                                   related_name="path_caches_as_end", verbose_name="终点")
    max_depth = models.IntegerField("最大深度", default=3)
    weighted = models.BooleanField("带权", default=False)
    path = models.JSONField("路径", default=list, blank=True)
    cost = models.FloatField("路径代价", default=0.0)
    generated_at = models.DateTimeField("生成时间", default=timezone.now)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "路径缓存"
        verbose_name_plural = "路径缓存"
        ordering = ["-generated_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "ontology", "start_entity",
                                            "end_entity", "max_depth", "weighted"],
                                    name="kg_pathcache_key_uniq"),
        ]
        indexes = [
            models.Index(fields=["start_entity", "end_entity"], name="kg_path_s_e_idx"),
        ]

    def __str__(self):
        return f"{self.start_entity_id}->{self.end_entity_id} d{self.max_depth}"


# ---------------------------------------------------------------------------
# 8. 审计
# ---------------------------------------------------------------------------


class GraphAudit(models.Model):
    """图谱审计日志：导入 / 合并 / 拆分 / 归档等写操作留痕。

    审计表只追加不更新；actor 用 SET_NULL 保留「账号删除后仍有操作记录」。
    detail 里冗余实体名称等可读信息，避免日后只能看到一堆 id。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="kg_audits", verbose_name="所有者")
    ontology = models.ForeignKey(Ontology, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="audits", verbose_name="本体")
    action = models.CharField("动作", max_length=40, db_index=True)
    target_type = models.CharField("对象类型", max_length=40, blank=True, default="")
    target_id = models.IntegerField("对象ID", null=True, blank=True)
    summary = models.CharField("摘要", max_length=300, blank=True, default="")
    detail = models.JSONField("细节", default=dict, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL,
                              related_name="kg_audit_actions", verbose_name="操作者")
    created_at = models.DateTimeField("时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "图谱审计"
        verbose_name_plural = "图谱审计"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ontology", "action"], name="kg_audit_ont_action_idx"),
            models.Index(fields=["actor", "created_at"], name="kg_audit_actor_time_idx"),
        ]

    def __str__(self):
        return f"{self.action} {self.target_type}#{self.target_id}"
