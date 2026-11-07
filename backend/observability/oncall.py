# -*- coding: utf-8 -*-
"""可观测性中心 · 值班排班与升级的纯函数实现。

为什么单独成模块
----------------
「当前谁值班」由「开始时间 + 轮换周期 + 成员顺序」确定性推导，不需要把
每一班都落库。单独成模块的好处是这些推导可以被值班表详情、当前值班、
未来排班、升级检查四个接口共用，且全部是纯函数（传入 now），测试不需要
mock 时钟。

时区
----
值班表带 ``timezone_name`` 字段，但本平台所有时间都以 UTC 存储、以
timezone.now() 读取；时区字段只作为「排班时区」的展示与人工核对依据。
这里不引入 zoneinfo 依赖（Python 3.13 自带，但项目约束不新增依赖行为），
按 UTC 边界对齐足以满足「按日/按周轮换」的语义。
"""
from datetime import timedelta

from django.utils import timezone

# 轮换周期 → 时长（天）
ROTATION_DAYS = {"daily": 1, "weekly": 7}

# 未来排班默认返回的班次数
DEFAULT_UPCOMING = 5

# 最多一次推导的班次数（防止请求超大 count 把进程拖死）
MAX_SHIFTS = 50


def rotation_days(schedule):
    """取轮换周期天数；未知周期按周处理（保守：班次更长、不会频繁骚扰）。"""
    return ROTATION_DAYS.get(schedule.rotation, 7)


def members_of(schedule):
    """成员列表标准化：去掉空白项，保证轮换不被空字符串打乱。"""
    raw = schedule.members or []
    if not isinstance(raw, list):
        return []
    return [str(m).strip() for m in raw if str(m).strip()]


def is_active_at(schedule, at):
    """值班表在指定时刻是否生效（考虑 active_from / active_until）。"""
    if schedule.status != "active":
        return False
    if schedule.active_from and at < schedule.active_from:
        return False
    if schedule.active_until and at >= schedule.active_until:
        return False
    return True


