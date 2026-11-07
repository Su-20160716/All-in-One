# -*- coding: utf-8 -*-
"""内部控制接口：CRUD + 启停 + 测试定义 CRUD + 执行测试 + 结果历史。

执行测试在本平台是「记录一次执行结论」而不是真的去跑脚本：
治理场景要的是可追溯的测试证据（谁、何时、什么结果、耗时多少），
真实执行器属于各技术团队自己的 CI。执行时一次性更新三处状态：
测试定义的 last_result/last_run_at、控制的上次测试时间、控制有效性，
三处必须同成同败，因此统一包在 transaction.atomic() 内。
"""
from django.db import transaction
from django.utils import timezone

from devtools.common import endpoint, ok

from governance import services
from governance.models import (
    CONTROL_FREQUENCIES,
    CONTROL_STATUS,
    TEST_METHODS,
    TEST_RESULTS,
    Control,
    ControlTest,
    ControlTestRun,
)
from governance.views_common import (
    apply_search,
    filter_choice,
    filter_int,
    get_control,
    get_control_test,
    paginate,
    param_bool,
    param_choice,
    param_int,
    param_list,
    param_str,
    param_text,
    scoped,
)

CONTROL_SEARCH_FIELDS = ("code", "name", "description", "category", "owner_name")
CONTROL_TEST_SEARCH_FIELDS = ("name", "pass_criteria")


@endpoint(("GET",))
def control_list(request):
    """控制列表：q/status/category/frequency/automated 过滤。"""
    qs = scoped(Control, request.user)
    qs = apply_search(qs, request, CONTROL_SEARCH_FIELDS)
    category = param_str(request, "category", max_len=60)
    if category:
        qs = qs.filter(category=category)
    qs = filter_choice(qs, request, "frequency", CONTROL_FREQUENCIES)
    if request.query_params.get("automated") not in (None, ""):
        qs = qs.filter(automated=str(request.query_params.get("automated")).lower()
                       in ("1", "true", "yes", "on"))
    return paginate(qs.order_by("-created_at"), request)


@endpoint()
def control_create(request):
    """新建控制（编码唯一，有效性初始为 0）。"""
    code = param_str(request, "code", required=True, max_len=60)
    name = param_str(request, "name", required=True, max_len=200)
    if Control.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("该控制编码已存在")
    control = Control.objects.create(
        owner=request.user,
        code=code,
        name=name,
        description=param_text(request, "description"),
        category=param_str(request, "category", default="通用", max_len=60),
        owner_name=param_str(request, "owner_name", max_len=80),
        frequency=param_choice(request, "frequency", CONTROL_FREQUENCIES, default="quarterly"),
        automated=bool(param_bool(request, "automated", False)),
        status=param_choice(request, "status", CONTROL_STATUS, default="active"),
    )
    return ok(control.to_dict())


@endpoint(("GET",))
def control_detail(request, pk):
    """控制详情：含测试定义、最近执行与有效性明细。"""
    control = get_control(pk, request.user)
    data = control.to_dict()
    stats = services.control_effectiveness(control)
    data["effectiveness_detail"] = stats
    tests = list(control.tests.all())
    data["tests"] = [test.to_dict() for test in tests]
    recent_runs = ControlTestRun.objects.filter(test__control=control).order_by("-run_at")[:10]
    data["recent_runs"] = [run.to_dict() for run in recent_runs]
    data["mapped_framework_controls"] = [
        {"id": m.framework_control_id,
         "code": m.framework_control.code,
         "title": m.framework_control.title}
        for m in control.framework_mappings.select_related("framework_control")
    ]
    return ok(data)


@endpoint()
def control_update(request, pk):
    """更新控制基础字段（编码冲突拒绝）。"""
    control = get_control(pk, request.user, write=True)
    code = param_str(request, "code", default=control.code, max_len=60)
    if code != control.code and Control.objects.filter(owner=control.owner, code=code).exists():
        raise ValueError("该控制编码已存在")
    control.code = code
    control.name = param_str(request, "name", default=control.name, max_len=200)
    control.description = param_text(request, "description", default=control.description)
    control.category = param_str(request, "category", default=control.category, max_len=60)
    control.owner_name = param_str(request, "owner_name", default=control.owner_name, max_len=80)
    control.frequency = param_choice(request, "frequency", CONTROL_FREQUENCIES,
                                     default=control.frequency)
    request_bool = str(request.data.get("automated", "")).lower() in ("1", "true", "yes", "on") \
        if hasattr(request, "data") else False
    if "automated" in (request.data if hasattr(request, "data") else {}):
        control.automated = request_bool
    control.save()
    return ok(control.to_dict())


