# PostgreSQL 数据中台切换

v1.3 将信贷数据中台的运行后端拆分为显式的 `sqlite`（开发/测试）与 `postgres`（生产）适配器。业务审批工作流在本阶段仍使用其独立仓储；数据中台的契约、批次、质量回执、规范记录与血缘链可单独切换，避免一次性跨域迁移破坏授信审批边界。

## 生产配置

```text
FINCREDIT_DATA_PLATFORM_BACKEND=postgres
FINCREDIT_DATA_PLATFORM_POSTGRES_DSN=postgresql://<user>:<password>@<host>:5432/<database>?sslmode=require
FINCREDIT_DATA_PLATFORM_POSTGRES_SCHEMA=fincredit_data
```

生产环境未启用 `postgres` 或缺少 DSN 时，`/ready` 返回失败；不会静默读取本地 SQLite 规范数据。PostgreSQL schema 由受控迁移表管理，JSON 规范记录使用 `JSONB`，当前视图与血缘链保留索引和哈希校验。

## 切换步骤

1. 在只读窗口运行 `python scripts\migrate_data_platform_postgres.py`，只获取各表行数和哈希构成的 source fingerprint，不输出原始规范数据。
2. 在隔离的空目标 schema 执行 `--execute --confirm-source-fingerprint <fingerprint>`；脚本拒绝覆盖非空目标。
3. 脚本在同一 PostgreSQL 事务内应用 schema、复制契约/批次/质量/规范记录/血缘，并规范化 JSON、布尔值、时间后核对逐表行数与内容哈希，再写入 cutover receipt；校验失败即回滚。
4. 以服务账号部署 `FINCREDIT_DATA_PLATFORM_BACKEND=postgres`，验证 `/ready`、数据契约、组织隔离读取和血缘完整性。
5. 保留 SQLite 为只读回退证据，完成签字和备份确认后才按企业保留策略处置。

切换工具不包含客户材料、审批报告或模型 Prompt，也不能复制到已有未知数据的目标。真实源系统接入仍应通过 CDC/ETL、对象存储、DLP 和受控服务身份完成。
