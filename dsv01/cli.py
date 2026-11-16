# -*- coding: utf-8 -*-
"""Ds v0.1 终端驱动。

两个入口：
- `dscc`：编译器风格驱动。`dscc file.ds` 解释执行（参考实现），支持规范里的
  `-o/--app/--bare/--target/--opt/--gc/--rt` 选项；`--emit tokens|ast|check` 查看中间产物。
- `ds`：Python 风格驱动。`ds file.ds` 运行脚本、`ds` 进入 REPL、`ds -c "code"` 直接执行。

退出码与规范一致：0 成功 / 1 编译或运行错误 / 2 用法错误 / 3 内部错误 / 4 链接不可用。
"""

from __future__ import annotations

import os
import sys
from . import __version__
from . import builtins as bi
from .interp import Interpreter
from .lexer import DsSyntaxError, significant, tokenize

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_INTERNAL, EXIT_LINK = 0, 1, 2, 3, 4

APP_DEFAULTS = {"gc": "tracing", "rt": "full"}
BARE_DEFAULTS = {"gc": "none", "rt": "minimal"}
GC_MODES = ("none", "rc", "arc", "tracing")
RT_KINDS = ("none", "minimal", "full")
EMIT_KINDS = ("run", "tokens", "ast", "check")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
def _build_parser(prog: str, require_input: bool):
    import argparse

    p = argparse.ArgumentParser(
        prog=prog,
        description="Ds v0.1 参考驱动（Python 解释执行；不产出机器码）",
        epilog="示例: %(prog)s examples/tour.ds --app   |   %(prog)s --emit tokens file.ds",
    )
    p.add_argument("input", nargs="?" if not require_input else None, help=".ds 源文件")
    p.add_argument("-o", "--output", help="[编译器兼容] 输出路径；参考驱动不产出可执行文件")
    p.add_argument("--app", action="store_true", help="应用模式（默认）")
    p.add_argument("--bare", action="store_true", help="裸机模式：无 GC/线程，默认 --gc none --rt minimal")
    p.add_argument("--target", default=None, help="目标三元组（参考驱动忽略，仅记录）")
    p.add_argument("--opt", default=None, help="优化级别 0|1|2|3|s|z（参考驱动忽略，仅记录）")
    p.add_argument("--gc", default=None, choices=GC_MODES, help="GC 策略")
    p.add_argument("--rt", default=None, choices=RT_KINDS, help="运行时种类")
    p.add_argument("--emit", default="run", choices=EMIT_KINDS, help="产物：run/tokens/ast/check")
    p.add_argument("--check", action="store_true", help="仅解析检查（等价 --emit check）")
    p.add_argument("-c", "--code", default=None, help="直接执行一段 Ds 源码（类似 python -c）")
    p.add_argument("--repl", action="store_true", help="进入交互式 REPL")
    p.add_argument("--quiet", action="store_true", help="安静模式")
    p.add_argument("-v", "--verbose", action="store_true", help="打印运行配置")
    p.add_argument("--version", action="version", version=f"%(prog)s (Ds v{__version__})")
    return p


# ---------------------------------------------------------------------------
# 选项校验
# ---------------------------------------------------------------------------
def _resolve_config(args) -> dict:
    if args.app and args.bare:
        raise SystemExit(_usage("--app 与 --bare 互斥"))
    bare = bool(args.bare)
    mode = "bare" if bare else "app"
    defaults = BARE_DEFAULTS if bare else APP_DEFAULTS
    gc_mode = args.gc if args.gc is not None else defaults["gc"]
    rt = args.rt if args.rt is not None else defaults["rt"]
    if bare and gc_mode != "none":
        raise SystemExit(_usage("--bare 下只允许 --gc none"))
    if bare and rt == "full":
        raise SystemExit(_usage("--bare 下不允许 --rt full"))
    opt_arg = args.opt if args.opt is not None else "2"
    if opt_arg not in ("0", "1", "2", "3", "s", "z"):
        raise SystemExit(_usage(f"非法 --opt 值：{opt_arg}"))
    return {
        "bare": bare,
        "mode": mode,
        "gc_mode": gc_mode,
        "rt": rt,
        "target": args.target or "host",
        "opt": 0 if opt_arg in ("0",) else 2,
    }


