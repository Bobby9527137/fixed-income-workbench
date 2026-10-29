"""WACC 工具：25 类输入材料的验收矩阵。

模拟界面的“上传 → 猜表头 → 猜参数连线 → 批量计算”链路：
    detect_header_row → read_table → guess_mapping → validate_selection → batch_compute
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT.parent / "wacc-tool"
sys.path.insert(0, str(TOOL))

import app  # noqa: E402
import wacc_core  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="wb-accept-wacc-"))


def expected_wacc(E, D, Re, Rd, Tc, DE=None):
    if E is None and DE is not None:
        E, D = 1.0, DE
    elif E is not None and D is None and DE is not None:
        D = E * DE
    ev = E / (E + D)
    dv = D / (E + D)
    return ev * Re + dv * Rd * (1 - Tc)


def write_xlsx(name, rows, *, title_rows=0, header=True, sheets=None):
    path = TMP / name
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if sheets:
            for sheet, (columns, data, pad) in sheets.items():
                frame = pd.DataFrame(data, columns=columns)
                if pad:
                    for i in range(pad):
                        frame.to_excel(writer, sheet_name=sheet, header=False, index=False, startrow=0)
                        break
                    frame.to_excel(writer, sheet_name=sheet, header=False, index=False, startrow=pad)
                else:
                    frame.to_excel(writer, sheet_name=sheet, index=False)
        else:
            frame = pd.DataFrame(rows)
            if title_rows:
                frame.to_excel(writer, sheet_name="Sheet1", index=False, startrow=title_rows, header=header)
            else:
                frame.to_excel(writer, sheet_name="Sheet1", index=False, header=header)
    return path


def write_csv(name, rows):
    path = TMP / name
    if name.endswith(".csv.gz"):
        pd.DataFrame(rows).to_csv(path, index=False, encoding="gbk")
    else:
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def run_case(name, path, *, sheet=None, expect_ok, expect_errors=0, waccs=None, missing=False,
             expect_header=None):
    try:
        data = path.read_bytes()
        hr = app.detect_header_row(path.name, data, sheet)
        if expect_header is not None:
            assert hr == expect_header, f"表头行 {hr} != {expect_header}"
        df = app.read_table(path.name, data, sheet, header_row=hr - 1)
        columns = [str(c) for c in df.columns]
        mapping = app.guess_mapping(columns)
        # 界面会为每个参数都建一个控件（未命中的是「不使用」），这里保持一致。
        selections = {key: ("none", None) for key in
                      ("E", "D", "DE", "Re", "Rf", "beta", "ERP", "Rd", "Tc")}
        selections.update({k: ("col", v) for k, v in mapping.items() if k != "sample_id"})
        problems = app.validate_selection(selections)
        if missing:
            assert problems, "预期缺少必填参数，但校验通过了"
            return {"case": name, "ok": True, "detail": f"正确拦截：{problems[0]}"}
        assert not problems, f"参数校验失败：{problems}；映射={mapping}"

        rows = []
        for _, rec in df.iterrows():
            kw = {}
            for key, col in mapping.items():
                if key == "sample_id":
                    continue
                value = rec[col]
                if pd.isna(value):
                    value = None
                kw[key] = value
            rows.append(kw)
        ok, errors = wacc_core.batch_compute(rows, pct_mode="auto")
        assert len(ok) == expect_ok, f"成功 {len(ok)} != {expect_ok}；错误={[e[2] for e in errors]}"
        assert len(errors) == expect_errors, f"错误 {len(errors)} != {expect_errors}：{errors}"
        if waccs:
            actual = [r["WACC"] for r in ok]
            for got, want in zip(actual, waccs):
                assert abs(got - want) < 1e-6, f"WACC {got} != {want}"
        return {
            "case": name,
            "ok": True,
            "detail": f"表头第 {hr} 行 / 成功 {len(ok)} / 跳过 {len(errors)}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"case": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def main():
    results = []

    # 1 CSV 基线（Re 直接给，小数）
    p = write_csv("1.csv", [{"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("1 CSV 基线（小数利率）", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25)]))

    # 2 xlsx 基线
    p = write_xlsx("2.xlsx", [{"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("2 XLSX 基线", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25)]))

    # 3 表头上方有标题 + 序号行
    p = write_xlsx("3.xlsx", [{"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}],
                   title_rows=2)
    results.append(run_case("3 表头上方两行", p, expect_ok=1, expect_header=3))

    # 4 表头在第 4 行
    p = write_xlsx("4.xlsx", [{"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}],
                   title_rows=3)
    results.append(run_case("4 表头在第 4 行", p, expect_ok=1, expect_header=4))

    # 5 百分数字符串
    p = write_xlsx("5.xlsx", [{"公司": "A", "E": 60, "D": 40, "Re": "10%", "Rd": "5%", "Tc": "25%"}])
    results.append(run_case("5 利率写成百分数字符串", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25)]))

    # 6 全角百分号
    p = write_xlsx("6.xlsx", [{"公司": "A", "E": 60, "D": 40, "Re": "10％", "Rd": "5％", "Tc": "25％"}])
    results.append(run_case("6 全角百分号", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25)]))

    # 7 仅 D/E
    p = write_xlsx("7.xlsx", [{"公司": "A", "D/E": 0.5, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("7 仅给 D/E", p, expect_ok=1,
                            waccs=[expected_wacc(None, None, 0.10, 0.05, 0.25, DE=0.5)]))

    # 8 E + D/E
    p = write_xlsx("8.xlsx", [{"公司": "A", "E": 100, "D/E": 0.5, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("8 给 E 与 D/E", p, expect_ok=1,
                            waccs=[expected_wacc(100, 50, 0.10, 0.05, 0.25)]))

    # 9 D + D/E
    p = write_xlsx("9.xlsx", [{"公司": "A", "D": 50, "D/E": 0.5, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("9 给 D 与 D/E", p, expect_ok=1,
                            waccs=[expected_wacc(100, 50, 0.10, 0.05, 0.25)]))

    # 10 CAPM
    p = write_xlsx("10.xlsx", [{"公司": "A", "E": 60, "D": 40, "Rf": 0.03, "β": 1.2, "ERP": 0.06,
                                "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("10 CAPM 推算 Re", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.03 + 1.2 * 0.06, 0.05, 0.25)]))

    # 11 同一表里 Re 与 CAPM 混用
    p = write_xlsx("11.xlsx", [
        {"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rf": 0.03, "β": 1.2, "ERP": 0.06, "Rd": 0.05, "Tc": 0.25},
        {"公司": "B", "E": 80, "D": 20, "Re": None, "Rf": 0.03, "β": 0.8, "ERP": 0.06, "Rd": 0.06, "Tc": 0.15},
    ])
    results.append(run_case("11 Re 与 CAPM 混用", p, expect_ok=2,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25),
                                   expected_wacc(80, 20, 0.03 + 0.8 * 0.06, 0.06, 0.15)]))

    # 12 负 E
    p = write_xlsx("12.xlsx", [
        {"公司": "A", "E": -1, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25},
        {"公司": "B", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25},
    ])
    results.append(run_case("12 负股权价值逐行跳过", p, expect_ok=1, expect_errors=1))

    # 13 缺 Rd（只有 E/D/Re/Tc）
    p = write_xlsx("13.xlsx", [{"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Tc": 0.25}])
    results.append(run_case("13 缺必填 Rd 被拦截", p, expect_ok=0, missing=True))

    # 14 E+D=0
    p = write_xlsx("14.xlsx", [{"公司": "A", "E": 0, "D": 0, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("14 E+D=0 逐行跳过", p, expect_ok=0, expect_errors=1))

    # 15 数字列混入文本
    p = write_xlsx("15.xlsx", [
        {"公司": "A", "E": "六十", "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25},
        {"公司": "B", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25},
    ])
    results.append(run_case("15 数字列混入文本", p, expect_ok=1, expect_errors=1))

    # 16 多余列
    p = write_xlsx("16.xlsx", [{"公司": "A", "行业": "制造", "E": 60, "D": 40, "备注": "x",
                                "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("16 多余未知列", p, expect_ok=1))

    # 17 序号作为样本标识
    p = write_xlsx("17.xlsx", [{"序号": 1, "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("17 序号列作为样本标识", p, expect_ok=1))

    # 18 千分位
    p = write_xlsx("18.xlsx", [{"公司": "A", "E": "1,200", "D": "800", "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("18 金额带千分位", p, expect_ok=1,
                            waccs=[expected_wacc(1200, 800, 0.10, 0.05, 0.25)]))

    # 19 中间夹空行
    p = write_xlsx("19.xlsx", [
        {"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25},
        {"公司": None, "E": None, "D": None, "Re": None, "Rd": None, "Tc": None},
        {"公司": "B", "E": 80, "D": 20, "Re": 0.09, "Rd": 0.04, "Tc": 0.25},
    ])
    results.append(run_case("19 中间夹空行", p, expect_ok=2, expect_errors=1))

    # 20 中文别名表头
    p = write_xlsx("20.xlsx", [{"权益价值": 60, "负债合计": 40, "权益成本": 0.10,
                                "借款利率": 0.05, "所得税": 0.25}])
    results.append(run_case("20 中文别名表头", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25)]))

    # 21 英文表头
    p = write_xlsx("21.xlsx", [{"Name": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}])
    results.append(run_case("21 英文表头", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25)]))

    # 22 多工作表
    path = TMP / "22.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([{"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}]).to_excel(
            writer, sheet_name="样本一", index=False)
        pd.DataFrame([{"公司": "B", "E": 80, "D": 20, "Re": 0.09, "Rd": 0.04, "Tc": 0.25}]).to_excel(
            writer, sheet_name="样本二", index=False)
    results.append(run_case("22 多工作表选第二张", path, sheet="样本二", expect_ok=1,
                            waccs=[expected_wacc(80, 20, 0.09, 0.04, 0.25)]))

    # 23 末尾合计行
    p = write_xlsx("23.xlsx", [
        {"公司": "A", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25},
        {"公司": "合计", "E": "—", "D": "—", "Re": "—", "Rd": "—", "Tc": "—"},
    ])
    results.append(run_case("23 末尾合计行被跳过", p, expect_ok=1, expect_errors=1))

    # 24 千分位 + 百分号组合
    p = write_xlsx("24.xlsx", [{"公司": "A", "E": "1,200.5", "D": "800.5", "Re": "10%",
                                "Rd": "5%", "Tc": "25%"}])
    results.append(run_case("24 千分位与百分号组合", p, expect_ok=1,
                            waccs=[expected_wacc(1200.5, 800.5, 0.10, 0.05, 0.25)]))

    # 25 GBK 编码 CSV
    p = TMP / "25.csv"
    pd.DataFrame([{"公司": "甲", "E": 60, "D": 40, "Re": 0.10, "Rd": 0.05, "Tc": 0.25}]).to_csv(
        p, index=False, encoding="gbk"
    )
    results.append(run_case("25 GBK 编码 CSV", p, expect_ok=1,
                            waccs=[expected_wacc(60, 40, 0.10, 0.05, 0.25)]))

    print(json.dumps(results, ensure_ascii=False, indent=1))
    passed = sum(1 for r in results if r["ok"])
    print(f"\nPASS {passed}/{len(results)}")
    (TMP / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
