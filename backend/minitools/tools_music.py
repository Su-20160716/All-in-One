# -*- coding: utf-8 -*-
"""minitools · 音乐家族（8 个，F693–F700）。

去重：minitools/num 有通用数学、date 有日期；这里只做乐理计算，不重复既有能力。
约定同其它家族：@endpoint() + ok()，参数缺失抛 ValueError（→400），异常兜底 422。
"""
from .common import endpoint, ok, opt_num, opt_str, req_list, req_num, req_str

# 十二平均律音名（升号记法）
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_INDEX = {n: i for i, n in enumerate(NOTES)}
# 常见等音写法
ENHARMONIC = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#",
              "CB": "B", "FB": "E", "E#": "F", "B#": "C"}

INTERVAL_NAMES = {
    0: "纯一度", 1: "小二度", 2: "大二度", 3: "小三度", 4: "大三度",
    5: "纯四度", 6: "增四度/减五度", 7: "纯五度", 8: "小六度", 9: "大六度",
    10: "小七度", 11: "大七度", 12: "纯八度",
}

CHORD_SHAPES = {
    (0, 4, 7): "", (0, 3, 7): "m", (0, 3, 6): "dim", (0, 4, 8): "aug",
    (0, 2, 7): "sus2", (0, 5, 7): "sus4",
    (0, 4, 7, 10): "7", (0, 4, 7, 11): "maj7", (0, 3, 7, 10): "m7",
    (0, 3, 6, 9): "dim7", (0, 3, 6, 10): "m7b5", (0, 5, 7, 10): "7sus4",
}

# 大调音阶在各调号上的升/降号数量（正数=升号，负数=降号）
KEY_SIGNATURES = {
    "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
    "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7,
    "Am": 0, "Em": 1, "Bm": 2, "F#m": 3, "C#m": 4, "G#m": 5, "D#m": 6, "A#m": 7,
    "Dm": -1, "Gm": -2, "Cm": -3, "Fm": -4, "Bbm": -5, "Ebm": -6, "Abm": -7,
}

SCALE_STEPS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic-minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic-minor": [0, 2, 3, 5, 7, 9, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    "pentatonic-major": [0, 2, 4, 7, 9],
    "pentatonic-minor": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
}


def _norm_note(raw):
    s = str(raw or "").strip().replace("♯", "#").replace("♭", "b")
    if not s:
        raise ValueError("音名不能为空")
    # 统一成「大写根音 + 大写升降号」用于查表，如 Db -> DB
    up = s[0].upper() + (s[1:].upper() if len(s) > 1 else "")
    if up in NOTE_INDEX:
        return up
    if up in ENHARMONIC:
        return ENHARMONIC[up]
    raise ValueError(f"无法识别的音名: {raw}（请用 C/C#/Db/Eb… 形式）")


@endpoint()
def interval(request):
    """MU01. 音程计算：给两个音名，返回半音数与音程名称。"""
    a = _norm_note(req_str(request, "from"))
    b = _norm_note(req_str(request, "to"))
    semis = (NOTE_INDEX[b] - NOTE_INDEX[a]) % 12
    up = (NOTE_INDEX[b] - NOTE_INDEX[a]) % 12
    return ok({
        "from": a, "to": b,
        "semitones_up": up,
        "semitones_down": (NOTE_INDEX[a] - NOTE_INDEX[b]) % 12,
        "name_up": INTERVAL_NAMES.get(up, "复音程"),
        "inversion": INTERVAL_NAMES.get((12 - up) % 12, "纯一度") if up else "纯一度",
        "is_consonant": up in (0, 3, 4, 5, 7, 8, 9, 12),
        "note": semis,
    })


@endpoint()
def scale(request):
    """MU02. 音阶构成：给根音与音阶类型，列出音阶音。"""
    root = _norm_note(req_str(request, "root"))
    kind = (opt_str(request, "kind", "major") or "major").lower()
    if kind not in SCALE_STEPS:
        raise ValueError(f"不支持的音阶类型: {kind}；可选 {'/'.join(sorted(SCALE_STEPS))}")
    steps = SCALE_STEPS[kind]
    start = NOTE_INDEX[root]
    notes = [NOTES[(start + s) % 12] for s in steps]
    return ok({"root": root, "kind": kind, "notes": notes,
               "degrees": len(notes), "steps": steps,
               "formula": " ".join(str(s) for s in steps)})