def _prog() -> str:
    """终端里显示的命令名（ds、dscc、启动ds 等）。"""
    name = os.path.basename(sys.argv[0] or "")
    return name if name else "ds"


def _usage(msg: str) -> int:
    print(f"{_prog()}: error: {msg}", file=sys.stderr)
    return EXIT_USAGE


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
def _make_interp(cfg: dict, *, stdout=None) -> Interpreter:
    return Interpreter(
        stdout=stdout,
        bare=cfg["bare"],
        gc_mode=cfg["gc_mode"],
        rt=cfg["rt"],
        target=cfg["target"],
        opt=cfg["opt"],
    )


def _read_source(args) -> tuple[str, str]:
    if args.code is not None:
        return args.code, "<code>"
    path = os.path.expanduser(args.input)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read(), path
    except FileNotFoundError:
        print(f"{_prog()}: error: 找不到源文件：{args.input}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
    except OSError as exc:
        print(f"{_prog()}: error: 读取失败：{exc}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def _report(exc: BaseException) -> int:
    if isinstance(exc, OSError):
        where = getattr(exc, "filename", None) or ""
        print(f"error: 无法读取文件：{where or exc}", file=sys.stderr)
        return EXIT_ERROR
    if isinstance(exc, DsSyntaxError):
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if isinstance(exc, bi.DsPanic):
        print(f"panic: {bi.to_str(exc.value)}", file=sys.stderr)
        return EXIT_ERROR
    if isinstance(exc, bi.DsRuntimeError):
        label = "type error" if getattr(exc, "check", False) else "runtime error"
        print(f"{label}: {exc.msg if hasattr(exc, 'msg') else exc}", file=sys.stderr)
        return EXIT_ERROR
    if isinstance(exc, RecursionError):
        print("runtime error: 递归过深", file=sys.stderr)
        return EXIT_ERROR
    print(f"internal error: {exc!r}", file=sys.stderr)
    return EXIT_INTERNAL


def _run(args, cfg: dict) -> int:
    emit = "check" if args.check else args.emit
    src, filename = _read_source(args)
    if args.output and emit == "run" and not args.quiet:
        print("提示: 参考驱动不产出可执行文件，-o 已忽略（可用 --emit tokens|ast 查看中间产物）",
              file=sys.stderr)
    if args.verbose:
        print(f"mode={cfg['mode']} gc={cfg['gc_mode']} rt={cfg['rt']} "
              f"target={cfg['target']} emit={emit}", file=sys.stderr)

    if emit == "tokens":
        try:
            tokens = tokenize(src, filename)
        except DsSyntaxError as exc:
            return _report(exc)
        for tok in significant(tokens):
            text = tok.text if isinstance(tok.text, str) else repr(tok.text)
            print(f"{tok.line}:{tok.col}\t{tok.kind}\t{text}")
        return EXIT_OK

    from .parser import parse_program

    if emit == "ast":
        try:
            program = parse_program(src, filename)
        except DsSyntaxError as exc:
            return _report(exc)
        print(program)
        return EXIT_OK

    interp = _make_interp(cfg)
    try:
        if emit == "check":
            program = parse_program(src, filename)
            from .checker import check_program
            check_program(program)
            return EXIT_OK
        interp.run_source(src, filename)
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 统一转退出码
        return _report(exc)
    return EXIT_OK


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------
REPL_HELP = """\
命令:
  :help            显示本帮助
  :quit / :q       退出
  :reset           重置解释器状态
  :load <文件>      运行一个 .ds 文件
  :version         版本
直接输入 Ds 代码回车执行；未闭合的块/括号会自动续行，空行结束。"""


def _readline_from(stream, prompt: str) -> str:
    if prompt:
        if stream is sys.stdin:
            print(prompt, end="", flush=True)   # stdin 只读，提示符走 stdout
        else:
            try:
                stream.write(prompt)
                stream.flush()
            except (OSError, ValueError):
                pass
    line = stream.readline()
    if line == "":
        raise EOFError
    return line.rstrip("\n")


def _repl(args, cfg: dict) -> int:
    from .parser import parse_repl

    interp = _make_interp(cfg)
    if not args.quiet:
        print(f"Ds v{__version__} 编译器 · 交互终端（:help 查看命令，Ctrl-D 退出）")

    stream = sys.stdin
    interactive = stream.isatty()
    if not interactive:
        tty = None
        for mode in ("r+", "r"):
            try:
                tty = open("/dev/tty", mode, encoding="utf-8", errors="replace")
                break
            except OSError:
                tty = None
        if tty is not None:
            stream = tty
            interactive = True

    had_input = False
    buffer = ""
    while True:
        prompt = (("ds> " if not buffer else "... ") if interactive else "")
        try:
            line = _readline_from(stream, prompt) if interactive else input("")
        except EOFError:
            if not had_input and not interactive:
                print(
                    f"Ds v{__version__} 编译器：当前 stdin 不是交互式终端，无法进入会话。\n"
                    "  · 在终端里直接运行：  启动ds\n"
                    "  · 运行脚本：          启动ds 文件.ds\n"
                    "  · 执行一段代码：      启动ds -c 'package t\nfn main() { println(\"hi\") }'",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            if interactive:
                print()
            return EXIT_OK
        except KeyboardInterrupt:
            print("\n(中断；已清空输入)")
            buffer = ""
            continue
        had_input = True
        stripped = line.strip()
        if not buffer and stripped.startswith(":"):
            if stripped in (":q", ":quit", ":exit"):
                return EXIT_OK
            if stripped == ":help":
                print(REPL_HELP)
                continue
            if stripped == ":reset":
                interp = _make_interp(cfg)
                print("(已重置)")
                continue
            if stripped == ":version":
                print(f"Ds v{__version__}")
                continue
            if stripped.startswith(":load "):
                path = os.path.expanduser(stripped[len(":load "):].strip())
                try:
                    interp.run_file(path)
                except BaseException as exc:  # noqa: BLE001
                    _report(exc)
                continue
            print(f"未知命令：{stripped}（:help）")
            continue
        buffer = f"{buffer}\n{line}" if buffer else line
        if not buffer.strip():
            buffer = ""
            continue
        if _brackets_open(buffer):
            continue
        try:
            nodes = parse_repl(buffer)
        except DsSyntaxError as exc:
            if _looks_incomplete(buffer):
                continue
            _report(exc)
            buffer = ""
            continue
        buffer = ""
        try:
            value = interp.run_repl_nodes(nodes)
        except DsSyntaxError as exc:
            _report(exc)
            continue
        except BaseException as exc:  # noqa: BLE001
            _report(exc)
            continue
        if value is not bi.UNIT:
            print(f"=> {bi.to_str(value)}")


def _brackets_open(text: str) -> bool:
    depth = 0
    quote = False
    escaped = False
    for ch in text:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quote = False
            continue
        if ch == '"':
            quote = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth > 0 or quote


def _looks_incomplete(text: str) -> bool:
    return _brackets_open(text)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _init_stdio() -> None:
    """管道被下游关闭时静默退出（python ... | head 场景）。"""
    try:
        import signal

        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass


def main_dscc(argv: list[str] | None = None) -> int:
    _init_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser("dscc", require_input=True)
    args = parser.parse_args(argv)
    try:
        cfg = _resolve_config(args)
    except SystemExit as exc:
        return int(exc.code or EXIT_USAGE)
    if args.repl:
        return _repl(args, cfg)
    return _run(args, cfg)


def main_ds(argv: list[str] | None = None) -> int:
    _init_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser("ds", require_input=False)
    args = parser.parse_args(argv)
    try:
        cfg = _resolve_config(args)
    except SystemExit as exc:
        return int(exc.code or EXIT_USAGE)
    if args.repl or (args.input is None and args.code is None):
        return _repl(args, cfg)
    return _run(args, cfg)


if __name__ == "__main__":
    sys.exit(main_dscc(sys.argv[1:]))
