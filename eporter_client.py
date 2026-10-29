import re
import requests
import urllib3
urllib3.disable_warnings()

STATUS_MAP = {
    'U1.gif': '未分派',
    'U2.gif': '已分派',
    'U3.gif': '執行中',
    'U4.gif': '已完成',
    'U5.gif': '已取消',
    'nursecancel.png': '護理取消'
}

class EPorterClient:
    def __init__(self, base_url="http://10.125.254.151/SHHePorterNursing", username="18507", password="18507"):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.logged_in = False

    def login(self):
        login_url = f"{self.base_url}/login.aspx"
        try:
            r = self.session.get(login_url, timeout=5)
            viewstate = re.search(r'name="__VIEWSTATE" id="__VIEWSTATE" value="([^"]+)"', r.text).group(1)
            viewstate_gen = re.search(r'name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="([^"]+)"', r.text).group(1)
            event_val = re.search(r'name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="([^"]+)"', r.text).group(1)

            login_data = {
                '__VIEWSTATE': viewstate,
                '__VIEWSTATEGENERATOR': viewstate_gen,
                '__EVENTVALIDATION': event_val,
                'txtUserName': self.username,
                'txtPassword': self.password,
                'btnLogin': '登入'
            }
            r_post = self.session.post(login_url, data=login_data, timeout=5)
            self.logged_in = True
            return True
        except Exception as e:
            print(f"[ePorter] 登入失敗: {e}")
            self.logged_in = False
            return False

    def get_all_eporter_tasks(self):
        """抓取今日所有 ePorter 任務，並識別『急照X-ray送單』與『執行中』等狀態"""
        if not self.logged_in:
            if not self.login():
                return []

        import datetime
        start_date = datetime.datetime(1899, 12, 30)
        today = datetime.datetime.now()
        today_serial = (today - start_date).days
        tomorrow_serial = today_serial + 1

        display_url = (
            f"{self.base_url}/frmDisplayItem.aspx?"
            f"dblSDdate={today_serial}&dblEDdate={tomorrow_serial}&straspLocation=&straspJob="
            "&strbutAction=true&straspFromLocation=&straspToLocation="
            "&straspNRIC=&straspName=&straspFromTime=0000&straspToTime=2359&stremergency="
        )
        try:
            r = self.session.get(display_url, timeout=10)
            if "login.aspx" in r.url:
                if self.login():
                    r = self.session.get(display_url, timeout=10)
                else:
                    return []

            rows = re.findall(r'<tr[^>]*>.*?</tr>', r.text, re.DOTALL | re.IGNORECASE)
            tasks = []
            for row in rows:
                m_img = re.search(r'src="Images/([^"]+)"', row)
                if not m_img:
                    continue
                img_name = m_img.group(1)
                status_text = STATUS_MAP.get(img_name, img_name)
                
                m_id = re.search(r"openDetailPage\('(\d+)',\s*(\d+)\)", row)
                task_id = m_id.group(1) if m_id else ""
                
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
                cleaned = [re.sub(r'<[^>]+>', ' ', c).strip() for c in cells]
                cleaned = [re.sub(r'\s+', ' ', c) for c in cleaned]
                
                time_str = cleaned[1] if len(cleaned) > 1 else ""
                from_loc = cleaned[2] if len(cleaned) > 2 else ""
                to_loc = cleaned[3] if len(cleaned) > 3 else ""
                task_name = cleaned[4] if len(cleaned) > 4 else ""
                chart_no = cleaned[5].strip() if len(cleaned) > 5 else ""
                patient_name = cleaned[6].strip() if len(cleaned) > 6 else ""
                bed_no = cleaned[7].strip() if len(cleaned) > 7 else ""
                submitter = cleaned[8].strip() if len(cleaned) > 8 else ""
                
                task_lower = task_name.lower()
                is_xray_urgent = (
                    ("急照" in task_name and ("x-ray" in task_lower or "x光" in task_lower or "送單" in task_name))
                    or ("急照x-ray" in task_lower)
                    or ("急照" in task_name)
                    or ("急診x光" in to_loc and ("x-ray" in task_lower or "送單" in task_name or "急照" in task_name))
                )
                is_running = (img_name == 'U3.gif')

                tasks.append({
                    'task_id': task_id,
                    'status': status_text,
                    'icon': img_name,
                    'time': time_str,
                    'from_loc': from_loc,
                    'to_loc': to_loc,
                    'task_name': task_name,
                    'chart_no': chart_no,
                    'patient_name': patient_name,
                    'bed_no': bed_no,
                    'submitter': submitter,
                    'is_xray_urgent': is_xray_urgent,
                    'is_running': is_running
                })
            return tasks
        except Exception as e:
            print(f"[ePorter] 抓取任務異常: {e}")
            return []

    def get_running_tasks(self):
        """相容舊方法：僅取得執行中任務"""
        tasks = self.get_all_eporter_tasks()
        return [t for t in tasks if t['is_running']]

if __name__ == "__main__":
    client = EPorterClient()
    tasks = client.get_all_eporter_tasks()
    xray = [t for t in tasks if t['is_xray_urgent']]
    print(f"總任務數: {len(tasks)}, 急照X-ray送單任務數: {len(xray)}")
    for t in xray:
        print(f"[{t['status']}] {t['task_id']} | {t['chart_no']} {t['patient_name']} ({t['bed_no']}) | {t['from_loc']} -> {t['to_loc']}")
