# -*- coding: utf-8 -*-
"""bizhub 数据模型：34 个业务模块共用一套记录 / 评论 / 活动 / 视图 / 订阅表。

设计要点
--------
- 记录只有固定列（标题/状态/分类/优先级/负责人/到期日/标签/归档/删除），
  模块差异全部落在 ``data`` JSON，字段 schema 由 ``modules.py`` 定义并在
  视图层做类型校验，因此新增模块不需要任何迁移。
- 软删除（``is_deleted``）与归档（``archived``）分离：回收站与归档列表各自独立。
- 收藏走 M2M through 表，列表页一次查出当前页的收藏集合，避免 N+1。
"""
from django.conf import settings
from django.db import models


class BizRecord(models.Model):
    """业务记录：所有模块的统一载体"""

    module = models.CharField(max_length=64, db_index=True, verbose_name="业务模块")
    title = models.CharField(max_length=200, verbose_name="标题")
    status = models.CharField(max_length=32, blank=True, default="", verbose_name="状态")
    category = models.CharField(max_length=64, blank=True, default="", verbose_name="分类")
    priority = models.CharField(max_length=16, default="normal", verbose_name="优先级")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="biz_records", verbose_name="负责人",
    )
    department = models.ForeignKey(
        "accounts.Department", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="biz_records", verbose_name="所属部门",
    )
    due_date = models.DateField(null=True, blank=True, verbose_name="到期日")
    tags = models.JSONField(default=list, blank=True, verbose_name="标签")
    data = models.JSONField(default=dict, blank=True, verbose_name="扩展字段")
    archived = models.BooleanField(default=False, verbose_name="已归档")
    is_deleted = models.BooleanField(default=False, verbose_name="已删除")
    favorited_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="biz_favorites", blank=True, verbose_name="收藏人",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="biz_created", verbose_name="创建人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "业务记录"
        verbose_name_plural = "业务记录"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["module", "is_deleted", "archived"], name="biz_rec_mod_state_idx"),
            models.Index(fields=["module", "status"], name="biz_rec_mod_status_idx"),
            models.Index(fields=["owner", "module"], name="biz_rec_owner_mod_idx"),
            models.Index(fields=["due_date"], name="biz_rec_due_idx"),
        ]

    def __str__(self):
        return f"{self.module}:{self.id} {self.title[:30]}"


class BizComment(models.Model):
    """记录下的评论（时间线与评论列表共用）"""

    record = models.ForeignKey(BizRecord, on_delete=models.CASCADE, related_name="comments", verbose_name="记录")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="biz_comments", verbose_name="评论人",
    )
    content = models.CharField(max_length=1000, verbose_name="内容")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "业务评论"
        verbose_name_plural = "业务评论"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["record", "-created_at"], name="biz_cmt_rec_created_idx")]

    def __str__(self):
        return f"{self.record_id}:{self.content[:20]}"


class BizActivity(models.Model):
    """记录操作留痕（创建/更新/状态流转/归档/合并等）"""

    record = models.ForeignKey(BizRecord, on_delete=models.CASCADE, related_name="activities", verbose_name="记录")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="biz_activities", verbose_name="操作人",
    )
    action = models.CharField(max_length=32, verbose_name="动作")
    detail = models.JSONField(default=dict, blank=True, verbose_name="明细")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "业务活动"
        verbose_name_plural = "业务活动"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["record", "-created_at"], name="biz_act_rec_created_idx")]

    def __str__(self):
        return f"{self.record_id} {self.action}"


class BizSavedView(models.Model):
    """保存视图：个人筛选组合，可共享给同模块所有人"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="biz_views", verbose_name="用户",
    )
    module = models.CharField(max_length=64, verbose_name="业务模块")
    name = models.CharField(max_length=80, verbose_name="视图名")
    params = models.JSONField(default=dict, blank=True, verbose_name="筛选参数")
    shared = models.BooleanField(default=False, verbose_name="共享")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "业务保存视图"
        verbose_name_plural = "业务保存视图"
        ordering = ["-created_at", "-id"]
        unique_together = [("user", "module", "name")]
        indexes = [models.Index(fields=["module", "shared"], name="biz_view_mod_shared_idx")]

    def __str__(self):
        return f"{self.module}/{self.name}"


class BizSubscription(models.Model):
    """模块到期订阅：由 bizhub_digest 按日/按周推送汇总"""

    FREQUENCY_CHOICES = [("daily", "每天"), ("weekly", "每周")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="biz_subscriptions", verbose_name="用户",
    )
    module = models.CharField(max_length=64, verbose_name="业务模块")
    enabled = models.BooleanField(default=False, verbose_name="已订阅")
    frequency = models.CharField(
        max_length=8, choices=FREQUENCY_CHOICES, default="daily", verbose_name="频率",
    )
    last_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="最近推送")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "业务订阅"
        verbose_name_plural = "业务订阅"
        ordering = ["-created_at", "-id"]
        unique_together = [("user", "module")]
        indexes = [models.Index(fields=["enabled", "frequency"], name="biz_sub_enabled_freq_idx")]

    def __str__(self):
        return f"{self.user_id}:{self.module}={self.frequency}"
