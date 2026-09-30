"""AI 创作工具：LLM 包装 + 本地降级实现（F647 翻译 / F648 起名 / F649 周报 /
F650 邮件 / F651 社交文案 / F653 算式分步讲解 / F656 会议议程）

约定
----
- 每个工具都有本地实现：无 LLM 密钥时同样返回可用结果，并标记 ``degraded=True``；
  有密钥时优先走大模型，失败（网络/超时/空回复）时自动回落到本地实现，绝不抛异常给用户。
- 算式讲解用 ``ast`` 白名单求值，不使用 ``eval``，非法/危险表达式抛 ValueError → 400。
"""
from __future__ import annotations

import ast
import random
import re

from assistant import llm

MAX_INPUT = 4000


# ---------------------------------------------------------------------------
# 公共：LLM 尝试
# ---------------------------------------------------------------------------

def try_llm(feature: str, system: str, prompt: str, user_id=None, temperature: float = 0.7):
    """尝试调用大模型；返回 (text|None, meta)。text 为 None 时调用方走本地降级。"""
    if not llm.is_configured():
        return None, {"provider": "local", "model": "local-template",
                      "fallback_reason": "未配置 LLM_API_KEY，已降级为本地实现"}
    res = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=temperature,
    )
    llm.log_usage(user_id, feature, res, len(prompt), len(res.get("content") or ""))
    text = (res.get("content") or "").strip()
    if res["ok"] and text:
        return text, {"provider": "llm", "model": res.get("model", ""), "fallback_reason": ""}
    return None, {"provider": "local", "model": res.get("model") or "local-template",
                  "fallback_reason": res.get("error", "") or "大模型返回为空，已降级"}


def degraded(meta: dict, text, **extra) -> dict:
    out = {"text": text, "degraded": True, "provider": "local",
           "model": "local-template", "fallback_reason": meta.get("fallback_reason", "")}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# F647 多语翻译（中/英/日/韩）：内置小型词典 + 逐词降级
# ---------------------------------------------------------------------------

