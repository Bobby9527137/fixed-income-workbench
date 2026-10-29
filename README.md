# 固收工作台（macOS）

把四个固定收益小工具收进一个本地入口：一次双击、一个页面、统一启停。

> **直接下载：** [固收工作台 v0.1.2 · macOS (Apple Silicon)](https://github.com/Bobby9527137/fixed-income-workbench/releases/tag/v0.1.2)

| 工具 | 作用 |
|---|---|
| 境内债制表 | 地方债 / 信用债原始表 → 标准制表 + 待发行播报 |
| 投标簿记提取 | 投标量表截图 + 债券文本行 → 标准簿记文案 |
| WACC 批量计算 | 上传表格或手动录入，批量计算加权平均资本成本 |
| 上市要素整理 | 任意排版的要素文本 → 固定模版 |

## 特点

- **纯本地**：只监听 `127.0.0.1`，运行期不访问网络，不上传任何数据。
- **离线自举**：内置 Python + 本地 wheelhouse，首次运行不需要联网。
- **单实例**：重复双击只会打开已有页面，不会起第二份。
- **环境自愈**：依赖缺失或损坏时自动重建，不需要手工 pip。
- **零框架前端**：原生 HTML/CSS/JS，无 CDN、无网络字体、无构建步骤。
- **工作台本体只用 Python 标准库**。

## 下载与运行

1. 到 **[Releases](https://github.com/Bobby9527137/fixed-income-workbench/releases/latest)** 下载 `fixed-income-workbench-macOS-arm64-v0.1.2.zip`。
2. 解压到本地目录（桌面、「应用程序」等均可）。
3. 首次运行：在 Finder 里**右键** `启动工作台.command` → **打开** → 再点一次**打开**。
4. 首次启动会解压内置 Python 并创建运行环境，约 1–3 分钟；之后双击秒开。

要求：**Apple Silicon（arm64）**，macOS 11 及以上。

> 如果双击被系统拦下，是 Gatekeeper 对下载脚本的常规隔离。右键打开一次即可；详见 [docs/使用说明.md](docs/使用说明.md)。

## 仓库内容

本仓库是 **macOS 发行版的源码快照**，包含工作台与四个工具的源码、macOS 启动器、依赖钉版和文档。

**不包含**（都在 Release 压缩包里）：

- 内置 Python 运行时（约 25 MB）
- macOS wheelhouse（约 179 MB）
- 打包好的 zip

```
.
├── 启动工作台.command        # macOS 双击入口
├── 诊断报告.command          # 一键生成诊断报告
├── start.py                  # 单实例 / 端口 / 信号 / 桌面快捷方式
├── tools.json                # 四个工具与环境配置
├── workbench/                # 工作台本体
├── 境内债制表工具/
├── bidbook_tool/
├── wacc-tool/
├── 上市要素整理/
├── requirements/             # 钉版依赖（macOS）
├── scripts/                  # 端到端自检 + 输入材料验收矩阵
└── docs/
```

## 端口

| 用途 | 默认端口 |
|---|---|
| 工作台 | 8787 |
| 境内债制表 | 8511 |
| 投标簿记提取 | 8765 |
| WACC 批量计算 | 8512 |
| 上市要素整理 | 8513 |

端口被占用时自动顺延，最多尝试 20 个。

## 单独运行某个工具

四个工具都可以脱离工作台单独启动，例如：

```bash
# 上市要素整理（纯标准库，零依赖）
python3 上市要素整理/app.py --port 8513

# 投标簿记提取
cd bidbook_tool && bash run.sh

# Streamlit 工具
cd 境内债制表工具 && python3 -m streamlit run scripts/app.py
cd wacc-tool && python3 -m streamlit run app.py
```

## 文档

- [使用说明](docs/使用说明.md) —— 给最终用户
- [交接说明](docs/交接说明.md) —— 目录地图、配置契约、加工具、打包
- [竞品与改进](docs/竞品与改进.md)

## 已知限制

- 发行包只针对 Apple Silicon；Intel Mac 需要自行准备 x86_64 的 Python 与 wheelhouse。
- macOS 真机的人工验收清单见 [docs/使用说明.md](docs/使用说明.md) 末尾。
- 工作台不内嵌工具页面，各工具在独立浏览器标签页中打开。
- 上市要素整理一次处理一只债；机构名靠后缀识别，无后缀简称需手动补。
