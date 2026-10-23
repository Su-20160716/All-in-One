# -*- coding: utf-8 -*-
"""S2-B1：存量分享明文密码批量转 hash。

0006 只改了字段长度；本迁移把库里已有的明文 password 逐条
make_password。重复执行安全：已是 hash 格式（含 `$` 分隔且以
算法名开头）的条目跳过。
"""
from django.contrib.auth.hashers import make_password
from django.db import migrations

# Django password hash 的统一格式：<algorithm>$...$...$...
# 明文密码（演示数据）几乎不可能长这样，以此区分存量明文与已 hash 数据


def _is_hashed(value: str) -> bool:
    return bool(value) and value.count("$") >= 2 and "=" not in value[:20]


def hash_plaintext(apps, schema_editor):
    ShareLink = apps.get_model("files", "ShareLink")
    converted = 0
    for link in ShareLink.objects.exclude(password="").only("id", "password"):
        if _is_hashed(link.password):
            continue
        ShareLink.objects.filter(pk=link.pk).update(
            password=make_password(link.password[:64])
        )
        converted += 1
    if converted:
        print(f"[0007] 已转换 {converted} 条存量明文分享密码为 hash")


def noop(apps, schema_editor):
    """反向迁移不还原（hash 不可逆）——回滚后旧链接密码需用户重设。"""


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0006_alter_sharelink_password"),
    ]

    operations = [
        migrations.RunPython(hash_plaintext, noop),
    ]