# (中文, 英文, 日文, 韩文) —— 覆盖日常高频词，查不到的词原样保留（逐词降级）
_LEX_ROWS = [
    ("你好", "Hello", "こんにちは", "안녕하세요"),
    ("谢谢", "Thank you", "ありがとう", "감사합니다"),
    ("再见", "Goodbye", "さようなら", "안녕히 가세요"),
    ("早上好", "Good morning", "おはようございます", "좋은 아침입니다"),
    ("晚上好", "Good evening", "こんばんは", "좋은 저녁입니다"),
    ("对不起", "Sorry", "すみません", "죄송합니다"),
    ("没关系", "It's okay", "大丈夫です", "괜찮아요"),
    ("请问", "Excuse me", "ちょっとお尋ねします", "잠시 묻겠습니다"),
    ("是的", "Yes", "はい", "네"),
    ("不是", "No", "いいえ", "아니요"),
    ("请", "Please", "どうぞ", "제발"),
    ("帮助", "Help", "助け", "도움"),
    ("我们", "We", "私たち", "우리"),
    ("你们", "You", "あなたたち", "너희"),
    ("他们", "They", "彼ら", "그들"),
    ("今天", "Today", "今日", "오늘"),
    ("明天", "Tomorrow", "明日", "내일"),
    ("昨天", "Yesterday", "昨日", "어제"),
    ("时间", "Time", "時間", "시간"),
    ("工作", "Work", "仕事", "일"),
    ("学习", "Study", "勉強", "학습"),
    ("会议", "Meeting", "会議", "회의"),
    ("项目", "Project", "プロジェクト", "프로젝트"),
    ("任务", "Task", "タスク", "작업"),
    ("笔记", "Note", "メ모", "노트"),
    ("文件", "File", "ファイル", "파일"),
    ("问题", "Question", "問題", "문제"),
    ("回答", "Answer", "答え", "답변"),
    ("喜欢", "Like", "好き", "좋아하다"),
    ("爱", "Love", "愛する", "사랑하다"),
    ("高兴", "Happy", "嬉しい", "기쁘다"),
    ("开心", "Glad", "楽しい", "즐겁다"),
    ("难过", "Sad", "悲しい", "슬프다"),
    ("朋友", "Friend", "友達", "친구"),
    ("家人", "Family", "家族", "가족"),
    ("老师", "Teacher", "先生", "선생님"),
    ("学生", "Student", "学生", "학생"),
    ("公司", "Company", "会社", "회사"),
    ("产品", "Product", "製品", "제품"),
    ("服务", "Service", "サービス", "서비스"),
    ("系统", "System", "システム", "시스템"),
    ("数据", "Data", "データ", "데이터"),
    ("分析", "Analysis", "分析", "분석"),
    ("报告", "Report", "報告", "보고서"),
    ("计划", "Plan", "計画", "계획"),
    ("目标", "Goal", "目標", "목표"),
    ("结果", "Result", "結果", "결과"),
    ("方法", "Method", "方法", "방법"),
    ("内容", "Content", "内容", "내용"),
    ("开始", "Start", "始まる", "시작하다"),
    ("结束", "Finish", "終わる", "끝나다"),
    ("完成", "Done", "完了", "완료"),
    ("进行", "Proceed", "進む", "진행"),
    ("需要", "Need", "必要", "필요"),
    ("可以", "Can", "できる", "할 수 있다"),
    ("应该", "Should", "べきです", "해야 합니다"),
    ("非常", "Very", "とても", "매우"),
    ("重要", "Important", "重要", "중요"),
    ("简单", "Simple", "簡単", "단순하다"),
    ("快速", "Fast", "速い", "빠르다"),
    ("很好", "Very good", "とても良い", "아주 좋습니다"),
    ("加油", "Come on", "頑張って", "힘내세요"),
    ("欢迎", "Welcome", "ようこそ", "환영합니다"),
    ("消息", "Message", "メッセージ", "메시지"),
    ("通知", "Notification", "通知", "알림"),
    ("公告", "Announcement", "お知らせ", "공지"),
    ("搜索", "Search", "検索", "검색"),
    ("摘要", "Summary", "要約", "요약"),
    ("翻译", "Translate", "翻訳", "번역"),
    ("生成", "Generate", "生成", "생성"),
    ("保存", "Save", "保存", "저장"),
    ("删除", "Delete", "削除", "삭제"),
    ("更新", "Update", "更新", "업데이트"),
    ("创建", "Create", "作成", "생성하다"),
    ("查看", "View", "見る", "보기"),
    ("下载", "Download", "ダウンロード", "다운로드"),
    ("上传", "Upload", "アップロード", "업로드"),
    ("分享", "Share", "共有", "공유"),
    ("设置", "Settings", "設定", "설정"),
    ("登录", "Login", "ログイン", "로그인"),
    ("首页", "Home", "ホーム", "홈"),
    ("本周", "This week", "今週", "이번 주"),
    ("下周", "Next week", "来週", "다음 주"),
    ("上午", "Morning", "午前", "오전"),
    ("下午", "Afternoon", "午後", "오후"),
    ("星期一", "Monday", "月曜日", "월요일"),
    ("星期二", "Tuesday", "火曜日", "화요일"),
    ("星期三", "Wednesday", "水曜日", "수요일"),
    ("星期四", "Thursday", "木曜일", "목요일"),
    ("星期五", "Friday", "金曜日", "금요일"),
    ("水", "Water", "水", "물"),
    ("火", "Fire", "火", "불"),
    ("山", "Mountain", "山", "산"),
    ("河", "River", "川", "강"),
    ("花", "Flower", "花", "꽃"),
    ("树", "Tree", "木", "나무"),
    ("吃", "Eat", "食べる", "먹다"),
    ("喝", "Drink", "飲む", "마시다"),
    ("走", "Walk", "歩く", "걷다"),
    ("看", "Look", "見る", "보다"),
    ("听", "Listen", "聞く", "듣다"),
    ("说", "Say", "言う", "말하다"),
    ("写", "Write", "書く", "쓰다"),
    ("读", "Read", "読む", "읽다"),
    ("想", "Think", "思う", "생각하다"),
    ("做", "Do", "する", "하다"),
    ("去", "Go", "行く", "가다"),
    ("来", "Come", "来る", "오다"),
    ("大", "Big", "大きい", "크다"),
    ("小", "Small", "小さい", "작다"),
    ("多", "Many", "多い", "많다"),
    ("少", "Few", "少ない", "적다"),
    ("好", "Good", "良い", "좋다"),
    ("新", "New", "新しい", "새롭다"),
    ("旧", "Old", "古い", "오래되다"),
    ("人", "Person", "人", "사람"),
    ("中国", "China", "中国", "중국"),
    ("北京", "Beijing", "北京", "베이징"),
    ("上海", "Shanghai", "上海", "상하이"),
    ("世界", "World", "世界", "세계"),
    ("天气", "Weather", "天気", "날씨"),
    ("饭", "Meal", "ご飯", "밥"),
    ("茶", "Tea", "お茶", "차"),
    ("咖啡", "Coffee", "コーヒー", "커피"),
    ("面包", "Bread", "パン", "빵"),
    ("苹果", "Apple", "りんご", "사과"),
]

