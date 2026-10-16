---
name: regional-enterprise-briefing
slug: regional-enterprise-briefing
version: "2.0.0"
displayName: 区域政企简报
summary: 为全国任意省市县或经济区编制可追溯的政企晨报、周报、月报与专题追踪；30余种阅读视角，4套配色×3种版式，支持手机阅读与PNG长图。
homepage: https://github.com/zleo-ai/regional-enterprise-briefing
description: 为中国任意省、市、县区或经济区（长三角、粤港澳大湾区、成渝等）编制可追溯的公开政企简报：晨报、周报、月报和专题追踪。当用户要整理某地政策文件、重大项目、招商签约、环评与招采公示、企业公告或金融同业公开动态，生成每日/每周/每月区域资讯，追踪重点企业或项目进展，做区域或行业专题，或把已核实简报导出为PNG长图时使用。支持招商、园区、政策研究、企业战略、投研咨询、媒体、银行保险等阅读视角，标准版、速读版、要报版三种版式与四套配色；逐条保留原文链接、发布日期和核验状态，缺源时降级为观察稿。不用于内部客户数据、个人背景调查、授信审批或投资建议。
agent_created: true
metadata: {"version":"2.0.0","runtime":"Python 3.10+ optional; PNG export additionally requires Playwright and a local Chromium-family browser","os":["darwin","linux","win32"],"network":"Host public web search and original-page reading required for live collection"}
---

# 区域政企简报

把公开的政策文件、产业项目、企业公告和金融同业动态，编成可追溯的晨报、周报、月报或专题简报。每条事实都带原始链接、发布日期和核验状态；事实、分析和待核事项分开写。交付自包含HTML和证据JSON，按需导出PNG长图。只生成本地文件，不代替授信审批、投资决策或对外发布。

## 快速路径

| 用户说 | 你做 |
|---|---|
| “出一份苏州昨天的政企晨报” | 地区取自请求，其余默认，直接编制 |
| “帮我做个晨报”（没说地区，也没有已保存配置） | 只问一句地区（见第1步引导语），不擅自选地区 |
| “长三角新能源汽车周报” | 经济区按[区域预设](references/region-presets.md)展开，主题过滤 |
| “追踪某公司/某项目最近三个月进展” | 专题简报 `kind=special`，自定周期；没说地区时不追问，按“全国+该企业”（`country`、`scope_mode=all`） |
| “给领导看的”“打印版” | 要报版 `memo`；手机快读用速读版 `compact` |
| “以后默认看九江”“保存设置” | 写入用户工作目录的 `briefing-config.json`，先备份旧版 |
| “导出长图/分享海报” | 第7步 `export_png.py` |

## 1. 范围、视角与模板

先读[配置规范](references/configuration.md)。只在用户明确的工作目录读取 `briefing-config.json`，不搜索主目录、通讯录或内部客户档案。

**地区没有默认值。** 依次取：当次请求 → 用户指定的配置文件 → 工作目录配置。企业或项目追踪可不指定地区，按“全国+该企业”配置。其他请求三者都没有时只问这一项：

```text
请告诉我关注哪个地区：省、市、县区都可以（如“江西省”“苏州市”“昆山市”），
也可以是经济区（如“长三角”“粤港澳大湾区”）或“全国+某行业”。
可选补充：重点企业全称、关注主题、只看政府/只看企业、阅读视角、版式。
```

其余项可留空：企业不限、主题不限、全部公开来源、通用阅读、标准版。晨报默认昨日，周报默认上一完整ISO周，月报默认上一完整自然月，专题按用户给定起止日。

- **经济区**：按[区域预设](references/region-presets.md)展开为省市列表，在 `region_label` 记名称，范围说明写清成员。
- **全国**：只用于行业或企业专题，必须 `scope_mode=all` 并配主题或企业，不做“全国全部新闻”。
- **阅读视角**：按[阅读视角目录](references/periodic-analysis.md)映射（政府园区、企业、研究咨询、媒体、金融机构五类共30余种）。视角只调整编辑排序、展开深度和跟踪问题，不改变事实、不扩大地域、不显示部门抬头。目录外的角色映射到最接近的已有视角；要长期新增枚举，须同步文档、配置、报告校验和测试。
- **模板**：版式与配色按优先级取：用户明确要求 > 配置 `presentation` > 所选阅读视角的推荐版式与[模板指引](references/templates.md)的场景推荐 > 标准版+暖纸深红。确定后写入 `04-final.json` 的 `presentation`（配置里保存的偏好也要复制过去），使HTML与PNG一致。

