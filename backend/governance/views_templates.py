# -*- coding: utf-8 -*-
"""内置条款库接口：预览模板、按模板建框架、向已有框架补齐条款。

设计要点
--------
- 模板是「初始数据」而不是「绑定关系」：应用后条款与手写条款完全同权，
  用户可以改标题、调权重、删除条目，模板不会回头覆盖（除非显式要求）。
- 「按模板建框架」把「建框架 + 写条款」放进同一个事务：条款写入失败时
  框架也不会留下空壳，避免出现「框架列表里有个 0 条款的残次品」。
- 重复应用同一模板是幂等的：以 (framework, code) 判重，只补缺不重置。
"""
from django.db import transaction

from devtools.common import endpoint, ok

from governance import services
from governance import templates as template_lib
from governance.models import FRAMEWORK_STATUS, Framework
from governance.views_common import (
    get_framework,
    param_bool,
    param_choice,
    param_str,
    param_text,
)


@endpoint(("GET",))
def template_list(request):
    """内置条款库列表：种类、条款总数与分类概览（不展开正文）。"""
    return ok(template_lib.list_templates())


@endpoint(("GET",))
def template_detail(request, kind):
    """条款库详情：完整条款清单，供「先预览再应用」的交互使用。"""
    return ok(template_lib.template_detail(kind))


@endpoint()
def framework_from_template(request):
    """按条款库新建框架并批量写入条款（建框架与写条款同一事务）。"""
    kinds = tuple(template_lib.template_kinds())
    kind = param_choice(request, "kind", kinds, required=True)
    spec = template_lib.get_template(kind)
    # 名称/版本缺省取模板元信息：最常见的用法就是「一键建 ISO 27001」，
    # 让用户少填两个字段；需要区分实例时再显式覆盖。
    name = param_str(request, "name", default=spec["name"], max_len=120)
    version = param_str(request, "version", default=spec["version"], max_len=40)
    if Framework.objects.filter(owner=request.user, name=name, version=version).exists():
        raise ValueError("同名同版本的框架已存在")
    with transaction.atomic():
        framework = Framework.objects.create(
            owner=request.user,
            name=name,
            version=version,
            kind=kind,
            description=param_text(request, "description", default=spec["description"]),
            status=param_choice(request, "status", FRAMEWORK_STATUS, default="draft"),
        )
        applied = services.apply_framework_template(framework, kind=kind)
    data = framework.to_dict()
    data["apply"] = applied
    return ok(data)


@endpoint()
def framework_apply_template(request, pk):
    """向已有框架补齐模板条款（按 code 幂等；update_existing 才覆盖）。"""
    framework = get_framework(pk, request.user, write=True)
    kinds = tuple(template_lib.template_kinds())
    kind = param_choice(request, "kind", kinds, default=None)
    update_existing = bool(param_bool(request, "update_existing", False))
    applied = services.apply_framework_template(
        framework, kind=kind, update_existing=update_existing)
    detail = framework.to_dict()
    detail["apply"] = applied
    return ok(detail)
