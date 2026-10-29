# -*- coding: utf-8 -*-
"""officesuite 路由：30 个业务子系统 × 249 接口 + 文档增强 3 + 目录 1 = 253 个 URL。

家族划分（与 views_*.py 的 *_FAMILY_COUNT 对应）：
- flow     approval(12) seal(6) expense(8) travel(7) contract(8)      = 41
- res      meeting(11) asset(9) vehicle(7) supplies(7) visitor(7) mailroom(5) = 46
- people   duty(13) timesheet(9) training(10) recognition(6) standup(7)
           okr(10) decision(7) todobox(11)                            = 73
- know     faq(7) policy(7) template(7) wiki(11) minutes(9)
           formcollect(8) announcement(8) poll(9) helpdesk(11)         = 78
- calendar calendar(11)                                               = 11
- catalog  目录                                                        = 1

F681–F692 新增 15 个接口（235 → 250）：
  calendar/conflict-check · calendar/free-busy · meeting/duration-templates ·
  duty/swap-request×4 · todo/quadrant · todo/repeat-scan ·
  ticket/rate · ticket/auto-assign · wiki/like · wiki/star ·
  minutes/action-items/toggle · minutes/action-items/stats

F45–F47 文档增强 3 个接口（250 → 253）：
  annotations（GET/POST 同路径）· formula/eval · outline-from-note
"""
from django.urls import path

from devtools.common import endpoint_index
from officesuite import views_cal as c
from officesuite import views_doc as dc
from officesuite import views_flow as f
from officesuite import views_know as k
from officesuite import views_people as pe
from officesuite import views_res as r


def _suite_catalog(request):
    """目录 + 接口明细（endpoints 字段为新增，向后兼容）。

    endpoints 放在 data 层，与 devtools/dataintel 目录结构对齐，前端一份逻辑三域通用。
    """
    resp = c.suite_catalog(request)
    try:
        inner = resp.data.get("data")
        if isinstance(inner, dict):
            inner["endpoints"] = endpoint_index(urlpatterns)
    except Exception:  # noqa: BLE001 —— 目录增强失败不影响主响应
        import logging
        import traceback

        logging.getLogger("officesuite").warning(
            "suite_catalog endpoints 导出失败:\n%s", traceback.format_exc()
        )
    return resp