只在地区、企业或主题确有歧义时追问。明确的追加、替换、移除指令不重复确认；多份配置并存时请用户指定，不按修改时间偷偷选。只有用户要求“保存/以后默认”才写配置，并保留旧版。真实配置、企业关注名单和运行材料不进入公开技能包。

## 2. 校验配置与确定周期

以下命令中 `$SKILL` 是技能根目录（含本文件的目录），`$RUN` 是用户工作目录下本次的运行目录（如 `简报/2026-10-15-晨报/`）。所有输出只写入 `$RUN`，不写入技能目录。Windows可用 `py -3`；无Python时按契约人工核对，并注明未运行脚本。

```bash
python3 "$SKILL/scripts/briefing_tool.py" validate-config "$RUN/config-effective.json"
python3 "$SKILL/scripts/briefing_tool.py" window --kind daily   --as-of 2026-10-15T07:00:00+08:00                      # 昨日
python3 "$SKILL/scripts/briefing_tool.py" window --kind weekly  --as-of 2026-10-15T07:00:00+08:00                      # 上一完整ISO周
python3 "$SKILL/scripts/briefing_tool.py" window --kind monthly --as-of 2026-10-15T07:00:00+08:00                      # 上一完整自然月
python3 "$SKILL/scripts/briefing_tool.py" window --kind weekly  --as-of 2026-10-15T07:00:00+08:00 --period 2026-W42    # 指定周或本周至今
python3 "$SKILL/scripts/briefing_tool.py" window --kind special --as-of 2026-10-15T07:00:00+08:00 --period 2026-07-01/2026-09-30
python3 "$SKILL/scripts/briefing_tool.py" options   # 列出报告类型、配色、版式、图表和阅读视角
```

`--period` 格式：晨报 `YYYY-MM-DD`，周报 `YYYY-Www`，月报 `YYYY-MM`，专题 `起始日/结束日`（含首尾）。指定当前周期即得到“至今”的部分周期。`window` 输出的三个字段可直接写入 `04-final.json` 的 `period`。

按[运行与证据契约](references/workflow.md)固定北京时间、发布窗口、截止时点和统计期。“本周/本月至今”生成部分周期观察稿并在首屏标明；不用事件日代替发布日。周月报优先聚合本地已有的合格晨报证据；用户直接点名要某一历史周期的报告而本地没有存档时，这个请求即视为公开补采授权：按该周期检索，`coverage.method=backfill_public`，首屏注明为事后检索。已有部分存档时先聚合，只对缺口日期补采并注明；用户说“只用已有记录”时不补采，缺档写入gaps并出观察稿。

离线工具只检查结构、时间和引用关系，不判断主体身份、网页真实性、来源独立性、主题语义和数字口径；校验通过不等于事实成立。

## 3. 采集与证据筛选

按[信源与安全规范](references/sources-safety.md)使用宿主已有的公开搜索和原文读取能力。去哪里找：按[信源地图](references/source-map.md)为目标地区建立政府、项目审批、公共资源交易、交易所披露等渠道清单，地区不同只换机构名称和域名，方法相同。连接器全部可选（见[可选连接器指引](references/optional-connectors.md)），不可用时继续走公开网页，不以安装或付费阻塞出报。脚本不采集新闻。

