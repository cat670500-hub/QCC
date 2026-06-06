log_path = r'C:\Users\user\.gemini\antigravity-ide\brain\7f176787-647d-4932-b612-4693633212d3\.system_generated\tasks\task-742.log'

keywords = [
    '手動報到',
    '轉發報到',
    '註冊',
    'agent_check_in_result',
    '收到代理端',
    '錯誤日誌'
]

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, 1):
        line_str = line.strip()
        # Check if line contains a client request from outside localhost
        is_external = False
        if '127.0.0.1' not in line_str and (' - - [' in line_str or '[系統] 新客戶端建立' in line_str or '[系統] 客戶端中斷' in line_str):
            is_external = True
            
        # Check if any keyword matches
        has_keyword = any(kw in line_str for kw in keywords)
        
        if is_external or has_keyword:
            print(f"{i}: {line_str}")
