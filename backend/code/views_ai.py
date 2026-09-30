# -*- coding: utf-8 -*-
"""代码工坊视图（二）：智能辅助 / 静态分析 / 协作 / 评论 / 分享。

智能辅助全部遵循「LLM 可用则用，不可用则本地降级」的项目约定，
本地降级实现基于 `code.runtime` 的静态分析，保证无 Key 也能用。
"""
import json
import re

from django.db.models import Q
from django.utils import timezone

from assistant import llm

from devtools.common import (
    endpoint, ok, fail, p, req, req_str, opt_str, req_num, opt_num, opt_bool, req_list,
    as_lines,
)

from . import runtime as rt
from .models import CodeComment, CodeFile, CodeShare, CodeSnippet, CodeVersion
from .serializers import file_brief, file_qs, get_file, get_ws

# ============================================================
# 一、静态分析（无需 LLM，第 53/54/58/59/60 条）
# ============================================================


@endpoint(("POST",))
def analyze(request):
    """综合分析：指标 + 复杂度 + 质量评分 + 问题清单。"""
    language, code = _read_code(request)
    metrics = rt.analyze_metrics(code, language)
    complexity = rt.estimate_complexity(code, language)
    issues = _lint_issues(code, language, metrics)
    return ok({
        "language": language,
        "metrics": metrics,
        "complexity": complexity,
        "issues": issues,
        "issue_count": len(issues),
    })


@endpoint(("POST",))
def code_stats(request):
    """F677 代码统计卡：行数 / 注释率 / 函数数等静态指标一览。

    复用 `analyze_metrics()` 的本地指标（不引新依赖），额外换算成
    「卡片视图」字段，前端可直接渲染成统计卡。
    """
    language, code = _read_code(request)
    m = rt.analyze_metrics(code, language)
    lines = (code or "").split("\n")
    total = len(lines)
    blank = sum(1 for ln in lines if not ln.strip())
    comment = int(m.get("comment_lines") or 0)
    code_lines = max(0, total - blank - comment)
    funcs = int(m.get("functions") or 0)
    card = {
        "total_lines": total,
        "blank_lines": blank,
        "code_lines": code_lines,
        "comment_lines": comment,
        "comment_ratio": round(comment / total, 4) if total else 0,
        "comment_ratio_pct": round(comment * 100 / total, 1) if total else 0.0,
        "blank_ratio_pct": round(blank * 100 / total, 1) if total else 0.0,
        "function_count": funcs,
        "class_count": int(m.get("classes") or 0),
        "function_density": round(funcs * 100 / code_lines, 1) if code_lines else 0.0,
        "avg_line_length": round(sum(len(ln) for ln in lines) / total, 1) if total else 0,
        "max_line_length": int(m.get("max_line_length") or 0),
        "todo_count": int(m.get("todos") or 0),
        "cyclomatic": int(m.get("cyclomatic") or 0),
        "quality_score": int(m.get("quality_score") or 0),
        "bytes": len((code or "").encode("utf-8")),
    }
    return ok({"language": language, "card": card, "metrics": m})


def _read_code(request):
    """统一取代码：优先 file，其次 language+code。"""
    file_id = opt_num(request, "file", integer=True)
    if file_id:
        f = get_file(request.user, file_id)
        code = p(request, "code")
        return f.language, (f.content if code is None else str(code))
    language = rt.normalize_language(req_str(request, "language", "python"))
    code = req_str(request, "code", "")
    return language, code


def _lint_issues(code, language, metrics):
    """轻量 lint：基于规则的常见问题扫描（本地兜底，第 59 条）。"""
    issues = []
    lines = (code or "").split("\n")
    lang = rt.normalize_language(language)

    for i, line in enumerate(lines, start=1):
        if len(line) > 120:
            issues.append({
                "line": i, "severity": "info", "rule": "line-too-long",
                "message": f"行长度 {len(line)} 超过 120 字符",
            })
        if line.rstrip() != line:
            issues.append({
                "line": i, "severity": "info", "rule": "trailing-whitespace",
                "message": "存在行尾空白",
            })
        if "\t" in line and lang == "python":
            issues.append({
                "line": i, "severity": "warning", "rule": "mixed-indent",
                "message": "Python 代码中出现制表符，建议统一为 4 空格",
            })
        m = re.search(r"(?:TODO|FIXME|XXX|HACK)\b[:\s]*(.*)", line, re.IGNORECASE)
        if m:
            issues.append({
                "line": i, "severity": "info", "rule": "todo",
                "message": f"待办：{m.group(1).strip()[:80] or '未说明'}",
            })
        if re.search(r"\bprint\s*\(", line) and lang == "python":
            issues.append({
                "line": i, "severity": "info", "rule": "debug-print",
                "message": "疑似调试用 print，提交前建议移除或改用 logging",
            })
        if re.search(r"\bconsole\.log\s*\(", line) and lang == "javascript":
            issues.append({
                "line": i, "severity": "info", "rule": "debug-log",
                "message": "疑似调试用 console.log",
            })
        if re.search(r"\bexcept\s*:\s*$", line) and lang == "python":
            issues.append({
                "line": i, "severity": "warning", "rule": "bare-except",
                "message": "裸 except 会吞掉所有异常（含 KeyboardInterrupt），建议指定异常类型",
            })
        if re.search(r"eval\s*\(", line):
            issues.append({
                "line": i, "severity": "warning", "rule": "unsafe-eval",
                "message": "eval 存在注入风险，建议用 ast.literal_eval 或显式解析",
            })
        if re.search(r"\bexec\s*\(", line) and lang == "python":
            issues.append({
                "line": i, "severity": "warning", "rule": "unsafe-exec",
                "message": "exec 执行动态代码存在风险，请确认来源可信",
            })
        if lang == "python" and re.search(r"==\s*(?:None|True|False)\b", line):
            issues.append({
                "line": i, "severity": "info", "rule": "identity-comparison",
                "message": "与 None/True/False 比较建议用 is / is not",
            })
        if re.search(r"(?:password|passwd|secret|api_key|apikey|token)\s*=\s*['\"][^'\"]{6,}['\"]", line, re.IGNORECASE):
            issues.append({
                "line": i, "severity": "error", "rule": "hardcoded-secret",
                "message": "疑似硬编码密钥/口令，请改为从环境变量读取",
            })

    # 未使用变量（Python 粗测）
    if lang == "python":
        assigned = re.findall(r"^\s*(\w+)\s*=\s*[^=]", code or "", re.MULTILINE)
        for name in set(assigned):
            if name in ("_", "self", "cls"):
                continue
            uses = len(re.findall(rf"\b{re.escape(name)}\b", code or ""))
            if uses <= 1 and not name.isupper():
                ln = next((i for i, l in enumerate(lines, 1)
                           if re.match(rf"^\s*{re.escape(name)}\s*=", l)), None)
                if ln:
                    issues.append({
                        "line": ln, "severity": "info", "rule": "unused-variable",
                        "message": f"变量 {name} 赋值后未被使用",
                    })

    if metrics["quality_score"] < 70:
        issues.append({
            "line": 1, "severity": "warning", "rule": "low-quality-score",
            "message": f"综合质量分仅 {metrics['quality_score']}，建议按下方扣分项整改",
        })

    return issues[:200]


@endpoint(("POST",))
def outline(request):
    """提取代码大纲：类/函数/结构体（第 6 条折叠 + 大纲面板）。"""
    language, code = _read_code(request)
    lang = rt.normalize_language(language)
    items = []
    stack = []

    if lang == "python":
        pat = re.compile(r"^(?P<indent>\s*)(?:(?P<deco>@\w+)|(?P<kind>class|def|async\s+def))\s*(?P<name>[\w]*)")
        for i, line in enumerate((code or "").split("\n"), start=1):
            m = pat.match(line)
            if not m or not m.group("kind"):
                continue
            indent = len(m.group("indent"))
            kind = m.group("kind")
            label = m.group("name")
            if kind.startswith("async"):
                kind = "func"
                label = m.group("name")
            ntype = "class" if "class" in kind else "function"
            while stack and stack[-1]["indent"] >= indent:
                stack.pop()
            node = {"line": i, "type": ntype, "name": label, "indent": indent}
            if stack:
                stack[-1]["node"].setdefault("children", []).append(node)
                stack[-1]["node"].setdefault("_c", []).append(node)
            else:
                items.append(node)
            stack.append({"indent": indent, "node": node})
    else:
        patterns = [
            (re.compile(r"^\s*(?:public|private|protected|static|final|abstract|\s)*class\s+(\w+)"), "class"),
            (re.compile(r"^\s*(?:struct|interface|trait|enum)\s+(\w+)"), "struct"),
            (re.compile(r"^\s*(?:function|func|fn)\s+(\w+)"), "function"),
            (re.compile(r"^\s*(?:(?:public|private|protected|static|const|async|virtual|\s)+)?[\w:<>,\s\*&]+\s+(\w+)\s*\([^;]*\)\s*\{"), "method"),
            (re.compile(r"^\s*(?:def|sub|proc)\s+(\w+)"), "function"),
        ]
        current_type = None
        for i, line in enumerate((code or "").split("\n"), start=1):
            for pat, ntype in patterns:
                m = pat.match(line)
                if not m:
                    continue
                name = m.group(1)
                if name in ("if", "for", "while", "switch", "return", "catch", "sizeof"):
                    continue
                indent = len(line) - len(line.lstrip())
                node = {"line": i, "type": ntype, "name": name, "indent": indent}
                if ntype in ("class", "struct"):
                    items.append(node)
                    current_type = node
                elif current_type is not None and indent > current_type["indent"]:
                    current_type.setdefault("children", []).append(node)
                else:
                    items.append(node)
                    current_type = None
                break

    def strip_internal(nodes):
        out = []
        for n in nodes:
            n2 = {k: v for k, v in n.items() if k in ("line", "type", "name")}
            if n.get("children"):
                n2["children"] = strip_internal(n["children"])
            out.append(n2)
        return out

    return ok({"outline": strip_internal(items), "count": sum(1 for _ in _walk(items))})


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("children") or [])


