# -*- coding: utf-8 -*-
import sys
import re
import difflib
from app import parse_voice_to_bed, is_fuzzy_bed_match, is_fuzzy_name_match

patients_data = [
    {'record_no': '1234567', 'name': '王小明', 'bed': '11B01', 'order_no': 'O001', 'source': '一般病房'},
    {'record_no': '9876543', 'name': '李大華', 'bed': '7C05', 'order_no': 'O002', 'source': '一般病房'},
    {'record_no': '5556667', 'name': '陳美麗', 'bed': '207-02S', 'order_no': 'O003', 'source': '一般病房'},
    {'record_no': '1112223', 'name': '林志玲', 'bed': 'ER05', 'order_no': 'O004', 'source': '急診'},
    {'record_no': '8889999', 'name': '周杰倫', 'bed': 'RCC10', 'order_no': 'O005', 'source': '一般病房'},
]

active_patients = [p for p in patients_data if p.get('source') != '急診' and 'er' not in p.get('bed', '').lower() and '急診' not in p.get('bed', '')]

def test_voice_match(text, expected_bed, test_name):
    matched = None
    
    # 1. Record no
    record_numbers = re.findall(r'\d{6,10}', text)
    if record_numbers:
        for r_no in record_numbers:
            r_no_clean = str(r_no).strip()
            for p in active_patients:
                if p['record_no'] == r_no_clean:
                    matched = p
                    break
    
    # 2. Name
    if not matched:
        for p in active_patients:
            if is_fuzzy_name_match(text, p['name']):
                matched = p
                break
                
    # 3. Bed
    if not matched:
        for p in active_patients:
            if is_fuzzy_bed_match(text, p['bed']):
                matched = p
                break
                
    # 4. Fallback
    if not matched:
        parsed_bed = parse_voice_to_bed(text).lower()
        if len(parsed_bed) >= 3:
            active_beds = {}
            for p in active_patients:
                bed_clean = p['bed'].replace(' ', '').replace('-', '').replace('_', '').lower()
                if 'rcc' in bed_clean or '呼吸' in bed_clean:
                    bed_clean = 'rcc'
                active_beds[bed_clean] = p
            matches = difflib.get_close_matches(parsed_bed, active_beds.keys(), n=1, cutoff=0.75)
            if matches:
                matched = active_beds[matches[0]]
                
    status = "無配對" if not matched else matched['bed']
    
    if status == expected_bed:
        result = f"[PASS] PASS (配對: {status})"
    else:
        result = f"[FAIL] FAIL (配對: {status}, 預期: {expected_bed})"
        
    print(f"語音: {text:<20} => {result}")
    
print("==================================================")
print("        QCC 語音配對測試 - 最新版本 (排除急診)")
print("==================================================\n")

print("【測試一：病歷號配對】")
test_voice_match("我推送1234567出去了", "11B01", "病歷號1234567")
test_voice_match("病患9876543準備好了", "7C05", "病歷號9876543")
test_voice_match("病患12345，這個長度不夠", "無配對", "太短的病歷號")
print("\n【測試二：姓名配對】")
test_voice_match("我推王小明去X光", "11B01", "王小明")
test_voice_match("幫陳美麗(志玲)送檢查", "207-02S", "陳美麗")
test_voice_match("林志玲準備好了", "無配對", "林志玲 (急診，應被忽略)")
print("\n【測試三：床號配對】")
test_voice_match("十一B洞一", "11B01", "11B01")
test_voice_match("七吸洞五", "7C05", "7C05")
test_voice_match("二大樓二洞七洞二S", "207-02S", "207-02S")
test_voice_match("急診洞五", "無配對", "ER05 (急診，應被忽略)")
test_voice_match("阿西西十", "RCC10", "RCC10")

print("==================================================")
