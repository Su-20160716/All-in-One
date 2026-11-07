"""F04 通知分渠道统一入口：站内 / 邮件 / Webhook + 静默时段。

对外只暴露 dispatch()；站内落库仍复用 core.models.notify()，老调用点无需改动。
外部渠道失败只记日志，绝不影响主流程（无邮件配置时自动只发站内）。
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from django.utils import timezone

from core.models import NotificationSetting, notify
from core.net_guard import NO_REDIRECT_OPENER, is_safe_outbound_url

logger = logging.getLogger(__name__)

VALID_CHANNELS = ("inapp", "email", "webhook")


def _setting_for(user, category):
    return NotificationSetting.objects.filter(user=user, category=category).first()


def _channel_setting(user, category):
    """渠道/静默配置按分类优先，未单独配置时回落到 system 行。"""
    setting = _setting_for(user, category)
    if setting is not None and (setting.channels or setting.webhook_url):
        return setting
    if category != "system":
        fallback = _setting_for(user, "system")
        if fallback is not None:
            return fallback
    return setting


def _in_quiet_hours(setting) -> bool:
    if setting is None or setting.quiet_start is None or setting.quiet_end is None:
        return False
    now = timezone.localtime().time()
    if setting.quiet_start <= setting.quiet_end:
        return setting.quiet_start <= now <= setting.quiet_end
    return now >= setting.quiet_start or now <= setting.quiet_end


def _window_state(start, end, now):
    """某日时间窗口相对 now 的状态：(是否命中, 窗口开始, 窗口结束)

    未命中时返回 now 之后最近的一次窗口（用于预告「下次可打扰时间」）。
    """
    today = now.date()

    def _at(day, t):
        return timezone.make_aware(datetime.combine(day, t))

    windows = []
    for offset in (-1, 0, 1):
        day = today + timedelta(days=offset)
        begin = _at(day, start)
        # 跨午夜（如 22:00 ~ 08:00）窗口结束顺延到次日
        finish = _at(day, end) if start <= end else _at(day + timedelta(days=1), end)
        windows.append((begin, finish))
    for begin, finish in windows:
        if begin <= now <= finish:
            return True, begin, finish
    upcoming = [(b, f) for b, f in windows if b > now]
    if not upcoming:
        return False, None, None
    begin, finish = min(upcoming, key=lambda x: x[0])
    return False, begin, finish


def quiet_state(user, category="system", now=None):
    """#338 静默预览：按 dispatch 的规则实时算出「当前是否静默 / 下次可打扰时间」

    与 dispatch/_in_quiet_hours 同源（分类优先，未单独配置回落 system 行），
    另把 User.dnd_start/dnd_end（notify 用来抑制即时推送的时段）一并纳入判定，
    这样设置页预览与用户真实感受一致。
    """
    now = now or timezone.localtime()
    setting = _channel_setting(user, category)
    windows = []
    if setting is not None and setting.quiet_start and setting.quiet_end:
        windows.append(("setting", setting.quiet_start, setting.quiet_end))
    dnd_start = getattr(user, "dnd_start", None)
    dnd_end = getattr(user, "dnd_end", None)
    if dnd_start and dnd_end:
        windows.append(("dnd", dnd_start, dnd_end))

    active, upcoming = [], []
    for source, start, end in windows:
        hit, begin, finish = _window_state(start, end, now)
        if hit:
            active.append((source, begin, finish))
        elif begin is not None:
            upcoming.append((source, begin, finish))

    state = {
        "currently_quiet": bool(active),
        "next_quiet_end": None,
        "next_quiet_start": None,
        "quiet_source": "",
        "quiet_hint": "当前不会被静音",
    }
    if active:
        source, _, finish = max(active, key=lambda x: x[2])
        state["quiet_source"] = source
        state["next_quiet_end"] = finish.isoformat()
        state["quiet_hint"] = f"当前静默中，{timezone.localtime(finish).strftime('%H:%M')} 后恢复打扰"
    elif upcoming:
        source, begin, finish = min(upcoming, key=lambda x: x[1])
        state["quiet_source"] = source
        state["next_quiet_start"] = begin.isoformat()
        state["next_quiet_end"] = finish.isoformat()
        state["quiet_hint"] = f"下次静默 {timezone.localtime(begin).strftime('%H:%M')} 开始"
    return state


def _send_email(address: str, title: str, content: str) -> None:
    try:
        from django.core.mail import send_mail

        send_mail(title, content or title, None, [address], fail_silently=True)
    except Exception:
        logger.warning("邮件通知发送失败：%s", address)


def _post_webhook(url: str, payload: dict) -> None:
    try:
        from core.net_guard import NO_REDIRECT_OPENER, is_safe_outbound_url

        if not is_safe_outbound_url(url):
            logger.warning("Webhook 地址被安全策略拒绝：%s", url)
            return
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        NO_REDIRECT_OPENER.open(req, timeout=3).read()
    except Exception:
        logger.warning("Webhook 通知发送失败：%s", url)


# ---------------------------------------------------------------------------
# #411–#413 事件级 Webhook 订阅：签名 / 单次投递 / 指数退避重试 / 投递记录
#
# 兼容铁律：
# - `_post_webhook(url, payload)` 的签名与「失败只记日志、绝不抛异常」的行为保持不变；
# - 下面的订阅投递全部包在 try/except 内，任何异常都不会影响站内通知；
# - 总耗时受 WEBHOOK_DISPATCH_BUDGET 约束（同步投递，不能把请求拖死）。
# ---------------------------------------------------------------------------
WEBHOOK_TIMEOUT = 3                 # 单次请求超时（秒）
WEBHOOK_MAX_ATTEMPTS = 3            # 单条投递最多尝试次数（含首次）
WEBHOOK_BACKOFF = (0.0, 0.5, 1.0)   # 指数退避：第 2 次 0.5s、第 3 次 1.0s
WEBHOOK_DELIVERY_BUDGET = 5.0       # 单条投递总耗时上限（秒，含重试与退避）
WEBHOOK_DISPATCH_BUDGET = 8.0       # 一次 dispatch 内所有订阅的投递总预算（秒）
WEBHOOK_MAX_SUBSCRIPTIONS = 20      # 单用户单事件最多投递的订阅数
WEBHOOK_SIGNATURE_HEADER = "X-Webhook-Signature"
WEBHOOK_TIMESTAMP_HEADER = "X-Webhook-Timestamp"
WEBHOOK_ID_HEADER = "X-Webhook-Id"


def sign_payload(secret: str, timestamp, body) -> str:
    """#413 计算签名：``sha256=hex(hmac_sha256(secret, str(timestamp) + raw_body))``

    timestamp 为 Unix 秒（字符串或整数），body 为实际发送的字节 / 字符串。
    接收方用同一公式重算并做常量时间比较即可验真；配合时间戳窗口可防重放。
    """
    import hashlib
    import hmac

    raw = body.encode("utf-8") if isinstance(body, str) else (body or b"")
    mac = hmac.new(
        (secret or "").encode("utf-8"), str(timestamp).encode("utf-8") + raw, hashlib.sha256
    )
    return "sha256=" + mac.hexdigest()


def webhook_headers(secret: str, timestamp, delivery_id: str) -> dict:
    """构造投递头（无 secret 时不带签名头，兼容不验签的接收方）"""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "qoder-webhook/1",
        WEBHOOK_TIMESTAMP_HEADER: str(timestamp),
        WEBHOOK_ID_HEADER: str(delivery_id or ""),
    }
    return headers


def _webhook_attempt(url: str, body: bytes, secret: str, delivery_id: str, timeout: int):
    """单次 HTTP 投递，返回 {ok,status,latency_ms,error,response}，绝不抛异常"""
    import time as _time

    result = {"ok": False, "status": None, "latency_ms": 0, "error": "", "response": ""}
    started = _time.perf_counter()
    try:
        timestamp = int(_time.time())
        req = urllib.request.Request(
            url,
            data=body,
            headers=webhook_headers(secret, timestamp, delivery_id),
            method="POST",
        )
        if secret:
            req.add_header(WEBHOOK_SIGNATURE_HEADER, sign_payload(secret, timestamp, body))
        try:
            with NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
                result["status"] = getattr(resp, "status", None) or resp.getcode()
                result["response"] = resp.read(2048).decode("utf-8", "replace")[:200]
        except urllib.error.HTTPError as exc:  # 4xx/5xx 也是有效响应，照样记录
            result["status"] = exc.code
            try:
                result["response"] = exc.read(2048).decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                result["response"] = ""
        result["ok"] = bool(result["status"] and 200 <= result["status"] < 300)
        if not result["ok"]:
            result["error"] = f"HTTP {result['status']}"
    except Exception as exc:  # noqa: BLE001 — 超时/DNS/连接失败都算投递失败
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    result["latency_ms"] = int((_time.perf_counter() - started) * 1000)
    return result


def _post_with_retry(url: str, body: bytes, secret: str, delivery_id: str, deadline=None) -> dict:
    """#412 指数退避重试（最多 WEBHOOK_MAX_ATTEMPTS 次），总耗时受 deadline 约束"""
    import time as _time

    result = {"ok": False, "status": None, "latency_ms": 0, "error": "未投递", "attempts": 0}
    if not is_safe_outbound_url(url):
        result["error"] = "地址被安全策略拒绝（仅允许公网 http/https）"
        return result
    now = _time.monotonic()
    local_deadline = now + WEBHOOK_DELIVERY_BUDGET
    if deadline is not None:
        local_deadline = min(local_deadline, deadline)
    for attempt in range(WEBHOOK_MAX_ATTEMPTS):
        if attempt:
            pause = WEBHOOK_BACKOFF[min(attempt, len(WEBHOOK_BACKOFF) - 1)]
            if _time.monotonic() + pause >= local_deadline:
                break
            _time.sleep(pause)
        if _time.monotonic() >= local_deadline:
            break
        timeout = max(1, min(WEBHOOK_TIMEOUT, int(local_deadline - _time.monotonic()) or 1))
        one = _webhook_attempt(url, body, secret, delivery_id, timeout)
        result.update({k: one[k] for k in ("ok", "status", "latency_ms", "error")})
        result["attempts"] = attempt + 1
        if one["ok"]:
            break
    return result