@endpoint(("POST",))
def complexity(request):
    """复杂度分析（第 58 条）。"""
    language, code = _read_code(request)
    return ok(rt.estimate_complexity(code, language))


@endpoint(("POST",))
def quality(request):
    """代码质量评分（第 59 条）。"""
    language, code = _read_code(request)
    metrics = rt.analyze_metrics(code, language)
    issues = _lint_issues(code, language, metrics)
    by_sev = {"error": 0, "warning": 0, "info": 0}
    for it in issues:
        by_sev[it["severity"]] = by_sev.get(it["severity"], 0) + 1
    return ok({
        "score": metrics["quality_score"],
        "grade": _grade(metrics["quality_score"]),
        "dimensions": {
            "readability": max(0, 100 - by_sev["info"] * 2),
            "correctness": max(0, 100 - by_sev["error"] * 15 - by_sev["warning"] * 5),
            "maintainability": max(0, 100 - int(metrics["avg_complexity"] * 8) - metrics["todos"] * 3),
            "documentation": min(100, int(metrics["comment_ratio"] * 400)),
        },
        "severity": by_sev,
        "issues": issues[:60],
        "metrics": metrics,
    })


def _grade(score):
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


@endpoint(("POST",))
def flow(request):
    """流程图节点抽取（第 62 条）。"""
    language, code = _read_code(request)
    return ok(rt.to_flow_nodes(code, language))


@endpoint(("POST",))
def similarity(request):
    """代码查重（第 64 条）：基于 shingle + Jaccard，跨文件比对。"""
    language, code = _read_code(request)
    ws_id = opt_num(request, "workspace", integer=True)
    if not ws_id:
        raise ValueError("缺少 workspace")
    ws = get_ws(request.user, ws_id)

    target = _fingerprint(code)
    results = []
    for f in ws.files.all():
        if f.content == code:
            continue
        other = _fingerprint(f.content)
        if not other["shingles"] or not target["shingles"]:
            continue
        inter = len(target["shingles"] & other["shingles"])
        union = len(target["shingles"] | other["shingles"]) or 1
        jac = inter / union
        if jac > 0.05:
            results.append({
                "file": f.id, "path": f.path,
                "similarity": round(jac, 4),
                "percent": f"{jac:.1%}",
                "common_lines": inter,
                "verdict": _sim_verdict(jac),
            })
    results.sort(key=lambda x: -x["similarity"])
    return ok({
        "target_fingerprint": target["count"],
        "matches": results[:30],
        "max_similarity": results[0]["similarity"] if results else 0,
    })


def _fingerprint(code, k=5, step=2):
    """代码指纹：归一化后取 k-gram shingle 集合。"""
    lines = []
    for ln in (code or "").split("\n"):
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("//") or s.startswith("*"):
            continue
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"['\"][^'\"]*['\"]", '""', s)
        s = re.sub(r"\b\d+\b", "0", s)
        lines.append(s)
    shingles = set()
    for i in range(max(0, len(lines) - k + 1)):
        shingles.add("|".join(lines[i:i + k]))
    if not shingles and lines:
        shingles = set(lines)
    return {"shingles": shingles, "count": len(lines)}


def _sim_verdict(jac):
    if jac >= 0.7:
        return "高度相似，建议人工核对是否重复"
    if jac >= 0.4:
        return "存在较多相似片段"
    if jac >= 0.15:
        return "有部分相似结构"
    return "相似度较低"


@endpoint(("POST",))
def secret_scan(request):
    """涉密/敏感信息扫描（第 61 条）。"""
    language, code = _read_code(request)
    findings = scan_secrets(code)
    return ok({
        "findings": findings,
        "count": len(findings),
        "risk": "high" if any(f["severity"] == "high" for f in findings) else (
            "medium" if findings else "none"),
    })


