# -*- coding: utf-8 -*-
"""minitools · 棋牌家族（6 个，F701–F706）。

去重：minitools/algo 做通用算法；这里只做棋类判定与牌型识别。
"""
import itertools
import random

from .common import endpoint, ok, opt_num, opt_str, req_list, req_num


@endpoint()
def tictactoe(request):
    """BD01. 井字棋胜负：给 9 格棋盘判胜负。"""
    cells = req_list(request, "cells", max_len=9)
    if len(cells) != 9:
        raise ValueError("cells 需为 9 个元素，按行排列；空格用空串或 0 表示")
    grid = []
    for c in cells:
        v = str(c).strip().upper()
        if v in ("", "0", "-", ".", "_"):
            grid.append("")
        elif v in ("X", "O"):
            grid.append(v)
        else:
            raise ValueError(f"非法格子取值: {c}（只允许 X / O / 空）")

    lines = [(0, 1, 2), (3, 4, 5), (6, 7, 8),
             (0, 3, 6), (1, 4, 7), (2, 5, 8),
             (0, 4, 8), (2, 4, 6)]
    for a, b, c in lines:
        if grid[a] and grid[a] == grid[b] == grid[c]:
            return ok({"winner": grid[a], "line": [a, b, c], "status": "win"})
    if all(grid):
        return ok({"winner": None, "status": "draw"})
    return ok({"winner": None, "status": "playing",
               "next_hint": "棋盘未满且无人连成三子"})


@endpoint()
def gomoku(request):
    """BD02. 五子棋判定：给棋盘与最后落子，判断是否五连。"""
    rows = req_list(request, "board", max_len=40)
    if not rows:
        raise ValueError("board 不能为空")
    grid = []
    for r in rows:
        line = str(r).replace(" ", "")
        grid.append([ch if ch in ("1", "2", "X", "O", "●", "○") else "" for ch in line])
    row = req_num(request, "row", integer=True, minimum=0, maximum=len(grid) - 1)
    col = req_num(request, "col", integer=True)
    r, c = int(row), int(col)
    if r >= len(grid) or c >= len(grid[0]):
        raise ValueError("row/col 超出棋盘范围")
    who = grid[r][c]
    if not who:
        raise ValueError("该位置没有棋子")
    dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for dr, dc in dirs:
        cnt = 1
        cells = [(r, c)]
        for sign in (1, -1):
            nr, nc = r + dr * sign, c + dc * sign
            while 0 <= nr < len(grid) and 0 <= nc < len(grid[0]) and grid[nr][nc] == who:
                cnt += 1
                cells.append((nr, nc))
                nr += dr * sign
                nc += dc * sign
        if cnt >= 5:
            return ok({"winner": who, "count": cnt, "direction": [dr, dc],
                       "cells": cells, "status": "win"})
    return ok({"winner": None, "status": "playing"})


def _sudoku_conflicts(grid):
    """返回冲突位置列表 [(r, c, 原因)]。"""
    bad = []
    for i in range(9):
        row = [grid[i][j] for j in range(9)]
        col = [grid[j][i] for j in range(9)]
        for seq, label, idx in ((row, "行", i), (col, "列", i)):
            seen = {}
            for k, v in enumerate(seq):
                if not v:
                    continue
                if v in seen:
                    bad.append((idx, k, f"{label}{idx + 1} 中 {v} 重复"))
                seen[v] = k
    for br in range(3):
        for bc in range(3):
            seen = {}
            for i in range(3):
                for j in range(3):
                    v = grid[br * 3 + i][bc * 3 + j]
                    if not v:
                        continue
                    if v in seen:
                        bad.append((br * 3 + i, bc * 3 + j, f"第{br * 3 + bc + 1}宫 {v} 重复"))
                    seen[v] = 1
    return bad


