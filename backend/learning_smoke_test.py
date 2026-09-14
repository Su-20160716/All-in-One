# -*- coding: utf-8 -*-
"""学习中心综合冒烟测试：真实 HTTP 调用，覆盖
编程学习 30 项 + K12 学科 30 项 + 学习工具 40 个 + 个人数据闭环，合计 100+。
运行（backend 目录）：venv/Scripts/python learning_smoke_test.py
"""
import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient  # noqa: E402

from learning.learn_tools import LEARN_TOOL_REGISTRY  # noqa: E402

passed, failed = [], []


def check(name, cond, extra=""):
    (passed if cond else failed).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {extra}"))


def register(client, username, password="test123", **extra):
    return client.post("/api/auth/register/", {"username": username, "password": password, **extra}, format="json")


# 40 个工具的样例入参
TOOL_SAMPLES = {
    "arith-gen": {"n": 5}, "fraction-simplify": {"a": 12, "b": 18}, "gcd-lcm": {"nums": "12,18,24"},
    "prime": {"n": 360}, "roman": {"mode": "to_roman", "n": 2024},
    "quadratic": {"a": 1, "b": -5, "c": 6}, "linear2": {"a1": 1, "b1": 1, "c1": 5, "a2": 1, "b2": -1, "c2": 1},
    "sequence": {"kind": "arithmetic", "a1": 2, "d": 3, "n": 10},
    "plane-geo": {"shape": "trapezoid", "dims": "3,4,2"}, "solid-geo": {"shape": "sphere", "dims": "2"},
    "percent": {"part": 25, "whole": 80}, "unit-convert": {"table": "length", "value": 1, "from": "km", "to": "m"},
    "temp": {"value": 100, "from": "c"}, "molar-mass": {"formula": "Ca(OH)2"},
    "balance-check": {"left": [{"f": "Fe", "n": 3}, {"f": "O2", "n": 2}], "right": [{"f": "Fe3O4", "n": 1}]},
    "en-word-freq": {"text": "I like apples. I like milk. Apples are good."},
    "en-readability": {"text": "The cat sat on the mat. It was a warm and sunny day. We played in the small green garden happily."},
    "en-inflect": {"word": "study"}, "pinyin": {"text": "学习中文"},
    "composition-count": {"text": "我爱学习。Learning is fun!\n\n第二段 here。"},
    "score-stats": {"scores": "66,77,88,99,100,77"}, "rank": {"scores": "90,80,90,70", "method": "dense"},
    "gpa": {"score": 87}, "ebbinghaus": {"start": "2026-09-11"}, "pomodoro": {"sessions": "25,25,50,65"},
    "roll-call": {"names": "张三,李四,王五,赵六", "n": 2}, "group": {"names": "a,b,c,d,e,f", "by": "count", "count": 3},
    "study-plan": {"total": 100, "days": 7, "rest_every": 4, "start": "2026-09-11"},
    "flashcard-sched": {"level": 2, "rating": "good"}, "truth-table": {"expr": "A and (B or not C)"},
    "study-time": {"start": "08:30", "end": "10:15"}, "rmb": {"number": 1234.56},
    "calendar-math": {"year": 2024, "date": "2026-09-11", "start": "2026-09-01", "end": "2026-09-11"},
    "points-to-flashcard": {"text": "光合作用：植物利用光能合成有机物\n呼吸作用：分解有机物释放能量\n- 牛顿第二定律：F=ma"},
}