def _delivery_item(delivery) -> dict:
    """投递记录的对外结构（列表 / 重试接口共用）"""
    sub = getattr(delivery, "subscription", None)
    return {
        "id": delivery.id,
        "subscription_id": delivery.subscription_id,
        "url": getattr(sub, "url", "") or "",
        "event": delivery.event,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "response_code": delivery.response_code,
        "latency_ms": delivery.latency_ms,
        "error": delivery.error,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else "",
    }


def run_delivery(delivery, deadline=None) -> dict:
    """对一条 WebhookDelivery 执行（或重试）投递并回写结果，绝不抛异常"""
    from core.models import WebhookDelivery

    try:
        sub = delivery.subscription
        payload = delivery.payload if isinstance(delivery.payload, dict) else {}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        result = _post_with_retry(
            sub.url, body, sub.secret, f"whd_{delivery.id}", deadline=deadline
        )
        delivery.status = "success" if result["ok"] else "failed"
        delivery.attempts = result["attempts"]
        delivery.response_code = result["status"]
        delivery.latency_ms = result["latency_ms"]
        delivery.error = "" if result["ok"] else (result["error"] or "投递失败")[:500]
        delivery.save(
            update_fields=["status", "attempts", "response_code", "latency_ms", "error"]
        )
        if not result["ok"]:
            logger.warning("Webhook 投递失败 sub=%s url=%s %s", sub.id, sub.url, delivery.error)
        return _delivery_item(delivery)
    except Exception:  # noqa: BLE001 —— 投递链路异常绝不外抛
        logger.exception("Webhook 投递异常 delivery=%s", getattr(delivery, "id", "-"))
        try:
            WebhookDelivery.objects.filter(pk=delivery.pk).update(
                status="failed", error="投递异常（详见服务端日志）"
            )
        except Exception:  # noqa: BLE001
            pass
        return _delivery_item(delivery)


