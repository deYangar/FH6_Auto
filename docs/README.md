# Release Notes 规范

每次推送到 main 分支时，GitHub Actions 会自动编译 Steam + Xbox 两个版本。

## 发布控制

在 `docs/` 目录下创建 `v{版本号}.md` 文件（版本号与 `config.py` 中 `CURRENT_VERSION` 一致）。

### Frontmatter 字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `version` | string | — | 版本号，如 `"1.2.7.0"` |
| `publish` | bool | `true` | `false` = 只编译不发布 Release |
| `prerelease` | bool | `false` | `true` = 发布为 Pre-release |

### 行为矩阵

| publish | prerelease | 结果 |
|---------|------------|------|
| `false` | 任意 | 编译，上传 artifact，**不创建 Release** |
| `true` | `false` | 编译 + 创建正式 Release |
| `true` | `true` | 编译 + 创建 Pre-release |

### 文件不存在时

如果 `docs/v{版本号}.md` 不存在，只编译并上传 artifact，不创建 Release。

## 文件示例

```markdown
---
version: "1.2.7.0"
prerelease: false
publish: true
---

# v1.2.7.0 更新内容

- 新增 XXX 功能
- 修复 YYY 问题
```

## 流程

1. 改完代码，更新 `config.py` 中的 `CURRENT_VERSION`
2. 在 `docs/` 创建 `v{新版本号}.md`，写好 frontmatter 和更新日志
3. `publish: false` 时只编译不发布，适合测试 CI
4. 确认没问题后改为 `publish: true`，推送到 main
5. CI 自动编译并发布 Release，两个 exe 作为资产上传
