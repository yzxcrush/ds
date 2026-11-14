# Ds C 参考驱动（核心子集）

纯 C（libc + libm）实现的 Ds 编译器前端 + 树遍历解释器，无第三方依赖。
与 Python 参考驱动**对拍测试**：同一批 `.ds` / `.dsf` 两边输出必须一致。

## 构建 / 运行

```bash
make -C c                 # 产物 c/build/ds
./c/build/ds 文件.ds       # 经典 / 精简写法
./c/build/ds 文件.dsf      # Flow 写法（或首行 #!flow / 以 \ 开头）
./c/build/ds -c 'p "hi"'  # -c 代码
./c/build/ds --check 文件.ds
./c/build/ds --emit tokens 文件.ds
```

## 支持

- 经典写法与 0.1c 精简写法：隐式入口、表达式函数体（`=`/`:`）、`:` 单语句体、复合赋值、`a..b`、f-string、`p/s/l/r` 短别名
- Flow 写法：`\` 定义、空白参数、并置调用、`.` 结束块、`?`/`^`/`;`
- 核心子集：函数/递归/闭包、数组/映射、字符串/字节串、控制流、`|>`、`opt/res`?（否）、`match`?（否）
- 明确**不支持**（会报错）：`class/trait/impl`、`match`、`opt/res`、`try/catch`、并发、内存原语、宏/comptime

## 包（dspm）与 `use`

C 驱动直接读取 dspm 安装布局（默认 `~/.ds`，可用 `DSPM_HOME` 覆盖）：

```ds
use hello
p(hello.hello("Ds"))
```

- 扫描 `$DSPM_HOME/pkg/*/*/ds.toml`，按 `exports` 匹配模块，按 `targets` 过滤（base 接受 ds/cut/base/app/bare）；
- 模块函数注册为 `模块名.函数名`（`use x as y` 可改命名空间）；
- 递归加载模块内 `use`，去重防环；不联网、不调用 dspm 可执行文件；
- 缺失诊断会提示 `dspm install <user>/<repo>`；
- 仅导出函数；模块顶层 let 会求值但不暴露；不做版本选择（用已安装目录）。

测试：`sh c/test_dspm_use.sh`（本地镜像装包 + use + 缺失诊断）。

## 对拍

```bash
sh c/run_tests.sh         # 与 Python 参考驱动逐用例比较 stdout
```

## 已知限制

- 仅核心子集；完整能力请用 Python 参考驱动（`dsv01/`）。
- Flow 的嵌套应用需显式括号（`p fib(10)`）。
