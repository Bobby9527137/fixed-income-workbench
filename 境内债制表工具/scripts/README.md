# scripts/ — 程序清单与用法

| 文件 | 职责 | 运行方式 |
|---|---|---|
| `bondtable.py` | **核心引擎**：读取 xlsx（路径或内存流）→ 自动定位表头行 → 债种识别（含别名：地方政府债→地方债、商金债→信用债）→ 按品种映射取列/多列合成（主/债评级、发行量实际优先）→ 清洗（日期/时间/代码/期限/数值）→ 排序＋行标黄（地方债：整表按发行日升序，贵州/陕西/江西/西藏行**原位**整行黄底、**不置顶**）→ 写出带排版的 xlsx；另含"待发行"播报文本生成（make_local_text：同日同地区合并＋期限集合，真实简称解析——'26内蒙古27'→内蒙古、'26广东债40(续发)'→广东 / make_credit_text：债券简称行式；头行今日/本周可切换） | 被下面各入口复用，不单独运行 |
| `transform.py` | 命令行批处理入口（处理文件或整个文件夹，逐张打印结果预览） | `python scripts/transform.py --input data/原始数据 [--outdir data/输出]` |
| `app.py` | Streamlit 可视化界面（上传 → 核对债种 → 一键制表 → 预览/下载；两债结果旁均一键生成"待发行"播报文本，头行"今日/本周"可切换，可复制/下载 .txt） | `python -m streamlit run scripts/app.py` |
| `make_mock_data.py` | 模拟数据生成器：地方债 35 列招标表、信用债 52 列真实导出表各生成一张，故意混入脏格式用例 | `python scripts/make_mock_data.py` |
| `make_single_day_sample.py` | **单日测试样本**生成器（2026-10-12 同日 20 券 × 两债，各放入 `data/原始数据/`）：地方债含 9 行标黄 + 同日同地区多券（贵州×3/江苏×2 等，验证播报合并与原位标黄不置顶）；信用债多品种 + 计划/实际混合；生成后自动过引擎打印行数/警告/播报预览 | `python scripts/make_single_day_sample.py` |
| `package_macos.py` | **macOS 分发包**打包脚本：生成 `dist/境内债制表工具_macOS.zip`（python zipfile → UTF-8 文件名，Mac 解压中文不乱码——**勿改用系统 tar / Compress-Archive**，中文区域下会写成 GBK 编码导致 Mac 上文件名乱码）；排除 .venv/.pydeps/输出/技能库杂物；打包后自动校验关键文件与排除项 | `python scripts/package_macos.py` |
| `test_transform.py` | 端到端断言自测：57 项检查（识别 1 + 通用 12 + 地方债 17 + 信用债 15 + 文本播报 7 + 回读 5，含按发行日排序/原位标黄不置顶/合并行与两债播报逐字比对；回读为**受控写出**，不依赖输出目录其他文件） | `python scripts/test_transform.py` |
| `bootstrap_deps.py` | 受限环境依赖引导：从 PyPI 下载 wheel 解压到 `.pydeps`（备用安装方式） | `python scripts/bootstrap_deps.py` |
| `requirements.txt` | 依赖清单（pandas / openpyxl / streamlit） | `python -m pip install -r scripts/requirements.txt` |
| `../启动.command` | **macOS 一键启动**（根目录，带自愈）：双击 → 自动建虚拟环境/装依赖 → 启动界面并自动打开浏览器；成功运行一次即自动清除隔离标记+补可执行权限，之后双击永久正常；虚拟环境损坏自动重建 | 双击（首次被拦时见 README"macOS 双击被拦怎么办"） |

## 设计原则

1. **映射配置化**：列的取舍、改名、清洗规则全部读 `config/表头映射.json`，表头调整只改配置不改代码
2. **跨平台纯 Python**：仅依赖 pandas + openpyxl（界面另需 streamlit），不使用任何平台专用组件
3. **面向非技术用户**：缺列、识别不了债种、格式异常都有中文提示；无法识别的单元格原样保留便于人工核查
4. **数据安全**：债券代码按文本读取保前导零（含"7位.IB"格式）；日期兼容 Excel 序列号、`2024/6/5`、`2024年6月5日` 等写法；地方债招标时间段逐点补零（9:30-10:10 → 09:30-10:10，单元格误存完整日期时间时自动剥离日期）；期限统一 Y 计年（'10年'→'10Y'）；信用债截标时间直取归一（'2026-09-24 17:00'→'09-24 17:00'，不带年份）、主/债评级=主体＋债项合成（'AAA/'）、发行量=实际优先空则计划、申购区间无值留空不占位；空行自动剔除

## 备注

- 双击启动说明：首次双击会自动建虚拟环境并联网装依赖（约 1-3 分钟）；之后每次双击直接启动。启动后如终端出现 Email 提示，直接按回车即可（仅首次）
- macOS 双击被拦（"无法验证的开发者"或双击无反应）：在终端 `cd` 进入项目文件夹后，执行 `chmod +x 启动.command && xattr -d com.apple.quarantine 启动.command 2>/dev/null`，之后双击即恢复正常；或右键文件 → 打开 → 再点打开
- Streamlit ≥ 1.65 手动指定端口时需同时加 `--global.developmentMode false`；直接 `streamlit run`（默认 8501 端口）则不受影响
- 旧版 `.xls` 文件请先在 Excel 中另存为 `.xlsx` 再处理
- Excel 打开的文件有 `~$` 前缀锁文件，命令行批处理会自动忽略
