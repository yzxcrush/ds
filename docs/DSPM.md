# dspm — Ds 包管理器（v0.1 原型）

> **包 = GitHub 仓库，版本 = git tag，源码即分发，无中心服务器。**
> 客户端：`tools/dspm.py`（单文件，Python 3.11+）；命令包装：`./dspm`。

## 快速开始

```bash
./dspm install yzxcrush/ds-json@v0.3.0        # 安装
./dspm install yzxcrush/ds-utf8@latest        # 最新 tag
./dspm list                                   # 已安装
./dspm update                                 # 检查/更新全部
./dspm remove yzxcrush/ds-json                # 卸载
./dspm cache-clean                            # 清缓存
./dspm resolve json --target ds               # 编译器用：解析模块路径
```

中文别名同样可用：`安装 / 移除 / 列表 / 更新 / 缓存清理`。

## 目录布局

```
~/.ds/
├── pkg/<user>/<repo>@<tag>/       # 安装后的源码（只解压，不执行）
├── cache/<user>/<repo>@<tag>.tar.gz
└── dspm.lock                      # JSON：tag + commit + tarball hash + 依赖
```

`DSPM_HOME` 可覆盖 `~/.ds`（测试/Android 私有目录用）。`DSPM_GITHUB_BASE`、`DSPM_GITHUB_API` 可覆盖端点（本地镜像/镜像站）。

## 命令

| 命令 | 行为 |
|---|---|
| `install <user>/<repo>[@tag]` | 下载 `https://github.com/<user>/<repo>/archive/refs/tags/<tag>.tar.gz`，解压、校验 ds.toml、递归装依赖、写 lock；已安装同 tag 直接用本地 |
| `install ...@latest` | 通过 GitHub API 查最新 tag（本地镜像按 tag 排序） |
| `remove <user>/<repo>` | 删除安装目录并移除 lock 条目 |
| `list` | 打印 包 / tag / commit / unsafe / path |
| `update [repo]` | 对已装包检查最新 tag，更新锁与目录（保留旧缓存） |
| `cache-clean` | 删除 `~/.ds/cache` |
| `resolve <module> [--target]` | 按 lock + exports 找模块源码路径，供编译器使用 |
| `--offline` | install/update 只用缓存，不联网 |
| `--yes` | 非交互确认（unsafe 包必需） |
| `--target ds\|cut\|base\|app\|bare\|plus` | 目标兼容过滤（默认 ds） |

### 目标兼容（三层架构）

`targets` 声明包支持的环境：

- 包 `targets = ["app"]` → Ds base 的 app 目标；
- `targets = ["bare"]` → Ds base 的 bare 目标；
- `targets = ["plus"]` → Ds+；
- `--target ds`（`cut`/`base` 是别名）接受 `targets` 含 `ds`/`app`/`bare` 的包；
- `--target plus` 要求 `targets` 含 `plus`。

> 需求中的“Cut 只装 目标 含 cut 的包”按 **Ds base** 处理：`cut` 映射到 `ds`，并接受 app/bare 包。

## ds.toml 规范

```toml
name = "ds-json"          # 必填：包名（唯一标识，建议 ds-<功能>）
version = "0.3.0"         # 必填：语义化版本
description = "JSON 解析/序列化"
authors = ["@somebody"]   # 可选：作者/维护者
license = "MIT"           # 可选
exports = ["json"]        # 模块导出名：use JSON 时查找 src/json.ds
deps = ["yzxcrush/ds-utf8@v0.2.1"]   # 依赖：<user>/<repo>[@tag]，默认 latest
targets = ["app", "bare"] # 支持的目标：app/bare/plus
```

补充约定：

- `exports` 省略时默认 `[name]`；`targets` 省略时默认 `["app"]`。
- 源码放在 `src/<export>.ds`（也接受根目录 `<export>.ds` / `.dsf`）。
- `ds.toml` **不包含任何 build/install 脚本**；dspm 从不执行包内命令。
- 兼容别名：`deps`/`DEPS`/`依赖`，便于早期手写文件。
- `unsafe` 不在 ds.toml 声明，由 dspm 扫描 `@asm/@raw` 等令牌自动判定。

