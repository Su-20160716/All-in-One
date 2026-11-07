# -*- coding: utf-8 -*-
"""bizhub 路由：34 个业务模块共用 24 条路径（31 个方法），前缀 /api/biz/。

顺序约定：``modules/``、``overview/``、``members/`` 必须排在动态 ``<slug>`` 之前，
否则会被当作模块 slug 吞掉。
"""
from django.urls import path

from . import views as v

urlpatterns = [
    # 模块元数据与全局视图
    path("modules/", v.modules_list),
    path("modules/<slug:slug>/", v.module_detail),
    path("overview/", v.overview),
    path("members/", v.members),
    # 记录 CRUD
    path("<slug:slug>/records/", v.record_collection),
    path("<slug:slug>/records/<int:pk>/", v.record_item),
    # 记录动作
    path("<slug:slug>/records/<int:pk>/restore/", v.record_restore),
    path("<slug:slug>/records/<int:pk>/archive/", v.record_archive),
    path("<slug:slug>/records/<int:pk>/unarchive/", v.record_unarchive),
    path("<slug:slug>/records/<int:pk>/duplicate/", v.record_duplicate),
    path("<slug:slug>/records/<int:pk>/comments/", v.record_comments),
    path("<slug:slug>/records/<int:pk>/timeline/", v.record_timeline),
    path("<slug:slug>/records/<int:pk>/favorite/", v.record_favorite),
    # 批量与数据交换
    path("<slug:slug>/bulk/", v.record_bulk),
    path("<slug:slug>/export/", v.record_export),
    path("<slug:slug>/import/", v.record_import),
    # 分析
    path("<slug:slug>/stats/", v.record_stats),
    path("<slug:slug>/trend/", v.record_trend),
    path("<slug:slug>/distribution/", v.record_distribution),
    path("<slug:slug>/overdue/", v.record_overdue),
    path("<slug:slug>/quality/", v.record_quality),
    # 效率与协作
    path("<slug:slug>/merge/", v.record_merge),
    path("<slug:slug>/saved-views/", v.saved_views),
    path("<slug:slug>/subscription/", v.subscription),
]
