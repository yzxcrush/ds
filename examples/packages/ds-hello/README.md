# ds-hello

dspm 示例包。结构：

```
ds-hello/
├── ds.toml
└── src/
    └── hello.ds
```

安装（本地测试可把仓库推到 GitHub 后）：

```bash
./dspm install <your-user>/ds-hello@v0.1.0
./dspm resolve hello
```

`ds.toml` 声明 `exports = ["hello"]`，因此 `use HELLO` 会解析到 `src/hello.ds`。
