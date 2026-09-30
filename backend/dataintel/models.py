# -*- coding: utf-8 -*-
"""dataintel 模型：数据集（列定义 + 行数据 JSON 存储，单数据集上限 5000 行）。"""
from django.conf import settings
from django.db import models

MAX_ROWS = 5000


class Dataset(models.Model):
    name = models.CharField("名称", max_length=120)
    description = models.TextField("描述", blank=True, default="")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="di_datasets", verbose_name="所有者")
    columns = models.JSONField("列定义", default=list, blank=True)
    rows = models.JSONField("行数据", default=list, blank=True)
    row_count = models.IntegerField("行数", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "数据集"
        verbose_name_plural = "数据集"

    def __str__(self):
        return f"{self.name}({self.row_count}行)"

    def save(self, *args, **kwargs):
        self.row_count = len(self.rows or [])
        if self.row_count > MAX_ROWS:
            raise ValueError(f"单数据集最多 {MAX_ROWS} 行")
        super().save(*args, **kwargs)
