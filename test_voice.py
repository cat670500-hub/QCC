import os
import sys

# 將當前目錄加入路徑以便載入 app.py
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import is_fuzzy_bed_match

test_cases = [
    # (bed_no, spoken_text, expected_result, description)
    ("7c01-2", "七C洞么兩", True, "一般病房附屬床號，消除 - 與 0 的防呆"),
    ("7c1", "七C十二", False, "防呆檢查：避免 7c1 錯誤配對到 7c12"),
    ("11b1", "十一B么", True, "十一B 轉換"),
    ("11a01", "C耶零么", True, "11A 轉換，加上 A 被聽成 耶"),
    ("nbc01", "恩逼吸洞么", True, "NBC 嬰兒室，單字母解析"),
    ("5a01", "哇洞么", True, "5A (wa) 連音測試"),
    ("9c12", "QC十二", True, "9C (qc) 連音測試"),
    ("micu01", "麥哭洞么", True, "ICU 專有名詞解析"),
    ("10b02", "SB洞兩", True, "10B (sb) 連音測試"),
    ("8a05", "BA零五", True, "8A (ba) 連音測試"),
]

print("=== 語音系統配對測試開始 ===")
all_pass = True
for bed, text, expected, desc in test_cases:
    result = is_fuzzy_bed_match(text, bed)
    status = "PASS" if result == expected else "FAIL"
    if result != expected:
        all_pass = False
    print(f"[{status}] 測試情境: {desc}")
    print(f"   床號: {bed:8} | 語音: {text:10} | 預期: {expected} | 實際: {result}")

if all_pass:
    print("\n所有語音防呆與轉換邏輯測試通過！")
else:
    print("\n有部分測試未通過，請檢查邏輯。")