1. 核实地区、企业全称、别名和子公司范围，保留公开身份依据。
2. 建立“地区×政策通知/产业项目/企业公告/公开同业”覆盖矩阵，叠加配置的企业和主题；不用一个宽泛查询冒充全部渠道已查。
3. 保存原始URL、原始披露主体、发布日期、事件日、取得时间、摘录、来源根和核验状态。不把搜索摘要当原文；正文缺日期时追同机构栏目列表或正式公告索引。
4. 先按R/E/T和 `scope_mode` 筛选，再叠加 `source_types`，以及启用后的 `require_topic_match`（见配置真值表）；每个候选记录命中和排除理由。
5. 按原始披露主体标 `publisher_type`，不按转载网站、建设单位或 `enterprise` 是否为空判断。同根转载合并为一个事项；不同实质进展保留关系。
6. 通过证据门后做编辑排序。逐条填一个主 `theme`（优先用[写作规范](references/writing-style.md)的主题词表）和准确 `stage`。`max_items` 只限制摘要卡片，不限制采集，被引用的证据须完整保留。
7. 停止前核对覆盖矩阵和高相关候选的最终处置。渠道失败或重要候选未追源时出观察稿并说明局限；条目少时诊断覆盖和待核原因，不凑数、不扩窗。

`primary_verified` 要求实际读到权威一手原文；单篇媒体稿不因“原创”或官方站转载而升级。未核实事项不进入正式稿或观察稿的事实卡。拟受理、拟批准、审批决定公开、采购启动、废标、备案、投产分别表述；不同金额口径不得相加，不从公开新闻推断贷款需求、融资需求或个人资产。

## 4. 编制内容

先读[写作规范](references/writing-style.md)：标题、正文、研究关注、速览、数字口径和禁用措辞都有样例。

