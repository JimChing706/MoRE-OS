#!/usr/bin/env python3
import csv
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "retrospective_tasks_table.csv")
JSON_PATH = os.path.join(BASE_DIR, "retrospective_summary.json")
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_PATH_FILE = os.path.join(BASE_DIR, "verify_script_path.txt")

EXPECTED_HEADER = [
    "task_id",
    "title",
    "module",
    "is_more_native",
    "execution_carrier",
    "trae_tools",
    "evidence"
]

def main():
    errors = []

    print("[1/4] 断言 CSV header 正确...")
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        if header == EXPECTED_HEADER:
            print("  ✓ PASS: header 与预期 7 列 schema 完全一致")
        else:
            errors.append(f"Header 不匹配。\n  预期: {EXPECTED_HEADER}\n  实际: {header}")
            print(f"  ✗ FAIL: header 不匹配")
    except Exception as e:
        errors.append(f"读取 CSV header 失败: {e}")
        print(f"  ✗ FAIL: 读取 CSV header 异常 - {e}")

    print("[2/4] 断言 CSV 行数 ≥ 25...")
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        data_row_count = len(rows) - 1
        if data_row_count >= 25:
            print(f"  ✓ PASS: 数据行数 = {data_row_count} (≥25)")
        else:
            errors.append(f"数据行数不足。实际 {data_row_count} 行，要求 ≥25 行")
            print(f"  ✗ FAIL: 数据行数 {data_row_count} < 25")
    except Exception as e:
        errors.append(f"统计 CSV 行数失败: {e}")
        print(f"  ✗ FAIL: 统计 CSV 行数异常 - {e}")

    print("[3/4] 断言 is_more_native 列全部为 false...")
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_false = True
            bad_rows = []
            for i, row in enumerate(reader, start=2):
                val = row.get("is_more_native", "").strip().lower()
                if val != "false":
                    all_false = False
                    bad_rows.append((i, row.get("task_id", "?"), val))
            if all_false:
                print("  ✓ PASS: is_more_native 列全部为 false")
            else:
                msg = f"is_more_native 存在非 false 行:\n"
                for ln, tid, v in bad_rows[:10]:
                    msg += f"    行{ln} task_id={tid} 值='{v}'\n"
                errors.append(msg)
                print(f"  ✗ FAIL: 发现 {len(bad_rows)} 行 is_more_native != false")
    except Exception as e:
        errors.append(f"检查 is_more_native 列失败: {e}")
        print(f"  ✗ FAIL: 检查 is_more_native 列异常 - {e}")

    print("[4/4] 断言 overall_native_pct = 0.0...")
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        pct = data.get("overall_native_pct")
        if pct == 0.0:
            print(f"  ✓ PASS: overall_native_pct = {pct}")
        else:
            errors.append(f"overall_native_pct 值错误。预期 0.0，实际 {pct}")
            print(f"  ✗ FAIL: overall_native_pct = {pct} ≠ 0.0")
    except Exception as e:
        errors.append(f"读取 JSON overall_native_pct 失败: {e}")
        print(f"  ✗ FAIL: 读取 JSON 异常 - {e}")

    print()
    if not errors:
        try:
            with open(SCRIPT_PATH_FILE, "w", encoding="utf-8") as f:
                f.write(SCRIPT_PATH + "\n")
        except Exception as e:
            print(f"⚠ 写入脚本路径文件失败: {e}")

        print("=" * 60)
        print("Task1_VERIFIED")
        print("=" * 60)
        print(f"验证脚本路径已写入: {SCRIPT_PATH_FILE}")
        print(f"CSV 文件: {CSV_PATH}")
        print(f"JSON 文件: {JSON_PATH}")
        sys.exit(0)
    else:
        print("=" * 60)
        print(f"验证失败，共 {len(errors)} 项错误:")
        for idx, err in enumerate(errors, 1):
            print(f"  [{idx}] {err}")
        print("=" * 60)
        sys.exit(1)

if __name__ == "__main__":
    main()
