# 评测集

- `evals.json`：行为评测。每条含用户请求、期望行为和可逐项判定的 expectations，覆盖地区引导、经济区展开、全国边界、部分周期、来源过滤、专题与版式选择、长图导出、内部数据与投资建议拒绝等。
- `trigger-evals.json`：触发评测，`should_trigger` 标明该请求是否应启用本技能，用于调整 `SKILL.md` 的 description。

发版前逐条运行并记录通过率，通过率低于上一版本时不发版。每个确认的坏案例若属流程判断问题，补一条评测。详见 [docs/operations.md](../docs/operations.md#4-评测集)。