@endpoint()
def sudoku_check(request):
    """BD03. 数独校验：检查 9×9 数独是否合法（空格可为 0）。"""
    rows = req_list(request, "grid", max_len=9)
    if len(rows) != 9:
        raise ValueError("grid 需为 9 行")
    grid = []
    for r in rows:
        s = str(r).replace(" ", "").replace(",", "")
        if len(s) != 9:
            raise ValueError("每行需 9 个字符")
        line = []
        for ch in s:
            if ch in ".0_":
                line.append(0)
            elif ch.isdigit() and 1 <= int(ch) <= 9:
                line.append(int(ch))
            else:
                raise ValueError(f"非法字符: {ch}")
        grid.append(line)
    bad = _sudoku_conflicts(grid)
    filled = sum(1 for r in grid for v in r if v)
    return ok({"valid": not bad, "conflicts": [{"row": r + 1, "col": c + 1, "reason": why}
                                               for r, c, why in bad],
               "filled": filled, "empty": 81 - filled,
               "complete": filled == 81 and not bad})


def _sudoku_solve(grid):
    """回溯求解，返回解或 None。"""
    for r in range(9):
        for c in range(9):
            if grid[r][c] == 0:
                nums = set(range(1, 10))
                nums -= {grid[r][k] for k in range(9)}
                nums -= {grid[k][c] for k in range(9)}
                br, bc = r // 3 * 3, c // 3 * 3
                nums -= {grid[br + i][bc + j] for i in range(3) for j in range(3)}
                for v in sorted(nums):
                    grid[r][c] = v
                    if _sudoku_solve(grid):
                        return True
                    grid[r][c] = 0
                return False
    return True


