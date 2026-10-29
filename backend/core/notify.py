"""F04 通知分渠道统一入口：站内 / 邮件 / Webhook + 静默时段。

对外只暴露 dispatch()；站内落库仍复用 core.models.notify()，老调用点无需改动。
外部渠道失败只记日志，绝不影响主流程（无邮件配置时自动只发站内）。
"""
import json
import logging
import urllib.request

from django.utils import timezone

from core.models import NotificationSetting, notify

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


def _send_email(address: str, title: str, content: str) -> None:
    try:
        from django.core.mail import send_mail

        send_mail(title, content or title, None, [address], fail_silently=True)
    except Exception:
        logger.warning("邮件通知发送失败：%s", address)


def _post_webhook(url: str, payload: dict) -> None:
    try:
        if not url.lower().startswith(("http://", "https://")):
            return
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        logger.warning("Webhook 通知发送失败：%s", url)


def dispatch(user, title, content="", category="system", level="info", link="", channels=None):
    """按用户偏好投递通知，返回站内 Notification 或 None。

    channels 显式传入时以其为准；否则读 NotificationSetting.channels（默认站内）。
    静默时段内只落库不推送外渠。分类被关闭时不产生任何通知。
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
    return notif