@endpoint()
def bpm_duration(request):
    """MU03. BPM ↔ 时长：给速度与拍数算时长，或给时长算可容纳拍数。"""
    bpm = req_num(request, "bpm", minimum=1, maximum=1000)
    beats = opt_num(request, "beats")
    seconds = opt_num(request, "seconds")
    if beats is None and seconds is None:
        raise ValueError("请提供 beats（拍数）或 seconds（秒数）之一")
    beat_ms = 60000.0 / bpm
    if beats is not None:
        total = beats * beat_ms / 1000.0
        return ok({"bpm": bpm, "beats": beats, "seconds": round(total, 3),
                   "ms_per_beat": round(beat_ms, 3),
                   "bar_4_4_seconds": round(4 * beat_ms / 1000.0, 3)})
    return ok({"bpm": bpm, "seconds": seconds, "beats": round(seconds * bpm / 60.0, 3),
               "ms_per_beat": round(beat_ms, 3)})


@endpoint()
def chord(request):
    """MU04. 和弦命名：给一组音名，识别和弦性质。"""
    raw = req_list(request, "notes", max_len=12)
    notes = [_norm_note(x) for x in raw]
    if len(notes) < 2:
        raise ValueError("至少给两个音")
    root = notes[0]
    idx = sorted({(NOTE_INDEX[n] - NOTE_INDEX[root]) % 12 for n in notes})
    key = tuple(idx)
    shape = CHORD_SHAPES.get(key)
    return ok({
        "root": root, "notes": notes, "intervals": idx,
        "quality": shape if shape is not None else "未识别",
        "chord": f"{root}{shape}" if shape is not None else f"{root}?",
        "known": shape is not None,
        "note": "按第一个音作为根音识别；不识别的和弦请检查音名拼写或转位。",
    })


@endpoint()
def transpose(request):
    """MU05. 移调：把音名或音名列表整体升高/降低若干半音。"""
    semis = req_num(request, "semitones", integer=True, minimum=-24, maximum=24)
    single = opt_str(request, "note", "")
    if single:
        items = [_norm_note(single)]
    else:
        items = [_norm_note(x) for x in req_list(request, "notes", max_len=64)]
    out = [NOTES[(NOTE_INDEX[n] + int(semis)) % 12] for n in items]
    return ok({"semitones": int(semis), "from": items, "to": out,
               "single": out[0] if len(out) == 1 else None})


@endpoint()
def key_signature(request):
    """MU06. 调号：给调名，返回升/降号数量与名称。"""
    key = req_str(request, "key").strip()
    canon = key[0].upper() + key[1:]
    if canon not in KEY_SIGNATURES:
        raise ValueError(f"不支持的调: {key}；示例 C/G/D/F/Bb/Am/Em")
    n = KEY_SIGNATURES[canon]
    order_sharp = ["F#", "C#", "G#", "D#", "A#", "E#", "B#"]
    order_flat = ["Bb", "Eb", "Ab", "Db", "Gb", "Cb", "Fb"]
    acc = order_sharp[:n] if n > 0 else (order_flat[:-n] if n < 0 else [])
    return ok({"key": canon, "accidentals": n,
               "type": "升号" if n > 0 else ("降号" if n < 0 else "无升降号"),
               "names": acc})


@endpoint()
def time_signature(request):
    """MU07. 拍号换算：给分子/分母，算每小节拍数与时长。"""
    num = req_num(request, "numerator", integer=True, minimum=1, maximum=32)
    den = req_num(request, "denominator", integer=True, minimum=1, maximum=32)
    if den not in (1, 2, 4, 8, 16, 32):
        raise ValueError("分母需为 1/2/4/8/16/32 之一")
    bpm = opt_num(request, "bpm")
    beats_per_bar = float(num) * (4.0 / den)  # 折算成四分音符拍
    out = {"numerator": int(num), "denominator": int(den),
           "quarter_note_beats": round(beats_per_bar, 3),
           "simple_or_compound": "复拍子" if num % 3 == 0 and num > 3 else "单拍子"}
    if bpm:
        out["seconds_per_bar"] = round(beats_per_bar * 60.0 / bpm, 3)
    return ok(out)


@endpoint()
def bars(request):
    """MU08. 小节数：按时长、速度与拍号算小节数。"""
    seconds = req_num(request, "seconds", minimum=0)
    bpm = req_num(request, "bpm", minimum=1)
    num = req_num(request, "numerator", integer=True, minimum=1)
    den = req_num(request, "denominator", integer=True, minimum=1)
    beats_per_bar = float(num) * (4.0 / den)
    total_beats = seconds * bpm / 60.0
    exact = total_beats / beats_per_bar
    return ok({"seconds": seconds, "bpm": bpm,
               "time_signature": f"{int(num)}/{int(den)}",
               "total_beats": round(total_beats, 3),
               "beats_per_bar": round(beats_per_bar, 3),
               "bars_exact": round(exact, 3),
               "bars_whole": int(exact)})