@endpoint()
def sudoku_gen(request):
    """BD04. 数独生成：生成有唯一解风格的题面（给定数可调）。"""
    clues = req_num(request, "clues", integer=True, default=30, minimum=17, maximum=60)
    seed = opt_num(request, "seed")
    rnd = random.Random(int(seed)) if seed is not None else random.Random()
    grid = [[0] * 9 for _ in range(9)]
    for i in range(3):  # 只填对角三宫（0/4/8 号宫），其余留空交给回溯求解
        nums = list(range(1, 10))
        rnd.shuffle(nums)
        for k in range(9):
            grid[i * 3 + k // 3][i * 3 + k % 3] = nums[k]
    if not _sudoku_solve(grid):
        raise ValueError("数独生成失败，请更换 seed 重试")
    solution = [row[:] for row in grid]
    cells = [(r, c) for r in range(9) for c in range(9)]
    rnd.shuffle(cells)
    for r, c in cells[clues:]:
        grid[r][c] = 0
    return ok({
        "clues": int(clues),
        "puzzle": ["".join(str(v) if v else "." for v in row) for row in grid],
        "solution": ["".join(str(v) for v in row) for row in solution],
        "note": "题目由完整解随机挖空生成，保证有解；不保证唯一解，如需唯一请自行校验。",
    })


@endpoint()
def twenty_four(request):
    """BD05. 24 点：给 4 个数，找等于 24 的算式。"""
    nums = req_list(request, "nums", max_len=4)
    if len(nums) != 4:
        raise ValueError("nums 需为 4 个数字")
    try:
        vals = [int(round(float(x))) for x in nums]
    except (TypeError, ValueError):
        raise ValueError("nums 必须是数字")

    ops = ["+", "-", "*", "/"]

    def calc(a, b, op):
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            return None
        return a / b

    solutions = []
    for perm in set(itertools.permutations(vals)):
        for o1, o2, o3 in itertools.product(ops, repeat=3):
            # ((a b) c) d
            r1 = calc(perm[0], perm[1], o1)
            if r1 is not None:
                r2 = calc(r1, perm[2], o2)
                if r2 is not None:
                    r3 = calc(r2, perm[3], o3)
                    if r3 is not None and abs(r3 - 24) < 1e-9:
                        solutions.append(f"(({perm[0]} {o1} {perm[1]}) {o2} {perm[2]}) {o3} {perm[3]}")
            # (a (b c)) d
            r1 = calc(perm[1], perm[2], o1)
            if r1 is not None:
                r2 = calc(perm[0], r1, o2)
                if r2 is not None:
                    r3 = calc(r2, perm[3], o3)
                    if r3 is not None and abs(r3 - 24) < 1e-9:
                        solutions.append(f"({perm[0]} {o2} ({perm[1]} {o1} {perm[2]})) {o3} {perm[3]}")
            # a ((b c) d)
            r1 = calc(perm[1], perm[2], o1)
            if r1 is not None:
                r2 = calc(r1, perm[3], o2)
                if r2 is not None:
                    r3 = calc(perm[0], r2, o3)
                    if r3 is not None and abs(r3 - 24) < 1e-9:
                        solutions.append(f"{perm[0]} {o3} (({perm[1]} {o1} {perm[2]}) {o2} {perm[3]})")
            # a (b (c d))
            r1 = calc(perm[2], perm[3], o1)
            if r1 is not None:
                r2 = calc(perm[1], r1, o2)
                if r2 is not None:
                    r3 = calc(perm[0], r2, o3)
                    if r3 is not None and abs(r3 - 24) < 1e-9:
                        solutions.append(f"{perm[0]} {o3} ({perm[1]} {o2} ({perm[2]} {o1} {perm[3]}))")
    uniq = sorted(set(solutions))
    return ok({"nums": vals, "solvable": bool(uniq),
               "count": len(uniq), "solutions": uniq[:8],
               "note": "只回前 8 个等价算式；除零的组合已自动跳过。"})


POKER_RANKS = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
               "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14, "T": 10}
HAND_NAMES = ["高牌", "一对", "两对", "三条", "顺子", "同花", "葫芦", "四条", "同花顺"]


@endpoint()
def poker_hand(request):
    """BD06. 扑克牌型：识别 5 张牌的牌型。"""
    raw = req_list(request, "cards", max_len=7)
    if len(raw) < 5:
        raise ValueError("至少给 5 张牌，形如 AS / 10H / KD / 2C")
    cards = []
    for item in raw:
        s = str(item).strip().upper().replace(" ", "")
        if len(s) < 2:
            raise ValueError(f"非法牌: {item}")
        rank, suit = s[:-1], s[-1]
        if rank not in POKER_RANKS:
            raise ValueError(f"非法点数: {rank}（可用 2-10/J/Q/K/A，10 也可写 T）")
        if suit not in ("S", "H", "D", "C"):
            raise ValueError(f"非法花色: {suit}（S 黑桃 / H 红心 / D 方块 / C 梅花）")
        cards.append((POKER_RANKS[rank], suit, s))
    cards = cards[:5]
    ranks = sorted((c[0] for c in cards), reverse=True)
    suits = {c[1] for c in cards}
    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    shape = sorted(counts.values(), reverse=True)
    is_flush = len(suits) == 1
    uniq = sorted(set(ranks))
    is_straight = len(uniq) == 5 and uniq[-1] - uniq[0] == 4
    if set(uniq) == {14, 2, 3, 4, 5}:  # A2345 轮子顺
        is_straight = True

    if is_straight and is_flush:
        level = 8
    elif shape == [4, 1]:
        level = 7
    elif shape == [3, 2]:
        level = 6
    elif is_flush:
        level = 5
    elif is_straight:
        level = 4
    elif shape == [3, 1, 1]:
        level = 3
    elif shape == [2, 2, 1]:
        level = 2
    elif shape == [2, 1, 1, 1]:
        level = 1
    else:
        level = 0
    return ok({"cards": [c[2] for c in cards], "hand": HAND_NAMES[level], "level": level,
               "is_flush": is_flush, "is_straight": is_straight,
               "ranks": ranks, "note": "按 5 张牌判定；超过 5 张只取前 5 张。"})