LANG_INDEX = {}  # lang -> {word: translation}
ZH_INDEX = {}    # 中文 -> {lang: translation}
for _zh, _en, _ja, _ko in _LEX_ROWS:
    ZH_INDEX[_zh] = {"en": _en, "ja": _ja, "ko": _ko}
    for _lang, _word in (("en", _en), ("ja", _ja), ("ko", _ko)):
        LANG_INDEX.setdefault(_lang, {})[_word.lower()] = _zh

SUPPORTED_LANGS = {"zh": "中文", "en": "English", "ja": "日本語", "ko": "한국어"}

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z']+|[^A-Za-z']+")
_ZH_KEYS = sorted(ZH_INDEX, key=len, reverse=True)


def _segment_zh(text: str):
    """中文贪心最长匹配切词：返回 [(片段, 是否命中词典)]，未命中的逐字/逐段保留"""
    out, i = [], 0
    while i < len(text):
        if "\u4e00" <= text[i] <= "\u9fff":
            hit = next((k for k in _ZH_KEYS if text.startswith(k, i)), None)
            if hit:
                out.append((hit, True))
                i += len(hit)
            else:
                out.append((text[i], False))
                i += 1
        else:
            j = i
            while j < len(text) and not ("\u4e00" <= text[j] <= "\u9fff"):
                j += 1
            out.append((text[i:j], False))
            i = j
    return out


def local_translate(text: str, target: str) -> dict:
    """无 LLM 时的逐词翻译：词典命中则替换，未命中原样保留（逐词降级），并统计覆盖率"""
    hits = total = 0

    if target == "zh":
        # 外语 → 中文：英文/日文/韩文整词反查词典；中文原样保留
        parts = []
        for tok in _WORD.findall(text):
            if re.fullmatch(r"[A-Za-z']+", tok):
                total += 1
                zh = (LANG_INDEX["en"].get(tok.lower())
                      or LANG_INDEX.get("ja", {}).get(tok.lower())
                      or LANG_INDEX.get("ko", {}).get(tok.lower()))
                if zh:
                    hits += 1
                    parts.append(zh)
                else:
                    parts.append(tok)
            else:
                parts.append(tok)
                if tok.strip():
                    total += 1
                    hits += 1  # 中文/符号原样保留视为命中
        out = "".join(parts)
    elif _CJK_RUN.search(text):
        # 中文 → 目标语：逐词最长匹配，命中替换，未命中原样保留
        parts = []
        for seg, ok in _segment_zh(text):
            total += 1
            if ok:
                hits += 1
                parts.append(ZH_INDEX.get(seg, {}).get(target, seg))
            else:
                parts.append(seg)
        out = "".join(parts)
    else:
        # 英文 → 日/韩：先 英文→中文，再 中文→目标语；查不到的词保留原文
        parts = []
        for tok in _WORD.findall(text):
            if re.fullmatch(r"[A-Za-z']+", tok):
                total += 1
                zh = LANG_INDEX["en"].get(tok.lower())
                if zh:
                    hits += 1
                    parts.append(ZH_INDEX.get(zh, {}).get(target, zh))
                else:
                    parts.append(tok)
            else:
                parts.append(tok)
        out = "".join(parts)

    return {
        "text": out, "hits": hits, "total": total,
        "coverage": round(hits / total, 2) if total else 0.0,
    }


def translate(text: str, target: str, user_id=None) -> dict:
    target = (target or "en").lower()
    if target not in SUPPORTED_LANGS:
        raise ValueError(f"暂不支持的目标语言：{target}（可选：{', '.join(SUPPORTED_LANGS)}）")
    text = (text or "").strip()[:MAX_INPUT]
    if not text:
        raise ValueError("请输入要翻译的内容")

    meta = {"provider": "local", "model": "local-dict", "fallback_reason": ""}
    if llm.is_configured():
        got, meta = try_llm(
            "translate",
            f"你是专业翻译，把用户给出的内容翻译成 {SUPPORTED_LANGS[target]}，"
            "只输出译文本身，不要解释、不要保留原文。",
            text, user_id, temperature=0.2,
        )
        if got:
            return {"text": got, "degraded": False, "provider": "llm",
                    "model": meta.get("model", ""), "fallback_reason": "",
                    "target": target, "hits": None, "total": None, "coverage": None}

    local = local_translate(text, target)
    return {
        "text": local["text"], "degraded": True, "provider": "local", "model": "local-dict",
        "fallback_reason": meta.get("fallback_reason") or "未配置 LLM_API_KEY，使用内置词典逐词翻译",
        "target": target, "hits": local["hits"], "total": local["total"],
        "coverage": local["coverage"],
    }


