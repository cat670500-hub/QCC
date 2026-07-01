# -*- coding: utf-8 -*-
import sys
import difflib
import re
from app import parse_voice_to_bed, is_fuzzy_name_match, log_voice_call

patients_data = [
    {'record_no': '1234567', 'name': '王小明', 'bed': '11B01', 'order_no': 'O001'},
    {'record_no': '9876543', 'name': '李大華', 'bed': '7C05', 'order_no': 'O002'},
    {'record_no': '5556667', 'name': '陳美麗', 'bed': '207-02S', 'order_no': 'O003'},
    {'record_no': '1112223', 'name': '林志玲', 'bed': 'ER05', 'order_no': 'O004'},
    {'record_no': '9998887', 'name': '張學友', 'bed': 'RCC10', 'order_no': 'O005'},
    {'record_no': '3334445', 'name': '黃曉明', 'bed': '10A02', 'order_no': 'O006'},
]

print("==================================================")
print("        QCC 語音智慧配對系統 - 全功能總測試")
print("==================================================\n")

# --- 1. 測試病歷號配對 ---
print("【測試一：病歷號精準配對 (6~10位數字)】")
tests_record = [
    ("那個幫我傳送1234567去照X光", "1234567"),
    ("病歷號9876543的病患準備好了", "9876543"),
    ("病患12345，這個太短應該不會配對", None), 
]

for text, expected in tests_record:
    record_numbers = re.findall(r'\d{6,10}', text)
    matched = None
    if record_numbers:
        for r_no in record_numbers:
            r_no_clean = str(r_no).strip()
            for p in patients_data:
                if str(p.get('record_no', '')).strip() == r_no_clean:
                    matched = p
                    break
    
    status = "[PASS] PASS" if (matched and matched['record_no'] == expected) or (not matched and expected is None) else "[FAIL] FAIL"
    res_str = matched['name'] + " (" + matched['record_no'] + ")" if matched else "無配對"
    print(f"語音: {text:<30} => {status} (配對: {res_str})")

print("\n【測試二：病患姓名模糊配對】")
tests_name = [
    ("幫我推王小明去二樓", "王小明"),
    ("那個李達華(大華)要傳送", "李大華"), # 測試同音字
    ("床號不確定，是陳沒力(美麗)嗎", "陳美麗"),
]

for text, expected in tests_name:
    matched = None
    for p in patients_data:
        if is_fuzzy_name_match(text, p['name']):
            matched = p
            break
            
    status = "[PASS] PASS" if matched and matched['name'] == expected else "[FAIL] FAIL"
    res_str = matched['name'] if matched else "無配對"
    print(f"語音: {text:<25} => {status} (配對: {res_str})")

print("\n【測試三：床號智慧配對 (含編輯距離糾錯)】")
tests_bed = [
    ("十一逼洞么", "11B01"),      # 完美嚴格配對
    ("十一低洞么", "11B01"),      # B聽成低 -> 編輯距離糾錯
    ("七吸洞五", "7C05"),        # 同音配對
    ("二大樓二洞七洞兩S", "207-02S"), # 二大樓特殊床號
    ("急診洞五", "ER05"),        # 特殊病房
    ("呼吸照護十", "RCC10"),      # 特殊病房
]

for text, expected in tests_bed:
    matched = None
    parsed_bed = parse_voice_to_bed(text).lower()
    

    for p in patients_data:
        p_bed = str(p.get('bed', '')).strip()
        from app import is_fuzzy_bed_match
        if is_fuzzy_bed_match(text, p_bed):
            matched = p
            break
            
    if not matched:
        parsed_bed = parse_voice_to_bed(text).lower()
        if len(parsed_bed) >= 3:
            active_beds = {}
            for p in patients_data:
                p_bed = str(p.get('bed', '')).strip()
                if p_bed:
                    bed_clean = p_bed.replace(' ', '').replace('-', '').replace('_', '').lower()
                    if '急診' in bed_clean:
                        bed_clean = bed_clean.replace('急診', 'er')
                    if 'rcc' in bed_clean or '呼吸' in bed_clean:
                        bed_clean = 'rcc'
                    active_beds[bed_clean] = p
            matches = difflib.get_close_matches(parsed_bed, active_beds.keys(), n=1, cutoff=0.75)
            if matches:
                matched = active_beds[matches[0]]

            
    status = "[PASS] PASS" if matched and matched['bed'] == expected else "[FAIL] FAIL"
    res_str = matched['bed'] if matched else "無配對"
    print(f"語音: {text:<20} => 解析: {parsed_bed:<7} => {status} (配對: {res_str})")

print("\n【測試四：過濾閒聊雜音機制】")
tests_noise = [
    "我等一下要去吃便當了你要吃什麼",
    "剛剛那個病人一直亂叫好煩喔",
    "你知道明天要排什麼班嗎",
]

for text in tests_noise:
    # 模擬 log_voice_call 的過濾邏輯
    text_clean = str(text).replace(" ", "").replace("　", "")
    is_noise = False
    
    if len(text_clean) > 8:
        # 如果長度 > 8 且沒有關鍵字，視為雜音
        keywords = ["床", "號", "傳送", "照相", "緊急", "病患", "病人", "推", "去"]
        if not any(k in text_clean for k in keywords):
            is_noise = True
            
    status = "[PASS] 成功過濾" if is_noise else "[FAIL] 過濾失敗"
    print(f"語音: {text:<25} => {status}")

print("\n==================================================")
print("測試完成！")
