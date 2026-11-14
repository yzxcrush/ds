# Step 9（P5）— 工具链与 AI 资产

> CLI：`ds-plus/tools/dsplus_cli.py`；语言卡：`ds-plus/ai/PLUS_CARD.md`；SFT：`ds-plus/datasets/ds_plus_sft.jsonl`。

```bash
dsplus parse file.ds --json         # plus 特征
dsplus check file.ds --profile bare # 语义检查
dsplus run file.ds --profile bare   # compat 模拟执行
dsplus ir file.ds --hash            # IR 哈希
dsplus abi --target x86_64-linux-gnu
dsplus build file.ds --bare --raw -o kernel.bin
dsplus --version
```

- SFT 10 条覆盖令牌/区域/约束/限制；
- 语言卡面向 AI：新增令牌、语法、规则、工具、限制；
- 后续：plus 评测集、自动评分器、llms 分支入口、Android 内核。