SECRET_RULES = [
    ("high", "私钥文件", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("high", "AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("high", "GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("high", "OpenAI/通用 sk- 密钥", re.compile(r"\bsk-[A-Za-z0-9\-_]{20,}\b")),
    ("high", "Google API Key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("high", "Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b")),
    ("high", "JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("medium", "疑似硬编码口令", re.compile(
        r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*['\"]([^'\"\s]{6,})['\"]",
        re.IGNORECASE)),
    ("medium", "数据库连接串（含口令）", re.compile(
        r"(?:mysql|postgres|postgresql|mongodb|redis|amqp)://[^\s'\"]*:[^\s'\"@]+@", re.IGNORECASE)),
    ("medium", "内网 IP", re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")),
    ("medium", "中国大陆手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("medium", "身份证号", re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
    ("low", "邮箱地址", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("low", "疑似内网域名", re.compile(r"\b[\w-]+\.(?:internal|local|corp|lan)\b", re.IGNORECASE)),
]


def scan_secrets(code):
    findings = []
    lines = (code or "").split("\n")
    for i, line in enumerate(lines, start=1):
        for sev, name, pat in SECRET_RULES:
            for m in pat.finditer(line):
                val = m.group(0)
                masked = val[:6] + "***" + val[-4:] if len(val) > 12 else "***"
                findings.append({
                    "line": i, "severity": sev, "type": name,
                    "masked": masked,
                    "snippet": line.strip()[:120],
                    "advice": _secret_advice(name),
                })
    # 同类型同值去重
    seen = set()
    uniq = []
    for f in findings:
        key = (f["type"], f["line"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq[:200]


def _secret_advice(name):
    if "私钥" in name:
        return "私钥严禁入库，请移出仓库并立即轮换"
    if "口令" in name or "密钥" in name or "Token" in name or "Key" in name:
        return "改用环境变量或密钥管理服务注入，并轮换已泄露的凭据"
    if "连接串" in name:
        return "连接串请拆分为环境变量，避免口令落库"
    if "IP" in name or "域名" in name:
        return "确认是否为可对外披露的信息，必要时脱敏"
    return "确认是否属于可公开内容"


@endpoint(("POST",))
def refactor_hints(request):
    """重构建议（本地规则版，作为 LLM 不可用时的降级）。"""
    language, code = _read_code(request)
    metrics = rt.analyze_metrics(code, language)
    cx = rt.estimate_complexity(code, language)
    issues = _lint_issues(code, language, metrics)
    hints = []

    if metrics["avg_complexity"] > 5:
        hints.append({
            "priority": "high", "title": "拆分高复杂度函数",
            "detail": f"平均圈复杂度 {metrics['avg_complexity']}，建议把长函数按职责拆成小函数。",
        })
    if cx["max_loop_depth"] >= 2:
        hints.append({
            "priority": "high", "title": "优化嵌套循环",
            "detail": f"检测到 {cx['max_loop_depth']} 层循环嵌套（{cx['big_o']}），可考虑用哈希表降低维度。",
        })
    if metrics["max_line_length"] > 120:
        hints.append({
            "priority": "medium", "title": "拆分超长行",
            "detail": f"最长行 {metrics['max_line_length']} 字符，建议按运算符换行。",
        })
    if metrics["comment_ratio"] < 0.05 and metrics["total_lines"] > 30:
        hints.append({
            "priority": "medium", "title": "补充关键注释",
            "detail": "注释率不足 5%，建议为复杂逻辑补上「为什么这么做」的说明。",
        })
    if metrics["functions"] == 0 and metrics["total_lines"] > 25:
        hints.append({
            "priority": "medium", "title": "抽出函数",
            "detail": "代码以流程式书写，建议按步骤抽成具名函数，便于单测与复用。",
        })
    if metrics["todos"]:
        hints.append({
            "priority": "low", "title": "清理待办标记",
            "detail": f"存在 {metrics['todos']} 处 TODO/FIXME，建议转为任务单跟踪。",
        })
    dup_issues = [i for i in issues if i["rule"] == "debug-print"]
    if len(dup_issues) > 3:
        hints.append({
            "priority": "low", "title": "移除调试输出",
            "detail": f"有 {len(dup_issues)} 处 print/console.log，建议改用日志框架或删除。",
        })
    hard = [i for i in issues if i["rule"] in ("hardcoded-secret", "unsafe-eval", "unsafe-exec")]
    for h in hard[:5]:
        hints.append({
            "priority": "high", "title": f"安全隐患：{h['rule']}",
            "detail": f"第 {h['line']} 行 —— {h['message']}",
        })

    return ok({"hints": hints, "count": len(hints), "source": "local"})


# ============================================================
# 二、AI 智能辅助（第 43–52、55–57、63 条）
# ============================================================

_PROMPTS = {
    "generate": (
        "你是资深工程师。请根据需求生成可直接运行的代码。\n"
        "要求：只输出代码（可用一行注释开头说明），不要解释、不要 Markdown 围栏。\n\n"
        "语言：{language}\n需求：{instruction}\n"
    ),
    "explain": (
        "你是耐心的技术讲师。请逐段解释下面这段{language}代码做了什么，"
        "指出关键数据结构与算法思路，最后给一句话总结。用中文回答，条理清晰。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "find_bugs": (
        "你是严格的代码审查员。请找出下面{language}代码中的 bug、边界问题与异常风险。\n"
        "输出格式：每条一行，`行号: 问题 —— 原因 —— 修复建议`；没有问题就回「未发现明显问题」。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "refactor": (
        "你是重构专家。请在**不改变外部行为**的前提下重构下面这段{language}代码，"
        "提升可读性与可维护性。只输出重构后的完整代码，不要解释。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "tests": (
        "你是测试工程师。请为下面的{language}代码编写单元测试。\n"
        "要求：覆盖正常路径、边界值与异常路径；只输出测试代码，不要解释。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "translate": (
        "请把下面的{language}代码翻译成 {target}，保持逻辑与行为完全一致。"
        "只输出目标语言代码，不要解释。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "comment": (
        "请为下面的{language}代码补全注释：函数/类前加文档注释，复杂逻辑处加行内注释。"
        "只输出加了注释的完整代码，不要额外解释。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "error_explain": (
        "下面是{language}代码运行时的报错信息，请用中文解释报错含义、"
        "最可能的根本原因，并给出具体的修复步骤（可引用行号）。\n\n"
        "代码：\n```{language}\n{code}\n```\n\n报错：\n```\n{error}\n```\n"
    ),
    "testdata": (
        "请为下面的{language}代码设计测试数据：包含正常用例 3 组、边界用例 3 组、异常用例 2 组。"
        "用简洁的列表输出，每项写明输入与预期输出。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "reverse_question": (
        "请根据下面的{language}代码反向出 3 道面试题，考察其涉及的算法/设计要点。"
        "每道题给出题干与参考答案要点。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "review": (
        "你是技术负责人，请对下面这段{language}代码做一次正式 code review。\n"
        "从【正确性】【可读性】【性能】【安全】【可测试性】五个维度给出结论与改进项，用中文。\n\n"
        "```{language}\n{code}\n```\n"
    ),
    "chat_edit": (
        "下面是一段{language}代码，用户提出了修改要求。请直接输出修改后的完整代码，"
        "不要解释、不要 Markdown 围栏。\n\n"
        "当前代码：\n```{language}\n{code}\n```\n\n"
        "修改要求：{instruction}\n"
    ),
    "regex": (
        "请根据下面的自然语言描述，生成对应的正则表达式。\n"
        "输出：先给正则本身（单独一行），再给一句说明，最后给 2 个匹配示例和 1 个不匹配示例。\n\n"
        "描述：{instruction}\n目标语言/风格：{language}\n"
    ),
    "nl2sql": (
        "你是数据库专家。请把下面的自然语言需求转成 SQL 查询。\n"
        "已知表结构：\n{schema}\n\n需求：{instruction}\n"
        "只输出 SQL，不要解释。"
    ),
    "learning_path": (
        "请为「{instruction}」这个学习目标制定一份循序渐进的学习路径，"
        "分为 4 个阶段，每阶段给出目标、要点与练习建议，用中文，条理清晰。"
    ),
}


def _llm_available():
    try:
        return llm.is_configured()
    except Exception:  # noqa: BLE001
        return False


def _call_llm(prompt, system=None, max_tokens=None):
    """统一 LLM 调用，返回 (text, meta)。失败返回 (None, meta_with_error)。"""
    try:
        res = llm.chat(
            [{"role": "user", "content": prompt}],
            system=system,
            max_tokens=max_tokens,
        )
    except Exception as e:  # noqa: BLE001
        return None, {"ok": False, "error": f"{type(e).__name__}: {e}", "provider": "none"}
    if not isinstance(res, dict):
        return None, {"ok": False, "error": "LLM 返回格式异常", "provider": "none"}
    if res.get("ok") and res.get("content"):
        return res["content"], {
            "ok": True, "provider": res.get("provider", ""),
            "model": res.get("model", ""), "duration_ms": res.get("duration_ms", 0),
        }
    return None, {
        "ok": False,
        "error": res.get("error") or "模型未返回内容",
        "code": res.get("code", ""),
        "provider": res.get("provider", "none"),
    }


@endpoint(("POST",))
def ai_generate(request):
    """AI 生成代码（第 43 条）。"""
    language = rt.normalize_language(req_str(request, "language", "python"))
    instruction = req_str(request, "instruction", "").strip()
    if not instruction:
        raise ValueError("请描述你的需求")

    prompt = _PROMPTS["generate"].format(language=language, instruction=instruction)
    text, meta = _call_llm(prompt, system="你是严谨的软件工程师，输出即用型代码。")

    if text is None:
        # 本地降级：给出可运行骨架 + 明确的接入说明
        skeleton = rt.language_meta(language).get("template", "")
        fallback = (
            f"{skeleton}\n\n"
            f"{rt.LANGUAGES.get(language, {}).get('comment', '#')} TODO 需求：{instruction[:200]}\n"
            f"{rt.LANGUAGES.get(language, {}).get('comment', '#')} "
            f"AI 当前不可用（{meta.get('error', '未配置模型密钥')}），已为你生成可运行骨架，请在此基础上补全。\n"
        )
        return ok({
            "code": fallback, "source": "local", "note": "AI 不可用，已降级为可运行骨架",
            "llm": meta,
        })
    return ok({"code": _strip_fence(text), "source": "llm", "llm": meta})


def _strip_fence(text):
    """去掉模型爱加的 Markdown 围栏。"""
    t = (text or "").strip()
    m = re.match(r"^```[\w+-]*\s*\n(.*?)\n?```$", t, re.DOTALL)
    if m:
        return m.group(1)
    return t


@endpoint(("POST",))
def ai_transform(request):
    """一个入口覆盖：解释 / 找 bug / 重构 / 生成测试 / 翻译 / 加注释 / 测试数据 / 反出题 / 审查。

    第 44–48、55–57、63 条。
    """
    action = req_str(request, "action", "").strip()
    if action not in _PROMPTS:
        raise ValueError(f"不支持的 action: {action}（可选：explain/find_bugs/refactor/tests/translate/comment/testdata/reverse_question/review）")
    language, code = _read_code(request)
    if not (code or "").strip():
        raise ValueError("代码不能为空")

    kwargs = {"language": language, "code": code}
    if action == "translate":
        kwargs["target"] = req_str(request, "target", "python")
    prompt = _PROMPTS[action].format(**kwargs)
    text, meta = _call_llm(prompt)

    if text is None:
        return ok({
            "result": _local_transform(action, language, code),
            "source": "local",
            "note": f"AI 不可用（{meta.get('error', '未配置模型密钥')}），以下为本地规则分析结果",
            "llm": meta,
        })
    payload = _strip_fence(text) if action in ("refactor", "tests", "translate", "comment", "generate") else text
    return ok({"result": payload, "source": "llm", "llm": meta})


def _local_transform(action, language, code):
    metrics = rt.analyze_metrics(code, language)
    cx = rt.estimate_complexity(code, language)
    issues = _lint_issues(code, language, metrics)

    if action in ("explain", "review"):
        lines = [
            f"【本地分析】{rt.LANGUAGES.get(language, {}).get('name', language)} · "
            f"{metrics['total_lines']} 行（有效代码 {metrics['code_lines']} 行）",
            "",
            f"· 函数 {metrics['functions']} 个，类 {metrics['classes']} 个",
            f"· 圈复杂度合计 {metrics['cyclomatic']}，平均每函数 {metrics['avg_complexity']}",
            f"· 时间复杂度估算：{cx['big_o']}",
            f"· 注释率 {metrics['comment_ratio']:.1%}，最长行 {metrics['max_line_length']} 字符",
            f"· 质量分 {metrics['quality_score']}（{_grade(metrics['quality_score'])}）",
        ]
        if metrics["function_names"]:
            lines += ["", "识别到的函数：" + "、".join(metrics["function_names"][:12])]
        if metrics["class_names"]:
            lines.append("识别到的类：" + "、".join(metrics["class_names"][:12]))
        lines += ["", cx["hint"]]
        if action == "review" and issues:
            lines += ["", f"发现 {len(issues)} 处可改进点："]
            lines += [f"  · 第 {i['line']} 行 [{i['rule']}] {i['message']}" for i in issues[:12]]
        return "\n".join(lines)

    if action == "find_bugs":
        if not issues:
            return "【本地扫描】未发现明显的模式化问题。\n注意：本地扫描只覆盖常见规则，建议开启 AI 做深度审查。"
        return "【本地扫描】发现以下疑似问题：\n\n" + "\n".join(
            f"第 {i['line']} 行 [{i['rule']}] {i['message']}" for i in issues[:40]
        ) + f"\n\n共 {len(issues)} 处。本地规则覆盖有限，建议开启 AI 做深度审查。"

    if action == "refactor":
        hints = []
        if cx["max_loop_depth"] >= 2:
            hints.append(f"{rt.LANGUAGES.get(language, {}).get('comment', '#')} 建议：当前有 {cx['max_loop_depth']} 层循环嵌套（{cx['big_o']}），考虑用字典/集合降低维度")
        if metrics["avg_complexity"] > 5:
            hints.append(f"{rt.LANGUAGES.get(language, {}).get('comment', '#')} 建议：平均圈复杂度 {metrics['avg_complexity']}，把长函数拆成小函数")
        if metrics["max_line_length"] > 120:
            hints.append(f"{rt.LANGUAGES.get(language, {}).get('comment', '#')} 建议：存在 {metrics['max_line_length']} 字符的长行，按运算符换行")
        head = "\n".join(hints) if hints else f"{rt.LANGUAGES.get(language, {}).get('comment', '#')} 本地未发现结构性问题"
        return head + "\n\n" + code

    if action == "tests":
        comment = rt.LANGUAGES.get(language, {}).get("comment", "#")
        names = metrics["function_names"] or ["main"]
        if language == "python":
            body = "\n\n".join(
                f"def test_{n}():\n"
                f"    \"\"\"TODO: 覆盖 {n} 的正常路径与边界条件\"\"\"\n"
                f"    assert callable({n})"
                for n in names[:5]
            )
            return f"{comment} 本地生成的测试骨架（pytest 风格），请补全断言\n\n{body}\n"
        if language == "javascript":
            body = "\n\n".join(
                f"test('{n} 正常路径', () => {{\n  // TODO: 补全断言\n  expect(typeof {n}).toBe('function');\n}});"
                for n in names[:5]
            )
            return f"{comment} 本地生成的测试骨架\n\n{body}\n"
        return f"{comment} 本地无法为 {language} 生成测试骨架，请开启 AI"

    if action == "testdata":
        return (
            "【本地建议的测试数据设计】\n\n"
            "正常用例：\n"
            "  1. 典型输入 → 期望按文档输出\n"
            "  2. 最小值输入 → 边界不越界\n"
            "  3. 最大值输入 → 无溢出/超时\n\n"
            "边界用例：\n"
            "  1. 空输入 / 空集合\n"
            "  2. 单元素输入\n"
            f"  3. 与循环上界相关的输入（当前 {cx['big_o']}，注意数据规模）\n\n"
            "异常用例：\n"
            "  1. 非法类型输入\n"
            "  2. 超出取值范围\n\n"
            f"代码规模：{metrics['total_lines']} 行 / {metrics['functions']} 个函数"
        )

    if action == "reverse_question":
        qs = []
        if cx["max_loop_depth"] >= 2:
            qs.append(f"1. 这段代码为什么是 {cx['big_o']}？如何在保持语义的前提下优化到更低复杂度？")
        if metrics["class_names"]:
            qs.append(f"2. 类 {metrics['class_names'][0]} 的职责边界是什么？如果需求变更你会怎么扩展？")
        if metrics["function_names"]:
            qs.append(f"3. 函数 {metrics['function_names'][0]} 的边界条件有哪些？你会为它设计哪些测试用例？")
        if not qs:
            qs.append("1. 这段代码的核心思路是什么？时间复杂度是多少？")
            qs.append("2. 如果输入规模放大 100 倍，需要怎么改造？")
            qs.append("3. 这段代码最容易出错的地方在哪里？")
        return "【本地反向出题】\n\n" + "\n\n".join(qs[:3])

    if action == "translate":
        return (
            "AI 不可用，本地无法做跨语言翻译。\n\n"
            "可先用本地分析了解代码结构，再手动迁移：\n"
            f"· 函数 {metrics['functions']} 个：{'、'.join(metrics['function_names'][:10]) or '无'}\n"
            f"· 类 {metrics['classes']} 个：{'、'.join(metrics['class_names'][:10]) or '无'}\n"
            f"· 圈复杂度 {metrics['cyclomatic']}，{cx['big_o']}"
        )

    if action == "comment":
        comment = rt.LANGUAGES.get(language, {}).get("comment", "#")
        if language == "python":
            out = []
            for ln in code.split("\n"):
                m = re.match(r"^(\s*)(def|class)\s+(\w+)\s*\((.*?)\)", ln)
                if m:
                    indent, kind, name, args = m.groups()
                    out.append(f'{indent}{comment} {name}: TODO 说明用途、参数与返回值')
                out.append(ln)
            return "\n".join(out)
        return f"{comment} TODO 为以下代码补全注释\n\n" + code

    return "本地无对应降级实现。"


@endpoint(("POST",))
def ai_error_explain(request):
    """解释报错（第 49 条）。"""
    language, code = _read_code(request)
    error = opt_str(request, "error", "").strip()
    if not error:
        # 从最近一次运行记录取
        from .models import CodeRun
        fid = opt_num(request, "file", integer=True)
        qs = CodeRun.objects.filter(owner=request.user)
        if fid:
            qs = qs.filter(file_id=fid)
        last = qs.first()
        error = (last.stderr if last else "") or ""
    if not error:
        raise ValueError("缺少报错信息（error），也没有可用的运行记录")

    prompt = _PROMPTS["error_explain"].format(language=language, code=code[:8000], error=error[:4000])
    text, meta = _call_llm(prompt)
    if text is None:
        local = _local_error_explain(language, error)
        return ok({"result": local, "source": "local", "llm": meta})
    return ok({"result": text, "source": "llm", "llm": meta})


def _local_error_explain(language, error):
    diags = rt.parse_diagnostics(language, error)
    lines = ["【本地报错解析】"]
    if not diags:
        lines.append("未能结构化识别该报错，原始信息如下：")
        lines.append("")
        lines.append(error[:2000])
        return "\n".join(lines)

    for d in diags[:5]:
        lines.append("")
        loc = f"第 {d.get('line')} 行" if d.get("line") else "位置未知"
        lines.append(f"· {loc}｜{d.get('type', d.get('severity'))}")
        lines.append(f"  {d.get('message', '')}")
        hint = _error_hint(d.get("type", ""), d.get("message", ""))
        if hint:
            lines.append(f"  建议：{hint}")

    frames = diags[0].get("frames") if diags else None
    if frames:
        lines.append("")
        lines.append("调用栈（由外向内）：")
        for fr in frames[-8:]:
            lines.append(f"  {fr.get('file')}:{fr.get('line')} in {fr.get('function') or '<module>'}")
    return "\n".join(lines)


_ERROR_HINTS = {
    "SyntaxError": "检查报错行及其上一行的冒号、括号与缩进是否配对。",
    "IndentationError": "统一缩进：Python 不要混用 Tab 与空格。",
    "NameError": "变量/函数名拼写错误，或在使用前未定义。",
    "TypeError": "参数类型不匹配，检查调用签名与传入实参。",
    "ValueError": "值本身不合法（如 int('abc')），做前置校验。",
    "IndexError": "下标越界，检查 len() 边界与循环范围。",
    "KeyError": "字典键不存在，改用 dict.get() 或先判断。",
    "ZeroDivisionError": "除数为 0，运算前做零值判断。",
    "AttributeError": "对象没有该属性，检查类型或是否已初始化。",
    "FileNotFoundError": "文件路径错误，注意工作目录用的是临时目录。",
    "ImportError": "模块不存在，检查依赖是否安装与拼写。",
    "ModuleNotFoundError": "依赖未安装，需先 pip/npm 安装相应包。",
    "RecursionError": "递归太深，检查递归出口或改为迭代。",
    "MemoryError": "内存不足，注意数据结构规模。",
    "TimeoutError": "执行超时，检查是否有死循环。",
    "RuntimeError": "运行时错误，结合上下文定位。",
    "segmentation fault": "段错误：常见于越界访问、空指针或野指针。",
}


def _error_hint(err_type, message):
    for k, v in _ERROR_HINTS.items():
        if k.lower() in (err_type or "").lower() or k.lower() in (message or "").lower():
            return v
    return ""


@endpoint(("POST",))
def ai_regex(request):
    """自然语言转正则（第 60 条）。"""
    instruction = req_str(request, "instruction", "").strip()
    language = opt_str(request, "language", "python")
    prompt = _PROMPTS["regex"].format(instruction=instruction, language=language)
    text, meta = _call_llm(prompt)
    if text is None:
        return ok({
            "result": "AI 不可用，本地无法可靠生成正则。\n\n可参考常用模式：\n"
                      "· 邮箱：^[\\w.+-]+@[\\w-]+\\.[\\w.-]+$\n"
                      "· 手机号（中国大陆）：^1[3-9]\\d{9}$\n"
                      "· 整数：^-?\\d+$\n"
                      "· 中国大陆身份证：^[1-9]\\d{5}(19|20)\\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\\d|3[01])\\d{3}[\\dXx]$",
            "source": "local", "llm": meta,
        })
    return ok({"result": text, "source": "llm", "llm": meta})


@endpoint(("POST",))
def ai_nl2sql(request):
    """自然语言转 SQL（第 57 条）。"""
    instruction = req_str(request, "instruction", "").strip()
    schema = opt_str(request, "schema", "（未提供表结构，请按通用命名假设）")
    prompt = _PROMPTS["nl2sql"].format(instruction=instruction, schema=schema[:6000])
    text, meta = _call_llm(prompt)
    if text is None:
        return ok({
            "result": "AI 不可用，本地无法可靠生成 SQL。\n\n请先提供表结构，或手动编写后使用「解释代码」功能做校验。",
            "source": "local", "llm": meta,
        })
    return ok({"result": _strip_fence(text), "source": "llm", "llm": meta})


@endpoint(("POST",))
def ai_learning_path(request):
    """学习路径规划（第 63 条）。"""
    goal = req_str(request, "goal", "").strip()
    prompt = _PROMPTS["learning_path"].format(instruction=goal)
    text, meta = _call_llm(prompt)
    if text is None:
        return ok({
            "result": (
                f"【本地学习路径建议】目标：{goal}\n\n"
                "阶段一 · 打基础\n  目标：能读懂并修改最简单的程序\n  要点：语法、变量、分支与循环\n  练习：写 10 个控制台小练习\n\n"
                "阶段二 · 建立结构感\n  目标：能拆解问题为函数/模块\n  要点：函数、数据结构、错误处理\n  练习：实现一个命令行小工具\n\n"
                "阶段三 · 工程化\n  目标：能写出可测试、可维护的代码\n  要点：单元测试、版本管理、调试技巧\n  练习：给阶段二的工具补测试并接 CI\n\n"
                "阶段四 · 专项深入\n  目标：在具体方向形成竞争力\n  要点：性能优化、并发、领域知识\n  练习：做一个小型完整项目并写文档"
            ),
            "source": "local", "llm": meta,
        })
    return ok({"result": text, "source": "llm", "llm": meta})


@endpoint(("POST",))
def ai_chat_edit(request):
    """对话式改代码（第 56 条）。"""
    language, code = _read_code(request)
    instruction = req_str(request, "instruction", "").strip()
    prompt = _PROMPTS["chat_edit"].format(language=language, code=code[:12000], instruction=instruction)
    text, meta = _call_llm(prompt)
    if text is None:
        return ok({
            "code": code,
            "explanation": f"AI 不可用（{meta.get('error', '未配置密钥')}），未做修改。\n"
                           f"你的诉求是：{instruction}\n"
                           "可先用「重构建议」与「质量评分」定位问题。",
            "source": "local", "llm": meta,
        })
    return ok({"code": _strip_fence(text), "source": "llm", "llm": meta})


@endpoint(("POST",))
def ai_inline(request):
    """行内智能补全 / ghost text（第 21、50 条）。

    入参：{language, prefix, suffix, max_tokens}
    返回：{completion, source}
    """
    language = rt.normalize_language(req_str(request, "language", "python"))
    prefix = opt_str(request, "prefix", "")[-4000:]
    suffix = opt_str(request, "suffix", "")[:2000]
    if not prefix.strip():
        return ok({"completion": "", "source": "none", "reason": "前缀为空"})

    prompt = (
        f"你是代码补全引擎。下面是一段{language}代码，光标在 <CURSOR> 处。\n"
        "请只输出光标处应当插入的内容（不要重复已有代码、不要解释、不要围栏），"
        "如果不需要补全就输出空字符串。\n\n"
        f"{prefix}<CURSOR>{suffix}"
    )
    text, meta = _call_llm(prompt, max_tokens=opt_num(request, "max_tokens", 200, integer=True, minimum=1, maximum=1000))
    if text is None:
        return ok({"completion": _local_inline(language, prefix), "source": "local", "llm": meta})
    return ok({"completion": (text or "").strip("\n"), "source": "llm", "llm": meta})


def _local_inline(language, prefix):
    """本地补全：基于当前行的结构化补全（无 AI 也有一点用）。"""
    last = prefix.split("\n")[-1]
    stripped = last.strip()

    if language == "python":
        m = re.match(r"^(\s*)def\s+(\w+)\s*\(\s*$", last)
        if m:
            return "):\n" + m.group(1) + "    "
        m = re.match(r"^(\s*)(if|elif|for|while|with|else|try|except|class)\b.*[^:]\s*$", last)
        if m:
            return ":"
        if re.match(r"^(\s*)print\s*$", last):
            return '("")'
    if language in ("javascript", "typescript"):
        if re.search(r"\bconsole\s*$", last):
            return ".log()"
        m = re.match(r"^(\s*)function\s+\w+\s*\(\s*$", last)
        if m:
            return ") {\n" + m.group(1) + "  "
        m = re.match(r"^(\s*)if\s*\(.*[^)]$", last)
        if m:
            return ")"
    if language in ("c", "cpp", "java"):
        if re.search(r"\bprintf\s*$", last):
            return '("");'
        if re.search(r"\bstd::cout\s*$", last):
            return " << "
        m = re.match(r"^(\s*)for\s*\(\s*$", last)
        if m:
            return "int i = 0; i < n; i++) {\n" + m.group(1) + "    "
    if language == "go":
        if re.search(r"\bfmt\.Print" if False else r"\bfmt\.$", last):
            return "Println()"
    if stripped.endswith("{"):
        indent = len(last) - len(last.lstrip())
        return "\n" + " " * (indent + 4)
    return ""


@endpoint(("POST",))
def ai_complete_apply(request, pk):
    """把 AI 生成/修改的代码写回文件（自动打快照）。"""
    f = get_file(request.user, pk)
    new_code = req_str(request, "code", "")
    if not new_code.strip():
        raise ValueError("code 不能为空")
    if new_code == f.content:
        return ok({"changed": False, "file": file_brief(f)})
    CodeVersion.objects.create(
        file=f, content=f.content,
        message=opt_str(request, "message", "AI 修改前快照"),
        size=len(f.content.encode("utf-8")), created_by=request.user,
    )
    f.content = new_code
    if p(request, "language"):
        f.language = rt.normalize_language(str(p(request, "language")))
    f.save()
    return ok({"changed": True, "file": file_brief(f)})


@endpoint(("GET",))
def ai_status(request):
    """智能能力状态（沿用 assistant 的探测）。"""
    try:
        st = llm.status()
    except Exception as e:  # noqa: BLE001
        st = {"configured": False, "error": str(e)}
    return ok({
        "llm": st,
        "local_capabilities": [
            "静态指标分析", "复杂度估算", "质量评分", "规则化 lint",
            "涉密扫描", "代码查重", "流程图抽取", "重构建议", "报错解析", "行内补全（结构级）",
        ],
    })


# ============================================================
# 三、协作：评论 / 协同状态（第 68–72 条）
# ============================================================


@endpoint(("GET",))
def comment_list(request, pk):
    f = get_file(request.user, pk)
    roots = f.comments.filter(parent__isnull=True).select_related("author")
    items = []
    for c in roots:
        items.append(_comment_payload(c, request.user))
    unresolved = sum(1 for c in roots if not c.resolved)
    return ok({"items": items, "unresolved": unresolved, "total": roots.count()})


def _comment_payload(c, user):
    return {
        "id": c.id,
        "line": c.line,
        "content": c.content,
        "author": c.author.username if c.author_id else "",
        "author_id": c.author_id,
        "is_mine": c.author_id == user.id,
        "resolved": c.resolved,
        "created_at": c.created_at,
        "replies": [_comment_payload(r, user) for r in c.replies.select_related("author")],
    }


@endpoint(("POST",))
def comment_create(request, pk):
    f = get_file(request.user, pk)
    content = req_str(request, "content", "").strip()
    if not content:
        raise ValueError("评论内容不能为空")
    line = opt_num(request, "line", 1, integer=True, minimum=1)
    parent_id = opt_num(request, "parent", integer=True)
    parent = None
    if parent_id:
        parent = f.comments.filter(id=parent_id).first()
        if not parent:
            raise ValueError(f"父评论不存在: {parent_id}")
    c = CodeComment.objects.create(
        file=f, author=request.user, line=line,
        content=content[:4000], parent=parent,
    )
    return ok(_comment_payload(c, request.user))


@endpoint(("POST",))
def comment_resolve(request, pk, cid):
    f = get_file(request.user, pk)
    c = f.comments.filter(id=cid).first()
    if not c:
        raise ValueError(f"评论不存在: {cid}")
    c.resolved = not c.resolved
    c.save(update_fields=["resolved"])
    return ok({"id": c.id, "resolved": c.resolved})


@endpoint(("POST",))
def comment_delete(request, pk, cid):
    f = get_file(request.user, pk)
    c = f.comments.filter(id=cid).first()
    if not c:
        raise ValueError(f"评论不存在: {cid}")
    if c.author_id != request.user.id and f.owner_id != request.user.id:
        raise ValueError("只能删除自己的评论")
    c.delete()
    return ok({"deleted": cid})


@endpoint(("GET",))
def collab_state(request, pk):
    """取协同状态（供前端 Yjs 初始化）。"""
    f = get_file(request.user, pk)
    st = getattr(f, "collab", None)
    payload = {
        "file": f.id,
        "revision": st.revision if st else 0,
        "contributors": (st.contributors if st else []) or [],
        "update_count": len(st.update_log) if st else 0,
        "updated_at": st.updated_at if st else None,
        "text_length": len(f.content),
    }
    if st and st.snapshot:
        import base64
        payload["snapshot_b64"] = base64.b64encode(bytes(st.snapshot)).decode("ascii")
    else:
        payload["snapshot_b64"] = ""
    return ok(payload)


@endpoint(("GET",))
def collab_ws_info(request, pk):
    """给出该文件的 WebSocket 地址（前端拼接 base 后连接）。"""
    f = get_file(request.user, pk)
    return ok({
        "file": f.id,
        "path": f"/ws/code/{f.id}/",
        "protocol": "yjs-crdt-relay",
        "message_types": [
            "collab.init", "yjs.update", "yjs.snapshot",
            "awareness", "presence", "collab.compact", "pong",
        ],
        "max_update_log": 200,
    })


# ============================================================
# 三·补、AI 深度能力（L3 补齐：翻译 / 注释 / 优化 / 单测 / 摘要）
#
# 全部遵循「LLM 可用则用，不可用则本地降级」约定。
# 本地降级不是占位符，而是真正可用的静态实现，保证无 Key 也有产出。
# ============================================================

# 目标语言 → 文件扩展名/注释符提示，供翻译与注释生成用
_LANG_HINT = {
    "python": "Python（4 空格缩进，PEP8）",
    "javascript": "JavaScript（ES2020+，2 空格缩进）",
    "typescript": "TypeScript（严格类型，2 空格缩进）",
    "java": "Java（4 空格缩进，类名大驼峰）",
    "cpp": "C++（4 空格缩进，标准库风格）",
    "c": "C（4 空格缩进）",
    "go": "Go（gofmt 风格，Tab 缩进）",
    "rust": "Rust（rustfmt 风格，4 空格缩进）",
    "php": "PHP（PSR-12 风格）",
    "ruby": "Ruby（2 空格缩进）",
    "lua": "Lua（2 空格缩进）",
    "sql": "SQL（大写关键字）",
    "bash": "Bash（set -euo pipefail）",
}


def _code_arg(request, key="code", need=True):
    """取代码参数；need=True 时空代码报错。"""
    code = p(request, key)
    if code is None and need:
        raise ValueError(f"{key} 不能为空")
    return str(code or "")


@endpoint(("POST",))
def ai_translate(request):
    """跨语言翻译（第 55 条）：把源码从一种语言翻到另一种。

    本地降级：不强行"翻译"（结构差异大，硬翻必错），
    改为输出「逐段对照说明 + 目标语言骨架」，诚实且可用。
    """
    source_code = _code_arg(request)
    src_lang = rt.normalize_language(opt_str(request, "language", "python"))
    dst_lang = rt.normalize_language(req_str(request, "target", ""))
    if dst_lang == src_lang:
        raise ValueError("目标语言与源语言相同")
    keep_style = opt_bool(request, "keep_style", True)

    prompt = (
        f"把下面这段 {_LANG_HINT.get(src_lang, src_lang)} 代码翻译成 "
        f"{_LANG_HINT.get(dst_lang, dst_lang)}。\n"
        f"{'保持原有的命名与代码风格。' if keep_style else '可改用目标语言的惯用写法。'}\n"
        "只输出翻译后的代码，不要解释、不要 markdown 代码块。\n\n"
        f"```{src_lang}\n{source_code[:12000]}\n```"
    )
    text, meta = _call_llm(
        prompt, system="你是精通多语言的资深工程师，翻译结果必须可直接运行。", max_tokens=3000
    )

    if text is not None:
        return ok({
            "code": _strip_fence(text),
            "source_language": src_lang, "target_language": dst_lang,
            "mode": "llm", "meta": meta,
        })

    # ---- 本地降级 ----
    flow = rt.to_flow_nodes(source_code, src_lang)
    outline = flow.get("nodes", []) if isinstance(flow, dict) else (flow or [])
    metrics = rt.analyze_metrics(source_code, src_lang)
    template = rt.language_meta(dst_lang).get("template", "")
    lines = [
        f"// 未能调用大模型，以下是结构对照（{src_lang} → {dst_lang}）",
        f"// 源文件规模：{metrics.get('total_lines', 0)} 行 / "
        f"{metrics.get('functions', 0)} 个函数 / {metrics.get('classes', 0)} 个类",
        "",
        f"// === {dst_lang} 骨架（可直接开始改写）===",
        template,
        "",
        "/* === 需要人工迁移的结构清单 ===",
    ]
    if outline:
        for n in outline[:20]:
            lines.append(f" * [{n.get('type') or n.get('kind')}] {n.get('label') or ''}  (源第 {n.get('line', '?')} 行)")
    else:
        lines.append(" * （未识别到显式结构，请按行迁移）")
    lines.append(" */")

    return ok({
        "code": "\n".join(lines),
        "source_language": src_lang, "target_language": dst_lang,
        "mode": "local",
        "meta": {"ok": False, "error": meta.get("error", ""), "provider": "none"},
        "note": "本地降级：结构差异大的语言间不做机械转换，请按清单人工迁移。",
    })


def _strip_fence(text):
    """去掉 LLM 爱加的 ``` 包裹。"""
    s = (text or "").strip()
    m = re.search(r"```[a-zA-Z0-9_+-]*\s*(.+?)\s*```", s, re.S)
    return m.group(1) if m else s


@endpoint(("POST",))
def ai_comment(request):
    """自动生成注释（第 51 条）：支持行内/函数级/全文三种粒度。

    本地降级可用度高——基于静态分析产出规范注释骨架，尤其是函数签名注释。
    """
    source_code = _code_arg(request)
    language = rt.normalize_language(opt_str(request, "language", "python"))
    style = opt_str(request, "style", "docstring")  # docstring / line / block

    prompt = (
        f"为下面的 {_LANG_HINT.get(language, language)} 代码补充注释。\n"
        f"注释风格：{style}（docstring=文档字符串，line=行内注释，block=块注释）。\n"
        "要求：只给函数/类/关键逻辑加注释，不要给每行都加、不要改代码逻辑。\n"
        "只输出加好注释的完整代码，不要解释、不要 markdown 代码块。\n\n"
        f"```{language}\n{source_code[:12000]}\n```"
    )
    text, meta = _call_llm(
        prompt, system="你是注重可读性的资深工程师，注释简洁准确、'为什么'优先于'做了什么'。",
        max_tokens=3500,
    )
    if text is not None:
        return ok({"code": _strip_fence(text), "language": language,
                   "style": style, "mode": "llm", "meta": meta})

    # ---- 本地降级：生成注释骨架，插在函数/类定义上方 ----
    lines = as_lines(source_code)
    comment = rt.language_meta(language).get("comment", "#")
    funcs = _scan_defs(source_code, language)

    out = []
    inserted = 0
    idx_map = {f["line"]: f for f in funcs}
    for i, ln in enumerate(lines, start=1):
        f = idx_map.get(i)
        if f and inserted < 60:
            indent = " " * (len(ln) - len(ln.lstrip()))
            if style == "docstring" and language == "python":
                out.append(f'{indent}"""{f["kind"]} {f["name"]}：TODO 补充说明')
                args = f.get("args") or []
                if args:
                    for a in args[:6]:
                        out.append(f"{indent}:param {a}: TODO 参数说明")
                out.append(f'{indent}"""')
            else:
                out.append(f"{indent}{comment} {f['kind']} {f['name']}：TODO 补充说明")
            inserted += 1
        out.append(ln)

    body = "\n".join(out)
    return ok({
        "code": body, "language": language, "style": style, "mode": "local",
        "meta": {"ok": False, "error": meta.get("error", ""), "provider": "none"},
        "note": f"本地降级：已为 {inserted} 个函数/类生成注释骨架，请填充 TODO。",
        "skeleton_count": inserted,
    })


def _scan_defs(code, language):
    """轻量扫描函数/类定义位置，用于注释骨架与单测骨架。"""
    out = []
    pats = {
        "python": [(r"^(\s*)def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", "函数", "def"),
                   (r"^(\s*)class\s+([A-Za-z_]\w*)", "类", "class")],
        "javascript": [(r"^(\s*)(?:export\s+)?function\s+([A-Za-z_$]\w*)\s*\(([^)]*)\)", "函数", "function"),
                       (r"^(\s*)(?:export\s+)?class\s+([A-Za-z_$]\w*)", "类", "class")],
        "typescript": [(r"^(\s*)(?:export\s+)?function\s+([A-Za-z_$]\w*)\s*\(([^)]*)\)", "函数", "function"),
                       (r"^(\s*)(?:export\s+)?class\s+([A-Za-z_$]\w*)", "类", "class")],
        "java": [(r"^\s*(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(([^)]*)\)\s*\{", "方法", "method"),
                 (r"^\s*(?:public|private)?\s*class\s+(\w+)", "类", "class")],
        "go": [(r"^func\s+(\w+)\s*\(([^)]*)\)", "函数", "func")],
        "rust": [(r"^\s*(?:pub\s+)?fn\s+(\w+)\s*\(([^)]*)\)", "函数", "fn")],
    }
    rules = pats.get(language)
    if not rules:
        return out
    for i, ln in enumerate(code.split("\n"), start=1):
        for rx, kind, _tag in rules:
            m = re.match(rx, ln)
            if not m:
                continue
            groups = m.groups()
            # java/go/rust 的元组结构与 python/js 不同，这里统一取「名字」和「参数」
            if language in ("python", "javascript", "typescript"):
                name, args_raw = groups[1], groups[2]
            elif language == "java":
                name = groups[0]
                args_raw = groups[1] if len(groups) > 1 else ""
                kind = "类" if not args_raw and "class" in ln else kind
            else:
                name = groups[0]
                args_raw = groups[1] if len(groups) > 1 else ""
            args = [a.strip().split(":")[0].split("=")[0].strip().lstrip("*")
                    for a in (args_raw or "").split(",") if a.strip()]
            out.append({"line": i, "name": name, "kind": kind, "args": args})
            break
    return out


@endpoint(("POST",))
def ai_optimize(request):
    """性能优化建议（第 56 条）：静态分析给确定性建议 + LLM 给深度建议。

    本地降级质量较高——基于圈复杂度、嵌套深度、循环内操作等给出可操作建议。
    """
    source_code = _code_arg(request)
    language = rt.normalize_language(opt_str(request, "language", "python"))

    clues = _local_optimize_hints(source_code, language)

    prompt = (
        f"下面是一段 {_LANG_HINT.get(language, language)} 代码，请给出性能与可维护性优化建议。\n"
        "要求：分点列出，每点说明「问题 → 为什么慢/难维护 → 怎么改」，可给代码片段。\n"
        "如果代码已经不错，就直接说没什么大问题，不要硬凑。\n\n"
        f"```{language}\n{source_code[:12000]}\n```"
    )
    text, meta = _call_llm(
        prompt, system="你是性能优化专家，建议具体可执行，避免空泛套话。", max_tokens=2500
    )

    if text is not None:
        return ok({
            "advice": text.strip(), "mode": "llm", "meta": meta,
            "local_hints": clues,
        })

    # ---- 本地降级：结构化建议清单 ----
    if not clues:
        advice = "本段代码未发现明显的性能或结构问题。"
    else:
        parts = ["本地静态分析发现的优化点：", ""]
        for i, c in enumerate(clues, start=1):
            parts.append(f"{i}. 【{c['level']}】{c['issue']}")
            parts.append(f"   位置：第 {c['line']} 行")
            parts.append(f"   建议：{c['suggestion']}")
            parts.append("")
        advice = "\n".join(parts)

    return ok({
        "advice": advice, "mode": "local", "local_hints": clues,
        "meta": {"ok": False, "error": meta.get("error", ""), "provider": "none"},
        "note": "本地降级：基于静态分析的确定性建议，未调用大模型。",
    })


def _local_optimize_hints(code, language):
    """本地优化检查：返回 [{level, line, issue, suggestion}]。"""
    hints = []
    lines = code.split("\n")
    complexity = rt.estimate_complexity(code, language)
    depth = complexity.get("max_depth", 0) or 0

    if depth >= 4:
        hints.append({
            "level": "中", "line": 1,
            "issue": f"嵌套深度达 {depth} 层，可读性差且影响分支预测",
            "suggestion": "用「卫语句提前 return」或抽取子函数降低嵌套。",
        })

    # 循环内重复计算 / 查找
    for i, ln in enumerate(lines, start=1):
        s = ln.strip()
        # Python: for 循环里做 len()/range(len())
        if re.search(r"for\s+\w+\s+in\s+range\(len\(", s):
            hints.append({
                "level": "低", "line": i,
                "issue": "使用 range(len(x)) 索引遍历",
                "suggestion": "改为 `for item in x:` 或 `for i, item in enumerate(x):`，更快更清晰。",
            })
        # 循环内字符串拼接
        if re.match(r"^\s*\w+\s*\+=\s*[\"']", s):
            hints.append({
                "level": "中", "line": i,
                "issue": "循环内用 += 拼接字符串",
                "suggestion": "改用列表收集后 `''.join(items)`，避免 O(n²) 反复分配。",
            })
        # 在循环里查询/IO
        if re.search(r"\.(query|filter|get|find|save|read|write)\(", s):
            hints.append({
                "level": "高", "line": i,
                "issue": "疑似在循环内执行 IO / 数据库操作",
                "suggestion": "批量预处理或移出循环（如一次性查出后建索引 dict）。",
            })
        # 重复 list 成员判断
        if re.search(r"if\s+\w+\s+in\s+\w+\.keys\(\)", s):
            hints.append({
                "level": "低", "line": i,
                "issue": "`in dict.keys()` 多余",
                "suggestion": "直接用 `if key in dict:`，少一次视图对象构造。",
            })
        # 全局变量在内层修改
        if re.match(r"^\s*global\s+", s):
            hints.append({
                "level": "低", "line": i,
                "issue": "使用 global 修改全局状态",
                "suggestion": "改用参数传递或类封装，避免隐式耦合与并发问题。",
            })

    # Python 特有：异常控制的循环
    if language == "python":
        if re.search(r"except\s*:", code):
            for i, ln in enumerate(lines, start=1):
                if re.match(r"^\s*except\s*:", ln):
                    hints.append({
                        "level": "中", "line": i,
                        "issue": "裸 except 会吞掉所有异常（含 KeyboardInterrupt）",
                        "suggestion": "明确捕获具体异常类型，或至少写 `except Exception:`。",
                    })
                    break

    # 圈复杂度告警
    cc = complexity.get("cyclomatic", 0) or 0
    if cc >= 15:
        hints.append({
            "level": "高", "line": 1,
            "issue": f"圈复杂度 {cc} 偏高",
            "suggestion": "按职责拆分函数，每个函数控制在一个逻辑分支组内。",
        })

    # 去重（按行+问题）
    seen = set()
    uniq = []
    for h in hints:
        k = (h["line"], h["issue"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    return uniq[:20]


@endpoint(("POST",))
def ai_testgen(request):
    """单元测试生成（第 52 条）：为函数生成测试骨架。

    本地降级产出可直接跑的 pytest/unittest 骨架（含边界用例提示），
    不含真实断言——断言需要理解业务语义，交给人工或 LLM 更诚实。
    """
    source_code = _code_arg(request)
    language = rt.normalize_language(opt_str(request, "language", "python"))
    framework = opt_str(request, "framework", "")

    if not framework:
        framework = {
            "python": "pytest", "javascript": "jest", "typescript": "jest",
            "java": "junit", "go": "gotest", "rust": "rusttest",
        }.get(language, "generic")

    prompt = (
        f"为下面的 {_LANG_HINT.get(language, language)} 代码生成单元测试，"
        f"测试框架用 {framework}。\n"
        "要求：覆盖正常路径、边界值、异常路径；测试函数命名清晰；"
        "只输出测试代码，不要解释、不要 markdown 代码块。\n\n"
        f"```{language}\n{source_code[:12000]}\n```"
    )
    text, meta = _call_llm(
        prompt, system="你是测试工程师，写出的测试要能直接跑起来。", max_tokens=3000
    )
    if text is not None:
        return ok({"code": _strip_fence(text), "language": language,
                   "framework": framework, "mode": "llm", "meta": meta})

    # ---- 本地降级：生成骨架 ----
    defs = _scan_defs(source_code, language)
    skeleton = _local_test_skeleton(language, framework, defs)
    return ok({
        "code": skeleton, "language": language, "framework": framework,
        "mode": "local", "function_count": len(defs),
        "meta": {"ok": False, "error": meta.get("error", ""), "provider": "none"},
        "note": "本地降级：已生成可运行的测试骨架，断言需按业务语义补全。",
    })


def _local_test_skeleton(language, framework, defs):
    """按语言生成测试骨架。"""
    if language == "python":
        head = [
            "import pytest",
            "",
            "# 假设被测代码在同一目录，按实际模块名调整导入",
            "# from solution import *",
            "",
        ]
        if not defs:
            return "\n".join(head + [
                "def test_todo():",
                "    # 未识别到可测函数，请手动补充",
                "    assert True",
            ])
        body = []
        for d in defs[:20]:
            if d["kind"] == "类":
                continue
            name = d["name"]
            if name.startswith("_"):
                continue
            body.append(f"def test_{name}_normal():")
            body.append(f"    # TODO: 构造 {name} 的正常输入")
            body.append('    # result = {n}(...)'.format(n=name))
            body.append("    # assert result == 期望值")
            body.append("    assert True  # 占位，请替换为真实断言")
            body.append("")
            if d.get("args"):
                body.append(f"def test_{name}_edge_cases():")
                body.append(f"    # TODO: 边界值测试 —— 参数：{', '.join(d['args'])}")
                body.append("    # 例：空值 / 零 / 最大最小 / 非法类型")
                body.append("    assert True  # 占位")
                body.append("")
            body.append(f"def test_{name}_raises():")
            body.append("    # TODO: 异常路径，非法输入应抛错")
            body.append("    # with pytest.raises(ValueError):")
            body.append(f"    #     {name}(非法参数)")
            body.append("    assert True  # 占位")
            body.append("")
        return "\n".join(head + body)

    if language in ("javascript", "typescript"):
        head = [
            "// 按实际路径调整导入",
            "// const { fn } = require('./solution')",
            "",
        ]
        body = []
        for d in defs[:20]:
            if d["kind"] != "函数" or d["name"].startswith("_"):
                continue
            body += [
                f"describe('{d['name']}', () => {{",
                f"  test('正常路径', () => {{",
                "    // TODO: 构造输入并断言",
                "    expect(true).toBe(true)",
                "  })",
                "",
                "  test('边界值', () => {",
                f"    // 参数：{', '.join(d.get('args') or []) or '（无参）'}",
                "    expect(true).toBe(true)",
                "  })",
                "})",
                "",
            ]
        return "\n".join(head + (body or ["test('todo', () => { expect(true).toBe(true) })"]))

    if language == "go":
        head = ["package main", "", 'import "testing"', ""]
        body = []
        for d in defs[:20]:
            if d["kind"] != "函数" or d["name"].startswith("_"):
                continue
            body += [
                f"func Test{d['name'].capitalize()}(t *testing.T) {{",
                "    // TODO: 构造输入并断言",
                "    _ = t",
                "}",
                "",
            ]
        return "\n".join(head + (body or ["func TestTodo(t *testing.T) { _ = t }"]))

    if language == "rust":
        return "\n".join([
            "#[cfg(test)]",
            "mod tests {",
            "    use super::*;",
            "",
            f"    // 框架：{framework}",
        ] + [
            f"    #[test]\n    fn test_{d['name']}() {{\n        // TODO: 断言\n    }}\n"
            for d in defs[:20] if d["kind"] == "函数" and not d["name"].startswith("_")
        ] + ["}"])

    if language == "java":
        return "\n".join([
            "import org.junit.jupiter.api.Test;",
            "import static org.junit.jupiter.api.Assertions.*;",
            "",
            "class SolutionTest {",
        ] + [
            f"    @Test\n    void test{d['name'].capitalize()}() {{\n        // TODO: 断言\n    }}\n"
            for d in defs[:20] if d["kind"] == "方法" and not d["name"].startswith("_")
        ] + ["}"])

    return (
        "// 本地降级：该语言暂未内置测试骨架模板\n"
        "// 建议手动编写测试，或配置 LLM_API_KEY 后使用 AI 生成\n"
    )


@endpoint(("POST",))
def ai_summary(request):
    """代码摘要（第 57 条）：一句话说明这段代码在干嘛。

    本地降级：基于静态分析生成结构化摘要（规模/结构/复杂度/风险点），
    虽然没有自然语言那么顺，但信息量足够。
    """
    source_code = _code_arg(request)
    language = rt.normalize_language(opt_str(request, "language", "python"))

    prompt = (
        f"用中文概括下面这段 {_LANG_HINT.get(language, language)} 代码的功能。\n"
        "要求：先用一句话说清「它做什么」，再列 2-4 条要点（关键流程/输入输出/依赖）。\n"
        "不要逐行翻译，不要复述语法。\n\n"
        f"```{language}\n{source_code[:12000]}\n```"
    )
    text, meta = _call_llm(
        prompt, system="你是技术写作专家，摘要精准、不啰嗦。", max_tokens=900
    )
    if text is not None:
        return ok({"summary": text.strip(), "mode": "llm", "meta": meta})

    # ---- 本地降级：结构化摘要 ----
    m = rt.analyze_metrics(source_code, language)
    cx = rt.estimate_complexity(source_code, language)
    flow = rt.to_flow_nodes(source_code, language)
    outline = flow.get("nodes", []) if isinstance(flow, dict) else (flow or [])

    kind_names = {"function": "函数", "class": "类", "condition": "条件分支",
                  "loop": "循环", "io": "输入输出", "start": "入口", "end": "结束"}
    kinds = {}
    for n in outline:
        k = n.get("type") or n.get("kind")
        kinds[k] = kinds.get(k, 0) + 1

    summary_lines = [
        f"这是一个 {language} 源码文件，共 {m.get('total_lines', 0)} 行"
        f"（有效代码 {m.get('code_lines', 0)} 行，注释率 {round((m.get('comment_ratio') or 0) * 100)}%）。"
    ]
    struct = "、".join(
        f"{kind_names.get(k, k)} {v} 个" for k, v in kinds.items() if k in kind_names
    )
    if struct:
        summary_lines.append(f"结构：{struct}。")
    if m.get("functions") or m.get("classes"):
        summary_lines.append(
            f"包含 {m.get('functions', 0)} 个函数、{m.get('classes', 0)} 个类。"
        )
    summary_lines.append(
        f"圈复杂度 {cx.get('cyclomatic', m.get('cyclomatic', 0))}，最大嵌套 {cx.get('max_depth', 0)} 层"
        f"{'，检测到递归调用' if cx.get('has_recursion') else ''}。"
    )
    quality = m.get("quality_score")
    if quality is not None:
        summary_lines.append(f"质量评分 {quality}/100。")
        for d in (m.get("deductions") or [])[:3]:
            summary_lines.append(f"  · 扣分：{d}")

    return ok({
        "summary": "\n".join(summary_lines), "mode": "local",
        "metrics": m, "complexity": cx,
        "meta": {"ok": False, "error": meta.get("error", ""), "provider": "none"},
        "note": "本地降级：基于静态分析的结构化摘要，未调用大模型。",
    })


# ============================================================
# 四、分享（第 73/74 条）
# ============================================================


@endpoint(("POST",))
def share_create(request):
    file_id = opt_num(request, "file", integer=True)
    snippet_id = opt_num(request, "snippet", integer=True)
    if not file_id and not snippet_id:
        raise ValueError("必须指定 file 或 snippet")

    f = get_file(request.user, file_id) if file_id else None
    s = None
    if snippet_id:
        s = CodeSnippet.objects.filter(id=snippet_id, owner=request.user).first()
        if not s:
            raise ValueError(f"代码片段不存在或无权访问: {snippet_id}")

    sh = CodeShare.objects.create(
        token=CodeShare.new_token(),
        file=f, snippet=s,
        owner=request.user,
        title=opt_str(request, "title", (f.name if f else s.title))[:200],
        allow_run=opt_bool(request, "allow_run", False),
        allow_download=opt_bool(request, "allow_download", True),
    )
    return ok({"token": sh.token, "url": f"/share/code/{sh.token}/",
               "allow_run": sh.allow_run, "allow_download": sh.allow_download})


@endpoint(("GET",))
def share_list(request):
    qs = CodeShare.objects.filter(owner=request.user)
    items = [{
        "token": s.token,
        "url": f"/share/code/{s.token}/",
        "title": s.title,
        "file": s.file_id,
        "file_path": s.file.path if s.file_id else "",
        "allow_run": s.allow_run,
        "allow_download": s.allow_download,
        "view_count": s.view_count,
        "created_at": s.created_at,
    } for s in qs[:100]]
    return ok({"items": items})


@endpoint(("POST",))
def share_update(request, token):
    sh = CodeShare.objects.filter(token=token, owner=request.user).first()
    if not sh:
        raise ValueError(f"分享不存在: {token}")
    if p(request, "allow_run") is not None:
        sh.allow_run = opt_bool(request, "allow_run")
    if p(request, "allow_download") is not None:
        sh.allow_download = opt_bool(request, "allow_download")
    if p(request, "title") is not None:
        sh.title = str(p(request, "title"))[:200]
    sh.save()
    return ok({"token": sh.token, "allow_run": sh.allow_run,
               "allow_download": sh.allow_download, "title": sh.title})


@endpoint(("POST", "DELETE"))
def share_revoke(request, token):
    n, _ = CodeShare.objects.filter(token=token, owner=request.user).delete()
    return ok({"deleted": n})


# 公开访问视图（无需登录）
def public_share_view(request, token):
    """公开分享页：返回代码内容 + 是否允许运行。

    这是唯一无需鉴权的接口，因此**严格只读**且不返回任何用户敏感信息。
    """
    from django.http import JsonResponse
    sh = CodeShare.objects.filter(token=token).first()
    if not sh:
        return JsonResponse({"ok": False, "error": "分享链接不存在或已失效"}, status=404)
    if sh.expires_at and sh.expires_at < timezone.now():
        return JsonResponse({"ok": False, "error": "分享链接已过期"}, status=410)

    CodeShare.objects.filter(id=sh.id).update(view_count=sh.view_count + 1)

    if sh.file_id:
        f = sh.file
        payload = {
            "kind": "file", "title": sh.title or f.name,
            "language": f.language, "code": f.content,
            "lines": f.lines, "allow_run": sh.allow_run,
            "allow_download": sh.allow_download,
        }
    else:
        s = sh.snippet
        payload = {
            "kind": "snippet", "title": sh.title or s.title,
            "language": s.language, "code": s.code,
            "lines": (s.code or "").count("\n") + 1,
            "allow_run": sh.allow_run,
            "allow_download": sh.allow_download,
        }
    return JsonResponse({"ok": True, "data": payload})


def public_share_run(request, token):
    """公开分享页的「在线运行」（无需登录）。

    安全约束（比登录态运行更严）：
    - 只执行**分享内容本身**，忽略请求体里的 code —— 防止把分享当免费代码执行器
    - 必须 share.allow_run 为真
    - 超时上限压到 10s，且不允许 allow_dangerous 绕过高危扫描
    - 不落 CodeRun 历史（没有 owner），只返回执行结果
    """
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "仅支持 POST"}, status=405)

    sh = CodeShare.objects.filter(token=token).first()
    if not sh:
        return JsonResponse({"ok": False, "error": "分享链接不存在或已失效"}, status=404)
    if sh.expires_at and sh.expires_at < timezone.now():
        return JsonResponse({"ok": False, "error": "分享链接已过期"}, status=410)
    if not sh.allow_run:
        return JsonResponse({"ok": False, "error": "该分享未开放在线运行"}, status=403)

    if sh.file_id:
        language, code = sh.file.language, sh.file.content
    else:
        language, code = sh.snippet.language, sh.snippet.code

    try:
        body = json.loads(request.body or b"{}")
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    stdin = str(body.get("stdin") or "")[:10000]

    # 公开通道不允许绕过高危扫描
    hits = rt.scan_dangerous(code)
    if hits:
        return JsonResponse({"ok": True, "data": {
            "status": "rejected", "rejected": True, "dangerous": hits,
            "stdout": "", "stderr": "检测到高危操作，已拒绝执行：\n"
            + "\n".join(f"  · {h['reason']}" for h in hits),
            "exit_code": -1, "duration_ms": 0,
        }})

    result = rt.run_code(language, code, stdin=stdin, timeout=10)
    return JsonResponse({"ok": True, "data": result})


# ============================================================
# AI 代码评审（#62）
# ============================================================


@endpoint(("POST",))
def ai_review(request):
    """AI 代码评审：生成 review 意见。

    POST {"code": "...", "language": "python"}
    有 Key 时由大模型评审；无 Key 时用静态分析规则生成 review。
    """
    language, code = _read_code(request)
    if not code.strip():
        raise ValueError("代码不能为空")

    metrics = rt.analyze_metrics(code, language)
    issues = _lint_issues(code, language, metrics)

    review = {
        "language": language,
        "score": metrics["quality_score"],
        "summary": "",
        "comments": [],
        "strengths": [],
        "suggestions": [],
        "provider": "local",
    }

    # 本地降级：基于规则生成评审意见
    by_sev = {"error": 0, "warning": 0, "info": 0}
    for it in issues:
        by_sev[it["severity"]] = by_sev.get(it["severity"], 0) + 1
        review["comments"].append({
            "line": it.get("line", 0),
            "severity": it["severity"],
            "message": it.get("message", ""),
        })
    if by_sev["error"]:
        review["summary"] = f"发现 {by_sev['error']} 个错误级问题，建议优先修复。"
    elif by_sev["warning"]:
        review["summary"] = f"代码可运行，但有 {by_sev['warning']} 个警告值得关注。"
    else:
        review["summary"] = "整体质量良好，未发现明显问题。"

    if metrics["comment_ratio"] < 0.05:
        review["suggestions"].append("注释偏少，建议补充关键函数与复杂逻辑的说明。")
    if metrics["avg_complexity"] > 6:
        review["suggestions"].append(f"平均圈复杂度 {metrics['avg_complexity']:.1f} 偏高，建议拆分长函数。")
    if metrics.get("todos"):
        review["suggestions"].append(f"代码中存在 {metrics['todos']} 处 TODO/FIXME，请跟进。")
    review["strengths"] = [s for s in (
        "代码结构清晰" if metrics["avg_complexity"] <= 6 else None,
        "命名规范" if not any(i.get("severity") == "error" for i in issues) else None,
        "注释充分" if metrics["comment_ratio"] >= 0.1 else None,
    ) if s]

    # 有 Key 时用大模型增强
    if llm.is_configured():
        prompt = (
            f"你是资深代码评审。请评审下面{language}代码，给出简短结论、3-5 条具体意见（含行号）、"
            "优点与改进建议。严格输出 JSON："
            '{"summary":"...","comments":[{"line":n,"severity":"error|warning|info","message":"..."}],'
            '"strengths":["..."],"suggestions":["..."]}\n\n'
            f"代码：\n{code[:4000]}"
        )
        parsed, result = llm.chat_json(
            [{"role": "system", "content": "你是严谨的代码评审专家。"},
             {"role": "user", "content": prompt}],
            fallback=None,
        )
        if isinstance(parsed, dict):
            review["summary"] = str(parsed.get("summary") or review["summary"])[:500]
            if isinstance(parsed.get("comments"), list):
                review["comments"] = [
                    {"line": int(c.get("line", 0) or 0),
                     "severity": str(c.get("severity", "info")),
                     "message": str(c.get("message", ""))[:300]}
                    for c in parsed["comments"] if isinstance(c, dict)
                ][:20]
            if isinstance(parsed.get("strengths"), list):
                review["strengths"] = [str(s)[:200] for s in parsed["strengths"]][:5]
            if isinstance(parsed.get("suggestions"), list):
                review["suggestions"] = [str(s)[:200] for s in parsed["suggestions"]][:5]
            review["provider"] = result.get("provider", "llm")
    return ok(review)