# ---------------------------------------------------------------------------
# F648 起名器（人名 / 项目 / 品牌）：本地词库可刷新
# ---------------------------------------------------------------------------

_NAME_BANK = {
    "person": {
        "surnames": ["林", "沈", "顾", "苏", "叶", "程", "宋", "陆", "许", "周", "陈", "白", "江", "夏", "韩", "傅"],
        "given1": ["清", "子", "亦", "知", "思", "雨", "晓", "书", "一", "文", "若", "明", "嘉", "云"],
        "given2": ["言", "然", "舟", "屿", "宁", "安", "和", "深", "辞", "涵", "航", "野", "桐", "音"],
        "en_first": ["Aria", "Evan", "Nova", "Liam", "Iris", "Noel", "Cyan", "Rowan", "Mira", "Theo"],
        "en_last": ["Lin", "Chen", "Walker", "Reed", "Frost", "Hayes", "Quinn", "Sage", "Moon", "Vale"],
    },
    "project": {
        "prefix": ["星火", "青云", "深蓝", "灵犀", "拾光", "北辰", "极光", "知行", "澜图", "云帆"],
        "core": ["看板", "工坊", "引擎", "中枢", "罗盘", "流水线", "工作台", "调度台", "知识库", "仪表盘"],
        "suffix": ["Pro", "Lite", "Hub", "Flow", "OS", "X", "One", "Next"],
        "keywords": ["协同", "智能", "自动化", "实时", "可视化"],
    },
    "brand": {
        "head": ["艾", "欧", "莱", "诺", "妍", "沐", "初", "森", "澜", "珂", "麦", "朵"],
        "tail": ["记", "舍", "坊", "集", "社", "里", "家", "时刻", "实验室", "研究所"],
        "category": ["茶饮", "服饰", "科技", "食品", "家居", "文创", "护肤", "咖啡"],
        "en": ["Lumina", "Verda", "Nestra", "Ori", "Kanso", "Mello", "Fjord", "Solis"],
    },
}

_MEANING = {
    "person": ["清雅内敛", "明朗果敢", "温润如玉", "志向高远", "灵动自由", "沉稳可靠"],
    "project": ["面向团队协作", "强调效率与自动化", "侧重数据可视化", "聚焦实时协同", "轻量可扩展"],
    "brand": ["简洁好记", "有温度感", "偏自然系", "偏国际范", "年轻有活力"],
}


def local_names(kind: str, count: int = 8, seed=None, hint: str = "") -> list[dict]:
    rng = random.Random(seed)
    bank = _NAME_BANK.get(kind, _NAME_BANK["project"])
    out, seen = [], set()
    while len(out) < count * 3 and len(out) < 40:
        if kind == "person":
            if rng.random() < 0.7:
                name = rng.choice(bank["surnames"]) + rng.choice(bank["given1"]) + rng.choice(bank["given2"])
                style = "中文名"
            else:
                name = f"{rng.choice(bank['en_first'])} {rng.choice(bank['en_last'])}"
                style = "英文名"
        elif kind == "brand":
            if rng.random() < 0.5:
                name = rng.choice(bank["head"]) + rng.choice(bank["tail"]) + rng.choice(bank["category"])
                style = "中文品牌"
            else:
                name = rng.choice(bank["en"]) + rng.choice(["", " Lab", " Studio", " Co."])
                style = "英文品牌"
        else:
            roll = rng.random()
            if roll < 0.4:
                name = rng.choice(bank["prefix"]) + rng.choice(bank["core"])
                style = "中文项目名"
            elif roll < 0.75:
                name = rng.choice(bank["keywords"]) + rng.choice(bank["core"])
                style = "描述式"
            else:
                name = rng.choice(bank["prefix"]) + rng.choice(bank["suffix"])
                style = "混合式"
        if hint and kind == "project":
            name = f"{hint}{name}" if rng.random() < 0.35 else name
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "style": style,
                    "note": rng.choice(_MEANING[kind])})
        if len(out) >= count:
            break
    return out


KIND_LABEL = {"person": "人名", "project": "项目名", "brand": "品牌名"}