def current_shift(schedule, now=None):
    """推导当前班次：返回 {member, shift_start, shift_end, index, rotation}。

    尚未开始（now < start_at）或已过生效区间时返回 None，前端据此显示
    「未排班」而不是随便挑一个人顶班。
    """
    now = now or timezone.now()
    members = members_of(schedule)
    if not members:
        return None
    if now < schedule.start_at:
        return None
    if not is_active_at(schedule, now):
        return None
    period = timedelta(days=rotation_days(schedule))
    elapsed = now - schedule.start_at
    index = int(elapsed.total_seconds() // period.total_seconds())
    shift_start = schedule.start_at + period * index
    shift_end = shift_start + period
    if schedule.active_until and shift_end > schedule.active_until:
        shift_end = schedule.active_until
    return {
        "member": members[index % len(members)],
        "shift_start": timezone.localtime(shift_start).isoformat(),
        "shift_end": timezone.localtime(shift_end).isoformat(),
        "index": index,
        "rotation": schedule.rotation,
        "team": schedule.team,
        "schedule_id": schedule.id,
        "schedule_name": schedule.name,
        "timezone": schedule.timezone_name,
    }


def next_shifts(schedule, count=DEFAULT_UPCOMING, now=None):
    """未来 count 个班次（含当前班次之后），用于「未来排班」与交接单。

    与 current_shift 用同一套推导，避免出现「当前值班人不在未来排班里」
    这种自相矛盾的结果。
    """
    now = now or timezone.now()
    count = max(min(int(count or DEFAULT_UPCOMING), MAX_SHIFTS), 1)
    members = members_of(schedule)
    if not members:
        return []
    period = timedelta(days=rotation_days(schedule))
    start = schedule.start_at
    if now > start:
        elapsed = now - start
        index = int(elapsed.total_seconds() // period.total_seconds())
    else:
        index = 0
    out = []
    for offset in range(count):
        current_index = index + offset
        shift_start = start + period * current_index
        shift_end = shift_start + period
        if schedule.active_until and shift_start >= schedule.active_until:
            break
        if schedule.active_from and shift_end <= schedule.active_from:
            continue
        out.append({
            "schedule_id": schedule.id,
            "team": schedule.team,
            "member": members[current_index % len(members)],
            "shift_start": timezone.localtime(shift_start).isoformat(),
            "shift_end": timezone.localtime(shift_end).isoformat(),
            "index": current_index,
            "is_current": offset == 0 and shift_start <= now < shift_end,
        })
    return out


def shift_at(schedule, at):
    """任意时刻的班次（用于「某时间谁值班」反查）。"""
    return current_shift(schedule, now=at)


def swap_shift(schedule, at, to_member):
    """换班：把 at 所在的那一班换成 to_member。

    实现方式是直接改写 members 中对应位置的成员，而不是引入「替班表」：
    值班表本身就是「顺序轮换」的声明式配置，替班只要改一个人名即可，
    额外建表会让「当前谁值班」需要同时看两张表，反而更容易出错。
    """
    members = members_of(schedule)
    if not members:
        raise ValueError("值班表没有配置成员，无法换班")
    target = str(to_member or "").strip()
    if not target:
        raise ValueError("缺少必填参数: to_member")
    shift = current_shift(schedule, now=at)
    if shift is None:
        raise ValueError("该时刻没有生效的值班班次，无法换班")
    position = shift["index"] % len(members)
    original = members[position]
    if original == target:
        raise ValueError("换班目标与当前值班人相同")
    members[position] = target
    schedule.members = members
    schedule.save(update_fields=["members", "updated_at"])
    return {"position": position, "from": original, "to": target,
            "shift_start": shift["shift_start"], "shift_end": shift["shift_end"]}


def team_current(team, now=None):
    """团队当前值班：一个团队可能有多张值班表（例如主备），全部返回。"""
    from observability.models import OnCallSchedule

    now = now or timezone.now()
    rows = []
    for schedule in OnCallSchedule.objects.filter(team=team, status="active"):
        shift = current_shift(schedule, now=now)
        if shift:
            rows.append(shift)
    return rows


def coverage_gap(schedule, now=None, days=7):
    """覆盖率检查：未来 N 天是否存在空档（成员为空或已过生效期）。

    返回 gaps 列表，前端在值班表卡片上打红点；空列表表示覆盖完整。
    """
    now = now or timezone.now()
    shifts = next_shifts(schedule, count=min(days * (2 if schedule.rotation == "daily" else 1),
                                             MAX_SHIFTS), now=now)
    if not members_of(schedule):
        return [{"reason": "值班表未配置成员", "shift_start": None, "shift_end": None}]
    if not shifts:
        return [{"reason": "值班表已超出生效区间", "shift_start": None, "shift_end": None}]
    horizon_end = now + timedelta(days=days)
    last_end = shifts[-1]["shift_end"]
    if last_end < horizon_end.isoformat():
        return [{"reason": f"未来 {days} 天排班不完整", "shift_start": last_end,
                 "shift_end": horizon_end.isoformat()}]
    return []


def escalation_timeline(policies, elapsed_minutes, now=None):
    """按升级策略推导「现在应该通知到第几级」。

    ``delay_minutes`` 是相对上一级的等待时间，所以每一级的绝对触发时刻
    是前面所有延迟的累加；返回每级的状态（notified/pending）与当前级别。
    """
    now = now or timezone.now()
    policies = sorted(policies, key=lambda p: (p.level, p.order))
    timeline = []
    cumulative = 0
    current_level = None
    for policy in policies:
        cumulative += max(int(policy.delay_minutes or 0), 0)
        due = elapsed_minutes >= cumulative
        if due:
            current_level = policy.level
        timeline.append({
            "policy_id": policy.id,
            "level": policy.level,
            "delay_minutes": policy.delay_minutes,
            "due_at_minutes": cumulative,
            "status": "notified" if due else "pending",
            "target_name": policy.target_name,
            "channels": policy.channels or [],
        })
    return {
        "elapsed_minutes": elapsed_minutes,
        "current_level": current_level,
        "levels": timeline,
        "escalate": current_level is not None,
        "generated_at": timezone.localtime(now).isoformat(),
    }
