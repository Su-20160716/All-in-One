# -*- coding: utf-8 -*-
"""officesuite 模型：统一抽象基类（owner/title/status/data JSON）+ 30 个业务子系统模型。

设计约定：
- 共性字段收口到 SuiteBase（owner / title / status / data / remark / 时间戳）；
- 子系统专属字段只在必要处显式建模，其余扩展信息放 data JSONField，避免碎片化迁移；
- 行级权限统一走 core.scoping（owner 字段），不在业务模型上加权限字段。
"""
from django.conf import settings
from django.db import models

STATUS_CHOICES = {
    "flow": ["pending", "approved", "rejected", "cancelled"],  # 审批类通用状态机
}


class SuiteBase(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="%(class)s_set", verbose_name="所有者")
    title = models.CharField("标题", max_length=200, blank=True, default="")
    status = models.CharField("状态", max_length=20, default="active", db_index=True)
    data = models.JSONField("扩展数据", default=dict, blank=True)
    remark = models.TextField("备注", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"#{self.pk} {self.title or self.__class__.__name__} [{self.status}]"


# ---------- 审批流 ----------
class ApprovalRequest(SuiteBase):
    class Meta(SuiteBase.Meta):
        verbose_name = "审批单"


class SealApply(SuiteBase):
    seal_type = models.CharField("印章类型", max_length=30, default="公章")
    copies = models.IntegerField("份数", default=1)

    class Meta(SuiteBase.Meta):
        verbose_name = "用印申请"


class ExpenseReport(SuiteBase):
    total = models.DecimalField("总金额", max_digits=12, decimal_places=2, default=0)
    invoice_count = models.IntegerField("发票张数", default=0)

    class Meta(SuiteBase.Meta):
        verbose_name = "报销单"


class TravelApply(SuiteBase):
    destination = models.CharField("目的地", max_length=120, blank=True, default="")
    start_date = models.DateField("出发日", null=True, blank=True)
    end_date = models.DateField("返回日", null=True, blank=True)
    estimate = models.DecimalField("预算", max_digits=12, decimal_places=2, default=0)

    class Meta(SuiteBase.Meta):
        verbose_name = "差旅申请"


class Contract(SuiteBase):
    party = models.CharField("对方主体", max_length=200, blank=True, default="")
    amount = models.DecimalField("金额", max_digits=14, decimal_places=2, default=0)
    sign_date = models.DateField("签订日", null=True, blank=True)
    expire_date = models.DateField("到期日", null=True, blank=True)

    class Meta(SuiteBase.Meta):
        verbose_name = "合同台账"


# ---------- 资源类 ----------
class MeetingRoom(models.Model):
    name = models.CharField("会议室名", max_length=100)
    capacity = models.IntegerField("容量", default=6)
    location = models.CharField("位置", max_length=120, blank=True, default="")
    facilities = models.JSONField("设备", default=list, blank=True)
    active = models.BooleanField("可用", default=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_meeting_rooms", verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class RoomBooking(SuiteBase):
    room = models.ForeignKey(MeetingRoom, on_delete=models.CASCADE, related_name="bookings", verbose_name="会议室")
    start_at = models.DateTimeField("开始时间")
    end_at = models.DateTimeField("结束时间")

    class Meta(SuiteBase.Meta):
        verbose_name = "会议室预订"


class Asset(SuiteBase):
    code = models.CharField("资产编码", max_length=60, blank=True, default="")
    category = models.CharField("类别", max_length=40, default="设备")
    holder_id = models.IntegerField("当前持有人ID", null=True, blank=True)
    holder_name = models.CharField("当前持有人", max_length=80, blank=True, default="")
    value = models.DecimalField("价值", max_digits=12, decimal_places=2, default=0)

    class Meta(SuiteBase.Meta):
        verbose_name = "资产"


class Vehicle(models.Model):
    plate = models.CharField("车牌", max_length=20)
    model_name = models.CharField("车型", max_length=60, blank=True, default="")
    seats = models.IntegerField("座位数", default=5)
    active = models.BooleanField("可用", default=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_vehicles", verbose_name="管理员")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.plate


class VehicleBooking(SuiteBase):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="bookings", verbose_name="车辆")
    use_at = models.DateTimeField("用车时间")
    return_at = models.DateTimeField("预计归还", null=True, blank=True)
    destination = models.CharField("目的地", max_length=120, blank=True, default="")

    class Meta(SuiteBase.Meta):
        verbose_name = "用车申请"


class SupplyItem(models.Model):
    name = models.CharField("物品", max_length=100)
    stock = models.IntegerField("库存", default=0)
    unit = models.CharField("单位", max_length=10, default="件")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_supplies", verbose_name="管理员")

    def __str__(self):
        return f"{self.name}(库存{self.stock})"


class SupplyApply(SuiteBase):
    item = models.ForeignKey(SupplyItem, on_delete=models.CASCADE, related_name="applies", verbose_name="物品")
    qty = models.IntegerField("数量", default=1)

    class Meta(SuiteBase.Meta):
        verbose_name = "物品领用"


class VisitorRecord(SuiteBase):
    visitor_name = models.CharField("访客", max_length=60)
    company = models.CharField("单位", max_length=120, blank=True, default="")
    host_name = models.CharField("接待人", max_length=60, blank=True, default="")
    visit_at = models.DateTimeField("到访时间", null=True, blank=True)

    class Meta(SuiteBase.Meta):
        verbose_name = "访客登记"


class MailParcel(SuiteBase):
    receiver_name = models.CharField("收件人", max_length=60)
    sender_info = models.CharField("寄件信息", max_length=120, blank=True, default="")
    picked_at = models.DateTimeField("领取时间", null=True, blank=True)

    class Meta(SuiteBase.Meta):
        verbose_name = "快递代收"


# ---------- 人员协作 ----------
class DutySchedule(models.Model):
    name = models.CharField("排班表名", max_length=120)
    start_date = models.DateField("开始日期", null=True, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_duty_schedules", verbose_name="创建人")

    def __str__(self):
        return self.name


class DutyShift(models.Model):
    schedule = models.ForeignKey(DutySchedule, on_delete=models.CASCADE, related_name="shifts", verbose_name="排班表")
    member_name = models.CharField("成员", max_length=60)
    duty_date = models.DateField("值班日")
    shift_name = models.CharField("班次", max_length=30, default="白班")
    swapped_to = models.CharField("换班给", max_length=60, blank=True, default="")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_duty_shifts", verbose_name="创建人")

    def __str__(self):
        return f"{self.duty_date} {self.member_name} {self.shift_name}"


class DutySwapRequest(SuiteBase):
    """F683 值班换班申请：发起 → 对方确认 → 记录（区别于直接换班）。

    status: pending / accepted / rejected / cancelled
    """

    shift = models.ForeignKey(DutyShift, on_delete=models.CASCADE,
                              related_name="swap_requests", verbose_name="班次")
    from_name = models.CharField("发起人", max_length=60, default="")
    to_name = models.CharField("接收人", max_length=60, default="")

    class Meta(SuiteBase.Meta):
        verbose_name = "换班申请"
        ordering = ["-created_at"]


class TimesheetEntry(SuiteBase):
    work_date = models.DateField("日期", null=True, blank=True)
    hours = models.DecimalField("工时", max_digits=5, decimal_places=2, default=0)
    project_name = models.CharField("项目", max_length=120, blank=True, default="")

    class Meta(SuiteBase.Meta):
        verbose_name = "工时记录"


class TrainingSession(models.Model):
    topic = models.CharField("主题", max_length=200)
    trainer = models.CharField("讲师", max_length=60, blank=True, default="")
    start_at = models.DateTimeField("开始时间", null=True, blank=True)
    capacity = models.IntegerField("名额", default=30)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_trainings", verbose_name="组织者")

    def __str__(self):
        return self.topic


class TrainingEnrollment(models.Model):
    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name="enrollments", verbose_name="培训")
    member_name = models.CharField("姓名", max_length=60)
    checked_in = models.BooleanField("已签到", default=False)
    feedback = models.TextField("反馈", blank=True, default="")
    rating = models.IntegerField("评分", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RecognitionRecord(SuiteBase):
    to_name = models.CharField("被表彰人", max_length=60)
    level = models.CharField("级别", max_length=20, default="部门")
    likes = models.IntegerField("点赞", default=0)

    class Meta(SuiteBase.Meta):
        verbose_name = "表彰记录"


class StandupEntry(SuiteBase):
    standup_date = models.DateField("日期", null=True, blank=True)
    yesterday = models.TextField("昨天", blank=True, default="")
    today = models.TextField("今天", blank=True, default="")
    blockers = models.TextField("阻碍", blank=True, default="")

    class Meta(SuiteBase.Meta):
        verbose_name = "站会汇报"


class Objective(SuiteBase):
    period = models.CharField("周期", max_length=30, default="Q4")
    progress = models.IntegerField("总进度", default=0)

    class Meta(SuiteBase.Meta):
        verbose_name = "OKR 目标"


class KeyResult(models.Model):
    objective = models.ForeignKey(Objective, on_delete=models.CASCADE, related_name="krs", verbose_name="目标")
    content = models.CharField("关键结果", max_length=300)
    progress = models.IntegerField("进度%", default=0)
    weight = models.IntegerField("权重", default=1)


class DecisionRecord(SuiteBase):
    context = models.TextField("背景", blank=True, default="")
    options = models.JSONField("候选方案", default=list, blank=True)
    choice = models.CharField("最终选择", max_length=200, blank=True, default="")

    class Meta(SuiteBase.Meta):
        verbose_name = "决策记录"


class TodoItem(SuiteBase):
    priority = models.CharField("优先级", max_length=10, default="normal")
    due_date = models.DateField("截止", null=True, blank=True)
    done = models.BooleanField("完成", default=False)
    # F690 四象限：重要标记（紧急度由 priority / due_date 推导）
    important = models.BooleanField("重要", default=False)
    # F689 重复规则：none/daily/weekly/workday（每周=同 weekday，工作日=周一至周五）
    repeat_rule = models.CharField("重复规则", max_length=16, default="none")
    repeat_until = models.DateField("重复截止", null=True, blank=True)
    last_generated = models.DateField("上次生成", null=True, blank=True)

    class Meta(SuiteBase.Meta):
        verbose_name = "轻待办"


# ---------- 知识与内容 ----------
class FaqEntry(SuiteBase):
    answer = models.TextField("答案", blank=True, default="")
    category = models.CharField("分类", max_length=40, default="通用")
    votes = models.IntegerField("有用票", default=0)

    class Meta(SuiteBase.Meta):
        verbose_name = "FAQ"


class PolicyDoc(SuiteBase):
    content = models.TextField("正文", blank=True, default="")
    version = models.CharField("版本", max_length=20, default="v1.0")
    effective_date = models.DateField("生效日", null=True, blank=True)
    acked_by = models.JSONField("已阅人", default=list, blank=True)

    class Meta(SuiteBase.Meta):
        verbose_name = "制度文档"


class DocTemplate(SuiteBase):
    content = models.TextField("模板正文", blank=True, default="")
    category = models.CharField("分类", max_length=40, default="通用")

    class Meta(SuiteBase.Meta):
        verbose_name = "文档模板"


class WikiPage(models.Model):
    title = models.CharField("标题", max_length=200)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="children", verbose_name="父页")
    content = models.TextField("内容", blank=True, default="")
    order = models.IntegerField("排序", default=0)
    revisions = models.JSONField("修订记录", default=list, blank=True)
    # F687 知识库文章点赞/收藏（纯新增可空：存用户名列表）
    likes = models.JSONField("点赞用户", default=list, blank=True)
    stars = models.JSONField("收藏用户", default=list, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_wiki_pages", verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class MeetingMinutes(SuiteBase):
    meeting_at = models.DateTimeField("会议时间", null=True, blank=True)
    attendees = models.JSONField("参会人", default=list, blank=True)
    content = models.TextField("纪要正文", blank=True, default="")

    class Meta(SuiteBase.Meta):
        verbose_name = "会议纪要"


class CollectForm(models.Model):
    title = models.CharField("表单名", max_length=200)
    fields = models.JSONField("字段定义", default=list, blank=True)  # [{name, type, required}]
    closed = models.BooleanField("已截止", default=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_collect_forms", verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class FormEntry(models.Model):
    form = models.ForeignKey(CollectForm, on_delete=models.CASCADE, related_name="entries", verbose_name="表单")
    values = models.JSONField("填写内容", default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class DeptAnnouncement(SuiteBase):
    audience = models.CharField("受众", max_length=60, default="全员")
    pinned = models.BooleanField("置顶", default=False)
    read_by = models.JSONField("已读人", default=list, blank=True)

    class Meta(SuiteBase.Meta):
        verbose_name = "部门公告"


class Poll(models.Model):
    question = models.CharField("问题", max_length=300)
    options = models.JSONField("选项", default=list)
    multiple = models.BooleanField("可多选", default=False)
    closed = models.BooleanField("已截止", default=False)
    deadline = models.DateField("截止日", null=True, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_polls", verbose_name="发起人")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question


class PollVote(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes", verbose_name="投票")
    voter_name = models.CharField("投票人", max_length=60)
    choices = models.JSONField("所选选项", default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class HelpTicket(SuiteBase):
    priority = models.CharField("优先级", max_length=10, default="normal")
    assignee_name = models.CharField("处理人", max_length=60, blank=True, default="")
    replies = models.JSONField("回复记录", default=list, blank=True)

    class Meta(SuiteBase.Meta):
        verbose_name = "工单"


class SuiteEvent(models.Model):
    title = models.CharField("标题", max_length=200, default="")
    status = models.CharField("状态", max_length=20, default="planned")
    remark = models.CharField("备注", max_length=500, blank=True, default="")
    data = models.JSONField("扩展数据", default=dict, blank=True)
    start_at = models.DateTimeField("开始")
    end_at = models.DateTimeField("结束", null=True, blank=True)
    kind = models.CharField("类型", max_length=20, default="event")
    attendees = models.JSONField("参与人", default=list, blank=True)
    replies = models.JSONField("回复", default=list, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="os_events", verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