def gen_names(kind: str, count: int = 8, seed=None, hint: str = "", user_id=None) -> dict:
    kind = (kind or "project").lower()
    if kind not in KIND_LABEL:
        raise ValueError(f"类型只能是 person / project / brand，收到：{kind}")
    count = max(3, min(int(count or 8), 12))
    meta = {"provider": "local", "model": "local-wordbank", "fallback_reason": ""}
    if llm.is_configured():
        got, meta = try_llm(
            "gen_names",
            "你是命名顾问，输出简洁、好记、有寓意的名字。",
            f"请为「{KIND_LABEL[kind]}」生成 {count} 个候选"
            + (f"，主题线索：{hint}" if hint else "")
            + "。严格输出 JSON 数组，每个元素为 {\"name\": \"...\", \"style\": \"...\", \"note\": \"一句话寓意\"}，"
              "不要输出数组以外的内容。",
            user_id, temperature=0.9,
        )
        parsed = _parse_json_array(got) if got else None
        items = []
        for it in parsed or []:
            if isinstance(it, dict) and it.get("name"):
                items.append({"name": str(it["name"])[:40],
                              "style": str(it.get("style") or "")[:20],
                              "note": str(it.get("note") or "")[:60]})
            elif isinstance(it, str) and it.strip():
                items.append({"name": it.strip()[:40], "style": "", "note": ""})
        if items:
            return {"items": items[:count], "kind": kind, "degraded": False,
                    "provider": "llm", "model": meta.get("model", ""), "fallback_reason": "",
                    "seed": seed}
    return {"items": local_names(kind, count, seed=seed, hint=hint), "kind": kind,
            "degraded": True, "provider": "local", "model": "local-wordbank",
            "fallback_reason": meta.get("fallback_reason") or "未配置 LLM_API_KEY，使用本地词库",
            "seed": seed}


def _parse_json_array(raw: str):
    import json
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception:
        s, e = raw.find("["), raw.rfind("]")
        if 0 <= s < e:
            try:
                data = json.loads(raw[s:e + 1])
                return data if isinstance(data, list) else None
            except Exception:
                return None
    return None


# ---------------------------------------------------------------------------
# F649 周报生成器 / F656 会议议程 / F650 邮件草稿 / F651 社交文案（本地模板降级）
# ---------------------------------------------------------------------------

def local_weekly(points, author: str = "", week_label: str = "") -> str:
    points = [str(p).strip() for p in (points or []) if str(p).strip()][:6]
    if not points:
        raise ValueError("至少需要 1 条要点")
    lines = [f"# {week_label or '本周'}工作周报", ""]
    if author:
        lines += [f"> 汇报人：{author}", ""]
    lines.append("## 一、本周要点")
    lines += [f"{i}. {p}" for i, p in enumerate(points, 1)]
    lines += ["", "## 二、进展说明"]
    lines += [f"- {p}：按计划推进，已完成阶段性产出，关键结果已同步相关同事。" for p in points]
    lines += ["", "## 三、风险与需要的支持",
              "- 需求变更与跨模块联调是主要风险点，已提前沟通对齐。",
              "- 如遇资源冲突，将优先保障本周里程碑。", "", "## 四、下周计划"]
    lines += [f"- 继续推进：{p}" for p in points[:3]]
    lines.append(f"- 预留 20% 机动时间处理临时事项。")
    return "\n".join(lines)


def weekly_report(points, author="", week_label="", user_id=None) -> dict:
    points = [str(p).strip() for p in (points or []) if str(p).strip()][:6]
    if not points:
        raise ValueError("请先填写 1-6 条本周要点")
    meta = {"provider": "local", "model": "local-template", "fallback_reason": ""}
    if llm.is_configured():
        got, meta = try_llm(
            "weekly_report",
            "你是职场写作助手，输出结构清晰的 Markdown 工作周报。",
            f"请根据下面的要点写一份工作周报（含本周要点/进展/风险/下周计划）。"
            + (f"汇报人：{author}。" if author else "")
            + f"周次：{week_label or '本周'}。\n要点：\n- " + "\n- ".join(points),
            user_id, temperature=0.5,
        )
        if got:
            return {"text": got, "degraded": False, "provider": "llm",
                    "model": meta.get("model", ""), "fallback_reason": "", "points": points}
    return {"text": local_weekly(points, author, week_label), "degraded": True,
            "provider": "local", "model": "local-template",
            "fallback_reason": meta.get("fallback_reason") or "未配置 LLM_API_KEY，使用本地周报模板",
            "points": points}


