# -*- coding: utf-8 -*-
import re

with open('learning/data/enhanced.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 查找所有语言模块的开始
print("=== Language module starts ===")
for i, line in enumerate(lines):
    if re.match(r'^\s*"[a-z+#]+":\s*\[', line):
        print(f"Line {i+1}: {line.strip()[:60]}")

# 查找 C# 模块的结束（Swift 开始之前）
print("\n=== C# module end (around line 6490-6510) ===")
for i in range(6489, 6515):
    print(f"Line {i+1}: {repr(lines[i][:100])}")