def deliver_event(subscription, event: str, payload: dict, deadline=None):
    """#411/#412 给一条订阅落一条投递记录并同步投递"""
    from core.models import WebhookDelivery

    delivery = WebhookDelivery.objects.create(
        subscription=subscription, event=(event or "")[:64], payload=payload, status="pending"
    )
    return run_delivery(delivery, deadline=deadline)


def deliver_subscriptions(user, event: str, payload: dict) -> list:
    """按事件把载荷投递给该用户所有匹配的订阅；任何失败都不外抛"""
    import time as _time

    out = []
    try:
        from core.models import WebhookSubscription

        subs = list(
            WebhookSubscription.objects.filter(owner=user, active=True)[:WEBHOOK_MAX_SUBSCRIPTIONS]
        )
        if not subs:
            return out
        deadline = _time.monotonic() + WEBHOOK_DISPATCH_BUDGET
        for sub in subs:
            if not sub.matches(event):
                continue
            if _time.monotonic() >= deadline:
                logger.warning("Webhook 投递预算耗尽，跳过剩余订阅 user=%s", getattr(user, "id", "-"))
                break
            try:
                out.append(deliver_event(sub, event, payload, deadline=deadline))
            except Exception:  # noqa: BLE001 —— 单条订阅失败不影响其它订阅
                logger.exception("Webhook 订阅投递失败 sub=%s", sub.id)
    except Exception:  # noqa: BLE001 —— 订阅查询失败也不能影响站内通知
        logger.exception("Webhook 订阅投递链路异常")
    return out


def send_signed_webhook(url: str, payload: dict, secret: str = "", timeout: int = 5) -> dict:
    """#413 自测用：带签名发一条载荷，返回状态码 / 耗时 / 响应片段"""
    import time as _time

    if not is_safe_outbound_url(url):
        return {"ok": False, "status": None, "latency_ms": 0,
                "error": "地址被安全策略拒绝（仅允许公网 http/https）", "response": ""}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _webhook_attempt(url, body, secret or "", f"test_{int(_time.time())}", timeout)


