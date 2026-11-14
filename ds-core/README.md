# ds-core（Ds / Ds+ 共享核心）

> 状态：Step 2 建立最小共享层；完整拆分见 Step 3。

## 职责

`ds-core` 是 Ds（base）与 Ds+ 共同依赖的唯一事实源，**不含分支特有实现**：

| 类别 | 内容 | 本步状态 |
|---|---|---|
| 关键字表 | base 77 冻结 + Ds+ `@` 令牌注册表 | ✅ `plus.keywords.json`（base 仍以 `spec/keywords.json` 为准） |
| ABI | `repr(Ds)` 默认、`@repr(C)`/`@abi("C")`、目标三元组 | 占位（Step 3） |
| IR 定义 | 节点/指令定义、inline asm、intrinsics、memory regions | 占位（Step 3） |
| 错误码 | `E_DS_PLUS_*`、通用诊断码 | ✅ 注册表中携带 |

## 文件

- `plus.keywords.json`：Ds+ 新增 12 个硬件关键字 + 4 个内存区域标注，含语义、PYX 对应、降级路径、base stub 文案、profile/目标/unsafe 约束。
- `README.md`：本文件。

## 约束

1. base 77 关键字**不在本目录重定义**，仍以 `spec/keywords.json` 为单一事实源；`plus.keywords.json` 只描述增量。
2. 任何 Ds+ 关键字必须 `@` 前缀，且不得与 base 的 73 个标识符关键字冲突。
3. 关键字表变更必须同步：`ds-plus/docs/`、`ds-core/plus.keywords.json`、base stub 守卫、AI 学习包（llms / 语言卡 / 数据集）。