def main():
    ts = int(time.time())
    anon = APIClient()
    r = register(anon, f"learner{ts}", nickname="学员")
    check("注册学习账号", r.status_code == 201, r.status_code)
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    # 未登录访问应被拦截
    check("学习接口需登录", APIClient().get("/api/learning/prog/languages/").status_code == 401)

    print("\n— 一、编程学习 30 项 —")
    gets = [
        ("P01语言总览", "/api/learning/prog/languages/"),
        ("P02语言详情", "/api/learning/prog/languages/python/"),
        ("P03学习路线", "/api/learning/prog/languages/python/roadmap/"),
        ("P04语法速查", "/api/learning/prog/languages/python/cheatsheet/"),
        ("P05关键字", "/api/learning/prog/languages/python/keywords/"),
        ("P06数据类型", "/api/learning/prog/languages/python/types/"),
        ("P07片段列表", "/api/learning/prog/languages/python/snippets/"),
        ("P08片段详情", "/api/learning/prog/languages/python/snippets/0/"),
        ("P09语言对比", "/api/learning/prog/languages/compare/?keys=python,go,rust"),
        ("P10术语词典", "/api/learning/prog/glossary/?q=变量"),
        ("P11编程范式", "/api/learning/prog/paradigms/"),
        ("P12课程列表", "/api/learning/prog/languages/python/lessons/"),
        ("P13课程详情", "/api/learning/prog/languages/python/lessons/0/"),
        ("P14单选练习", "/api/learning/prog/drill/quiz/?lang=python&n=3"),
        ("P15读程序", "/api/learning/prog/drill/output/?lang=python&n=3"),
        ("P16代码填空", "/api/learning/prog/drill/fill/?lang=python&n=3"),
        ("P17找错题", "/api/learning/prog/drill/bug/?lang=python&n=3"),
        ("P19随机抽题", "/api/learning/prog/drill/random/?lang=java"),
        ("P20语言推荐", "/api/learning/prog/recommend/?goal=ai"),
        ("P21报错排查", "/api/learning/prog/languages/python/troubleshoot/"),
        ("P22算法目录", "/api/learning/prog/algorithms/"),
        ("P23数据结构", "/api/learning/prog/data-structures/"),
        ("P24IDE指南", "/api/learning/prog/languages/python/ide/"),
        ("P25编码规范", "/api/learning/prog/languages/python/style/"),
        ("P27每日一题", "/api/learning/prog/daily-challenge/"),
        ("P28进度列表", "/api/learning/prog/progress/"),
        ("P30收藏列表", "/api/learning/prog/snippets/bookmarks/"),
    ]
    for name, path in gets:
        rr = c.get(path)
        check(name, rr.status_code == 200, rr.status_code)

    # 10 语言全覆盖
    rr = c.get("/api/learning/prog/languages/")
    check("语言库恰好10种", rr.status_code == 200 and rr.data["total"] == 10, rr.data.get("total"))

    # P18 判分
    q = c.get("/api/learning/prog/drill/quiz/?lang=python&n=1").data["list"][0]
    rr = c.post("/api/learning/prog/drill/grade/", {"id": q["id"], "answer": q.get("options") and 0 or ""}, format="json")
    check("P18单题判分", rr.status_code == 200 and "correct" in rr.data and "right_answer" in rr.data, rr.status_code)

    # P26 整卷计分
    qs = c.get("/api/learning/prog/drill/quiz/?n=5").data["list"]
    rr = c.post("/api/learning/prog/drill/quiz-submit/", {"answers": [{"id": x["id"], "answer": 0} for x in qs]}, format="json")
    check("P26整卷计分", rr.status_code == 200 and rr.data["total"] == len(qs) and "score" in rr.data, rr.status_code)

    # P29 进度 upsert
    rr = c.post("/api/learning/prog/progress/", {"domain": "programming", "target_key": "python",
                                                 "target_name": "Python", "percent": 40}, format="json")
    check("P29进度更新", rr.status_code == 200 and rr.data["percent"] == 40, rr.status_code)
    rr = c.get("/api/learning/prog/progress/")
    check("进度可回读", rr.data["total"] >= 1)

    # P30 收藏闭环
    rr = c.post("/api/learning/prog/snippets/bookmarks/", {"language": "python", "title": "Hello", "code": "print('hi')"}, format="json")
    bid = rr.data.get("id")
    check("P30新增收藏", rr.status_code == 201 and bid)
    rr = c.delete(f"/api/learning/prog/snippets/bookmarks/?id={bid}")
    check("收藏可删除", rr.status_code == 200 and rr.data["deleted"] is True)

    print("\n— 二、K12 学科 30 项 —")
    sgets = [
        ("S01学段目录", "/api/learning/school/stages/"),
        ("S02学科详情", "/api/learning/school/stages/junior/subjects/math/"),
        ("S03知识点树", "/api/learning/school/knowledge/?stage=junior&subject=math"),
        ("S04知识点详情", "/api/learning/school/knowledge/junior.math.0.0/"),
        ("S05知识搜索", "/api/learning/school/knowledge/search/?q=方程"),
        ("S06公式列表", "/api/learning/school/formulas/"),
        ("S09古诗目录", "/api/learning/school/poems/"),
        ("S11古诗接句", "/api/learning/school/poems/drill/?n=3"),
        ("S12英语词表", "/api/learning/school/words/?stage=primary"),
        ("S14单词听写", "/api/learning/school/words/dictation/?n=3"),
        ("S15单词选择", "/api/learning/school/words/quiz/?n=3"),
        ("S16生词本列表", "/api/learning/school/words/wordbook/"),
        ("S17题库列表", "/api/learning/school/questions/"),
        ("S19智能组卷", "/api/learning/school/paper/compose/?stage=junior&subject=math&count=3"),
        ("S21错题本列表", "/api/learning/school/mistakes/"),
        ("S22掌握度", "/api/learning/school/mastery/"),
        ("S23成语词典", "/api/learning/school/idioms/"),
        ("S24成语接龙", "/api/learning/school/idioms/chain/?word=一心一意"),
        ("S25汉字字典", "/api/learning/school/hanzi/"),
        ("S26元素表", "/api/learning/school/elements/"),
        ("S27元素详情", "/api/learning/school/elements/1/"),
        ("S28化学方程式", "/api/learning/school/equations/"),
        ("S29语法目录", "/api/learning/school/grammar/"),
    ]
    for name, path in sgets:
        rr = c.get(path)
        check(name, rr.status_code == 200, f"{rr.status_code} {path}")

    # 动态：公式详情 + S08 计算
    flist = c.get("/api/learning/school/formulas/").data["list"]
    f0 = flist[0]
    rr = c.get(f"/api/learning/school/formulas/{f0['key']}/")
    check("S07公式详情", rr.status_code == 200 and rr.data["name"] == f0["name"], rr.status_code)
    calc_ok = 0
    for f in flist:
        if "quadratic" in f["key"] or "heron" in f["key"]:
            continue
        vals = {vk: 2 for vk, _ in f["vars"]}
        rr = c.post("/api/learning/school/formulas/calc/", {"key": f["key"], "values": vals}, format="json")
        calc_ok += rr.status_code == 200
    check("S08公式代入计算", calc_ok >= 10, f"仅{calc_ok}个可算")

    # 动态：古诗详情
    p0 = c.get("/api/learning/school/poems/").data["list"][0]
    rr = c.get(f"/api/learning/school/poems/{p0['key']}/")
    check("S10古诗详情", rr.status_code == 200 and "text" in rr.data, rr.status_code)

    # 动态：单词详情
    w0 = c.get("/api/learning/school/words/").data["list"][0]
    rr = c.get(f"/api/learning/school/words/{w0['word']}/")
    check("S13单词详情", rr.status_code == 200 and rr.data["word"] == w0["word"], rr.status_code)

    # 动态：题目详情
    q0 = c.get("/api/learning/school/questions/?answer=1").data["list"][0]
    rr = c.get(f"/api/learning/school/questions/{q0['id']}/")
    check("S18题目详情", rr.status_code == 200 and "analysis" in rr.data, rr.status_code)

    # 动态：语法详情
    g0 = c.get("/api/learning/school/grammar/").data["list"][0]
    rr = c.get(f"/api/learning/school/grammar/{g0['key']}/")
    check("S30语法详情", rr.status_code == 200 and "rule" in rr.data, rr.status_code)

    # S20 交卷判分：用答案卷的正确答案作答，应得满分
    paper = c.get("/api/learning/school/paper/compose/?stage=junior&subject=math&count=5").data
    ans = [{"id": a["id"], "answer": a["answer"]} for a in paper["answer_sheet"]]
    rr = c.post("/api/learning/school/paper/grade/", {"answers": ans}, format="json")
    check("S20交卷判分(满分)", rr.status_code == 200 and rr.data["score"] == 100.0, rr.data.get("score"))

    # 生词本闭环
    rr = c.post("/api/learning/school/words/wordbook/", {"word": w0["word"]}, format="json")
    wid = rr.data.get("id")
    check("S16加入生词本", rr.status_code in (200, 201) and wid)
    rr = c.patch("/api/learning/school/words/wordbook/", {"id": wid}, format="json")
    check("生词本标记掌握", rr.status_code == 200 and rr.data["mastered"] is True)
    rr = c.delete(f"/api/learning/school/words/wordbook/?id={wid}")
    check("生词本删除", rr.status_code == 200)

    # 错题本闭环
    rr = c.post("/api/learning/school/mistakes/", {"stage": "junior", "subject": "math", "stem": "1+1=?",
                                                   "answer": "2", "user_answer": "3"}, format="json")
    mid = rr.data.get("id")
    check("S21加入错题", rr.status_code == 201 and mid)
    rr = c.patch("/api/learning/school/mistakes/", {"id": mid}, format="json")
    check("错题标记订正", rr.status_code == 200 and rr.data["mastered"] is True)
    rr = c.delete(f"/api/learning/school/mistakes/?id={mid}")
    check("错题删除", rr.status_code == 200)

    print("\n— 三、40 个学习工具 —")
    rr = c.get("/api/learning/tools/catalog/")
    check("工具目录", rr.status_code == 200 and rr.data["total"] == 40, rr.data.get("total"))
    tool_ok = 0
    for key in LEARN_TOOL_REGISTRY:
        body = {"tool": key, **TOOL_SAMPLES.get(key, {})}
        rr = c.post("/api/learning/tools/run/", body, format="json")
        good = rr.status_code == 200 and rr.data.get("result") is not None
        tool_ok += good
        if not good:
            check(f"工具 {key}", False, f"{rr.status_code} {rr.data}")
    check("40 工具全部可运行", tool_ok == 40, f"{tool_ok}/40")
    # 直达路由
    rr = c.get("/api/learning/tools/gpa/?score=90")
    check("工具直达路由", rr.status_code == 200 and "result" in rr.data, rr.status_code)

    print("\n— 四、个人学习中心（附加闭环）—")
    rr = c.post("/api/learning/study/sessions/", {"subject": "数学", "minutes": 25,
                                                  "study_date": "2026-09-11"}, format="json")
    sid = rr.data.get("id")
    check("专注打卡", rr.status_code == 201 and sid)
    rr = c.get("/api/learning/study/sessions/")
    check("专注汇总", rr.status_code == 200 and rr.data["total_minutes"] >= 25)
    rr = c.post("/api/learning/study/plans/", {"title": "30天背单词", "subject": "英语", "total": 300,
                                               "days": 30, "start_date": "2026-09-11"}, format="json")
    pid = rr.data.get("id")
    check("创建学习计划", rr.status_code == 201 and pid)
    rr = c.patch("/api/learning/study/plans/", {"id": pid, "finished": 10}, format="json")
    check("更新计划进度", rr.status_code == 200 and rr.data["finished"] == 10)
    rr = c.delete(f"/api/learning/study/plans/?id={pid}")
    check("删除计划", rr.status_code == 200)
    c.delete(f"/api/learning/study/sessions/?id={sid}")

    print(f"\n结果：通过 {len(passed)} 项，失败 {len(failed)} 项")
    if failed:
        print("失败项：", failed)
        raise SystemExit(1)
    print("学习中心全部冒烟通过 ✓")


if __name__ == "__main__":
    main()