# #339 Webhook 自检的样例载荷（与 dispatch 真实载荷同结构）
SAMPLE_WEBHOOK_PAYLOAD = {
    "title": "Webhook 自检",
    "content": "这是一条来自通知中心的测试消息，收到即表示地址与网络可达。",
    "category": "system",
    "level": "info",
    "link": "/dashboard",
    "user": "self-test",
    "test": True,
}


def send_test_webhook(url: str, payload: dict = None, timeout: int = 5) -> dict:
    """#339 发一条样例载荷并回报状态码 / 耗时 / 响应前 200 字

    与 _post_webhook 使用同一套 SSRF 校验与「不跟随重定向」的 opener，
    失败不抛异常，全部落到返回值里供设置页展示。
    """
    import time as _time
    from urllib.parse import urlparse

    body_data = payload if isinstance(payload, dict) else SAMPLE_WEBHOOK_PAYLOAD
    body_data = {**SAMPLE_WEBHOOK_PAYLOAD, **body_data}
    started = _time.perf_counter()
    result = {
        "ok": False, "status": None, "elapsed_ms": 0, "response": "",
        "error": "", "url_host": "", "blocked_reason": "",
    }
    if not url:
        result["error"] = "未配置 Webhook 地址"
        result["blocked_reason"] = "missing_url"
        return result
    if not is_safe_outbound_url(url):
        result["error"] = "Webhook 地址被安全策略拒绝（仅允许公网 http/https）"
        result["blocked_reason"] = "unsafe_url"
        result["elapsed_ms"] = int((_time.perf_counter() - started) * 1000)
        return result
    result["url_host"] = urlparse(url).hostname or ""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body_data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "qoder-notify-self-test"},
            method="POST",
        )
        try:
            with NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
                result["status"] = getattr(resp, "status", None) or resp.getcode()
                result["response"] = resp.read(4096).decode("utf-8", "replace")[:200]
        except urllib.error.HTTPError as exc:  # 4xx/5xx 也是有效结果，读出响应体
            result["status"] = exc.code
            try:
                result["response"] = exc.read(4096).decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                result["response"] = ""
            result["error"] = f"HTTP {exc.code}"
        result["ok"] = bool(result["status"] and 200 <= result["status"] < 300)
    except Exception as exc:  # noqa: BLE001 — 超时/DNS/连接失败都算自检失败
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_ms"] = int((_time.perf_counter() - started) * 1000)
    return result


def dispatch(user, title, content="", category="system", level="info", link="", channels=None,
             event=""):
    """按用户偏好投递通知，返回站内 Notification 或 None。

    channels 显式传入时以其为准；否则读 NotificationSetting.channels（默认站内）。
    静默时段内只落库不推送外渠。分类被关闭时不产生任何通知。

    #411 事件订阅：除旧版单地址 webhook 外，还会按事件匹配 WebhookSubscription
    逐条投递（投递结果落 WebhookDelivery，失败不影响站内通知）。
    ``event`` 为可选的显式事件名（如 ``file.uploaded``），缺省用
    ``notification.<category>``。
    """
    if user is None:
        return None
    setting = _setting_for(user, category)
    if setting is not None and not setting.enabled:
        return None

    channel_setting = _channel_setting(user, category)
    wanted = channels if channels is not None else (
        channel_setting.channels if channel_setting and channel_setting.channels else ["inapp"]
    )
    wanted = [c for c in wanted if c in VALID_CHANNELS]

    notif = notify(user, title, content, category=category, level=level, link=link) if "inapp" in wanted else None
    if _in_quiet_hours(channel_setting):
        return notif

    if "email" in wanted and getattr(user, "email", ""):
        _send_email(user.email, title, content)
    if "webhook" in wanted and channel_setting is not None and channel_setting.webhook_url:
        _post_webhook(
            channel_setting.webhook_url,
            {"title": title, "content": content, "category": category,
             "level": level, "link": link, "user": user.get_username()},
        )
    # #411 事件级订阅（与上面的单地址 webhook 独立，互不影响）
    event_name = (event or "").strip() or f"notification.{category}"
    try:
        deliver_subscriptions(
            user,
            event_name,
            {
                "event": event_name,
                "title": title,
                "content": content,
                "category": category,
                "level": level,
                "link": link,
                "user": user.get_username(),
                "timestamp": timezone.now().isoformat(),
            },
        )
    except Exception:  # noqa: BLE001 —— 投递链路绝不能阻塞站内通知
        logger.exception("Webhook 订阅事件投递异常")
    return notif
