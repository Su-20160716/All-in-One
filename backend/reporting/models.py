# -*- coding: utf-8 -*-
"""报表与仪表盘 · 数据模型（reporting）。

设计要点
--------
1. **配置与结果分离**：数据集 / 报表 / 组件只存「怎么算」（配置 JSON），
   算出来的东西落到 ReportRun（执行流水，用于统计与排障）与
   ReportSnapshot（结果缓存，带 TTL），避免把大 JSON 反复写回配置表。
2. **owner 收口行级权限**：所有模型都有 owner 外键，读走 core.scoping
   的 scope_queryset（同数据范围只读可见），写走 can_write（仅本人）。
   related_name 全部带 ``rep_`` 前缀 + 语义名，保证全工程唯一。
3. **数据集只引用模型白名单里的模型标签**（``app_label.ModelName``），
   绝不存 SQL 片段或 Python import 路径 —— 执行时由
   ``reporting.whitelist`` 用 apps.get_model 解析，杜绝任意代码/任意 SQL。
4. **http / file 数据源只做配置校验与模拟探测**：项目运行环境不允许联网，
   真实探活交给外部任务，这里只保证「配置结构合法 + 状态可流转」。
5. 组件类型（table/bar/line/pie/kpi/pivot/heatmap/text）只影响渲染与
   后处理，取数统一走数据集编译器，前端拿到的都是 columns/rows/meta。
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# 枚举（取值集中在这里，views / services 直接从模型导入，避免各处硬编码漂移）
# ---------------------------------------------------------------------------

SOURCE_KINDS = [
    ("orm", "ORM 模型"),
    ("http", "HTTP 接口"),
    ("file", "文件导入"),
]

SOURCE_STATUS = [
    ("active", "可用"),
    ("inactive", "已停用"),
    ("error", "异常"),
]

FIELD_TYPES = [
    ("string", "文本"),
    ("number", "数值"),
    ("integer", "整数"),
    ("decimal", "金额"),
    ("datetime", "时间"),
    ("date", "日期"),
    ("bool", "布尔"),
    ("json", "JSON"),
]

AGGREGATES = [
    ("none", "不聚合"),
    ("count", "计数"),
    ("sum", "求和"),
    ("avg", "平均值"),
    ("min", "最小值"),
    ("max", "最大值"),
    ("count_distinct", "去重计数"),
    ("median", "中位数"),
]

BUCKETS = [
    ("", "不分组"),
    ("hour", "小时"),
    ("day", "日"),
    ("week", "周"),
    ("month", "月"),
    ("quarter", "季度"),
    ("year", "年"),
]

JOIN_TYPES = [
    ("left", "左连接"),
    ("inner", "内连接"),
]

PARAM_TYPES = [
    ("string", "文本"),
    ("number", "数值"),
    ("date", "日期"),
    ("bool", "布尔"),
]

REPORT_STATUS = [
    ("draft", "草稿"),
    ("published", "已发布"),
    ("archived", "已归档"),
]

WIDGET_TYPES = [
    ("table", "表格"),
    ("bar", "柱状图"),
    ("line", "折线图"),
    ("pie", "饼图"),
    ("kpi", "指标卡"),
    ("pivot", "透视表"),
    ("heatmap", "热力图"),
    ("text", "文本"),
]

RUN_TRIGGERS = [
    ("manual", "手动执行"),
    ("schedule", "计划任务"),
    ("api", "接口调用"),
    ("cache", "缓存命中"),
    ("share", "分享访问"),
]

RUN_STATUS = [
    ("running", "执行中"),
    ("success", "成功"),
    ("failed", "失败"),
]

EXPORT_FORMATS = [
    ("csv", "CSV"),
    ("json", "JSON"),
]

JOB_STATUS = [
    ("queued", "排队中"),
    ("done", "已完成"),
    ("failed", "失败"),
]

SUB_CHANNELS = [
    ("email", "邮件"),
    ("im", "站内信"),
    ("webhook", "Webhook"),
]

SUB_FREQUENCIES = [
    ("daily", "每天"),
    ("weekly", "每周"),
    ("monthly", "每月"),
    ("on_publish", "发布时"),
]

DASHBOARD_STATUS = [
    ("active", "启用"),
    ("archived", "已归档"),
]


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------


class DataSource(models.Model):
    """数据源：orm（白名单模型）/ http（接口配置）/ file（文件配置）。

    http 与 file 的 ``config`` 只在 service 层做结构校验 + 模拟探测，
    不会发起网络请求也不会读磁盘 —— 演示环境不允许外联。
    """

    name = models.CharField("名称", max_length=120)
    kind = models.CharField("类型", max_length=16, choices=SOURCE_KINDS, default="orm")
    description = models.CharField("描述", max_length=255, blank=True, default="")
    config = models.JSONField("配置", default=dict, blank=True)
    status = models.CharField("状态", max_length=16, choices=SOURCE_STATUS, default="active", db_index=True)
    last_ok_at = models.DateTimeField("最近连通时间", null=True, blank=True)
    last_checked_at = models.DateTimeField("最近探测时间", null=True, blank=True)
    last_message = models.CharField("最近探测信息", max_length=255, blank=True, default="")
    check_count = models.IntegerField("探测次数", default=0)
    ok_count = models.IntegerField("连通次数", default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_sources", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "数据源"
        verbose_name_plural = "数据源"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status"], name="rep_src_owner_status_idx"),
            models.Index(fields=["kind", "status"], name="rep_src_kind_status_idx"),
        ]

    def __str__(self):
        return f"{self.name}({self.kind})"

    def summarize(self):
        """给列表/详情用的连通性摘要（成功率按探测次数算）。"""
        rate = round((self.ok_count / self.check_count) * 100, 1) if self.check_count else None
        return {
            "check_count": self.check_count,
            "ok_count": self.ok_count,
            "success_rate_pct": rate,
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
        }


# ---------------------------------------------------------------------------
# 数据集（主模型 + 过滤 + 字段 + 关联 + 参数）
# ---------------------------------------------------------------------------


class Dataset(models.Model):
    """数据集：一份可执行的取数配置。

    ``primary_model`` 必须是模型白名单里的 ``app_label.ModelName``；
    ``filter`` 是结构化 JSON（见 services.compiler.compile_filter），
    由编译器翻译成 ORM Q 对象，不接受任何 SQL 字符串。
    """

    name = models.CharField("名称", max_length=120)
    description = models.TextField("描述", blank=True, default="")
    primary_model = models.CharField("主模型", max_length=120, db_index=True)
    source = models.ForeignKey(
        DataSource, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rep_datasets", verbose_name="数据源",
    )
    filter = models.JSONField("过滤条件", default=dict, blank=True)
    distinct_fields = models.JSONField("去重字段", default=list, blank=True)
    default_limit = models.IntegerField("默认行数", default=200)
    cache_ttl = models.IntegerField("缓存秒数", default=300)
    status = models.CharField("状态", max_length=16, default="active", db_index=True)
    last_preview_at = models.DateTimeField("最近预览时间", null=True, blank=True)
    preview_count = models.IntegerField("预览次数", default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_datasets", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "数据集"
        verbose_name_plural = "数据集"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status"], name="rep_ds_owner_status_idx"),
            models.Index(fields=["primary_model", "status"], name="rep_ds_model_status_idx"),
        ]

    def __str__(self):
        return f"{self.name} → {self.primary_model}"

    def touch_preview(self):
        """预览计数 + 时间戳：用于「冷数据集」治理视图（长期没人用的可归档）。"""
        Dataset.objects.filter(pk=self.pk).update(
            last_preview_at=timezone.now(), preview_count=models.F("preview_count") + 1,
        )


class DatasetField(models.Model):
    """数据集字段：维度（is_group / aggregate=none）或指标（aggregate≠none）。"""

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="rep_dataset_fields", verbose_name="数据集",
    )
    path = models.CharField("字段路径", max_length=160)
    alias = models.CharField("别名", max_length=60, blank=True, default="")
    ftype = models.CharField("类型", max_length=16, choices=FIELD_TYPES, default="string")
    aggregate = models.CharField("聚合函数", max_length=20, choices=AGGREGATES, default="none")
    is_group = models.BooleanField("参与分组", default=False)
    bucket = models.CharField("时间分桶", max_length=10, choices=BUCKETS, blank=True, default="")
    order = models.IntegerField("排序", default=0)
    fmt = models.CharField("格式化", max_length=24, blank=True, default="")
    visible = models.BooleanField("可见", default=True)

    class Meta:
        verbose_name = "数据集字段"
        verbose_name_plural = "数据集字段"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["dataset", "order"], name="rep_dsf_ds_order_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "alias"], condition=~models.Q(alias=""),
                name="rep_dsf_alias_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.dataset_id}:{self.alias or self.path}"

    @property
    def key(self):
        """输出列名：别名优先，其次路径（把点换成下划线，保证 JSON 键可读）。"""
        return self.alias or self.path.replace(".", "_")


class DatasetJoin(models.Model):
    """数据集关联：从主模型沿 ``via`` 关系走到目标模型。

    ``via`` 是关系字段名（支持 ``a__b`` 两跳），目标模型必须与
    ``target_model`` 一致，否则视为配置错误 —— 不允许凭标签瞎连。
    """

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="rep_dataset_joins", verbose_name="数据集",
    )
    target_model = models.CharField("关联模型", max_length=120)
    via = models.CharField("关系路径", max_length=80)
    left_field = models.CharField("本表字段", max_length=80, blank=True, default="")
    right_field = models.CharField("关联表字段", max_length=80, blank=True, default="")
    join_type = models.CharField("连接方式", max_length=10, choices=JOIN_TYPES, default="left")
    order = models.IntegerField("排序", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "数据集关联"
        verbose_name_plural = "数据集关联"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "via"], name="rep_dsj_via_uniq"),
        ]

    def __str__(self):
        return f"{self.dataset_id}:{self.via}→{self.target_model}"


class DatasetParam(models.Model):
    """数据集参数：报表执行时按名字绑定，过滤器里用 ``$param`` 占位。"""

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="rep_dataset_params", verbose_name="数据集",
    )
    name = models.CharField("参数名", max_length=60)
    ptype = models.CharField("类型", max_length=10, choices=PARAM_TYPES, default="string")
    default = models.JSONField("默认值", null=True, blank=True)
    required = models.BooleanField("必填", default=False)
    description = models.CharField("说明", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "数据集参数"
        verbose_name_plural = "数据集参数"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "name"], name="rep_dsp_name_uniq"),
        ]

    def __str__(self):
        return f"{self.dataset_id}:${self.name}"


# ---------------------------------------------------------------------------
# 报表定义 / 页面 / 组件 / 过滤器
# ---------------------------------------------------------------------------


class ReportDefinition(models.Model):
    """报表：页面 → 组件 的树形配置；执行结果只进 Run/Snapshot。"""

    code = models.CharField("编码", max_length=80)
    name = models.CharField("名称", max_length=160)
    category = models.CharField("分类", max_length=40, default="通用", db_index=True)
    description = models.TextField("描述", blank=True, default="")
    status = models.CharField("状态", max_length=16, choices=REPORT_STATUS, default="draft", db_index=True)
    permissions = models.JSONField("权限", default=dict, blank=True)
    theme = models.CharField("主题", max_length=20, default="light")
    cache_ttl = models.IntegerField("结果缓存秒数", default=300)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    run_count = models.IntegerField("执行次数", default=0)
    last_run_at = models.DateTimeField("最近执行时间", null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_reports", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表定义"
        verbose_name_plural = "报表定义"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status"], name="rep_rep_owner_status_idx"),
            models.Index(fields=["category", "status"], name="rep_rep_cat_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["owner", "code"], name="rep_rep_owner_code_uniq"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def effective_cache_ttl(self):
        """缓存秒数下限 0、上限 1 天：防止把过期时间算到几百年后。"""
        return max(0, min(int(self.cache_ttl or 0), 86400))

    def mark_run(self, rows=0):
        """执行计数与最近执行时间（用 update 避免覆盖并发修改的配置字段）。"""
        ReportDefinition.objects.filter(pk=self.pk).update(
            run_count=models.F("run_count") + 1, last_run_at=timezone.now(),
        )


class ReportPage(models.Model):
    """报表页面：一个报表按 tab 分页，布局 JSON 交给前端栅格渲染。"""

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_pages", verbose_name="报表",
    )
    title = models.CharField("标题", max_length=120)
    description = models.CharField("描述", max_length=255, blank=True, default="")
    order = models.IntegerField("排序", default=0)
    layout = models.JSONField("布局", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表页面"
        verbose_name_plural = "报表页面"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["report", "order"], name="rep_page_rep_order_idx")]

    def __str__(self):
        return f"{self.report_id}/{self.title}"


class ReportWidget(models.Model):
    """报表组件：table/bar/line/pie/kpi/pivot/heatmap/text。

    位置尺寸（x/y/w/h）按 12 栅格存，前端零计算直接摆；
    ``config`` 存该类型专属配置（轴、系列、KPI 公式、对照周期等）。
    """

    page = models.ForeignKey(
        ReportPage, on_delete=models.CASCADE, related_name="rep_widgets", verbose_name="页面",
    )
    rtype = models.CharField("类型", max_length=16, choices=WIDGET_TYPES, default="table")
    title = models.CharField("标题", max_length=160)
    description = models.CharField("描述", max_length=255, blank=True, default="")
    dataset = models.ForeignKey(
        Dataset, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rep_widgets", verbose_name="数据集",
    )
    config = models.JSONField("配置", default=dict, blank=True)
    x = models.IntegerField("X", default=0)
    y = models.IntegerField("Y", default=0)
    w = models.IntegerField("宽", default=6)
    h = models.IntegerField("高", default=4)
    order = models.IntegerField("排序", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表组件"
        verbose_name_plural = "报表组件"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["page", "order"], name="rep_wdg_page_order_idx")]

    def __str__(self):
        return f"{self.title}({self.rtype})"


class WidgetFilter(models.Model):
    """组件筛选器：field/operator/default_value 构成默认条件，``bound_param``
    指向数据集参数名 —— 前端改筛选即改参数，不用改组件配置。
    """

    widget = models.ForeignKey(
        ReportWidget, on_delete=models.CASCADE, related_name="rep_widget_filters", verbose_name="组件",
    )
    field = models.CharField("字段", max_length=120)
    operator = models.CharField("操作符", max_length=20, default="eq")
    default_value = models.JSONField("默认值", null=True, blank=True)
    bound_param = models.CharField("绑定参数", max_length=60, blank=True, default="")
    label = models.CharField("显示名", max_length=80, blank=True, default="")
    order = models.IntegerField("排序", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "组件筛选器"
        verbose_name_plural = "组件筛选器"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["widget", "order"], name="rep_wf_wdg_order_idx")]

    def __str__(self):
        return f"{self.field}{self.operator}={self.default_value}"


# ---------------------------------------------------------------------------
# 执行流水 / 结果缓存
# ---------------------------------------------------------------------------


class ReportRun(models.Model):
    """一次报表执行：无论成功失败都落一行，指标概览全靠它算分位与失败率。"""

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_runs", verbose_name="报表",
    )
    trigger = models.CharField("触发方式", max_length=16, choices=RUN_TRIGGERS, default="manual")
    params = models.JSONField("参数", default=dict, blank=True)
    status = models.CharField("状态", max_length=16, choices=RUN_STATUS, default="running", db_index=True)
    duration_ms = models.IntegerField("耗时毫秒", default=0)
    row_count = models.IntegerField("行数", default=0)
    error = models.TextField("错误", blank=True, default="")
    result = models.JSONField("结果", default=dict, blank=True)
    result_size = models.IntegerField("结果字节数", default=0)
    started_at = models.DateTimeField("开始时间", default=timezone.now)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_runs", verbose_name="触发人",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "报表执行"
        verbose_name_plural = "报表执行"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["report", "-created_at"], name="rep_run_rep_created_idx"),
            models.Index(fields=["status", "created_at"], name="rep_run_status_created_idx"),
            models.Index(fields=["trigger", "created_at"], name="rep_run_trigger_created_idx"),
        ]

    def __str__(self):
        return f"run#{self.pk} {self.status} {self.duration_ms}ms"

    def finish_success(self, payload, rows):
        """成功收尾：写状态、耗时、行数与结果快照（结果只留前 200 行，防表膨胀）。"""
        import json as _json

        trimmed = _trim_payload(payload)
        self.status = "success"
        self.row_count = int(rows or 0)
        self.finished_at = timezone.now()
        self.duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
        self.result = trimmed
        self.result_size = len(_json.dumps(trimmed, ensure_ascii=False, default=str))
        self.save(update_fields=[
            "status", "row_count", "finished_at", "duration_ms", "result",
            "result_size", "trigger",
        ])

    def finish_failure(self, message):
        """失败收尾：错误只留前 2000 字，够排障又不至于把日志表撑爆。"""
        self.status = "failed"
        self.error = str(message)[:2000]
        self.finished_at = timezone.now()
        self.duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
        self.save(update_fields=["status", "error", "finished_at", "duration_ms"])


def _trim_payload(payload):
    """执行结果裁剪：每页每组件只留前 200 行，避免 ReportRun.result 无界增长。"""
    if not isinstance(payload, dict):
        return {}
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return payload
    out = dict(payload)
    new_pages = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        page = dict(p)
        widgets = []
        for w in page.get("widgets") or []:
            if not isinstance(w, dict):
                continue
            item = dict(w)
            result = item.get("result")
            if isinstance(result, dict) and isinstance(result.get("rows"), list):
                result = dict(result)
                if len(result["rows"]) > 200:
                    result["rows"] = result["rows"][:200]
                    meta = dict(result.get("meta") or {})
                    meta["truncated"] = True
                    result["meta"] = meta
                item["result"] = result
            widgets.append(item)
        page["widgets"] = widgets
        new_pages.append(page)
    out["pages"] = new_pages
    return out


class ReportSnapshot(models.Model):
    """报表结果缓存：同一报表 + 同一参数指纹只存一份，过期即失效。

    （report, params_key）唯一 —— 重复执行同参数只更新 payload/expires_at。
    """

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_snapshots", verbose_name="报表",
    )
    params_key = models.CharField("参数指纹", max_length=64)
    params = models.JSONField("参数", default=dict, blank=True)
    payload = models.JSONField("结果", default=dict, blank=True)
    row_count = models.IntegerField("行数", default=0)
    expires_at = models.DateTimeField("过期时间", db_index=True)
    hits = models.IntegerField("命中次数", default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_snapshots", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表结果快照"
        verbose_name_plural = "报表结果快照"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["report", "params_key"], name="rep_snap_key_idx"),
            models.Index(fields=["expires_at"], name="rep_snap_expire_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["report", "params_key"], name="rep_snap_report_key_uniq"),
        ]

    def __str__(self):
        return f"snap#{self.pk} {self.params_key[:8]}"

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    def touch_hit(self):
        """命中计数走 update：避免把整个 payload 重新写一遍。"""
        ReportSnapshot.objects.filter(pk=self.pk).update(
            hits=models.F("hits") + 1, updated_at=timezone.now(),
        )


# ---------------------------------------------------------------------------
# 计划任务 / 订阅 / 分享
# ---------------------------------------------------------------------------


class ReportSchedule(models.Model):
    """报表计划任务：5 段 cron（分 时 日 月 周）+ 时区。

    下一运行时间由 ``reporting.cron.compute_next_run`` 计算（不依赖 celery beat），
    ``next_run_at`` 落库只是给前端展示与「到期扫描」用。
    """

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_schedules", verbose_name="报表",
    )
    name = models.CharField("名称", max_length=120, blank=True, default="")
    cron_expr = models.CharField("cron 表达式", max_length=120, default="0 9 * * 1-5")
    timezone = models.CharField("时区", max_length=64, default="Asia/Shanghai")
    next_run_at = models.DateTimeField("下次运行", null=True, blank=True)
    last_run_at = models.DateTimeField("上次运行", null=True, blank=True)
    enabled = models.BooleanField("已启用", default=False, db_index=True)
    recipients = models.JSONField("收件人", default=list, blank=True)
    run_count = models.IntegerField("运行次数", default=0)
    last_status = models.CharField("上次状态", max_length=16, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_schedules", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表计划任务"
        verbose_name_plural = "报表计划任务"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["enabled", "next_run_at"], name="rep_sch_enabled_next_idx"),
            models.Index(fields=["report", "enabled"], name="rep_sch_rep_enabled_idx"),
        ]

    def __str__(self):
        return f"{self.report_id}:{self.cron_expr}"

    def refresh_next_run(self, save=True):
        """重算 next_run_at：cron 非法时抛 ValueError（调用方转 400）。"""
        from reporting.cron import compute_next_run

        nxt = compute_next_run(self.cron_expr, self.timezone)
        self.next_run_at = nxt
        if save:
            self.save(update_fields=["next_run_at", "updated_at"])
        return nxt


class ReportSubscription(models.Model):
    """用户订阅：谁、通过什么渠道、多久收一次。"""

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_subscriptions", verbose_name="报表",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_subscriptions", verbose_name="订阅人",
    )
    channel = models.CharField("渠道", max_length=16, choices=SUB_CHANNELS, default="email")
    frequency = models.CharField("频率", max_length=16, choices=SUB_FREQUENCIES, default="weekly")
    enabled = models.BooleanField("已启用", default=True)
    last_sent_at = models.DateTimeField("最近发送", null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_subscriptions_created", verbose_name="创建人",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表订阅"
        verbose_name_plural = "报表订阅"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["report", "enabled"], name="rep_sub_rep_enabled_idx"),
            models.Index(fields=["user", "enabled"], name="rep_sub_user_enabled_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["report", "user"], name="rep_sub_report_user_uniq"),
        ]

    def __str__(self):
        return f"{self.report_id}→{self.user_id}/{self.channel}"


class ReportShare(models.Model):
    """分享链接：token 只读访问，可设过期与停用；view_count 用于热度排序。"""

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_shares", verbose_name="报表",
    )
    token = models.CharField("令牌", max_length=64, unique=True)
    readonly = models.BooleanField("只读", default=True)
    expires_at = models.DateTimeField("过期时间", null=True, blank=True)
    enabled = models.BooleanField("启用", default=True, db_index=True)
    note = models.CharField("备注", max_length=200, blank=True, default="")
    view_count = models.IntegerField("访问次数", default=0)
    last_viewed_at = models.DateTimeField("最近访问", null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_shares", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "报表分享"
        verbose_name_plural = "报表分享"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["enabled", "expires_at"], name="rep_share_enabled_exp_idx")]

    def __str__(self):
        return f"share:{self.token[:8]}"

    @property
    def is_valid(self):
        """启用 + 未过期才算有效；过期不自动删，便于审计。"""
        if not self.enabled:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def register_view(self):
        """公开访问计数（update 而非 save，避免覆盖并发改动）。"""
        ReportShare.objects.filter(pk=self.pk).update(
            view_count=models.F("view_count") + 1,
            last_viewed_at=timezone.now(),
        )


# ---------------------------------------------------------------------------
# 仪表盘
# ---------------------------------------------------------------------------


class Dashboard(models.Model):
    """仪表盘：跨报表拼装的看板，组件通过 DashboardWidget 引用 ReportWidget。"""

    name = models.CharField("名称", max_length=120)
    description = models.TextField("描述", blank=True, default="")
    layout = models.JSONField("布局", default=dict, blank=True)
    theme = models.CharField("主题", max_length=20, default="light")
    default_filters = models.JSONField("默认筛选", default=dict, blank=True)
    status = models.CharField("状态", max_length=16, choices=DASHBOARD_STATUS, default="active", db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_dashboards", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "仪表盘"
        verbose_name_plural = "仪表盘"
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["owner", "status"], name="rep_dash_owner_status_idx")]

    def __str__(self):
        return self.name


class DashboardWidget(models.Model):
    """仪表盘里的组件：引用报表组件 + 覆盖配置 + 自己的位置尺寸。"""

    dashboard = models.ForeignKey(
        Dashboard, on_delete=models.CASCADE, related_name="rep_dashboard_widgets", verbose_name="仪表盘",
    )
    widget = models.ForeignKey(
        ReportWidget, on_delete=models.CASCADE, related_name="rep_dashboard_links", verbose_name="报表组件",
    )
    override = models.JSONField("覆盖配置", default=dict, blank=True)
    x = models.IntegerField("X", default=0)
    y = models.IntegerField("Y", default=0)
    w = models.IntegerField("宽", default=6)
    h = models.IntegerField("高", default=4)
    order = models.IntegerField("排序", default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_dashboard_widgets", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "仪表盘组件"
        verbose_name_plural = "仪表盘组件"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["dashboard", "order"], name="rep_dw_dash_order_idx")]
        constraints = [
            models.UniqueConstraint(fields=["dashboard", "widget"], name="rep_dw_dash_widget_uniq"),
        ]

    def __str__(self):
        return f"{self.dashboard_id}→{self.widget_id}"


# ---------------------------------------------------------------------------
# 批注 / 导出任务 / 收藏
# ---------------------------------------------------------------------------


class ReportAnnotation(models.Model):
    """图表批注：钉在某个组件（或整张报表）的某个数据点上。"""

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_annotations", verbose_name="报表",
    )
    widget = models.ForeignKey(
        ReportWidget, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rep_annotations", verbose_name="组件",
    )
    body = models.TextField("内容")
    data_point = models.JSONField("数据点", default=dict, blank=True)
    color = models.CharField("颜色", max_length=20, default="#f59e0b")
    resolved = models.BooleanField("已解决", default=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_annotations", verbose_name="作者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表批注"
        verbose_name_plural = "报表批注"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["report", "resolved"], name="rep_ann_rep_resolved_idx"),
            models.Index(fields=["widget", "-created_at"], name="rep_ann_wdg_created_idx"),
        ]

    def __str__(self):
        return f"{self.pk}:{self.body[:20]}"


class ReportExportJob(models.Model):
    """导出任务：CSV/JSON 同步生成但留档（行数、耗时、错误可追）。"""

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rep_export_jobs", verbose_name="报表",
    )
    fmt = models.CharField("格式", max_length=10, choices=EXPORT_FORMATS, default="csv")
    status = models.CharField("状态", max_length=16, choices=JOB_STATUS, default="queued", db_index=True)
    row_count = models.IntegerField("行数", default=0)
    error = models.TextField("错误", blank=True, default="")
    params = models.JSONField("参数", default=dict, blank=True)
    filename = models.CharField("文件名", max_length=160, blank=True, default="")
    size_bytes = models.IntegerField("字节数", default=0)
    duration_ms = models.IntegerField("耗时毫秒", default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_export_jobs", verbose_name="所有者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报表导出任务"
        verbose_name_plural = "报表导出任务"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status"], name="rep_exp_owner_status_idx"),
            models.Index(fields=["fmt", "created_at"], name="rep_exp_fmt_created_idx"),
        ]

    def __str__(self):
        return f"export#{self.pk} {self.fmt}:{self.status}"


class ReportFavorite(models.Model):
    """收藏：每个用户对同一报表最多一条，(report,user) 唯一约束兜底并发。"""

    report = models.ForeignKey(
        ReportDefinition, on_delete=models.CASCADE, related_name="rep_favorites", verbose_name="报表",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_favorites", verbose_name="用户",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="rep_favorites_created", verbose_name="创建人",
    )
    created_at = models.DateTimeField("收藏时间", auto_now_add=True)

    class Meta:
        verbose_name = "报表收藏"
        verbose_name_plural = "报表收藏"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "-created_at"], name="rep_fav_user_created_idx")]
        constraints = [
            models.UniqueConstraint(fields=["report", "user"], name="rep_fav_report_user_uniq"),
        ]

    def __str__(self):
        return f"{self.user_id}★{self.report_id}"


# ---------------------------------------------------------------------------
# 汇总口径常量（urls.py 的接口数量断言与目录页共用）
# ---------------------------------------------------------------------------

MODEL_REGISTRY = {
    "datasource": DataSource,
    "dataset": Dataset,
    "datasetfield": DatasetField,
    "datasetjoin": DatasetJoin,
    "datasetparam": DatasetParam,
    "report": ReportDefinition,
    "reportpage": ReportPage,
    "reportwidget": ReportWidget,
    "widgetfilter": WidgetFilter,
    "reportrun": ReportRun,
    "reportsnapshot": ReportSnapshot,
    "reportschedule": ReportSchedule,
    "reportsubscription": ReportSubscription,
    "reportshare": ReportShare,
    "dashboard": Dashboard,
    "dashboardwidget": DashboardWidget,
    "reportannotation": ReportAnnotation,
    "reportexportjob": ReportExportJob,
    "reportfavorite": ReportFavorite,
}


def snapshot_expiry(ttl_seconds):
    """快照过期时间：ttl<=0 视为立即过期（等价于禁用缓存）。"""
    return timezone.now() + timedelta(seconds=max(0, int(ttl_seconds or 0)))
