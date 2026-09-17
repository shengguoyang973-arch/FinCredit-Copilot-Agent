# SIEM 与企业工单出站集成

v1.3 使用持久化出站箱连接 SIEM 与企业工单，而不是在告警或审批事务中直接发 HTTP。漂移告警、Prompt 处置作业单和灰度评测结论先与本地状态一起写入数据库，再由受控调度器投递；失败会保留尝试历史并按退避策略重试或进入 dead letter。

## 配置与安全边界

```text
FINCREDIT_INTEGRATION_DELIVERY_MODE=webhook
FINCREDIT_SIEM_WEBHOOK_URL=https://siem.example.com/events
FINCREDIT_WORK_ITEM_WEBHOOK_URL=https://work.example.com/fincredit
FINCREDIT_INTEGRATION_HMAC_SECRET=<secret-from-manager>
FINCREDIT_INTEGRATION_TIMEOUT_SECONDS=5
FINCREDIT_INTEGRATION_MAX_ATTEMPTS=5
```

生产仅接受 HTTPS，且 HMAC 密钥至少 32 字符。事件载荷只包含事件 ID、治理资源 ID、状态、严重度、规则/数据集指纹及时间；代码拒绝客户、材料、报告、Prompt 正文和人工评论字段。默认 `disabled` 只保留待投递事件，不会访问外部地址。

## 运行与处置

用受控服务账号/调度器运行：

```powershell
python scripts\dispatch_integration_outbox.py --limit 50
```

合规管理员可查询 `GET /v1/operations/integration-outbox`、`GET /v1/operations/integration-outbox/{event_id}/attempts`，或在故障演练时调用 `POST /v1/operations/integration-outbox/dispatch`。投递成功、失败、重试、阻塞和 dead letter 都保存最小化证据。该接口不能创建授信决定、修改 Prompt 或执行工单动作。