@endpoint()
def control_delete(request, pk):
    """删除控制（测试与执行历史级联删除，条款映射一并解除）。"""
    control = get_control(pk, request.user, write=True)
    with transaction.atomic():
        control.assessment_items.update(control=None)
        control.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def control_toggle(request, pk):
    """启停控制：active ↔ inactive（幂等：重复调用仍返回当前状态）。"""
    control = get_control(pk, request.user, write=True)
    target = param_str(request, "status", max_len=20)
    if target and target not in CONTROL_STATUS:
        raise ValueError("状态必须是 active/inactive 之一")
    control.status = target or ("inactive" if control.status == "active" else "active")
    control.save(update_fields=["status", "updated_at"])
    return ok(control.to_dict())


@endpoint(("GET",))
def control_test_list(request):
    """控制测试列表（可按 control_id/method/status 过滤）。"""
    qs = scoped(ControlTest, request.user)
    qs = apply_search(qs, request, CONTROL_TEST_SEARCH_FIELDS, status_field="last_result")
    qs = filter_int(qs, request, "control_id", "control_id")
    qs = filter_choice(qs, request, "method", TEST_METHODS)
    return paginate(qs.select_related("control").order_by("-created_at"), request)


@endpoint()
def control_test_create(request):
    """新增控制测试定义（步骤为字符串数组）。"""
    control_id = param_int(request, "control_id", required=True, minimum=1)
    control = get_control(control_id, request.user, write=True)
    test = ControlTest.objects.create(
        owner=request.user,
        control=control,
        name=param_str(request, "name", required=True, max_len=200),
        method=param_choice(request, "method", TEST_METHODS, default="manual"),
        steps=param_list(request, "steps"),
        pass_criteria=param_text(request, "pass_criteria"),
    )
    return ok(test.to_dict())


@endpoint(("GET",))
def control_test_detail(request, pk):
    """测试详情：含最近 20 次执行记录。"""
    test = get_control_test(pk, request.user)
    data = test.to_dict()
    data["runs"] = [run.to_dict() for run in test.runs.all()[:20]]
    return ok(data)


@endpoint()
def control_test_update(request, pk):
    """更新测试定义（方法/步骤/通过条件）。"""
    test = get_control_test(pk, request.user, write=True)
    test.name = param_str(request, "name", default=test.name, max_len=200)
    test.method = param_choice(request, "method", TEST_METHODS, default=test.method)
    test.steps = param_list(request, "steps") or test.steps
    test.pass_criteria = param_text(request, "pass_criteria", default=test.pass_criteria)
    test.save()
    return ok(test.to_dict())


@endpoint()
def control_test_delete(request, pk):
    """删除测试定义（历史执行记录随测试删除）。"""
    test = get_control_test(pk, request.user, write=True)
    with transaction.atomic():
        test.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def control_test_run(request, pk):
    """执行测试：写入执行记录并同步测试/控制/有效性三处状态。"""
    test = get_control_test(pk, request.user, write=True)
    result = param_choice(request, "result", TEST_RESULTS, default="unknown")
    duration = param_int(request, "duration_ms", default=0, minimum=0, maximum=86400000)
    note = param_text(request, "note", max_len=2000)
    runner = param_str(request, "runner_name",
                       default=getattr(request.user, "display_name", "") or
                       getattr(request.user, "username", ""), max_len=80)
    now = timezone.now()
    with transaction.atomic():
        run = ControlTestRun.objects.create(
            owner=request.user,
            test=test,
            result=result,
            note=note,
            runner_name=runner,
            duration_ms=duration,
            run_at=now,
        )
        test.last_result = result
        test.last_run_at = now
        test.save(update_fields=["last_result", "last_run_at", "updated_at"])
        control = test.control
        control.last_tested_at = now
        control.save(update_fields=["last_tested_at", "updated_at"])
        stats = services.refresh_control_effectiveness(control)
    return ok({"run": run.to_dict(), "test": test.to_dict(),
               "control_effectiveness": stats["effectiveness"]})


@endpoint(("GET",))
def control_test_history(request, pk):
    """测试结果历史（倒序分页，可按 result 过滤）。"""
    test = get_control_test(pk, request.user)
    qs = test.runs.all().order_by("-run_at")
    qs = filter_choice(qs, request, "result", TEST_RESULTS)
    return paginate(qs, request)


@endpoint(("GET",))
def control_gaps(request):
    """控制差距：久未测试 / 停用仍被映射 / 有效性过低。"""
    return ok(services.control_gaps(request.user))
