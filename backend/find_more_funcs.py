# -*- coding: utf-8 -*-
with open('learning/data/enhanced.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 查找所有 _more_modulesN 函数的开始和结束
print("=== _more_modules functions ===")
for i, line in enumerate(lines):
    if 'def _more_modules' in line:
        print(f"Line {i+1}: {line.strip()}")
    if line.strip() == '}' and i > 6470:
        # 检查是否是函数的 return 字典结束
        print(f"Line {i+1} (possible end): {repr(line)}")

# 检查第7860-7880行（Swift 第5个模块结束附近）
print("\n=== Lines 7860-7880 ===")
for i in range(7859, 7880):
    print(f"Line {i+1}: {repr(lines[i][:100])}")
