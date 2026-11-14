# -*- coding: utf-8 -*-
"""Ds v0.1 运行时的值、内建对象与 prelude（解释器与 CLI 共用）。

这里只放「值」和与求值无关的小工具；真正的求值逻辑在 interp.py。
"""

from __future__ import annotations

import math
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from . import ast


# ---------------------------------------------------------------------------
# 基础值
# ---------------------------------------------------------------------------
class _Unit:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "unit"

    def __bool__(self) -> bool:
        return False


UNIT = _Unit()


class _Never:
    """`never` 类型/不可能值（panic 的返回占位）。"""

    def __repr__(self) -> str:
        return "never"


NEVER = _Never()


class Opt:
    """opt[T]：some(v) / none。"""

    __slots__ = ("value", "is_none")

    def __init__(self, value: Any = None, is_none: bool = False):
        self.value = value
        self.is_none = is_none

    def __repr__(self) -> str:
        return "none" if self.is_none else f"some({self.value!r})"


NONE = Opt(is_none=True)


def some(v: Any) -> Opt:
    return Opt(v)


class Res:
    """res[T, E]：ok(v) / err(e)。"""

    __slots__ = ("ok", "value")

    def __init__(self, ok: bool, value: Any):
        self.ok = ok
        self.value = value

    def __repr__(self) -> str:
        return f"ok({self.value!r})" if self.ok else f"err({self.value!r})"


def ok(v: Any) -> Res:
    return Res(True, v)


def err(e: Any) -> Res:
    return Res(False, e)


class DsErrorValue:
    """prelude error 值：`error("message")`。"""

    __slots__ = ("message", "kind")

    def __init__(self, message: Any = "", kind: str = "error"):
        self.message = message
        self.kind = kind

    def __repr__(self) -> str:
        return f"error({self.message!r})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, DsErrorValue) and other.message == self.message


class DsPanic(Exception):
    """`panic` 抛出；被 `catch panic` 捕获或由 CLI 终止。"""

    def __init__(self, value: Any):
        self.value = value
        super().__init__(str(value))


class DsRuntimeError(Exception):
    """运行期错误（类型不匹配、未定义名字等）。"""

    def __init__(self, msg: str, line: int = 0, col: int = 0):
        self.msg, self.line, self.col = msg, line, col
        super().__init__(msg)


class TryPropagate(Exception):
    """`try e` 遇到 err 时用于立即从所在函数返回 err。"""

    def __init__(self, err_value: Any):
        self.err_value = err_value


# ---------------------------------------------------------------------------
# 函数
# ---------------------------------------------------------------------------
class NativeFunction:
    __slots__ = ("name", "fn")

    def __init__(self, name: str, fn: Callable[[list, list], Any]):
        self.name = name
        self.fn = fn

    def __repr__(self) -> str:
        return f"<native fn {self.name}>"


class DsFunction:
    """用户函数（含方法）。闭包是 interp.Env（鸭子类型）。"""

    __slots__ = ("decl", "closure", "interp", "is_class_method", "owner_type")

    def __init__(self, decl: ast.FnDecl, closure: Any, interp: Any,
                 is_class_method: bool = False, owner_type: Any = None):
        self.decl = decl
        self.closure = closure
        self.interp = interp
        self.is_class_method = is_class_method
        self.owner_type = owner_type

    @property
    def name(self) -> str:
        return self.decl.name

    def __repr__(self) -> str:
        return f"<fn {self.decl.name}>"


class BoundMethod:
    __slots__ = ("receiver", "func")

    def __init__(self, receiver: Any, func: DsFunction):
        self.receiver = receiver
        self.func = func

    def __repr__(self) -> str:
        return f"<bound {self.func.name}>"


class SuperProxy:
    """`super`：指向父类实现，绑定到同一个实例。"""

    __slots__ = ("instance", "parent")

    def __init__(self, instance: Any, parent: Any):
        self.instance = instance
        self.parent = parent


