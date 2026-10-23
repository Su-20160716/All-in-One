# -*- coding: utf-8 -*-
"""站点设置的缓存收口（S2-B1）。

公开设置（`/api/core/settings/public/`）是**每个页面加载都会请求**的
高频接口，但配置本身低频变更——用短 TTL 缓存挡掉重复查询，管理员
保存时主动失效，保证改完立刻生效。

缓存键单一（`site_settings:public`），失效粒度是整个公开设置字典：
配置项总共个位数，全量失效的实现成本远低于逐键失效，且避免漏清。
"""
from django.core.cache import cache

# 与 settings.CACHES 的 TIMEOUT 保持一致（300s）
CACHE_KEY = "site_settings:public"
CACHE_TTL = 300


def get_public_settings(loader):
    """带缓存的公开设置读取。

    :param loader: 无参函数，真正查库返回 {key: value} 字典（缓存未命中时调用）
    :returns: {key: value}
    """
    data = cache.get(CACHE_KEY)
    if data is None:
        data = loader() or {}
        cache.set(CACHE_KEY, data, CACHE_TTL)
    return data


def invalidate_public_settings():
    """管理员保存设置后调用——立即失效，下次读取回源。"""
    cache.delete(CACHE_KEY)
