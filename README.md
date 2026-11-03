# 固收工作台

把十二个固定收益工具收进一个本地入口：

| 工具 | 说明 |
|---|---|
| 境内债制表 | 地方债 / 信用债原始表 → 标准制表 + 待发行播报 |
| 投标簿记提取 | 投标量表截图 + 债券文本行 → 标准簿记文案 |
| 报价要素生成 | 交易行文本 + DM 截图 → 一行固定格式报价 |
| WACC 批量计算 | 上传表格或手动录入，批量算加权平均资本成本 |
| 上市要素整理 | 任意排版的要素文本 → 固定模版（纯本地规则） |
| 债券计算器 | 净价/全价、YTM、久期、凸性、DV01、持有期情景 |
| 回购/资金计算器 | 回购到期金额、实际资金成本、质押券与杠杆 |
| 现金流/付息日历 | 持仓表 → 未来付息/兑付明细与年度汇总 |
| 组合风险快照 | 加权久期、总 DV01、评级/行业集中度、利率情景 |
| 国债期货基差 | CTD 基差、净基差、IRR、DV01 对冲手数 |
| 投标/中标统计 | 按债券汇总投标量、加权利率、中标率 |
| 交易要素提取 | 交易聊天文本 → 结构化台账 + Excel |

- 只在本机运行（`127.0.0.1`），除可关闭的 GitHub 更新检查外**不联网**，不上传任何数据。
- 十二个工具各自独立：工作台只负责启动/停止/打开，**不打通数据**；工具在浏览器独立标签页使用。右侧上半显示运行中的工具，下半收纳较少用的计算/整理工具。
- 统一浅色主题：工作台固定白底，子进程通过 `STREAMLIT_THEME_BASE=light` 让 Streamlit 工具也保持白底。
- 工作台本体只用 Python 标准库，前端无框架、无 CDN。
- **自动更新**：启动后检查 GitHub Release；版本号旁显示「暂无更新 / 有新版本」，确认后下载增量包覆盖并重启。
- 主交付 macOS（Apple Silicon，macOS 11+）；Windows 版用于回归验证。

## 目录

```
固收工作台/
├── 启动工作台.command     # macOS 双击入口
├── 启动工作台.bat         # Windows 双击入口
├── 诊断报告.command       # 生成诊断报告
├── start.py               # 启动逻辑（单实例、锁、信号清理）
├── tools.json             # 十二个工具的配置（端口 / 入口 / 输出目录）
├── workbench/             # 工作台本体（config/ports/manager/bootstrap/server/web/...）
├── requirements/          # 钉版依赖（mac / win 各两份）
├── scripts/selftest.py    # 端到端自检
├── build/                 # 构建脚本（抓 wheel / 校验 / staging / 打包）
├── tests/                 # unittest（纯标准库）
├── docs/使用说明.md        # 用户手册（含 Gatekeeper 图文步骤与 Mac 验收清单）
└── runtime/               # 运行期依赖（内置 Python 与 wheelhouse，打包用）
```

## 使用

普通用户请看 **[docs/使用说明.md](docs/使用说明.md)**。

维护者 / 想加新工具的人请看 **[docs/交接说明.md](docs/交接说明.md)**；
AI 模型请先读 **[AGENTS.md](AGENTS.md)**。首次运行会在 macOS 桌面自动生成一个直达快捷方式。

## 开发 / 构建

```powershell
# 全部测试（Windows 本机用 Python 3.11）
py -3.11 -m unittest discover -v

# 抓 wheel（构建期联网，固定走阿里云镜像）
py -3.11 build/build_wheels.py --requirements requirements/streamlit-mac.txt `
  --out runtime/wheels/macos-arm64-cp312 `
  --platform macosx_11_0_arm64 --python-version 3.12 --abi cp312

# 校验 wheelhouse（离线，含依赖闭包干跑）
py -3.11 build/verify_bundle.py --wheelhouse runtime/wheels/macos-arm64-cp312 `
  --requirements requirements/streamlit-mac.txt `
  --platform macosx_11_0_arm64 --python-version 3.12 --abi cp312

# 下载内置 Python（可选：也可以直接放 tar.gz）
py -3.11 build/fetch_python.py --dest runtime/python

# 生成 staging 并打 zip
py -3.11 build/stage.py --platform darwin
py -3.11 build/make_bundle.py --stage build/stage-mac/固收工作台 `
  --out dist/固收工作台-macOS-arm64.zip

# 端到端自检（起真实工具 → 等就绪 → 停止 → 验证端口释放）
py -3.11 scripts/selftest.py --timeout 240
```

## 设计要点

- **单实例**：`workbench.lock` + `/api/ping` 复验 + `launch.lock` 原子占位；第二次双击只开页面。
- **归属模型**：`self` / `orphan`（上次残留，可停）/ `external`（不是我们起的，拒绝停止）。
- **离线自举**：内置 Python → venv → `pip install --no-index --find-links`，失败可重建。
- **端口**：工作台 8787 / 制表 8511 / 簿记 8765 / 报价 8766 / WACC 8512，被占顺延最多 20 个。
- **安全**：只绑 `127.0.0.1`；校验 `Host` 与 `Origin`；探测绕系统代理、禁重定向。

设计与实施记录见 `docs/superpowers/`。