AGENDA_TEMPLATE = [
    ("开场与议程确认", 0.10, "主持人介绍议题、目标与时间规则"),
    ("背景与现状回顾", 0.15, "简要回顾上期结论与当前进展"),
    ("核心议题讨论一", 0.25, "围绕第一个议题充分讨论，记录分歧点"),
    ("核心议题讨论二", 0.20, "围绕第二个议题或备选方案讨论"),
    ("决议与行动项确认", 0.20, "逐条确认决议、责任人与截止时间"),
    ("总结与散会", 0.10, "总结结论、确认下次会议时间"),
]


def local_agenda(topic: str, minutes: int) -> list[dict]:
    minutes = max(10, min(int(minutes), 480))
    items, allocated = [], 0
    for i, (name, ratio, note) in enumerate(AGENDA_TEMPLATE):
        dur = minutes - allocated if i == len(AGENDA_TEMPLATE) - 1 else int(round(minutes * ratio))
        dur = max(1, dur)
        allocated += dur
        items.append({"title": name, "minutes": dur, "note": note, "topic": topic})
    # 修正累计误差，使总时长严格等于 minutes
    diff = minutes - sum(x["minutes"] for x in items)
    if diff:
        items[-1]["minutes"] = max(1, items[-1]["minutes"] + diff)
    start = 0
    for it in items:
        it["start"] = start
        it["range"] = f"{_fmt_min(start)}–{_fmt_min(start + it['minutes'])}"
        start += it["minutes"]
    return items


def _fmt_min(m: int) -> str:
    h, mm = divmod(int(m), 60)
    return f"{h}:{mm:02d}"


def agenda(topic: str, minutes, user_id=None) -> dict:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("请填写会议主题")
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise ValueError("会议时长需为分钟数（整数）")
    if minutes < 5 or minutes > 480:
        raise ValueError("会议时长需在 5-480 分钟之间")

    meta = {"provider": "local", "model": "local-template", "fallback_reason": ""}
    if llm.is_configured():
        got, meta = try_llm(
            "agenda",
            "你是资深会议主持人，输出分钟级议程。",
            f"会议主题：{topic}，总时长 {minutes} 分钟。请输出议程，"
            '严格 JSON：{"items":[{"title":"环节","minutes":10,"note":"要点"}]}，'
            "各环节分钟数之和必须等于总时长。",
            user_id, temperature=0.4,
        )
        import json
        parsed = None
        if got:
            try:
                parsed = json.loads(got)
            except Exception:
                parsed = None
        items = []
        if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
            for it in parsed["items"][:12]:
                if isinstance(it, dict) and it.get("title"):
                    items.append({"title": str(it["title"])[:60],
                                  "minutes": max(1, int(it.get("minutes") or 1)),
                                  "note": str(it.get("note") or "")[:200]})
            if items and sum(i["minutes"] for i in items) != minutes:
                # 模型给的时长不守恒 → 归一化到总时长
                total = sum(i["minutes"] for i in items)
                acc = 0
                for i, it in enumerate(items):
                    if i == len(items) - 1:
                        it["minutes"] = max(1, minutes - acc)
                    else:
                        it["minutes"] = max(1, round(minutes * it["minutes"] / total))
                        acc += it["minutes"]
        if items:
            start = 0
            for it in items:
                it["start"] = start
                it["range"] = f"{_fmt_min(start)}–{_fmt_min(start + it['minutes'])}"
                start += it["minutes"]
            return {"topic": topic, "minutes": minutes, "items": items, "degraded": False,
                    "provider": "llm", "model": meta.get("model", ""), "fallback_reason": ""}
    return {"topic": topic, "minutes": minutes,
            "items": local_agenda(topic, minutes), "degraded": True,
            "provider": "local", "model": "local-template",
            "fallback_reason": meta.get("fallback_reason") or "未配置 LLM_API_KEY，使用本地议程模板"}


EMAIL_TONES = {
    "formal": "正式", "neutral": "平实", "friendly": "亲切", "urgent": "紧急",
}

def _local_email(scene: str, tone: str, to: str, key_points, extra: str) -> str:
    tone_open = {
        "formal": "您好：",
        "neutral": "你好：",
        "friendly": "嗨，",
        "urgent": "您好（紧急）：",
    }.get(tone, "您好：")
    points = [str(p).strip() for p in (key_points or []) if str(p).strip()][:6]
    body = []
    if scene:
        body.append(f"关于「{scene}」，现将相关情况说明如下：")
    for i, p in enumerate(points, 1):
        body.append(f"{i}. {p}")
    if extra:
        body.append(extra)
    if not body:
        body.append("详见附件与后续沟通，如有疑问请随时回复本邮件。")
    close = {
        "formal": "以上，请审阅。此致\n敬礼",
        "neutral": "如有疑问请随时告知，谢谢。",
        "friendly": "有问题随时找我哈，谢谢！",
        "urgent": "情况紧急，烦请尽快反馈，谢谢！",
    }.get(tone, "如有疑问请随时告知，谢谢。")
    subject = f"【{tone and EMAIL_TONES.get(tone, '通知')}】{scene or '工作沟通'}"
    return "\n".join([
        f"主题：{subject}",
        f"收件人：{to or '（请填写）'}",
        "",
        tone_open,
        "",
        *[ln for ln in body],
        "",
        close,
    ])