| 类型 | 写法 |
|---|---|
| 晨报 `daily` | 昨日发布的新事实；旧事件的新公告以公告发布日入窗并保留旧事件日；方法说明压缩，便于快读 |
| 周报 `weekly` | 按[周期分析](references/periodic-analysis.md)去重、归并主题，区分主题持续、跨日进展和多源印证，每个信号列具体ID和日期 |
| 月报 `monthly` | 选2–3个证据充分的专题，按事实、机制、可比口径、反证、条件化判断和后续问题展开；材料不足可少于此数或出观察稿 |
| 专题 `special` | 企业追踪、项目追踪、政策解读、区域对比或行业扫描，按[专题模板](references/periodic-analysis.md#专题简报模板)组织；周期不超过366天，结束日未到时截至发稿并出观察稿 |

**一句话速览**（`summary`）：读完全部已核实事项后提炼最值得关注的实际变化、主体和状态，通常60–140字，写入 `summary.text` 和 `evidence_ids`。不写“本期N条、政府N条”，不复制标题目录，不截取专题首句。渲染器不生成摘要；旧档缺字段时页面明示“尚未编制”。

**关键数字**（`key_figures`，可选，最多6个）：只放单一口径、可追溯的数字，`note` 写清口径（计划总投资/备案总投资/中标金额/募资净额等），不同口径分开列、不相加。

**后续关注**（`watchlist`，可选，最多12条）：写下一步可公开核实的文件或节点，有依据时引用事项ID；不写营销、拜访或授信安排。

含日期编码、抓取、附件解析等技术说明的采集摘要，另编 `reader_summary` 作为读者正文，必要时编 `reader_analysis` 作为“研究关注”；原 `summary`、`analysis` 和完整时间戳保留在折叠核验记录中。不得用自动删句代替内容审校。

## 5. 质量检查

```bash
python3 "$SKILL/scripts/briefing_tool.py" lint --data "$RUN/04-final.json"
```

渲染前先运行。`lint` 检查可机器判断的写作规范：速览用条数充数、读者正文夹带编制说明、推断贷款/营销/投资建议、渲染性措辞、标题过长、分类字段缺失、主题过碎、周月报缺专题等，输出 `error/warning/info` 和质量分。有 `error` 必须改正后再渲染；`warning` 逐条处理或说明保留理由。`lint` 不判断真实性和语义，通过后仍需人工复核摘要逐句证据、金额与阶段口径、范围与实际覆盖差异。

## 6. 渲染：模板与图表

只用 `scripts/briefing_tool.py` 从最终JSON完整渲染（内置 `report_design.py` 与 `assets/report.css`），不在报告外临时注入图表，不手改成品。

```bash
python3 "$SKILL/scripts/briefing_tool.py" render --data "$RUN/04-final.json" --out "$RUN/简报.html"
python3 "$SKILL/scripts/briefing_tool.py" render --data "$RUN/04-final.json" --out "$RUN/简报-要报.html" --layout memo --theme ink
```

输出文件已存在时拒绝覆盖；修改后重新渲染请换新文件名（如加版本号）。

| 版式 `layout` | 适用 |
|---|---|
| `standard` 标准版 | 默认；概况图表+双栏卡片，桌面与手机自适应 |
| `compact` 速读版 | 晨报、手机、事项多时；单栏列表，图表只保留来源构成 |
| `memo` 要报版 | 管理层、政府与打印；内容提要在前，“一、（一）1.”编号，默认不出图 |

配色 `theme`：`classic` 暖纸深红、`navy` 商务蓝、`ink` 素墨、`jade` 青绿；默认随系统深色模式切换，`color_scheme=light` 可固定浅色。也可在最终JSON的 `presentation` 写入 `theme/layout/color_scheme/charts`，命令行参数优先。

图表由渲染器按数据自动选择，`presentation.charts` 可显式指定 `publisher/theme/region/enterprise/stage`：来源构成用分段条，主题、地区、企业用按数量排序的横向条形图，超过7类折叠为“其余N项合计”（只列数字、不画条），未分类单列在末尾；少于两类的维度不成图，主题、地区、企业、阶段图另要求事项不少于3条。每张图附数据表。不同项目的阶段不串成漏斗或转化率，本期不按发布日期计数。页面只保留图名、图例、数字，不展示编制或实现说明。

首屏可见实际编制范围、观察稿、部分周期和重要覆盖限制（`coverage.highlights` 最多3条）；完整缺口和时间戳在折叠区。页面不含脚本、远程字体、跟踪资源、导出按钮或主题切换。

## 7. 按需导出PNG长图

只有用户要“长图、分享海报、PNG”时才调用，不随HTML自动导出，不在页面放导出入口。需要Playwright和本地Chromium/Chrome/Edge；先检测现有环境，不自动联网安装或下载浏览器，依赖不可用时如实报告，仍交付HTML/JSON。

```bash
python3 "$SKILL/scripts/export_png.py" --data "$RUN/04-final.json" --out "$RUN/分享长图.png" [--layout compact] [--theme navy] [--executable-path /path/to/chrome]
```

默认540 CSS像素×2倍=1080像素宽，高度随内容；手机排版下速览在图表之前。保留标题、日期、观察稿与覆盖说明、图表、摘要、全部可见事实、来源名称和专题；技术证据折叠，完整证据在HTML/JSON。网络拦截、页面脚本禁用，不截断、不覆盖已有文件；超大长图明确失败，降倍率或拆分后重试。请求导出只授权本地生成，不授权发送。

## 8. 留存与交付

在用户工作目录建单次运行目录，留存 `config-effective.json`、`00-raw.json`、`01-evidence.json`、`02-selected.json`、`03-analysis.json`、`04-final.json`、`RUN-STATE.json`；不写入技能安装目录。字段依照[运行契约](references/workflow.md)，核对去重、筛选、展示和图表计数。重复运行不得重复插入摘要或“本期主题”章节。

交付前逐项确认：`coverage.method` 与实际做法一致（当期检索 `live_public`、聚合存档 `aggregate_only`、事后补采 `backfill_public`）；摘要逐句有证据；原始发布日、金额与阶段口径正确；默认范围与本期实际覆盖的差异已写明；`lint` 无 `error`；宽窄屏无横向溢出；图表数字与证据一致且全部证据可达。重要覆盖限制始终可见。尽量由独立审查者复核并修订复检，不以旧测试全部通过代替当期验收。

交付HTML、证据JSON、已请求的PNG，以及必要的覆盖缺口说明。没有运行的能力不称已验证；报告附公开信息参阅及非授信/投资意见声明。公开分享、邮件、消息、部署、定时和上架仅按用户另行明确的指令执行。
