# 境内债制表工具

把地方债 / 信用债原始数据表一键转换为分品种的**标准表格**：

- 地方债：11 列（源表为 35 列招标表）
- 信用债：11 列新表头（源表为 52 列导出表）

制表结果旁可一键生成「待发行」播报文本（「今日 / 本周」头行可切换）。

## 启动（macOS）

**方式一：双击**

在 Finder 里 **右键** `启动.command` → **打开**（首次会被 Gatekeeper 拦一次，右键打开即可）。之后再双击就能直接运行。

**方式二：命令行**

```bash
python3 -m pip install -r scripts/requirements.txt
python3 -m streamlit run scripts/app.py
```

浏览器会打开 `http://localhost:8501`。

## 怎么用

1. 上传地方债或信用债原始表（`.xlsx`）。
2. 选择品种与表头行；工具会自动识别表头并给出提示。
3. 生成标准表，下载 Excel。
4. 需要播报时，点「生成待发行播报」，选择「今日 / 本周」。
5. 切换「今日 / 本周」后，已生成的内容会同步更新。

## 目录

```
境内债制表工具/
├── 启动.command            # macOS 双击入口
├── 首次运行(Mac必读).txt    # 首次使用说明
├── scripts/
│   ├── app.py              # Streamlit 界面
│   ├── bondtable.py        # 制表逻辑
│   ├── transform.py        # 字段转换
│   ├── test_transform.py   # 转换测试
│   └── requirements.txt
├── config/表头映射.json     # 表头映射
└── docs/                   # 需求、表头对照、测试记录
```

## 测试

```bash
python3 scripts/test_transform.py
```

## 已知限制

- 原始表的表头行位置因导出工具而异；自动识别不准时手动指定表头行。
- 只支持 `.xlsx`；旧版 `.xls` 请先另存为 `.xlsx`。
- 所有处理都在本机完成，不联网。