## dspm.lock

JSON 格式（示例）：

```json
{
  "version": 1,
  "packages": {
    "yzxcrush/ds-json": {
      "tag": "v0.3.0",
      "commit": "9f2c...",
      "tarball_sha256": "…",
      "path": "pkg/yzxcrush/ds-json@v0.3.0",
      "targets": ["app", "bare"],
      "unsafe": false,
      "deps": ["yzxcrush/ds-utf8@v0.2.1"],
      "name": "ds-json"
    }
  }
}
```

- `commit` 来自 GitHub API `commits/<tag>`；离线/本地镜像时为 `""`，但 `tarball_sha256` 始终记录。
- 依赖解析：深度优先、按 `<user>/<repo>` 去重（先到先得）；不做 SAT 求解。

## 安全

1. **不执行**包内任何 build/install 脚本（dspm 没有 postinstall 机制）。
2. 解压时拒绝：绝对路径、`..` 越界、符号链接/硬链接。
3. 安装前显示：包名/版本、作者、目标、依赖数、文件数。
4. 扫描 `@asm/@raw` 等令牌 → `unsafe=true`；**需要 `--yes`**（或交互确认）才安装。
5. 源码即分发：建议安装前 review 仓库；dspm 不做运行时沙箱。

## 编译器 `use` 解析（伪代码）

```text
function resolve_use(module_name, target):
    lock = read("~/.ds/dspm.lock")
    for pkg in lock.packages:
        meta = read_toml(pkg.path / "ds.toml")
        if module_name not in meta.exports: continue
        if not target_ok(meta, target): continue
        for cand in [pkg.path/src/{module}.ds,
                     pkg.path/{module}.ds,
                     pkg.path/src/{module}.dsf]:
            if exists(cand): return cand
    error("找不到模块 {module_name}；请运行 `dspm install <user>/<repo>`")
```

编译器侧建议：

1. 解析 `use JSON` → 模块名 `JSON`；
2. 调 `dspm resolve JSON --target ds`（或直接读 lock，避免子进程）；
3. 把返回文件加入本次编译单元 / 模块依赖图；
4. 未找到时输出带安装提示的诊断（`DSPM2001`）；
5. `--target` 与当前分支一致（Ds base = `ds`，Ds+ = `plus`）。

## Android App 集成方案（简述）

App 是离线 WebView（`assets/ds.js`）且不内置 Python，推荐**原生 Kotlin 重写 dspm 核心**：

1. **存储**：`context.filesDir/ds/`（私有）：`pkg/`、`cache/`、`dspm.lock`；UI 增加「包管理」抽屉/标签页。
2. **网络**：`HttpURLConnection`/OkHttp 下载 GitHub tarball；`java.util.zip.GZIPInputStream + TarArchiveInputStream`（commons-compress）解压；复用同一套路径校验（拒绝 `..`/链接）。
3. **锁/清单**：JSON 用 org.json；ds.toml 用轻量 TOML 解析器（如 tomlj）或仅解析必需字段。
4. **UI**：已装列表（tag/commit/unsafe）、安装输入框 `<user>/<repo>[@tag]`、卸载、缓存清理、离线开关；安装前显示元信息，unsafe 二次确认。
5. **目标过滤**：App 内核是 Ds base → `--target ds`；未来 Ds+ 内核传 `plus`。
6. **安全**：不执行包脚本；只解压源码；限制单包大小/文件数；网络需 `INTERNET` 权限。
7. **可选**：支持 GitHub token（仅内存保存）提升 API 限额；不内置镜像。
8. 测试：JVM 单测覆盖 ds.toml/lock/路径校验；UI 测试用 MockWebServer 模拟 GitHub。

## 示例包：ds-hello

见 `examples/packages/ds-hello/`（可直接作为 GitHub 仓库模板）。

## 限制（v0.1）

- 无版本范围/冲突求解；同包多版本只保留先装入的 tag。
- 无签名/哈希校验（除 tarball sha256 记录）。
- 不做依赖图循环检测（深度优先 + 去重足够）。
- Python 原型；C/Java 移植后续。
