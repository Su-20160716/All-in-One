# -*- coding: utf-8 -*-
"""officesuite 后台管理：全部模型注册，方便运营侧直接维护。"""
from django.contrib import admin

from officesuite import models as m

_PLAIN = [
    # 审批流
    m.ApprovalRequest, m.SealApply, m.ExpenseReport, m.TravelApply, m.Contract,
    # 资源
    m.MeetingRoom, m.RoomBooking, m.Asset, m.Vehicle, m.VehicleBooking,
    m.SupplyItem, m.SupplyApply, m.VisitorRecord, m.MailParcel,
    # 人员协作
    m.DutySchedule, m.DutyShift, m.TimesheetEntry, m.TrainingSession,
    m.TrainingEnrollment, m.RecognitionRecord, m.StandupEntry,
    m.Objective, m.KeyResult, m.DecisionRecord, m.TodoItem,
    # 知识与内容
    m.FaqEntry, m.PolicyDoc, m.DocTemplate, m.WikiPage, m.MeetingMinutes,
    m.CollectForm, m.FormEntry, m.DeptAnnouncement, m.Poll, m.PollVote,
    m.HelpTicket, m.SuiteEvent,
]


class SuiteAdmin(admin.ModelAdmin):
    """通用后台：默认列 + 时间倒序。"""
    list_display = ("__str__",)
    ordering = ("-id",)

    def __init__(self, model, admin_site):
        fields = [f.name for f in model._meta.get_fields()
                  if getattr(f, "concrete", False) and not f.name.startswith("data")]
        self.list_display = tuple(fields[:8])
        super().__init__(model, admin_site)


class SimpleAdmin(admin.ModelAdmin):
    ordering = ("-id",)

    def __init__(self, model, admin_site):
        fields = [f.name for f in model._meta.get_fields()
                  if getattr(f, "concrete", False)]
        self.list_display = tuple(fields[:8])
        super().__init__(model, admin_site)


for _model in _PLAIN:
    _admin = SuiteAdmin if hasattr(_model, "status") else SimpleAdmin
    admin.site.register(_model, _admin)