def email_draft(scene, tone="neutral", to="", key_points=None, extra="", user_id=None) -> dict:
    scene = (scene or "").strip()
    if not scene:
        raise ValueError("请填写使用场景（例如：项目进度汇报）")
    tone = (tone or "neutral").lower()
    if tone not in EMAIL_TONES:
        raise ValueError(f"语气只能是：{', '.join(EMAIL_TONES)}")
    meta = {"provider": "local", "model": "local-template", "fallback_reason": ""}
    if llm.is_configured():
        got, meta = try_llm(
            "email_draft",
            "你是商务邮件写作助手，输出可直接发送的邮件草稿。",
            f"场景：{scene}；语气：{EMAIL_TONES[tone]}；收件人：{to or '同事'}；"
            f"要点：{'、'.join(str(p) for p in (key_points or [])) or '（无）'}；补充：{extra or '无'}。\n"
            "输出格式：第一行「主题：xxx」，随后是邮件正文。",
            user_id, temperature=0.6,
        )
        if got:
            return {"text": got, "degraded": False, "provider": "llm",
                    "model": meta.get("model", ""), "fallback_reason": "",
                    "scene": scene, "tone": tone}
    return {"text": _local_email(scene, tone, to, key_points, extra), "degraded": True,
            "provider": "local", "model": "local-template",
            "fallback_reason": meta.get("fallback_reason") or "未配置 LLM_API_KEY，使用本地邮件模板",
            "scene": scene, "tone": tone}


SOCIAL_STYLES = {
    "fresh": "清新简洁", "energetic": "活力种草", "business": "专业干货", "humor": "轻松幽默",
}


def _local_social(topic: str, style: str, platform: str, count: int) -> list[str]:
    topic = topic.strip() or "今天的分享"
    patterns = {
        "fresh": [
            f"{topic}，简单记录一下。",
            f"今日份｜{topic}。",
            f"{topic}。愿每天都有小进步。",
        ],
        "energetic": [
            f"必须安利！{topic} 真的太值得了 🔥",
            f"谁懂啊，{topic} 也太上头了吧！",
            f"{topic} 冲冲冲，已经二刷了！",
        ],
        "business": [
            f"关于 {topic}，三点思考：①信息密度 ②执行成本 ③长期复利。",
            f"{topic} 的关键不在于做多少，而在于做对什么。",
            f"复盘 {topic}：先小步快跑，再逐步放大。",
        ],
        "humor": [
            f"{topic}：只要我不尴尬，尴尬的就是别人。",
            f"本日 KPI：把 {topic} 搞定（已完成 1%）。",
            f"{topic} 使我快乐（并不）。",
        ],
    }
    base = patterns.get(style, patterns["fresh"])
    extra = {
        "朋友圈": ["\n\n#日常 #记录", "\n\n#生活碎片", "\n\n#今日份"],
        "短文案": ["", "", ""],
        "微博": ["\n\n#话题#", "\n\n来看看#", "\n\n日常打卡#"],
        "小红书": ["\n\n#好物分享 #日常", "\n\n#干货 #自用", "\n\n#记录生活"],
    }.get(platform, ["", "", ""])
    return [(base[i % len(base)] + extra[i % len(extra)]).strip() for i in range(max(1, count))]


def social_copy(topic, style="fresh", platform="朋友圈", count=3, user_id=None) -> dict:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("请填写文案主题")
    style = (style or "fresh").lower()
    if style not in SOCIAL_STYLES:
        raise ValueError(f"风格只能是：{', '.join(SOCIAL_STYLES)}")
    count = max(1, min(int(count or 3), 6))
    meta = {"provider": "local", "model": "local-template", "fallback_reason": ""}
    if llm.is_configured():
        got, meta = try_llm(
            "social_copy",
            "你是社交媒体文案策划，输出符合平台调性的短文案。",
            f"主题：{topic}；平台：{platform}；风格：{SOCIAL_STYLES[style]}；"
            f"输出 {count} 条互不相同的文案，每条不超过 80 字，用换行分隔，不要编号。",
            user_id, temperature=0.9,
        )
        if got:
            lines = [ln.strip() for ln in got.splitlines() if ln.strip()][:count]
            if lines:
                return {"items": lines, "style": style, "platform": platform,
                        "degraded": False, "provider": "llm", "model": meta.get("model", ""),
                        "fallback_reason": ""}
    return {"items": _local_social(topic, style, platform, count), "style": style,
            "platform": platform, "degraded": True, "provider": "local",
            "model": "local-template",
            "fallback_reason": meta.get("fallback_reason") or "未配置 LLM_API_KEY，使用本地文案模板"}


