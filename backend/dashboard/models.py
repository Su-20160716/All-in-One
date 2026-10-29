# -*- coding: utf-8 -*-
"""dashboard 模型：仪表盘卡片顺序（F668 机动项）

拖拽排序除 localStorage 外再同步一份到服务端，换浏览器/换设备登录后顺序一致。
纯新增可空数据，不影响任何既有接口。
"""
from django.conf import settings
from django.db import models


class DashboardCardOrder(models.Model):
    """用户工作台卡片的自定义顺序（order 为卡片 key 数组）"""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="dashboard_card_order", verbose_name="用户",
    )
    order = models.JSONField(default=list, blank=True, verbose_name="卡片顺序")
    # F28/F29：布局与卡片可见性（跨设备同步，localStorage 仅作离线兜底）
    layout = models.JSONField(default=dict, blank=True, verbose_name="卡片布局")
    enabled = models.JSONField(default=list, blank=True, verbose_name="启用的卡片")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "仪表盘卡片顺序"
        verbose_name_plural = "仪表盘卡片顺序"

    def __str__(self):
        return f"{self.owner} · {len(self.order)} 张卡片"
