# -*- coding: utf-8 -*-
"""运行时探测与安全执行沙箱。

设计要点（对齐项目「可降级适配器」约定）：
- **可用性优先**：启动/首次调用时探测本机有哪些解释器/编译器，探测不到的
  语言返回结构化 `RUNTIME_NOT_FOUND`，前端据此把按钮置灰，**绝不 500**；
- **进程级隔离**：`subprocess` + 独立临时目录 + 环境变量白名单 + 无 shell；
- **资源约束**：超时用 communicate(timeout) + kill；输出按字节截断；
  内存上限在 POSIX 上用 `resource.setrlimit`，Windows 上降级为「不限制 + 记录」；
- **危险模式拦截**：执行前静态扫描明显危险调用（rm -rf /、格式化磁盘、
  反弹 shell、fork 炸弹等），命中则直接拒绝（第 40 条）。

安全性说明：本模块面向「本机自用 + 可信内网」场景，属于**软隔离**（进程级）。
若需对抗恶意代码，请叠加容器/虚拟机，本模块不承担强隔离职责。
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------- 常量 ----------

DEFAULT_TIMEOUT = 5          # 秒，与第 24 条的「默认 5s」一致
MAX_TIMEOUT = 30
OUTPUT_LIMIT = 64 * 1024     # 单路输出截断上限（第 26 条：64KB）
MAX_SOURCE_BYTES = 256 * 1024
MEMORY_LIMIT_MB = 256        # POSIX 生效；Windows 降级

IS_WINDOWS = platform.system() == "Windows"


# ---------- 语言定义 ----------
# kind: "interpreted" 直接执行；"compiled" 需先编译再执行
# probe: 探测可执行文件名的候选列表（按顺序取第一个存在的）

LANGUAGES = {
    "python": {
        "name": "Python 3",
        "ext": ".py",
        "kind": "interpreted",
        "probe": [sys.executable, "python3", "python", "py"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "python",
        "monaco": "python",
        "comment": "#",
        "available_hint": "系统自带 python",
    },
    "javascript": {
        "name": "JavaScript (Node)",
        "ext": ".js",
        "kind": "interpreted",
        "probe": ["node", "node.exe"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "javascript",
        "monaco": "javascript",
        "comment": "//",
        "available_hint": "需安装 Node.js",
    },
    "typescript": {
        "name": "TypeScript",
        "ext": ".ts",
        "kind": "interpreted",
        "probe": ["ts-node", "deno", "bun"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "typescript",
        "monaco": "typescript",
        "comment": "//",
        "available_hint": "需安装 ts-node / deno / bun",
    },
    "bash": {
        "name": "Bash / Shell",
        "ext": ".sh",
        "kind": "interpreted",
        "probe": ["bash", "sh"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "sh",
        "monaco": "shell",
        "comment": "#",
        "available_hint": "需 POSIX shell（Windows 下为 Git Bash）",
    },
    "c": {
        "name": "C (GCC)",
        "ext": ".c",
        "kind": "compiled",
        "probe": ["gcc", "cc"],
        "compile": ["{exe}", "{src}", "-o", "{out}", "-lm", "-O1"],
        "run": ["{out}"],
        "ace_mode": "c_cpp",
        "monaco": "c",
        "comment": "//",
        "available_hint": "需安装 GCC / MinGW",
    },
    "cpp": {
        "name": "C++ (G++)",
        "ext": ".cpp",
        "kind": "compiled",
        "probe": ["g++", "clang++"],
        "compile": ["{exe}", "{src}", "-o", "{out}", "-std=c++17", "-O1"],
        "run": ["{out}"],
        "ace_mode": "c_cpp",
        "monaco": "cpp",
        "comment": "//",
        "available_hint": "需安装 G++ / MinGW",
    },
    "go": {
        "name": "Go",
        "ext": ".go",
        "kind": "compiled",
        "probe": ["go"],
        "compile": ["{exe}", "build", "-o", "{out}", "{src}"],
        "run": ["{out}"],
        "ace_mode": "golang",
        "monaco": "go",
        "comment": "//",
        "available_hint": "需安装 Go 工具链",
    },
    "rust": {
        "name": "Rust",
        "ext": ".rs",
        "kind": "compiled",
        "probe": ["rustc"],
        "compile": ["{exe}", "{src}", "-o", "{out}", "-O"],
        "run": ["{out}"],
        "ace_mode": "rust",
        "monaco": "rust",
        "comment": "//",
        "available_hint": "需安装 rustc",
    },
    "java": {
        "name": "Java",
        "ext": ".java",
        "kind": "compiled",
        "probe": ["java"],
        "compile": ["javac", "{src}", "-d", "{dir}"],
        "run": ["{exe}", "-cp", "{dir}", "Main"],
        "ace_mode": "java",
        "monaco": "java",
        "comment": "//",
        "available_hint": "需安装 JDK",
    },
    "php": {
        "name": "PHP",
        "ext": ".php",
        "kind": "interpreted",
        "probe": ["php"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "php",
        "monaco": "php",
        "comment": "//",
        "available_hint": "需安装 PHP",
    },
    "ruby": {
        "name": "Ruby",
        "ext": ".rb",
        "kind": "interpreted",
        "probe": ["ruby"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "ruby",
        "monaco": "ruby",
        "comment": "#",
        "available_hint": "需安装 Ruby",
    },
    "sql": {
        "name": "SQL (SQLite)",
        "ext": ".sql",
        "kind": "interpreted",
        "probe": ["sqlite3"],
        "run": ["{exe}", ":memory:"],
        "ace_mode": "sql",
        "monaco": "sql",
        "comment": "--",
        "available_hint": "需安装 sqlite3 CLI",
    },
    "lua": {
        "name": "Lua",
        "ext": ".lua",
        "kind": "interpreted",
        "probe": ["lua", "luajit"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "lua",
        "monaco": "lua",
        "comment": "--",
        "available_hint": "需安装 Lua",
    },
    "r": {
        "name": "R",
        "ext": ".r",
        "kind": "interpreted",
        "probe": ["Rscript"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "r",
        "monaco": "r",
        "comment": "#",
        "available_hint": "需安装 R",
    },
    "perl": {
        "name": "Perl",
        "ext": ".pl",
        "kind": "interpreted",
        "probe": ["perl"],
        "run": ["{exe}", "{src}"],
        "ace_mode": "perl",
        "monaco": "perl",
        "comment": "#",
        "available_hint": "需安装 Perl",
    },
}

# 语言别名归一
ALIASES = {
    "py": "python", "python3": "python",
    "js": "javascript", "node": "javascript", "mjs": "javascript",
    "ts": "typescript",
    "sh": "bash", "shell": "bash", "zsh": "bash",
    "c++": "cpp", "cxx": "cpp", "cc": "cpp", "hpp": "cpp",
    "golang": "go",
    "rs": "rust",
    "rb": "ruby",
    "htm": "html", "html": "html",
    "yml": "yaml", "yaml": "yaml",
    "json": "json", "md": "markdown", "markdown": "markdown",
}

# 按扩展名推断语言
EXT_TO_LANG = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".go": "go", ".rs": "rust", ".java": "java",
    ".php": "php", ".rb": "ruby", ".sql": "sql",
    ".lua": "lua", ".r": "r", ".pl": "perl",
}

# 高危模式（第 40 条）：命中即拒绝执行
DANGEROUS_PATTERNS = [
    (r"rm\s+-rf\s+/(?:\s|$)", "递归删除根目录"),
    (r"rm\s+-rf\s+~(?:/|\s|$)", "递归删除用户主目录"),
    (r"rm\s+-rf\s+[A-Za-z]:[\\/](?:\s|$)", "递归删除磁盘根目录"),
    (r":\(\)\s*\{.*\};\s*:", "fork 炸弹"),
    (r"mkfs(?:\.\w+)?\s", "格式化文件系统"),
    (r"dd\s+if=.*of=/dev/[sh]d", "直接写入裸磁盘"),
    (r"format\s+[A-Za-z]:", "Windows 格式化磁盘"),
    (r">\s*/dev/sd[a-z]", "覆盖块设备"),
    (r"\bnc\s+-[el]|/dev/tcp/", "反弹 shell"),
    (r"\bcurl\b[^\n|]*\|\s*(?:ba)?sh", "管道执行远程脚本"),
    (r"\bwget\b[^\n|]*\|\s*(?:ba)?sh", "管道执行远程脚本"),
    (r"(?:shutil\.rmtree|os\.remove|os\.unlink)\s*\(\s*['\"]/(?:\s|['\"])", "递归删除根目录"),
    (r"subprocess\.(?:call|run|Popen)\s*\(\s*['\"]rm\s+-rf", "调用系统级删除"),
    (r"\\\\.\\PhysicalDrive", "写入物理磁盘"),
    (r"shutdown\s+[-/][rs]", "关闭/重启系统"),
    (r"\breg\s+delete\b", "删除注册表项"),
    (r"chmod\s+-R\s+777\s+/(?:\s|$)", "危险的权限放大"),
]

# 环境变量白名单（子进程继承的最小集合）
SAFE_ENV_KEYS = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL",
    "PYTHONIOENCODING", "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE",
    "NODE_PATH", "GOCACHE", "GOPATH", "GOROOT",
)


# ---------- 探测 ----------

_runtime_cache = None


def _which(candidates):
    """按顺序找第一个可用的可执行文件。"""
    for c in candidates:
        if not c:
            continue
        # 绝对路径且存在
        if os.path.isabs(c) and os.path.exists(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def detect_runtime(language):
    """探测单个语言的运行时；返回 (exe, meta) 或 (None, meta)。"""
    lang = normalize_language(language)
    spec = LANGUAGES.get(lang)
    if not spec:
        return None, None
    exe = _which(spec.get("probe", []))
    return exe, spec


def detect_all(force=False):
    """探测所有语言，返回 {lang: {available, exe, name, ...}}。结果带缓存。"""
    global _runtime_cache
    if _runtime_cache is not None and not force:
        return _runtime_cache

    out = {}
    for lang, spec in LANGUAGES.items():
        exe = _which(spec.get("probe", []))
        entry = {
            "key": lang,
            "name": spec["name"],
            "available": bool(exe),
            "exe": exe or "",
            "ext": spec["ext"],
            "kind": spec["kind"],
            "comment": spec.get("comment", "#"),
            "available_hint": spec.get("available_hint", ""),
        }
        if exe:
            entry["version"] = _probe_version(lang, exe)
        out[lang] = entry
    _runtime_cache = out
    return out


def _probe_version(lang, exe):
    """尽量取一句版本号，失败静默返回空串（探测本身不能影响主流程）。"""
    flag = {
        "python": ["--version"],
        "javascript": ["--version"],
        "typescript": ["--version"],
        "bash": ["--version"],
        "c": ["--version"],
        "cpp": ["--version"],
        "go": ["version"],
        "rust": ["--version"],
        "java": ["-version"],
        "php": ["--version"],
        "ruby": ["--version"],
        "sql": ["--version"],
        "lua": ["-v"],
        "r": ["--version"],
        "perl": ["--version"],
    }.get(lang, ["--version"])
    try:
        proc = subprocess.run(
            [exe] + flag,
            capture_output=True,
            timeout=5,
            env=_safe_env(),
            creationflags=_no_window(),
        )
        raw = (proc.stdout or b"") + (proc.stderr or b"")
        text = raw.decode("utf-8", errors="replace").strip()
        return text.splitlines()[0][:120] if text else ""
    except Exception:  # noqa: BLE001
        return ""


def _no_window():
    """Windows 下不弹黑框。"""
    if IS_WINDOWS:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def _safe_env(extra=None):
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if extra:
        # 仅允许注入 ASCII 键名，值强制转字符串
        for k, v in extra.items():
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)):
                env[str(k)] = str(v)
    return env


# ---------- 归一化 ----------

def normalize_language(raw):
    if not raw:
        return "python"
    key = str(raw).strip().lower()
    if key in LANGUAGES:
        return key
    return ALIASES.get(key, key)


def language_from_path(path):
    ext = Path(path or "").suffix.lower()
    return EXT_TO_LANG.get(ext, "plaintext")


def language_meta(raw):
    """返回语言的展示元信息（含默认模板）。"""
    lang = normalize_language(raw)
    spec = LANGUAGES.get(lang)
    if not spec:
        return {
            "key": lang, "name": lang or "纯文本", "ext": ".txt",
            "kind": "none", "comment": "#", "available": False,
            "available_hint": "不支持的语言", "template": "",
        }
    return {
        "key": lang,
        "name": spec["name"],
        "ext": spec["ext"],
        "kind": spec["kind"],
        "comment": spec.get("comment", "#"),
        "available_hint": spec.get("available_hint", ""),
        "template": TEMPLATES.get(lang, ""),
    }


# ---------- 代码模板（第 17 条）----------

TEMPLATES = {
    "python": 'def main():\n    print("Hello, 代码工坊!")\n\n\nif __name__ == "__main__":\n    main()\n',
    "javascript": 'function main() {\n  console.log("Hello, 代码工坊!");\n}\n\nmain();\n',
    "typescript": 'function main(): void {\n  console.log("Hello, 代码工坊!");\n}\n\nmain();\n',
    "bash": '#!/usr/bin/env bash\nset -euo pipefail\necho "Hello, 代码工坊!"\n',
    "c": '#include <stdio.h>\n\nint main(void) {\n    printf("Hello, 代码工坊!\\n");\n    return 0;\n}\n',
    "cpp": '#include <iostream>\n\nint main() {\n    std::cout << "Hello, 代码工坊!" << std::endl;\n    return 0;\n}\n',
    "go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, 代码工坊!")\n}\n',
    "rust": 'fn main() {\n    println!("Hello, 代码工坊!");\n}\n',
    "java": 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello, 代码工坊!");\n    }\n}\n',
    "php": '<?php\necho "Hello, 代码工坊!\\n";\n',
    "ruby": 'puts "Hello, 代码工坊!"\n',
    "sql": 'CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT);\nINSERT INTO demo (name) VALUES (\'代码工坊\');\nSELECT * FROM demo;\n',
    "lua": 'print("Hello, 代码工坊!")\n',
    "r": 'cat("Hello, 代码工坊!\\n")\n',
    "perl": 'use strict;\nuse warnings;\nprint "Hello, 代码工坊!\\n";\n',
}


# ---------- 危险扫描（第 40 条）----------

def scan_dangerous(code):
    """扫描高危模式，返回命中列表 [{pattern, reason}]。"""
    hits = []
    text = code or ""
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
            hits.append({"pattern": pattern, "reason": reason})
    return hits


# ---------- 执行 ----------

class RunResult(dict):
    """运行结果字典，便于直接 JSON 序列化。"""


def run_code(language, code, stdin="", timeout=None, args=None, env=None,
             allow_dangerous=False, files=None):
    """安全执行一段代码。

    :param files: 附加文件 {相对路径: 内容}，用于多文件工程（第 78 条）
    :returns: dict —— 恒返回，不抛异常（异常内部转 status）
    """
    lang = normalize_language(language)
    spec = LANGUAGES.get(lang)

    if not code or not str(code).strip():
        raise ValueError("代码不能为空")
    if len(str(code).encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"代码超过 {MAX_SOURCE_BYTES // 1024}KB 上限")
    if not spec:
        return _unavailable(lang, f"暂不支持的语言：{lang}")

    # 危险模式拦截
    hits = scan_dangerous(code)
    if hits and not allow_dangerous:
        return {
            "status": "rejected",
            "stdout": "",
            "stderr": "检测到高危操作，已拒绝执行：\n" + "\n".join(
                f"  · {h['reason']}" for h in hits
            ),
            "exit_code": -1,
            "duration_ms": 0,
            "rejected": True,
            "dangerous": hits,
        }

    exe, _ = detect_runtime(lang)
    if not exe:
        return _unavailable(lang, spec.get("available_hint", "运行时未安装"))

    timeout = _clamp_timeout(timeout)
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="codeforge_") as tmp:
        tmpdir = Path(tmp)
        src_name = _source_name(lang)
        src = tmpdir / src_name
        src.write_text(str(code), encoding="utf-8")

        # 附加文件
        if files and isinstance(files, dict):
            for rel, content in list(files.items())[:50]:
                safe_rel = _safe_relative(rel)
                if not safe_rel:
                    continue
                target = tmpdir / safe_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")

        argv_src = [str(src)]
        argv_out = [str(tmpdir / (src.stem + (".exe" if IS_WINDOWS else ".out")))]

        # 编译阶段
        if spec["kind"] == "compiled":
            compile_argv = _build_argv(spec.get("compile"), exe, src, argv_out, tmpdir)
            if lang == "java":
                # javac 的 exe 走 javac，但探测的是 java；此处单独定位
                javac = shutil.which("javac")
                if not javac:
                    return _unavailable(lang, "未找到 javac（需完整 JDK）")
                compile_argv[0] = javac
            cproc = _spawn(compile_argv, "", tmpdir, timeout, env)
            if cproc["exit_code"] != 0:
                return {
                    "status": "compile_error",
                    "stdout": cproc["stdout"],
                    "stderr": cproc["stderr"] or "编译失败",
                    "exit_code": cproc["exit_code"],
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "diagnostics": parse_diagnostics(lang, cproc["stderr"]),
                    "truncated": cproc["truncated"],
                }

        # 执行阶段
        run_argv = _build_argv(spec.get("run"), exe, src, argv_out, tmpdir)
        if args:
            run_argv = run_argv + [str(a) for a in list(args)[:20]]
        proc = _spawn(run_argv, stdin, tmpdir, timeout, env)

    elapsed = int((time.perf_counter() - started) * 1000)
    status = {
        0: "ok",
        None: "timeout",
    }.get(proc.get("exit_code"), "error")
    if proc.get("timed_out"):
        status = "timeout"
    elif proc.get("memory_exceeded"):
        status = "memory"

    return {
        "status": status,
        "stdout": proc["stdout"],
        "stderr": proc["stderr"],
        "exit_code": proc.get("exit_code", 0),
        "signal_name": proc.get("signal_name", ""),
        "duration_ms": elapsed,
        "memory_kb": proc.get("memory_kb", 0),
        "truncated": proc.get("truncated", False),
        "diagnostics": parse_diagnostics(lang, proc["stderr"]),
        "language": lang,
    }


def _clamp_timeout(timeout):
    try:
        t = float(timeout if timeout is not None else DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT
    return max(0.5, min(t, MAX_TIMEOUT))


def _source_name(lang):
    if lang == "java":
        return "Main.java"
    ext = LANGUAGES.get(lang, {}).get("ext", ".txt")
    return f"main{ext}"


def _safe_relative(rel):
    """只允许工作目录内的相对路径，杜绝 ../ 穿越。"""
    s = str(rel or "").replace("\\", "/").strip().lstrip("/")
    if not s or ".." in s.split("/"):
        return None
    if re.match(r"^[A-Za-z]:", s):
        return None
    return s[:200]


def _build_argv(template, exe, src, out, tmpdir):
    if not template:
        return [exe, str(src)]
    mapping = {
        "{exe}": exe,
        "{src}": str(src),
        "{out}": out[0],
        "{dir}": str(tmpdir),
    }
    argv = []
    for tok in template:
        for k, v in mapping.items():
            tok = tok.replace(k, v)
        argv.append(tok)
    return argv


def _spawn(argv, stdin, cwd, timeout, env):
    """启动子进程并收集结果；恒定返回字典，不抛异常。"""
    result = {
        "stdout": "", "stderr": "", "exit_code": 0,
        "timed_out": False, "signal_name": "", "memory_kb": 0,
        "truncated": False, "memory_exceeded": False,
    }
    preexec = _limit_memory() if not IS_WINDOWS else None
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=_safe_env(env),
            shell=False,
            preexec_fn=preexec,
            creationflags=_no_window(),
        )
    except FileNotFoundError as e:
        result["stderr"] = f"找不到可执行文件：{e}"
        result["exit_code"] = 127
        return result
    except PermissionError as e:
        result["stderr"] = f"没有执行权限：{e}"
        result["exit_code"] = 126
        return result
    except OSError as e:
        result["stderr"] = f"启动失败：{e}"
        result["exit_code"] = 126
        return result

    try:
        out, err = proc.communicate(
            input=(stdin or "").encode("utf-8"),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        _kill(proc)
        try:
            out, err = proc.communicate(timeout=2)
        except Exception:  # noqa: BLE001
            out, err = b"", b""
        out = (out or b"") + "\n[执行超时，进程已被终止]".encode("utf-8")
        result["exit_code"] = None
        result["stderr"] = _decode(err)
        result["stdout"] = _decode(out)
        return result

    stdout, trunc1 = _decode_limited(out)
    stderr, trunc2 = _decode_limited(err)
    result["stdout"] = stdout
    result["stderr"] = stderr
    result["truncated"] = trunc1 or trunc2
    result["exit_code"] = proc.returncode
    if proc.returncode is not None and proc.returncode < 0:
        result["signal_name"] = _signal_name(-proc.returncode)
    result["memory_kb"] = _peak_memory_kb()
    return result


def _kill(proc):
    # B23：收窄异常——原来 except Exception 会把 MemoryError 之类真bug也吞了。
    # 杀进程在清理路径上，预期失败只有「进程已退出/无权终止」（都是 OSError 家族）
    try:
        proc.kill()
    except OSError:
        pass


def _decode(raw):
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")


def _decode_limited(raw):
    """解码并按字节截断（第 26 条）。"""
    if not raw:
        return "", False
    truncated = len(raw) > OUTPUT_LIMIT
    if truncated:
        raw = raw[:OUTPUT_LIMIT]
    text = _decode(raw)
    if truncated:
        text += f"\n\n… [输出超过 {OUTPUT_LIMIT // 1024}KB，已截断]"
    return text, truncated


def _signal_name(num):
    """把负的 returncode 还原成信号名，便于前端展示（第 31 条）。"""
    names = {
        1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 4: "SIGILL", 6: "SIGABRT",
        8: "SIGFPE", 9: "SIGKILL", 11: "SIGSEGV", 13: "SIGPIPE",
        14: "SIGALRM", 15: "SIGTERM",
    }
    return names.get(num, f"SIG{num}")


def _limit_memory():
    """POSIX 下限制子进程地址空间；Windows 无法设置，返回 None 降级。"""
    try:
        import resource  # noqa: PLC0415

        limit = MEMORY_LIMIT_MB * 1024 * 1024

        def _set():
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

        return _set
    except Exception:  # noqa: BLE001
        return None


def _peak_memory_kb():
    """尽力取本次进程树峰值内存；取不到返回 0（不阻塞主流程）。"""
    try:
        import resource  # noqa: PLC0415

        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        if IS_WINDOWS:
            return int(usage.ru_maxrss)  # Windows 上单位是字节
        return int(usage.ru_maxrss)  # Linux 上是 KB
    except Exception:  # noqa: BLE001
        return 0


def _unavailable(lang, hint):
    return {
        "status": "unavailable",
        "code": "RUNTIME_NOT_FOUND",
        "stdout": "",
        "stderr": f"{hint}\n\n该语言的运行时在本机不可用，代码已保存但未执行。",
        "exit_code": -1,
        "duration_ms": 0,
        "available": False,
        "language": lang,
    }


# ---------- 结构化诊断（第 36/37 条）----------

_TRACEBACK_FRAME = re.compile(
    r'^\s*File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>.+))?\s*$'
)
_GCC_DIAG = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<level>error|warning|note):\s*(?P<msg>.+)$",
    re.MULTILINE,
)
_GENERIC_DIAG = re.compile(
    r"^(?P<file>[^:\n]+?\.\w+):(?P<line>\d+):\s*(?P<level>error|warning):\s*(?P<msg>.+)$",
    re.MULTILINE,
)


def parse_diagnostics(language, stderr):
    """把编译/运行报错解析成结构化列表，供编辑器做行内标注。"""
    if not stderr:
        return []
    lang = normalize_language(language)
    out = []

    if lang == "python":
        frames = []
        for line in stderr.splitlines():
            m = _TRACEBACK_FRAME.match(line)
            if m:
                frames.append({
                    "file": Path(m.group("file")).name,
                    "line": int(m.group("line")),
                    "function": (m.group("func") or "").strip(),
                })
        err_type, err_msg = _python_error_line(stderr)
        if frames or err_type:
            last = frames[-1] if frames else {}
            out.append({
                "severity": "error",
                "type": err_type or "Error",
                "message": err_msg,
                "line": last.get("line"),
                "file": last.get("file", ""),
                "function": last.get("function", ""),
                "frames": frames,
            })
        return out

    if lang in ("c", "cpp", "go", "rust", "java"):
        for m in _GCC_DIAG.finditer(stderr):
            out.append({
                "severity": "error" if m.group("level") == "error" else "warning",
                "type": m.group("level"),
                "message": m.group("msg").strip(),
                "line": int(m.group("line")),
                "column": int(m.group("col")),
                "file": Path(m.group("file")).name,
            })
        if not out:
            # rustc 风格：error[E0382]: ...
            for m in re.finditer(r"^(?P<sev>error|warning)(?:\[(?P<code>[^\]]+)\])?:\s*(?P<msg>.+)$",
                                 stderr, re.MULTILINE):
                out.append({
                    "severity": "error" if m.group("sev") == "error" else "warning",
                    "type": m.group("code") or m.group("sev"),
                    "message": m.group("msg").strip(),
                })
        return out

    for m in _GENERIC_DIAG.finditer(stderr):
        out.append({
            "severity": "error" if m.group("level") == "error" else "warning",
            "type": m.group("level"),
            "message": m.group("msg").strip(),
            "line": int(m.group("line")),
            "file": Path(m.group("file")).name,
        })
    return out


def _python_error_line(stderr):
    """从 traceback 末尾取 'ValueError: xxx' 这类信息。"""
    for line in reversed(stderr.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt|Iteration|Overflow|Recursion)):\s*(.*)$", line)
        if m:
            return m.group(1), m.group(2)
        if re.match(r"^[A-Za-z_][\w.]*:\s", line):
            name, _, msg = line.partition(":")
            return name.strip(), msg.strip()
    return "", stderr.strip().splitlines()[-1][:300] if stderr.strip() else ""


# ---------- 语言静态分析（第 43–64 条的本地降级基础）----------

def analyze_metrics(code, language):
    """本地静态指标分析：行数、复杂度、函数/类数量、注释率、圈复杂度估算。

    不依赖 LLM，作为 AI 能力不可用时的兜底（第 53/54 条）。
    """
    text = code or ""
    lines = text.split("\n")
    total = len(lines)
    blank = sum(1 for ln in lines if not ln.strip())

    lang = normalize_language(language)
    comment_token = LANGUAGES.get(lang, {}).get("comment", "#")
    comment = sum(1 for ln in lines if ln.strip().startswith(comment_token))
    # C 系多行注释粗估
    if lang in ("c", "cpp", "java", "javascript", "typescript", "go", "rust", "php"):
        comment += text.count("//")
        comment += text.count("/*")

    code_lines = max(1, total - blank - comment)

    # 圈复杂度估算：分支关键字 + 逻辑运算符
    branch_pat = (
        r"\bif\b|\belse\s+if\b|\belif\b|\bfor\b|\bwhile\b|\bcase\b|\bcatch\b"
        r"|\bswitch\b|\bmatch\b|\?\s*[^:]+:|&&|\|\||\band\b|\bor\b"
    )
    branches = len(re.findall(branch_pat, text))

    # 函数/类定义
    funcs = re.findall(r"(?:^|\n)\s*(?:def|function|func|fn|void|int|double|float|char|public|private|static|async)\s+([A-Za-z_]\w*)\s*\(", text)
    classes = re.findall(r"(?:^|\n)\s*(?:class|struct|interface|enum|trait)\s+([A-Za-z_]\w*)", text)

    max_line = max((len(ln) for ln in lines), default=0)
    long_lines = sum(1 for ln in lines if len(ln) > 120)
    todos = re.findall(r"(?:TODO|FIXME|XXX|HACK)\b", text, re.IGNORECASE)
    has_trailing_ws = sum(1 for ln in lines if ln.rstrip() != ln)

    # 质量评分（0-100），扣分项透明可解释
    score = 100
    deductions = []
    if max_line > 120:
        score -= min(10, (max_line - 120) // 20 + 2)
        deductions.append(f"存在超长行（最长 {max_line} 字符）")
    if long_lines > total * 0.15 and total > 10:
        score -= 8
        deductions.append(f"超长行占比偏高（{long_lines}/{total}）")
    if todos:
        score -= min(6, len(todos))
        deductions.append(f"存在 {len(todos)} 处 TODO/FIXME")
    if has_trailing_ws:
        score -= min(5, has_trailing_ws // 3 + 1)
        deductions.append(f"{has_trailing_ws} 行有行尾空白")
    if total > 30 and comment == 0:
        score -= 10
        deductions.append("代码超过 30 行但没有任何注释")
    if branches > 0 and funcs and branches / max(1, len(funcs)) > 8:
        score -= 10
        deductions.append(f"平均每函数分支数偏高（{branches}/{len(funcs)}），建议拆分")
    if not funcs and total > 25 and lang not in ("sql", "bash"):
        score -= 6
        deductions.append("没有识别到函数定义，可能未做模块化")
    score = max(0, min(100, score))

    return {
        "total_lines": total,
        "code_lines": code_lines,
        "blank_lines": blank,
        "comment_lines": comment,
        "comment_ratio": round(comment / max(1, total), 3),
        "max_line_length": max_line,
        "long_lines": long_lines,
        "functions": len(set(funcs)),
        "function_names": sorted(set(funcs))[:50],
        "classes": len(set(classes)),
        "class_names": sorted(set(classes))[:50],
        "cyclomatic": branches + 1,
        "avg_complexity": round((branches + 1) / max(1, len(set(funcs))), 2),
        "todos": len(todos),
        "todo_items": todos[:20],
        "quality_score": score,
        "deductions": deductions,
    }


def to_flow_nodes(code, language):
    """把代码粗粒度抽成流程图节点（第 62 条）——基于缩进的轻量启发式。

    返回 {nodes: [{id, label, type, line}], edges: [{from, to, label}]}
    """
    lang = normalize_language(language)
    lines = (code or "").split("\n")
    nodes, edges = [], []
    stack = []      # [(node_id, indent)]
    counter = [0]

    def new_id(prefix):
        counter[0] += 1
        return f"{prefix}{counter[0]}"

    start = new_id("n")
    nodes.append({"id": start, "label": "开始", "type": "start", "line": 1})
    stack.append((start, -1))
    last = start

    patterns = [
        (r"^\s*(?:if|elif)\b|^\s*else\s+if\b", "condition", "if"),
        (r"^\s*else\b", "condition", "else"),
        (r"^\s*(?:for|while)\b", "loop", "loop"),
        (r"^\s*(?:def|function|func|fn)\s+(\w+)", "function", None),
        (r"^\s*class\s+(\w+)", "class", None),
        (r"^\s*(?:return|break|continue|raise|throw)\b", "io", "return"),
        (r"^\s*(?:print|console\.log|fmt\.Print|System\.out|echo)\b", "io", "output"),
        (r"^\s*(?:input|readline|scanf|std::cin|gets)\b", "io", "input"),
    ]

    for idx, line in enumerate(lines, start=1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        indent = len(line) - len(line.lstrip())
        for pat, ntype, label in patterns:
            m = re.match(pat, line)
            if not m:
                continue
            if ntype == "function" and m.lastindex:
                text = f"函数 {m.group(1)}"
            elif ntype == "class" and m.lastindex:
                text = f"类 {m.group(1)}"
            else:
                text = {"condition": "条件判断", "loop": "循环",
                        "io": {"return": "返回", "output": "输出", "input": "输入"}.get(label, "IO")}.get(ntype, s[:32])
            nid = new_id("n")
            while stack and stack[-1][1] >= indent:
                stack.pop()
            parent = stack[-1][0] if stack else start
            nodes.append({"id": nid, "label": text, "type": ntype, "line": idx})
            edges.append({"from": parent, "to": nid, "label": ""})
            stack.append((nid, indent))
            last = nid
            break

    end = new_id("n")
    nodes.append({"id": end, "label": "结束", "type": "end", "line": len(lines)})
    edges.append({"from": last, "to": end, "label": ""})
    return {"nodes": nodes, "edges": edges}


def estimate_complexity(code, language):
    """复杂度分析（第 58 条）：Big-O 估算 + 嵌套深度。"""
    lines = (code or "").split("\n")
    depth = 0
    max_depth = 0
    loop_depths = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        indent = len(line) - len(line.lstrip())
        cur = indent // 4
        if re.match(r"^\s*(?:for|while)\b", line):
            loop_depths.append(cur + 1)
        depth = cur
        max_depth = max(max_depth, cur)

    max_loop = max(loop_depths) if loop_depths else 0
    if max_loop >= 3:
        big_o = "O(n^3) 或更高"
        hint = "三层及以上嵌套循环，注意数据规模"
    elif max_loop == 2:
        big_o = "O(n^2)"
        hint = "双层循环，考虑用哈希表/排序优化到 O(n log n)"
    elif max_loop == 1:
        big_o = "O(n)"
        hint = "线性复杂度，通常可以接受"
    else:
        big_o = "O(1)"
        hint = "没有检测到循环，为常数级"

    # 递归检测
    recursive = False
    for m in re.finditer(r"(?:def|function|func|fn)\s+(\w+)", code or ""):
        name = m.group(1)
        body = (code or "")[m.end():]
        if re.search(rf"\b{re.escape(name)}\s*\(", body):
            recursive = True
            break
    if recursive:
        big_o += "（含递归）"
        hint += "；检测到递归调用，注意栈深度与重复子问题"

    return {
        "big_o": big_o,
        "max_loop_depth": max_loop,
        "max_indent_depth": max_depth,
        "recursive": recursive,
        "hint": hint,
    }