class Macro:
    __slots__ = ("decl", "closure", "interp")

    def __init__(self, decl: ast.MacroDecl, closure: Any, interp: Any):
        self.decl = decl
        self.closure = closure
        self.interp = interp

    def __repr__(self) -> str:
        return f"<macro {self.decl.name}>"


# ---------------------------------------------------------------------------
# 类型与实例
# ---------------------------------------------------------------------------
class TypeDef:
    """type / class / trait 的运行时描述。"""

    __slots__ = ("name", "kind", "fields", "defaults", "methods", "parent_expr",
                 "parent", "packed", "generics", "alias", "traits", "interp")

    def __init__(self, name: str, kind: str, fields: list[ast.FieldDecl] | None = None,
                 parent_expr: ast.TypeExpr | None = None, packed: bool = False,
                 generics: list[str] | None = None, alias: ast.TypeExpr | None = None,
                 interp: Any = None):
        self.name = name
        self.kind = kind                      # type | class | trait
        self.fields = fields or []
        self.defaults = [f.default for f in self.fields]
        self.methods: dict[str, DsFunction] = {}
        self.parent_expr = parent_expr
        self.parent: TypeDef | None = None
        self.packed = packed
        self.generics = generics or []
        self.alias = alias
        self.traits: list[str] = []
        self.interp = interp

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def resolve_parent(self):
        if self.parent is None and self.parent_expr is not None:
            name = type_name_of(self.parent_expr)
            if name:
                self.parent = self.interp.find_type(name)
        return self.parent

    def lookup_method(self, name: str, seen=None) -> DsFunction | None:
        if name in self.methods:
            return self.methods[name]
        parent = self.resolve_parent()
        if parent is not None:
            return parent.lookup_method(name)
        return None

    def is_subclass_of(self, other: "TypeDef") -> bool:
        cur: TypeDef | None = self
        guard = 0
        while cur is not None and guard < 64:
            if cur is other or cur.name == other.name:
                return True
            cur = cur.resolve_parent()
            guard += 1
        return False

    def __repr__(self) -> str:
        return f"<{self.kind} {self.name}>"


class DsInstance:
    __slots__ = ("type_def", "fields")

    def __init__(self, type_def: TypeDef, fields: dict[str, Any] | None = None):
        self.type_def = type_def
        self.fields = fields or {}

    def __repr__(self) -> str:
        items = ", ".join(f"{k}: {v!r}" for k, v in self.fields.items())
        return f"{self.type_def.name}({items})"


class TraitObject:
    """`dyn Trait` 装箱值（保留真实实例与目标 trait 名）。"""

    __slots__ = ("value", "trait_name")

    def __init__(self, value: Any, trait_name: str):
        self.value = value
        self.trait_name = trait_name

    def __repr__(self) -> str:
        return f"dyn {self.trait_name}"


class Module:
    __slots__ = ("name", "env", "file", "interp")

    def __init__(self, name: str, env: dict | None = None, file: str | None = None):
        self.name = name
        self.env = env or {}
        self.file = file
        self.interp = None

    def get(self, name: str):
        env = self.env
        if hasattr(env, "lookup"):           # interp.Env
            try:
                return env.lookup(name)
            except Exception:
                raise DsRuntimeError(f"模块 {self.name} 中没有 {name}")
        if name not in env:
            raise DsRuntimeError(f"模块 {self.name} 中没有 {name}")
        return env[name]

    def __repr__(self) -> str:
        return f"<mod {self.name}>"


# ---------------------------------------------------------------------------
# 并发原语
# ---------------------------------------------------------------------------
class Chan:
    """chan[T]。容量 0 在参考驱动中按无界缓冲近似（见 README 限制）。"""

    __slots__ = ("cap", "buf", "cond", "closed", "elem_type")

    def __init__(self, cap: int = 0, elem_type: str = "?"):
        self.cap = int(cap)
        self.buf: deque = deque()
        self.cond = threading.Condition()
        self.closed = False
        self.elem_type = elem_type

    def send(self, value: Any) -> Res:
        with self.cond:
            if self.closed:
                return err(DsErrorValue("send on closed channel"))
            self.buf.append(value)
            self.cond.notify_all()
        return ok(UNIT)

    def recv(self) -> Opt:
        with self.cond:
            while not self.buf and not self.closed:
                self.cond.wait()
            if self.buf:
                return some(self.buf.popleft())
            return NONE

    def close(self) -> _Unit:
        with self.cond:
            self.closed = True
            self.cond.notify_all()
        return UNIT

    def __repr__(self) -> str:
        return f"<chan {self.elem_type}>"


