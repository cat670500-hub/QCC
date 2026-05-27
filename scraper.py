import time
import requests
from playwright.sync_api import sync_playwright

# Flask 系統的網址
FLASK_API_URL = "http://127.0.0.1:5000/api/update_patients"

def run_scraper():
    # 啟動 Playwright
    with sync_playwright() as p:
        # headless=False 會顯示瀏覽器視窗，方便您看它自動操作
        # 若未來不想看到視窗，可改為 headless=True
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("開始登入 TPRIS...")
        page.goto("https://tprisweb.shh.org.tw/#/login", wait_until="domcontentloaded")
        
        # 等待網頁載入
        page.wait_for_timeout(3000)
        
        # 填寫帳號與密碼 (使用 placeholder 或 type 進行定位)
        try:
            page.get_by_placeholder("帳號").fill("18507")
            page.get_by_placeholder("密碼").fill("18507")
            page.get_by_role("button", name="Log In").click()
        except Exception as e:
            print("找不到登入輸入框，請確認網頁結構或手動登入:", e)
        
        print("登入中，等待跳轉...")
        page.wait_for_timeout(10000)
        
        print("前往 CR 報到排程頁面...")
        page.goto("https://tprisweb.shh.org.tw/#/checkInCenter/check-in/schedule?Modality=CR&returnPath=checkin", wait_until="domcontentloaded")
        
        # 等待網頁載入資料
        page.wait_for_timeout(5000) 
        
        bed_cache = {} # 加入快取機制，避免重複點擊同一位病患的卡片
        exam_cache = {} # 新增檢查部位快取
        
        while True:
            try:
                print(f"[{time.strftime('%H:%M:%S')}] 正在確保頁面位於 Portable 分類並抓取最新資料...")
                
                # 每次抓取前，確保在「顯示檢查室」的分類中，「只有」 Portable 被勾選，其餘皆取消勾選
                try:
                    js_enforce_portable = """
                    () => {
                        let labels = Array.from(document.querySelectorAll('label'));
                        let portableLabel = labels.find(l => l.innerText.includes('Portable'));
                        if (portableLabel) {
                            // 尋找包裹這些按鈕的父容器 (通常是 group)
                            let parentGroup = portableLabel.closest('.el-checkbox-group, .el-radio-group, div[role="group"]') || portableLabel.parentElement;
                            if (parentGroup) {
                                let allLabels = parentGroup.querySelectorAll('label');
                                let changed = false;
                                allLabels.forEach(l => {
                                    let inp = l.querySelector('input');
                                    let isChecked = l.classList.contains('is-checked') || l.classList.contains('is-active') || (inp && inp.checked);
                                    let isPortable = l.innerText.includes('Portable');
                                    
                                    // 如果是 Portable 但沒勾，就點擊勾選
                                    if (isPortable && !isChecked) {
                                        l.click();
                                        changed = true;
                                    } 
                                    // 如果不是 Portable 但卻被勾了，就點擊取消勾選
                                    else if (!isPortable && isChecked) {
                                        l.click();
                                        changed = true;
                                    }
                                });
                                return changed;
                            }
                        }
                        return false;
                    }
                    """
                    changed = page.evaluate(js_enforce_portable)
                    if changed:
                        print("✅ 已強制重置檢查室：僅保留「Portable」選項！")
                        page.wait_for_timeout(2000) # 給網頁時間切換與重新讀取名單
                except Exception as e:
                    print(f"[警告] 強制檢查 Portable 篩選器狀態時發生錯誤: {e}")

                extracted_patients = []
                
                # 使用 JavaScript 尋找包含「櫃台報到」或「櫃檯報到」的卡片
                js_script = """
                () => {
                    let results = [];
                    // 1. 找出畫面上所有包含「櫃台報到」的最內層節點
                    let elements = Array.from(document.querySelectorAll('*'))
                        .filter(el => el.children.length === 0 && 
                                      (el.textContent.includes('櫃台報到') || el.textContent.includes('櫃檯報到')));
                        
                    for(let el of elements) {
                        let current = el.parentElement;
                        let cardText = "";
                        
                        // 2. 往上層容器找 (最多往上找 7 層)
                        for(let i=0; i<7; i++) {
                            if(current) {
                                let text = current.innerText || "";
                                let lines = text.split(/\\r?\\n/).map(t => t.trim()).filter(t => t.length > 0);
                                
                                // 3. 確保抓到「完整的卡片」：檢查文字中是否包含病歷號 (連續 6~10 位數字)
                                if(/\\d{6,10}/.test(text) && lines.length >= 2) {
                                    cardText = text;
                                    break; // 成功抓到這張完整卡片後，就停止往上找
                                }
                                current = current.parentElement;
                            }
                        }
                        
                        if(cardText) {
                            // 避免重複加入
                            if(!results.includes(cardText)) {
                                results.push(cardText);
                            }
                        }
                    }
                    return results;
                }
                """
                
                yellow_card_texts = page.evaluate(js_script)
                
                for card_text in yellow_card_texts:
                    lines = [line.strip() for line in card_text.splitlines() if line.strip()]
                    
                    if len(lines) >= 2:
                        name = "未知"
                        record_no = ""
                        exam = "Portable" # 預設值
                        bed = ""
                        
                        import re
                        # 將卡片文字中所有可能的符號(如 |, ｜, │) 換成空白，再拆分成單字陣列
                        clean_text = card_text.replace('|', ' ').replace('｜', ' ').replace('│', ' ')
                        words = clean_text.split()
                        
                        record_idx = -1
                        for idx, w in enumerate(words):
                            if re.fullmatch(r'\d{6,10}', w):
                                record_idx = idx
                                record_no = w
                                break
                                
                        if record_idx != -1:
                            # 姓名通常在病歷號的前面 (通常是第一個單字)
                            if record_idx > 0:
                                name = words[0]
                                
                            # 從病歷號後面的單字尋找病房 (從後面找回來最準確)
                            for w in reversed(words[record_idx+1:]):
                                w_upper = w.upper()
                                if "急診" in w_upper:
                                    bed = "急診"
                                    break
                                # 檢查是否為英數混合或是純數字的病房號碼 (排除中文與時間格式如 10:54)
                                if 3 <= len(w) <= 8 and any(c.isdigit() for c in w) and all(ord(c) < 128 for c in w) and ':' not in w:
                                    bed = w_upper
                                    break
                                    
                        if not record_no:
                            print(f"[忽略假卡片] 找不到病歷號: {card_text.replace(chr(10), ' ')}")
                            continue
                            
                        # 新增條件：急診CR不抓
                        if "急診CR" in card_text.replace(" ", "").upper():
                            print(f"[忽略急診CR] 此為急診CR非Portable，跳過病歷號: {record_no}")
                            continue
                        
                        extracted_patients.append({
                            "name": name,
                            "record_no": record_no,
                            "bed": bed,
                            "exam": exam
                        })
                
                # ------ 新增：點擊卡片擷取病房號碼與檢查部位 ------
                for patient in extracted_patients:
                    record_no = patient['record_no']
                    
                    # 如果卡片上已經直接抓到病房了，就更新快取
                    if patient['bed'] and record_no not in bed_cache:
                        bed_cache[record_no] = patient['bed']
                        print(f"-> 從卡片表面直接抓到病房 {patient['name']} ({record_no}): {patient['bed']}")
                    
                    # 使用快取機制讀取
                    if not patient['bed'] and record_no in bed_cache:
                        patient['bed'] = bed_cache[record_no]
                        print(f"-> 沿用快取病房 {patient['name']} ({record_no}): {patient['bed']}")
                        
                    if record_no in exam_cache:
                        patient['exam'] = exam_cache[record_no]
                        print(f"-> 沿用快取檢查部位 {patient['name']} ({record_no}): {patient['exam']}")

                    # 如果病房和檢查部位(非預設值)都有了，就跳過點擊
                    if patient['bed'] and patient['exam'] != 'Portable':
                        continue

                    print(f"嘗試點擊病患 {patient['name']} ({record_no}) 的卡片...")
                    try:
                        current_url = page.url
                        card_element = page.get_by_text(record_no)
                        if card_element.count() > 0:
                            card_element.first.click()
                            page.wait_for_timeout(800) # 縮短等待時間 (從 1500 改為 800)
                            
                            body_text = page.locator("body").inner_text()
                            extract_text = body_text
                            
                            # 如果有彈出視窗(Modal)，優先從彈出視窗抓取以避免抓到背景的其他卡片
                            dialogs = page.locator("dialog, [role='dialog'], .modal, .el-dialog, .v-dialog, .modal-content")
                            for i in range(dialogs.count()):
                                if dialogs.nth(i).is_visible():
                                    extract_text = dialogs.nth(i).inner_text()
                                    break
                                    
                            # --- 抓取檢查部位 ---
                            lines = [line.strip() for line in extract_text.splitlines() if line.strip()]
                            exam_item = ""
                            for i, line in enumerate(lines):
                                if "檢查部位" in line or "檢查項目" in line:
                                    for j in range(i+1, min(i+4, len(lines))):
                                        candidate = lines[j]
                                        if candidate.isdigit() or "註記" in candidate:
                                            continue
                                        exam_item = candidate
                                        break
                                    break
                            
                            if exam_item:
                                patient['exam'] = exam_item
                                exam_cache[record_no] = exam_item
                                print(f"-> 成功抓取檢查部位: {exam_item}")
                            # -------------------
                            
                            # 如果外層卡片沒抓到病房，才從內頁尋找
                            if not patient['bed']:
                                bed_no = ""
                                # 內頁的左上角同樣會顯示「病歷號 | 科別 | 狀態 | 床號」，我們用相同的邏輯來抓取
                                for line in lines[:10]: # 只找前幾行
                                    if ('|' in line or '｜' in line or '│' in line) and str(record_no) in line:
                                        import re
                                        clean_line = line.replace('|', ' ').replace('｜', ' ').replace('│', ' ')
                                        words = clean_line.split()
                                        r_idx = -1
                                        for idx, w in enumerate(words):
                                            if re.fullmatch(r'\d{6,10}', w):
                                                r_idx = idx
                                                break
                                        if r_idx != -1:
                                            for w in reversed(words[r_idx+1:]):
                                                w_upper = w.upper()
                                                if "急診" in w_upper:
                                                    bed_no = "急診"
                                                    break
                                                if 3 <= len(w) <= 8 and any(c.isdigit() for c in w) and all(ord(c) < 128 for c in w) and ':' not in w:
                                                    bed_no = w_upper
                                                    break
                                        if bed_no:
                                            break
                                            
                                # 備用方案：如果還是找不到，再用原本的寬鬆正則與急診字眼
                                if not bed_no:
                                    if "急診" in extract_text:
                                        bed_no = "急診"
                                    else:
                                        import re
                                        found_words = re.findall(r'\b[A-Za-z0-9-]{4,7}\b', extract_text)
                                        for w in found_words:
                                            if any(c.isdigit() for c in w) and w.upper() not in ["PORTABLE"]:
                                                bed_no = w.upper()
                                                break

                                if bed_no:
                                    patient['bed'] = bed_no
                                    bed_cache[record_no] = bed_no
                                    print(f"-> 成功從內頁抓取病房: {bed_no}")
                                else:
                                    patient['bed'] = "(無病房資料)"
                                    bed_cache[record_no] = "(無病房資料)"
                                    print("-> 畫面上找不到符合的病房號碼")
                                
                            # 關閉視窗或返回
                            if page.url != current_url:
                                page.go_back()
                                page.wait_for_timeout(1000)
                            else:
                                page.keyboard.press("Escape")
                                page.wait_for_timeout(300)
                                page.mouse.click(5, 5) # 點擊左上角安全區確保 Modal 關閉
                                page.wait_for_timeout(300)
                    except Exception as e:
                        print(f"擷取病房時發生錯誤: {e}")
                        patient['bed'] = "(擷取失敗)"
                # ----------------------------------------

                print(f"抓取完畢，共找到 {len(extracted_patients)} 筆病患。")
                
                # 將這批名單透過 POST 打給我們的 Flask 伺服器
                try:
                    response = requests.post(FLASK_API_URL, json=extracted_patients)
                    if response.status_code == 200:
                        print("成功同步最新名單至 Flask 系統！")
                except Exception as e:
                    print(f"無法連線到 Flask 系統 (請確定 app.py 有啟動): {e}")

            except Exception as e:
                print(f"抓取過程中發生錯誤: {e}")
            
            # 等待 10 秒後再次重新抓取 (加速更新頻率)
            print("等待 10 秒...\n" + "-"*30)
            time.sleep(10)
            
            # 移除了 page.reload()，依賴醫院系統自身的自動更新，或是讓爬蟲單純讀取畫面

if __name__ == "__main__":
    # 若執行時顯示找不到 playwright，請先在終端機執行：
    # pip install playwright requests
    # playwright install chromium
    run_scraper()
