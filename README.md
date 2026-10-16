# 区域政企简报

按地区、重点企业、主题和阅读视角编制公开政企晨报、周报和月报，保留来源和核验记录，支持电脑宽屏、手机单栏及按需PNG长图。

## 技能信息

- 技能标识：`regional-enterprise-briefing`
- 中文名称：区域政企简报
- 版本：`1.4.0`
- 入口：仓库根目录 `SKILL.md`
- 来源仓库：https://github.com/zleo-ai/regional-enterprise-briefing

## 使用示例

- “生成江西政企晨报，重点看制造业数智化和产业项目。”
- “汇总上一完整周的公开证据，编制政企周报。”
- “把这份已核实月报导出为PNG分享长图。”

首次无配置时关注江西全省，可选择地市、企业、主题及阅读视角；实际采集不足时如实标为观察稿，不把默认全省范围当作完整覆盖。只处理公开材料，不处理内部客户数据、个人背景调查或自动授信判断。

## 结构

```text
SKILL.md
scripts/
  briefing_tool.py
  report_design.py
  export_png.py
assets/report.css
references/
examples/
tests/
```

基础校验与HTML渲染只需要Python 3.10+标准库。实时信息采集使用宿主提供的公开搜索和原文读取能力；连接器均为可选项。PNG导出另需Playwright及本地Chromium、Chrome或Edge，脚本不会自动下载浏览器。

```bash
python3 scripts/briefing_tool.py validate-config examples/config-minimal.json
python3 -B -m unittest discover -s tests
python3 scripts/briefing_tool.py render --data examples/report-empty.json --out preview-empty.html
python3 scripts/export_png.py --data /path/to/04-final.json --out /path/to/share.png
```

现有输出文件不会被覆盖。PNG仅在用户要求时生成，HTML不含导出按钮。

## SkillHub同步准备

仓库根目录的 `SKILL.md` 已提供官方发布说明要求的 `slug`、`version`、`displayName`，并保留通用技能格式的 `name`、`description` 和完整资源。

在SkillHub的导入入口选择本仓库及 `main` 分支，技能目录为仓库根目录 `/`。如使用CLI，可先按官方教程执行本地预检，再由仓库所有者自行发布：

```bash
skillhub publish . --host https://api.skillhub.cn --dry-run
```

本仓库上传不代表已同步、审核或上架SkillHub，slug是否被平台占用以同步时的检查结果为准。

官方规范：

- https://skillhub.cn/ai/release.md
- https://skillhub.cn/tutorials#publish-via-cli

## 数据与验证边界

仓库仅包含技能本体及公开示例，不包含用户真实配置、运行记录、研究报告或工作站凭证。历史公开回放仅用于演示，不表示现行政策或最新新闻。已通过83项本地测试；Windows/Linux实机及完整信源覆盖不在本次验证范围。

本项目尚未指定开源许可证；不要将公开可读误认为授予特定开源许可。
