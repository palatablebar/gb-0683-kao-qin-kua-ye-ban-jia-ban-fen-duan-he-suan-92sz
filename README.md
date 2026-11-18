# 考勤跨夜班与加班分段核算

面向制造企业薪酬核算员，处理采信、判定、核算、复核与归档。

## 启动

```bash
docker compose up --build -d
```

访问 http://localhost:18252 。初次启动自动运行脏样例，可切换 clean.csv 与 legacy.csv。顶部“运行批次”会重新计算，同源输入复用批次。

## 业务模块

- 打卡采信：`/m1_ingest`、`/api/m1_ingest`
- 班次日历：`/m2_mapping`、`/api/m2_mapping`
- 跨夜配对：`/m3_versions`、`/api/m3_versions`
- 缺卡复核：`/m4_segments`、`/api/m4_segments`
- 工时切段：`/m5_calculate`、`/api/m5_calculate`
- 薪资对账：`/m6_reconcile`、`/api/m6_reconcile`
- 周期归档：`/m7_archive`、`/api/m7_archive`

## 核心规则

跨夜按班次归属日配对，休息区间先扣除，再按法定日期和工时阈值切分倍率。完整数值、边界和异常定义见 `docs/DATA-DICTIONARY.md`。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

原始样例在 `sample_data/`（`clock.csv` 为打卡机快17分钟的校时样例）。测试在 `tests/`。封存文件是单份CSV，含运行清单、校时口径、维修单、逐卡校时证据、计算证据、隔离原因与对账。复核需提交当前版本，陈旧复核返回409。

维修单校时：`POST /api/runs/<run_id>/corrections`，提交 `version`、`clock_tickets`、可选 `correction_policy`。默认按维修单修正全部受影响班次（班次级原子修正，未申诉员工同样修正）；`appeals` 口径仅修正申诉班次。切换成功版本+1并重新封存；同一维修单重跑返回 `NOOP`（409），不重复回拨；校验或事务失败保留旧版。页面顶部“重算工时”只校验重算结果与封存证据一致，不一致返回 409 且不改写。

## 数据与限制

SQLite保存在records命名卷，普通重启与构建不会清除。确认可丢弃本项目数据后，运行 `docker compose down -v` 再启动可重置。单文件上限2MB；不接入外部业务系统；历史规则由本项目样例定义，不代表实际行业标准。
