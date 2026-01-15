import requests
import os
import sys
import re
import time
from datetime import datetime, timedelta, timezone

# 强制输出即时显示
sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# 1. 核心配置
# ==========================================
SS_TOKEN = "X8vKsJvDfh4DQgt23m1cMPShn5f"
DATA_SHEET_ID = "df5ecd" # 大表
LOG_SHEET_ID = "u4ACeT"  # 日志统计表

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

DOMAIN_GLOBAL = "https://open.feishu.cn"

def get_tenant_token():
    url = f"{DOMAIN_GLOBAL}/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        return res.get("tenant_access_token")
    except: return None

def parse_feishu_link(cell_data):
    if isinstance(cell_data, list) and len(cell_data) > 0:
        item = cell_data[0]
        if isinstance(item, dict) and 'link' in item:
            return item['link']
    return str(cell_data) if cell_data else ""

def check_google_play(raw_link):
    link = parse_feishu_link(raw_link)
    if not link or "id=" not in link: return True, "跳过"
    try:
        package_id = re.search(r"id=([a-zA-Z0-9._]+)", link).group(1)
        url = f"https://play.google.com/store/apps/details?id={package_id}&hl=pt&gl=BR"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        res = requests.get(url, headers=headers, timeout=25)
        if res.status_code == 404: return False, "404"
        content = res.text.lower()
        if 'itemprop="name"' in content and ("instalar" in content or "install" in content):
            return True, "online"
        return False, "下架"
    except: return False, "异常"

def main():
    start_time = time.time()
    print(f"🎬 === Google Play 巴西区监控启动 ({datetime.now().strftime('%H:%M:%S')}) ===")
    
    token = get_tenant_token()
    if not token: return
    headers = {"Authorization": f"Bearer {token}"}

    # 【诊断步骤】尝试读取更大范围的数据 (A到Z列)
    data_url = f"{DOMAIN_GLOBAL}/open-apis/sheets/v2/spreadsheets/{SS_TOKEN}/values/{DATA_SHEET_ID}!A1:Z10"
    data_res = requests.get(data_url, headers=headers).json()
    rows = data_res.get("data", {}).get("valueRange", {}).get("values", [])

    if not rows:
        print("❌ 错误：读取不到数据，请检查 DATA_SHEET_ID 是否正确。")
        return

    # ---------------------------------------------------------
    # 🔍 自动化诊断逻辑：打印前 3 行的数据结构
    # ---------------------------------------------------------
    print("\n--- 📝 表格结构诊断开始 ---")
    for i, row in enumerate(rows[:3]):
        print(f"第 {i+1} 行原始数据 (共 {len(row)} 列):")
        for idx, val in enumerate(row):
            # 处理可能的富文本链接显示
            display_val = val[0].get('text') if isinstance(val, list) and val and isinstance(val[0], dict) else val
            print(f"  索引 [{idx}] : {display_val}")
    print("--- 📝 表格结构诊断结束 ---\n")

    # 根据诊断结果，我们需要在这里手动确认索引
    # 目前先根据你的描述尝试 +1 位的逻辑 (即索引 1, 6, 14)
    NAME_IDX = 1
    STATUS_IDX = 6
    LINK_IDX = 14

    down_list = []
    abnormal_names = []
    online_count = 0

    # 正式开始从第二行检查
    for row_idx, row in enumerate(rows[1:]):
        # 补齐长度防止溢出
        while len(row) <= max(NAME_IDX, STATUS_IDX, LINK_IDX): row.append(None)
        
        app_name = row[NAME_IDX] or "未命名"
        status = str(row[STATUS_IDX] or "").strip().lower()
        raw_link = row[LINK_IDX]

        if status == "online":
            online_count += 1
            print(f"🔍 [{online_count}] 检查: {app_name}...")
            time.sleep(1.2)
            is_live, desc = check_google_play(raw_link)
            if not is_live:
                abnormal_names.append(app_name)
                down_list.append(f"• {app_name} ({desc})\n链接: {parse_feishu_link(raw_link)}")

    # ---------------------------------------------------------
    # 写入结果
    # ---------------------------------------------------------
    if down_list and TG_BOT_TOKEN:
        msg = f"🚨 <b>Google Play 下架报警</b>\n\n" + "\n\n".join(down_list)
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", 
                      data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"})

    duration = round(time.time() - start_time, 2)
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    summary = f"监控:{online_count} | 异常:{len(down_list)}"
    ab_str = ", ".join(abnormal_names) if abnormal_names else "
