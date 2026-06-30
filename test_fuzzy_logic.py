# -*- coding: utf-8 -*-
import sys
import difflib
from app import parse_voice_to_bed

active_beds = {
    '6a01': 'Patient 6A01',
    '7b05': 'Patient 7B05',
    '8c12': 'Patient 8C12',
    '9a08': 'Patient 9A08',
    '10b02': 'Patient 10B02',
    '11c05': 'Patient 11C05',
    '0705s': 'Patient 207-05S',
    '0810': 'Patient 208-10',
    '1002': 'Patient 210-02',
    '1705s': 'Patient 217-05S',
    '1801': 'Patient 218-01',
    '1912s': 'Patient 219-12S',
}

tests = [
    '六A洞么',
    '七逼洞五',
    '八吸么兩',
    '九A洞八',
    '十逼洞兩',
    '十一西洞五',
    '二大樓二洞七洞五S',
    '二洞八么洞',
    '二一洞洞兩',
    '二大樓二一七洞五S',
    '二一八洞么',
    '二大樓二一九么兩S',
]

print('\n=== Levenshtein Fuzzy Match Test (6F-11F & 2nd Building) ===')
for t in tests:
    parsed = parse_voice_to_bed(t).lower()
    exact_match = None
    fuzzy_match = None
    
    for bed in active_beds:
        if bed in parsed:
            exact_match = bed
            break
            
    if not exact_match:
        matches = difflib.get_close_matches(parsed, active_beds.keys(), n=1, cutoff=0.75)
        if matches:
            fuzzy_match = matches[0]
            
    print(f'Input: {t:<15} => Parsed: {parsed:<7} | ', end='')
    if exact_match:
        print(f'[EXACT MATCH] {active_beds[exact_match]} ({exact_match})')
    elif fuzzy_match:
        print(f'[FUZZY MATCH] {active_beds[fuzzy_match]} ({fuzzy_match})')
    else:
        print('[FAILED]')
print('================================================================')
