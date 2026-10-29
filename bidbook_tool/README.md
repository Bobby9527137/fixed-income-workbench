# 投标簿记提取

把「投标量固定表头」的表格**截图** + 聊天/邮件里的**债券文本行**，合成固定格式的簿记文案。

## 怎么跑（macOS）

```bash
cd bidbook_tool
bash run.sh            # 起服务并打开浏览器
```

也可以直接双击 `启动.command`（首次可能需要先在终端执行一次 `chmod +x run.sh 启动.command`）。

首次运行会自动：建虚拟环境 `.venv` → 装依赖 → 自检 → 启动 → 打开浏览器。之后复用同一个 `.venv`。

```bash
./run.sh --doctor      # 只自检，能修的自己修
./run.sh --reinstall   # 删掉 .venv 全部重装
./run.sh --selftest    # 只跑逻辑自检（解析/匹配/成文，不用 OCR、不联网）
```

网页默认地址 <http://127.0.0.1:8765>（端口被占用会自动顺延）。

## 依赖与镜像

首次安装会走清华镜像。想换源或只用官方源：

```bash
export BIDBOOK_MIRROR=https://mirrors.aliyun.com/pypi/simple/
export BIDBOOK_MIRROR=off
./run.sh
```

安装期间终端没动静是正常的（pip 在下载/解包），不要急着 Ctrl+C；真要中断，重跑一次即可。

## 怎么用

1. 上传/粘贴投标量表格截图。
2. 粘贴债券文本行（代码、简称、量、价格等）。
3. 核对识别结果，必要时补数。
4. 生成标准簿记文案，一键复制。

## 目录

```
bidbook_tool/
├── app.py               # 入口
├── bidbook/             # OCR、表格检测、文本解析、页面
├── tests/               # 逻辑与 Web 测试
├── run.sh               # macOS 启动脚本
├── 启动.command          # macOS 双击入口
├── probe                # 用例探针（开发用）
└── requirements.txt
```

## 测试

```bash
bash run.sh --selftest
python3 -m pytest tests        # 如已安装 pytest
```

## 已知限制

- 字号 ≥26px 且债券简称较长时，汉字竖笔可能被当成表格竖线，导致整表识别为 0 行。临时绕法：截图字号 ≤22px，或手工补数。
- OCR 只在本机运行，不联网。