# ---------------------------------------------------------------------------
# F653 算式分步讲解：ast 白名单求值（绝不 eval）
# ---------------------------------------------------------------------------

_BIN_OPS = {
    ast.Add: ("+", "加"),
    ast.Sub: ("-", "减"),
    ast.Mult: ("×", "乘"),
    ast.Div: ("÷", "除"),
    ast.FloorDiv: ("//", "整除"),
    ast.Mod: ("%", "取余"),
    ast.Pow: ("**", "幂"),
}
_UNARY_OPS = {ast.UAdd: ("+", "正"), ast.USub: ("-", "负")}


def _fmt_num(x) -> str:
    if isinstance(x, bool):
        raise ValueError("不支持布尔值")
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


def _allowed(node, depth=0):
    """白名单校验：只允许 数字 / 四则运算 / 括号 / 一元正负号"""
    if depth > 40:
        raise ValueError("表达式嵌套过深")
    if isinstance(node, ast.Expression):
        return _allowed(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"不支持的字面量：{node.value!r}（只允许数字）")
        return True
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _allowed(node.operand, depth + 1)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _allowed(node.left, depth + 1) and _allowed(node.right, depth + 1)
    raise ValueError(
        f"不支持的表达式元素：{type(node).__name__}（仅允许数字、+ - × ÷ // % ** 与括号）"
    )


def _eval(node, steps, label=""):
    """求值并在过程中记录分步解释"""
    if isinstance(node, ast.Expression):
        return _eval(node.body, steps, label)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp):
        val = _eval(node.operand, steps, label)
        sym, cn = _UNARY_OPS[type(node.op)]
        out = val if sym == "+" else -val
        if sym == "-":
            steps.append(f"取负：-{_fmt_num(val)} = {_fmt_num(out)}")
        return out
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, steps, label)
        right = _eval(node.right, steps, label)
        op = type(node.op)
        sym, cn = _BIN_OPS[op]
        left_txt, right_txt = _fmt_num(left), _fmt_num(right)
        expr_txt = f"{left_txt} {sym} {right_txt}"
        if op is ast.Add:
            out = left + right
        elif op is ast.Sub:
            out = left - right
        elif op is ast.Mult:
            out = left * right
        elif op is ast.Div:
            if right == 0:
                raise ValueError("除数不能为 0")
            out = left / right
        elif op is ast.FloorDiv:
            if right == 0:
                raise ValueError("除数不能为 0")
            out = left // right
        elif op is ast.Mod:
            if right == 0:
                raise ValueError("除数不能为 0")
            out = left % right
        else:  # Pow
            if abs(right) > 16 or (right != int(right)):
                raise ValueError("幂运算指数需为绝对值不超过 16 的整数")
            out = left ** right
        steps.append(f"{cn}：{expr_txt} = {_fmt_num(out)}")
        return out
    raise ValueError("不支持的表达式")


def explain_math(expr: str) -> dict:
    expr = (expr or "").strip().replace("×", "*").replace("÷", "/").replace("（", "(").replace("）", ")")
    if not expr:
        raise ValueError("请输入算式")
    if len(expr) > 300:
        raise ValueError("算式过长（上限 300 字符）")
    if re.search(r"[A-Za-z_]", expr):
        raise ValueError("只允许数字与四则运算符，不支持变量或函数")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise ValueError("算式语法错误，请检查括号与运算符是否配对")
    _allowed(tree)

    steps: list[str] = []
    result = _eval(tree, steps)
    pretty = expr.replace("*", " × ").replace("/", " ÷ ").replace("**", " ^ ").replace("//", " // ")
    pretty = re.sub(r"\s+", " ", pretty).strip()
    return {
        "expression": expr,
        "pretty": pretty,
        "steps": steps,
        "result": _fmt_num(result),
        "result_raw": result if isinstance(result, (int, float)) else None,
        "step_count": len(steps),
        "provider": "local",
        "degraded": False,
    }