class DsMutex:
    __slots__ = ("value", "lock_obj")

    def __init__(self, value: Any = UNIT):
        self.value = value
        self.lock_obj = threading.RLock()

    def lock(self) -> "MutexGuard":
        self.lock_obj.acquire()
        return MutexGuard(self)

    def __repr__(self) -> str:
        return f"<mutex {self.value!r}>"


class MutexGuard:
    __slots__ = ("mutex", "held")

    def __init__(self, mutex: DsMutex):
        self.mutex = mutex
        self.held = True

    def unlock(self) -> _Unit:
        if self.held:
            self.held = False
            try:
                self.mutex.lock_obj.release()
            except RuntimeError:
                pass
        return UNIT

    def __del__(self):  # 守卫离开作用域自动解锁（CPython 引用计数）
        self.unlock()


class Task:
    __slots__ = ("interp", "thread", "result", "error", "done", "name")

    def __init__(self, interp: Any, name: str = "task"):
        self.interp = interp
        self.thread: threading.Thread | None = None
        self.result: Any = UNIT
        self.error: BaseException | None = None
        self.done = threading.Event()
        self.name = name

    def start(self, fn: Callable[[], Any], detached: bool = False):
        def runner():
            try:
                self.result = fn()
            except BaseException as exc:  # noqa: BLE001 - panic 需要跨线程传递
                self.error = exc
            finally:
                self.done.set()

        self.thread = threading.Thread(target=runner, name=f"ds-{self.name}", daemon=detached)
        self.thread.start()
        return self

    def wait(self) -> Res:
        self.done.wait()
        if self.error is not None:
            return err(self.error.value if isinstance(self.error, DsPanic) else DsErrorValue(str(self.error)))
        return ok(self.result)

    def __repr__(self) -> str:
        return f"<task {self.name}>"


class ThreadHandle(Task):
    def __repr__(self) -> str:
        return "<thread>"


# ---------------------------------------------------------------------------
# 内存原语（参考驱动的近似实现）
# ---------------------------------------------------------------------------
class Ptr:
    """ptr[T] / raw：addr 模式模拟任意地址；buf 模式模拟 alloc 出的真实块。"""

    __slots__ = ("buf", "offset", "addr", "elem_size", "mutable", "volatile", "freed", "type_name")

    def __init__(self, buf: bytearray | None = None, offset: int = 0, addr: int | None = None,
                 elem_size: int = 1, mutable: bool = True, volatile: bool = False,
                 type_name: str = "u8"):
        self.buf = buf
        self.offset = offset
        self.addr = addr
        self.elem_size = elem_size
        self.mutable = mutable
        self.volatile = volatile
        self.freed = False
        self.type_name = type_name

    def read(self) -> Any:
        if self.buf is None:
            return 0
        if self.offset < 0 or self.offset + self.elem_size > len(self.buf):
            raise DsRuntimeError("指针越界读取")
        chunk = self.buf[self.offset:self.offset + self.elem_size]
        return chunk[0] if self.elem_size == 1 else int.from_bytes(chunk, "little")

    def write(self, value: Any) -> _Unit:
        if self.buf is None:
            return UNIT
        if self.offset < 0 or self.offset + self.elem_size > len(self.buf):
            raise DsRuntimeError("指针越界写入")
        ival = int(value) & ((1 << (8 * self.elem_size)) - 1)
        self.buf[self.offset:self.offset + self.elem_size] = ival.to_bytes(self.elem_size, "little")
        return UNIT

    def shift(self, n: int) -> "Ptr":
        return Ptr(buf=self.buf, offset=self.offset + n * self.elem_size,
                   addr=None if self.addr is None else self.addr + n * self.elem_size,
                   elem_size=self.elem_size, mutable=self.mutable,
                   volatile=self.volatile, type_name=self.type_name)

    def __repr__(self) -> str:
        where = f"addr=0x{self.addr:x}" if self.addr is not None else f"off={self.offset}"
        return f"<ptr {self.type_name} {where}>"


