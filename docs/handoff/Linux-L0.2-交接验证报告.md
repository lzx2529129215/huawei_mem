# Linux L0.2 交接验证报告

状态：`IN PROGRESS`。本文件只在 clean clone 和 remote clone 验证完成后更新为最终状态；不得用历史报告替代当前执行证据。

## 来源

- Type：kernel.org fixed tarball
- URL：`https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.17.tar.xz`
- Version/tag：`6.17` / `v6.17`
- Commit：`e5f0a698b34ed76002dc5cff3804a61c80233a7a`
- Archive SHA256：`9b607166a1c999d8326098121222feb080a20a3253975fcdfa2de96ba7f757a7`
- Pristine manifest SHA256：`5291fc5e8fe33cbe00b491947bc79316baf3eb812d77b4e9f863ee884308dd09`
- 逐项证明：90,506 canonical paths；missing 0；content/mode differences 0。

## 补丁

- 0002：`ecc0e4f473ea4a657578568b2a57658ed37590c1a89e366ede7c2c81814d2711`
- 0003：`35bacaea2de3aae1552f24564d853b0ffb352f7d9929091da3d6026d2cd70b89`

## 当前验证结果

| 项目 | 状态 | 证据 |
|---|---|---|
| 现有用户态测试 | HISTORICAL_EVIDENCE / PASS | `docs/reports/linux-l02-validation.md` |
| runtime smoke | NOT RUN / ENVIRONMENT BLOCKED | 既有报告；需按当前设备重跑 |
| TSan | NOT RUN / ENVIRONMENT BLOCKED | `unexpected memory mapping` |
| clean-clone fetch | PENDING | 待执行 |
| clean-clone patch chain | PENDING | 待执行 |
| clean-clone bzImage/modules | PENDING | 待执行 |
| remote-clone verification | PENDING | 待 push 后执行 |

## 结果字段

最终执行后补充：local start/final HEAD、remote HEAD、clone 路径、构建时长、kernelrelease、产物路径和 SHA256。只有所有成功标准满足时才写 `LINUX L0.2 CROSS-DEVICE HANDOFF COMPLETE`；否则写 `HUMAN DECISION REQUIRED` 并列出差异。