urlpatterns = [
    path("catalog/", _suite_catalog, name="suite-catalog"),

    # ---- approval（12）----
    path("approval/templates/", f.approval_templates),
    path("approval/submit/", f.approval_submit),
    path("approval/my-submitted/", f.approval_my_submitted),
    path("approval/my-pending/", f.approval_my_pending),
    path("approval/stats/", f.approval_stats),
    path("approval/<int:pk>/", f.approval_detail),
    path("approval/<int:pk>/approve/", f.approval_approve),
    path("approval/<int:pk>/reject/", f.approval_reject),
    path("approval/<int:pk>/cancel/", f.approval_cancel),
    path("approval/<int:pk>/comment/", f.approval_comment),
    path("approval/<int:pk>/events/", f.approval_events),
    path("approval/<int:pk>/urge/", f.approval_urge),

    # ---- seal（6）----
    path("seal/apply/", f.seal_apply),
    path("seal/mine/", f.seal_mine),
    path("seal/log/", f.seal_log),
    path("seal/stats/", f.seal_stats),
    path("seal/<int:pk>/", f.seal_detail),
    path("seal/<int:pk>/approve/", f.seal_approve),

    # ---- expense（8）----
    path("expense/submit/", f.expense_submit),
    path("expense/mine/", f.expense_mine),
    path("expense/stats/", f.expense_stats),
    path("expense/export/", f.expense_export),
    path("expense/<int:pk>/", f.expense_detail),
    path("expense/<int:pk>/approve/", f.expense_approve),
    path("expense/<int:pk>/reject/", f.expense_reject),
    path("expense/<int:pk>/pay/", f.expense_pay),

    # ---- travel（7）----
    path("travel/apply/", f.travel_apply),
    path("travel/mine/", f.travel_mine),
    path("travel/all/", f.travel_list_all),
    path("travel/stats/", f.travel_stats),
    path("travel/<int:pk>/", f.travel_detail),
    path("travel/<int:pk>/approve/", f.travel_approve),
    path("travel/<int:pk>/cancel/", f.travel_cancel),

    # ---- contract（8）----
    path("contract/create/", f.contract_create),
    path("contract/list/", f.contract_list),
    path("contract/expiring/", f.contract_expiring),
    path("contract/stats/", f.contract_stats),
    path("contract/<int:pk>/", f.contract_detail),
    path("contract/<int:pk>/status/", f.contract_update_status),
    path("contract/<int:pk>/payments/", f.contract_payments),
    path("contract/<int:pk>/delete/", f.contract_delete),

    # ---- meeting（11：10 + F682 时长模板）----
    path("meeting/room/create/", r.meeting_room_create),
    path("meeting/room/list/", r.meeting_room_list),
    path("meeting/room/<int:pk>/update/", r.meeting_room_update),
    path("meeting/room/<int:pk>/delete/", r.meeting_room_delete),
    path("meeting/room/<int:pk>/availability/", r.meeting_room_availability),
    path("meeting/duration-templates/", r.meeting_duration_templates),
    path("meeting/book/", r.meeting_book),
    path("meeting/booking/<int:pk>/cancel/", r.meeting_booking_cancel),
    path("meeting/booking/<int:pk>/detail/", r.meeting_booking_detail),
    path("meeting/my-bookings/", r.meeting_my_bookings),
    path("meeting/stats/", r.meeting_stats),

    # ---- asset（9）----
    path("asset/create/", r.asset_create),
    path("asset/list/", r.asset_list),
    path("asset/stats/", r.asset_stats),
    path("asset/my-held/", r.asset_my_held),
    path("asset/<int:pk>/update/", r.asset_update),
    path("asset/<int:pk>/delete/", r.asset_delete),
    path("asset/<int:pk>/assign/", r.asset_assign),
    path("asset/<int:pk>/return/", r.asset_return),
    path("asset/<int:pk>/detail/", r.asset_detail),

    # ---- vehicle（7）----
    path("vehicle/create/", r.vehicle_create),
    path("vehicle/list/", r.vehicle_list),
    path("vehicle/<int:pk>/update/", r.vehicle_update),
    path("vehicle/book/", r.vehicle_book),
    path("vehicle/booking/<int:pk>/approve/", r.vehicle_booking_approve),
    path("vehicle/booking/<int:pk>/cancel/", r.vehicle_booking_cancel),
    path("vehicle/my-bookings/", r.vehicle_my_bookings),

    # ---- supplies（7）----
    path("supplies/item/create/", r.supplies_item_create),
    path("supplies/item/list/", r.supplies_item_list),
    path("supplies/item/<int:pk>/restock/", r.supplies_item_restock),
    path("supplies/apply/", r.supplies_apply),
    path("supplies/apply/<int:pk>/cancel/", r.supplies_apply_cancel),
    path("supplies/my-applies/", r.supplies_my_applies),
    path("supplies/stats/", r.supplies_stats),

    # ---- visitor（7）----
    path("visitor/create/", r.visitor_create),
    path("visitor/list/", r.visitor_list),
    path("visitor/today/", r.visitor_today),
    path("visitor/<int:pk>/update/", r.visitor_update),
    path("visitor/<int:pk>/checkin/", r.visitor_checkin),
    path("visitor/<int:pk>/checkout/", r.visitor_checkout),
    path("visitor/<int:pk>/delete/", r.visitor_delete),

    # ---- mailroom（5）----
    path("mailroom/create/", r.mailroom_create),
    path("mailroom/list/", r.mailroom_list),
    path("mailroom/pending/", r.mailroom_pending),
    path("mailroom/stats/", r.mailroom_stats),
    path("mailroom/<int:pk>/pickup/", r.mailroom_pickup),

    # ---- duty（13：9 + F683 换班申请 4）----
    path("duty/schedule/create/", pe.duty_schedule_create),
    path("duty/schedule/list/", pe.duty_schedule_list),
    path("duty/schedule/<int:pk>/delete/", pe.duty_schedule_delete),
    path("duty/shift/add/", pe.duty_shift_add),
    path("duty/shift/list/", pe.duty_shift_list),
    path("duty/shift/<int:pk>/swap/", pe.duty_shift_swap),
    path("duty/shift/<int:pk>/delete/", pe.duty_shift_delete),
    path("duty/week/", pe.duty_week),
    path("duty/my-shifts/", pe.duty_my_shifts),
    path("duty/swap-request/create/", pe.duty_swap_request_create),
    path("duty/swap-request/list/", pe.duty_swap_request_list),
    path("duty/swap-request/<int:pk>/confirm/", pe.duty_swap_request_confirm),
    path("duty/swap-request/<int:pk>/cancel/", pe.duty_swap_request_cancel),

    # ---- timesheet（9）----
    path("timesheet/create/", pe.timesheet_create),
    path("timesheet/list/", pe.timesheet_list),
    path("timesheet/week/", pe.timesheet_week),
    path("timesheet/summary/", pe.timesheet_summary),
    path("timesheet/stats/", pe.timesheet_stats),
    path("timesheet/export/", pe.timesheet_export),
    path("timesheet/<int:pk>/update/", pe.timesheet_update),
    path("timesheet/<int:pk>/delete/", pe.timesheet_delete),
    path("timesheet/<int:pk>/approve/", pe.timesheet_approve),

    # ---- training（10）----
    path("training/create/", pe.training_create),
    path("training/list/", pe.training_list),
    path("training/<int:pk>/detail/", pe.training_detail),
    path("training/<int:pk>/update/", pe.training_update),
    path("training/<int:pk>/delete/", pe.training_delete),
    path("training/<int:pk>/enroll/", pe.training_enroll),
    path("training/<int:pk>/roster/", pe.training_roster),
    path("training/enroll/<int:pk>/cancel/", pe.training_enroll_cancel),
    path("training/enroll/<int:pk>/checkin/", pe.training_checkin),
    path("training/enroll/<int:pk>/feedback/", pe.training_feedback),

    # ---- recognition（6）----
    path("recognition/create/", pe.recognition_create),
    path("recognition/list/", pe.recognition_list),
    path("recognition/ranking/", pe.recognition_ranking),
    path("recognition/stats/", pe.recognition_stats),
    path("recognition/<int:pk>/like/", pe.recognition_like),
    path("recognition/<int:pk>/delete/", pe.recognition_delete),

    # ---- standup（7）----
    path("standup/create/", pe.standup_create),
    path("standup/list/", pe.standup_list),
    path("standup/today/", pe.standup_today),
    path("standup/summary/", pe.standup_summary),
    path("standup/export/", pe.standup_export),
    path("standup/<int:pk>/update/", pe.standup_update),
    path("standup/<int:pk>/delete/", pe.standup_delete),

    # ---- okr（10）----
    path("okr/objective/create/", pe.okr_objective_create),
    path("okr/objective/list/", pe.okr_objective_list),
    path("okr/objective/<int:pk>/", pe.okr_objective_detail),
    path("okr/objective/<int:pk>/update/", pe.okr_objective_update),
    path("okr/objective/<int:pk>/delete/", pe.okr_objective_delete),
    path("okr/objective/<int:pk>/kr/add/", pe.okr_kr_add),
    path("okr/kr/<int:pk>/progress/", pe.okr_kr_progress),
    path("okr/kr/<int:pk>/delete/", pe.okr_kr_delete),
    path("okr/overview/", pe.okr_overview),
    path("okr/history/", pe.okr_history),

    # ---- decision（7）----
    path("decision/create/", pe.decision_create),
    path("decision/list/", pe.decision_list),
    path("decision/archive/", pe.decision_archive),
    path("decision/<int:pk>/", pe.decision_detail),
    path("decision/<int:pk>/update/", pe.decision_update),
    path("decision/<int:pk>/decide/", pe.decision_decide),
    path("decision/<int:pk>/delete/", pe.decision_delete),

    # ---- todobox（11：9 + F689 重复规则 + F690 四象限）----
    path("todo/create/", pe.todo_create),
    path("todo/list/", pe.todo_list),
    path("todo/batch-complete/", pe.todo_batch_complete),
    path("todo/stats/", pe.todo_stats),
    path("todo/quadrant/", pe.todo_quadrant),
    path("todo/repeat-scan/", pe.todo_repeat_scan),
    path("todo/<int:pk>/update/", pe.todo_update),
    path("todo/<int:pk>/complete/", pe.todo_complete),
    path("todo/<int:pk>/reopen/", pe.todo_reopen),
    path("todo/<int:pk>/delete/", pe.todo_delete),
    path("todo/due-check/", pe.todo_due_check),

    # ---- faq（7）----
    path("faq/create/", k.faq_create),
    path("faq/list/", k.faq_list),
    path("faq/search/", k.faq_search),
    path("faq/stats/", k.faq_stats),
    path("faq/<int:pk>/update/", k.faq_update),
    path("faq/<int:pk>/delete/", k.faq_delete),
    path("faq/<int:pk>/vote/", k.faq_vote),

    # ---- policy（7）----
    path("policy/create/", k.policy_create),
    path("policy/list/", k.policy_list),
    path("policy/<int:pk>/", k.policy_detail),
    path("policy/<int:pk>/update/", k.policy_update),
    path("policy/<int:pk>/ack/", k.policy_ack),
    path("policy/<int:pk>/ack-list/", k.policy_ack_list),
    path("policy/<int:pk>/delete/", k.policy_delete),

    # ---- template（7）----
    path("template/create/", k.template_create),
    path("template/list/", k.template_list),
    path("template/categories/", k.template_categories),
    path("template/<int:pk>/", k.template_detail),
    path("template/<int:pk>/update/", k.template_update),
    path("template/<int:pk>/delete/", k.template_delete),
    path("template/<int:pk>/render/", k.template_render),

    # ---- wiki（11：9 + F687 点赞/收藏）----
    path("wiki/create/", k.wiki_create),
    path("wiki/list/", k.wiki_list),
    path("wiki/search/", k.wiki_search),
    path("wiki/tree/", k.wiki_tree),
    path("wiki/<int:pk>/", k.wiki_detail),
    path("wiki/<int:pk>/update/", k.wiki_update),
    path("wiki/<int:pk>/delete/", k.wiki_delete),
    path("wiki/<int:pk>/revisions/", k.wiki_revisions),
    path("wiki/<int:pk>/move/", k.wiki_move),
    path("wiki/<int:pk>/like/", k.wiki_like),
    path("wiki/<int:pk>/star/", k.wiki_star),

    # ---- minutes（9：7 + F692 行动项 toggle/stats）----
    path("minutes/create/", k.minutes_create),
    path("minutes/list/", k.minutes_list),
    path("minutes/stats/", k.minutes_stats),
    path("minutes/action-items/stats/", k.minutes_action_items_stats),
    path("minutes/<int:pk>/", k.minutes_detail),
    path("minutes/<int:pk>/update/", k.minutes_update),
    path("minutes/<int:pk>/delete/", k.minutes_delete),
    path("minutes/<int:pk>/action-items/", k.minutes_action_items),
    path("minutes/<int:pk>/action-items/toggle/", k.minutes_action_items_toggle),
    path("minutes/<int:pk>/to-todo/", k.minutes_to_todo),

    # ---- formcollect（8）----
    path("form/create/", k.form_create),
    path("form/list/", k.form_list),
    path("form/<int:pk>/", k.form_detail),
    path("form/<int:pk>/update/", k.form_update),
    path("form/<int:pk>/delete/", k.form_delete),
    path("form/<int:pk>/submit/", k.form_submit),
    path("form/<int:pk>/entries/", k.form_entries),
    path("form/<int:pk>/export/", k.form_export),

    # ---- announcement（8）----
    path("announcement/create/", k.announcement_create),
    path("announcement/list/", k.announcement_list),
    path("announcement/<int:pk>/", k.announcement_detail),
    path("announcement/<int:pk>/update/", k.announcement_update),
    path("announcement/<int:pk>/pin/", k.announcement_pin),
    path("announcement/<int:pk>/read/", k.announcement_read),
    path("announcement/<int:pk>/readers/", k.announcement_readers),
    path("announcement/<int:pk>/delete/", k.announcement_delete),

    # ---- poll（9）----
    path("poll/create/", k.poll_create),
    path("poll/list/", k.poll_list),
    path("poll/my-votes/", k.poll_my_votes),
    path("poll/<int:pk>/", k.poll_detail),
    path("poll/<int:pk>/vote/", k.poll_vote),
    path("poll/<int:pk>/results/", k.poll_results),
    path("poll/<int:pk>/close/", k.poll_close),
    path("poll/<int:pk>/reopen/", k.poll_reopen),
    path("poll/<int:pk>/delete/", k.poll_delete),

    # ---- helpdesk（11：9 + F684 满意度评分 + F685 轮询分配）----
    path("ticket/create/", k.ticket_create),
    path("ticket/list/", k.ticket_list),
    path("ticket/stats/", k.ticket_stats),
    path("ticket/auto-assign/", k.ticket_auto_assign),
    path("ticket/<int:pk>/", k.ticket_detail),
    path("ticket/<int:pk>/assign/", k.ticket_assign),
    path("ticket/<int:pk>/reply/", k.ticket_reply),
    path("ticket/<int:pk>/resolve/", k.ticket_resolve),
    path("ticket/<int:pk>/reopen/", k.ticket_reopen),
    path("ticket/<int:pk>/priority/", k.ticket_priority),
    path("ticket/<int:pk>/rate/", k.ticket_rate),

    # ---- calendar（11：9 + F681/F686 冲突预检 + F691 忙闲查询）----
    path("calendar/event/create/", c.calendar_event_create),
    path("calendar/conflict-check/", c.calendar_conflict_check),
    path("calendar/free-busy/", c.calendar_free_busy),
    path("calendar/event/list/", c.calendar_event_list),
    path("calendar/agenda/today/", c.agenda_today),
    path("calendar/agenda/week/", c.agenda_week),
    path("calendar/event/<int:pk>/", c.calendar_event_detail),
    path("calendar/event/<int:pk>/update/", c.calendar_event_update),
    path("calendar/event/<int:pk>/delete/", c.calendar_event_delete),
    path("calendar/event/<int:pk>/rsvp/", c.calendar_event_rsvp),
    path("calendar/event/<int:pk>/attendees/", c.calendar_event_attendees),

    # ---- 文档增强（F45–F47，3）----
    path("annotations/", dc.annotations, name="doc-annotations"),
    path("formula/eval/", dc.formula_eval, name="doc-formula-eval"),
    path("outline-from-note/", dc.outline_from_note, name="doc-outline-from-note"),
]

_count = (1 + 41 + 46 + 73 + 78 + 11 + 3)
assert len(urlpatterns) == 253 == _count, \
    f"officesuite 接口数应为 253（1+41+46+73+78+11+3），实际 {len(urlpatterns)}"