class RefBox:
    """`&expr` 的引用视图（简化版借用）：读/写都转发回原位置。"""

    __slots__ = ("getter", "setter", "mutable")

    def __init__(self, getter: Callable[[], Any], setter: Callable[[Any], None] | None, mutable: bool):
        self.getter = getter
        self.setter = setter
        self.mutable = mutable

    def __repr__(self) -> str:
        return f"<ref {self.getter()!r}>"


class RefCount:
    """rc[T] / arc[T]：引用计数所有权（CPython 引用计数 + 显式计数近似）。"""

    __slots__ = ("value", "count", "atomic", "interp", "lock")

    def __init__(self, value: Any, atomic: bool = False, interp: Any = None):
        self.value = value
        self.count = 1
        self.atomic = atomic
        self.interp = interp
        self.lock = threading.Lock() if atomic else None

    def clone(self) -> "RefCount":
        if self.lock is not None:
            with self.lock:
                self.count += 1
        else:
            self.count += 1
        return self

    def release(self) -> None:
        if self.lock is not None:
            with self.lock:
                self.count -= 1
                zero = self.count <= 0
        else:
            self.count -= 1
            zero = self.count <= 0
        if zero and self.interp is not None:
            self.interp.drop_value(self.value)
            self.value = UNIT

    def __del__(self):
        try:
            if self.count > 0:
                self.release()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"<{'arc' if self.atomic else 'rc'} {self.value!r}>"


class GcBox:
    __slots__ = ("value",)

    def __init__(self, value: Any):
        self.value = value

    def __repr__(self) -> str:
        return f"<gc {self.value!r}>"


class TypeInfo:
    __slots__ = ("name", "size", "align", "fields", "traits", "kind")

    def __init__(self, name: str, size: int, align: int, fields: list[dict],
                 traits: list[str], kind: str = "type"):
        self.name = name
        self.size = size
        self.align = align
        self.fields = fields
        self.traits = traits
        self.kind = kind

    def __repr__(self) -> str:
        return f"TypeInfo({self.name})"


# ---------------------------------------------------------------------------
# 类型工具（供 sizeof / 类型测试使用）
# ---------------------------------------------------------------------------
BUILTIN_SIZES = {
    "i8": 1, "i16": 2, "i32": 4, "i64": 8, "i128": 16,
    "u8": 1, "u16": 2, "u32": 4, "u64": 8, "u128": 16,
    "isize": 8, "usize": 8, "f32": 4, "f64": 8,
    "bool": 1, "unit": 0, "str": 16, "bytes": 16, "raw": 8,
}
BUILTIN_ALIGNS = {
    "i8": 1, "i16": 2, "i32": 4, "i64": 8, "i128": 16,
    "u8": 1, "u16": 2, "u32": 4, "u64": 8, "u128": 16,
    "isize": 8, "usize": 8, "f32": 4, "f64": 8,
    "bool": 1, "unit": 1, "str": 8, "bytes": 8, "raw": 8,
}
BUILTIN_RANGES = {
    "i8": (-2 ** 7, 2 ** 7 - 1), "i16": (-2 ** 15, 2 ** 15 - 1),
    "i32": (-2 ** 31, 2 ** 31 - 1), "i64": (-2 ** 63, 2 ** 63 - 1),
    "i128": (-2 ** 127, 2 ** 127 - 1),
    "u8": (0, 2 ** 8 - 1), "u16": (0, 2 ** 16 - 1), "u32": (0, 2 ** 32 - 1),
    "u64": (0, 2 ** 64 - 1), "u128": (0, 2 ** 128 - 1),
    "isize": (-2 ** 63, 2 ** 63 - 1), "usize": (0, 2 ** 64 - 1),
}
INT_KINDS = set(BUILTIN_RANGES)
FLOAT_KINDS = {"f32", "f64"}

