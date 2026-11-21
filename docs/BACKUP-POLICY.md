# 备份策略

从 2026-11-21 起，每完成一个项目/里程碑，生成一个补充包，追加到 `交接` 的备份序列。

## 位置

手机：

```text
/sdcard/Download/DsBackups/
```

命名：

```text
DsBackup-<项目>-<里程碑>-<YYYYMMDD-HHMMSS>.zip
```

## 包含

- 当前项目源码快照（含 git 历史，排除 `.tmp`/缓存）
- 关键产物（镜像、kernel、机器码、APK）
- `HANDOFF.md` / 状态 / 下一步
- 对话 `chat.md` + `chat.jsonl`（已脱敏）
- `MANIFEST.json` + `SHA256SUMS`

不包含：

- `.dsh` 凭证、SSH 私钥、GitHub token
- 未脱敏原始日志
- `.tmp`/构建缓存

## 命令

```bash
python3 tools/make_backup.py \
  --name DsBackup-DsOS-M1-20261121-1900 \
  --milestone "DsOS Phase1 QEMU alive" \
  --out /sdcard/Download/DsBackups
```

## 规则

- 每个项目完成必须先跑备份，再宣布完成。
- 备份生成后做 token 扫描和 SHA256 校验。
- 失败/未验证的里程碑也要备份，但状态标记为 `unverified`。