PTR_TYPE_NAMES = {"ptr", "ref", "volatile", "raw", "rc", "arc", "gc", "chan", "mutex",
                  "task", "thread", "opt", "res", "dyn", "fn"}


def type_name_of(t: ast.TypeExpr | None) -> str | None:
    """从 TypeExpr 提取基础名字（用于查找 TypeDef / 内建类型）。"""
    if t is None:
        return None
    if isinstance(t, ast.TypeName):
        return t.name
    if isinstance(t, ast.BoxType):
        return t.kind
    if isinstance(t, (ast.OptType,)):
        return "opt"
    if isinstance(t, ast.ResType):
        return "res"
    if isinstance(t, ast.RawType):
        return "raw"
    if isinstance(t, ast.DynType):
        return "dyn"
    if isinstance(t, ast.FnType):
        return "fn"
    return None


def to_str(v: Any) -> str:
    """println/format 的字符串化规则（近似 Display）。"""
    if v is UNIT:
        return ""
    if v is NEVER:
        return "never"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        text = repr(v)
        return text if text not in ("inf", "-inf", "nan") else text
    if isinstance(v, bytes):
        return "".join(chr(b) if 32 <= b < 127 else f"\\x{b:02x}" for b in v)
    if isinstance(v, (list, tuple)):
        return "[" + " ".join(to_str(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{to_str(k)}: {to_str(vv)}" for k, vv in v.items()) + "}"
    if isinstance(v, Opt):
        return "none" if v.is_none else f"some({to_str(v.value)})"
    if isinstance(v, Res):
        return f"ok({to_str(v.value)})" if v.ok else f"err({to_str(v.value)})"
    if isinstance(v, DsErrorValue):
        return str(v.message)
    if isinstance(v, DsInstance):
        return f"{v.type_def.name}({', '.join(f'{k}: {to_str(x)}' for k, x in v.fields.items())})"
    return str(v)


# ---------------------------------------------------------------------------
# prelude
# ---------------------------------------------------------------------------
def _and(a: list, b: list, interp) -> Any:
    return a[0]


def make_math_module() -> Module:
    env = {
        "sqrt": NativeFunction("sqrt", lambda a, k: math.sqrt(float(a[0]))),
        "round": NativeFunction("round", lambda a, k: float(round(float(a[0])))),
        "floor": NativeFunction("floor", lambda a, k: float(math.floor(float(a[0])))),
        "ceil": NativeFunction("ceil", lambda a, k: float(math.ceil(float(a[0])))),
        "abs": NativeFunction("abs", lambda a, k: abs(a[0])),
        "pow": NativeFunction("pow", lambda a, k: float(a[0]) ** float(a[1])),
        "sin": NativeFunction("sin", lambda a, k: math.sin(float(a[0]))),
        "cos": NativeFunction("cos", lambda a, k: math.cos(float(a[0]))),
        "tan": NativeFunction("tan", lambda a, k: math.tan(float(a[0]))),
        "pi": math.pi,
        "e": math.e,
    }
    mod = Module("math", env)
    return mod


def make_prelude(interp) -> dict[str, Any]:
    """构造 prelude 环境（规范 §1.4 + 少量运行期便利项）。"""

    def _println(args, kwargs):
        text = " ".join(to_str(a) for a in args)
        print(text, file=interp.stdout)
        return UNIT

    def _print(args, kwargs):
        print("".join(to_str(a) for a in args), end="", file=interp.stdout)
        return UNIT

    def _format(args, kwargs):
        if not args:
            return ""
        if isinstance(args[0], str) and "{}" in args[0]:
            out = args[0]
            for a in args[1:]:
                out = out.replace("{}", to_str(a), 1)
            return out
        return "".join(to_str(a) for a in args)

    def _concat(args, kwargs):
        a, b = args[0], args[1]
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        if isinstance(a, (list, bytes)) and isinstance(b, type(a)):
            return a + b
        raise DsRuntimeError("concat 需要两个 str 或同型序列")

    def _range(args, kwargs):
        if len(args) == 1:
            return list(range(int(args[0])))
        return list(range(int(args[0]), int(args[1])))

    def _error(args, kwargs):
        return DsErrorValue(args[0] if args else "", "error")

    def _panic(args, kwargs):
        raise DsPanic(args[0] if args else "panic")

    def _len(args, kwargs):
        if len(args) != 1:
            raise DsRuntimeError("len 需要 1 个参数")
        v = args[0]
        if isinstance(v, (list, dict, str, bytes)):
            return len(v)
        raise DsRuntimeError(f"len 不支持 {type(v).__name__}")

    def _to_str(args, kwargs):
        if len(args) != 1:
            raise DsRuntimeError("str 需要 1 个参数")
        return to_str(args[0])

    def _abs(args, kwargs):
        if len(args) != 1:
            raise DsRuntimeError("abs 需要 1 个参数")
        return abs(args[0])

    def _pow(args, kwargs):
        if len(args) != 2:
            raise DsRuntimeError("pow 需要 2 个参数")
        return float(args[0]) ** float(args[1])

    prelude: dict[str, Any] = {
        "true": True,
        "false": False,
        "none": NONE,
        "unit": UNIT,
        "never": NEVER,
        "some": NativeFunction("some", lambda a, k: some(a[0])),
        "ok": NativeFunction("ok", lambda a, k: ok(a[0])),
        "err": NativeFunction("err", lambda a, k: err(a[0])),
        "error": NativeFunction("error", _error),
        "panic": NativeFunction("panic", _panic),
        "println": NativeFunction("println", _println),
        "print": NativeFunction("print", _print),
        "format": NativeFunction("format", _format),
        "concat": NativeFunction("concat", _concat),
        "range": NativeFunction("range", _range),
        "len": NativeFunction("len", _len),
        "str": NativeFunction("str", _to_str),
        "abs": NativeFunction("abs", _abs),
        "pow": NativeFunction("pow", _pow),
        "math": make_math_module(),
    }
    prelude.update(native_constructors(interp))
    # 短别名（Flow/精简写作用；用户可用同名绑定遮蔽）
    prelude.setdefault("p", prelude["println"])
    prelude.setdefault("s", prelude["str"])
    prelude.setdefault("l", prelude["len"])
    prelude.setdefault("r", prelude["range"])
    return prelude


def native_constructors(interp) -> dict[str, Any]:
    """alloc/free/rc/arc/gc/chan/mutex/thread 等内建构造器。"""

    def _alloc(args, kwargs):
        size = int(args[0])
        if size < 0:
            raise DsRuntimeError("alloc 大小不能为负")
        return Ptr(buf=bytearray(size), elem_size=1, type_name="u8")

    def _free(args, kwargs):
        p = args[0]
        if isinstance(p, Ptr):
            p.freed = True
        return UNIT

    def _rc(args, kwargs):
        return RefCount(args[0], atomic=False, interp=interp)

    def _arc(args, kwargs):
        return RefCount(args[0], atomic=True, interp=interp)

    def _gc(args, kwargs):
        return GcBox(args[0])

    def _chan(args, kwargs):
        cap = int(args[0]) if args else 0
        return Chan(cap)

    def _mutex(args, kwargs):
        return DsMutex(args[0] if args else UNIT)

    def _thread(args, kwargs):
        target = args[0]
        handle = ThreadHandle(interp, "thread")

        def runner():
            return interp.call_value(target, [], [])

        return handle.start(runner, detached=False)

    return {
        "alloc": NativeFunction("alloc", _alloc),
        "free": NativeFunction("free", _free),
        "rc": NativeFunction("rc", _rc),
        "arc": NativeFunction("arc", _arc),
        "gc": NativeFunction("gc", _gc),
        "chan": NativeFunction("chan", _chan),
        "mutex": NativeFunction("mutex", _mutex),
        "thread": NativeFunction("thread", _thread),
        "asm": NativeFunction("asm", lambda a, k: UNIT),
    }
