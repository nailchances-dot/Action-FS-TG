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
    print(f"🎬 === Google Play 巴西区监控诊断模式启动 ({datetime.now().strftime('%H:%M:%S')}) ===")
    
    token = get_tenant_token()
    if not token: 
        print("❌ 无法获取 token，请检查 APP_ID 和 SECRET")
        return
    headers = {"Authorization": f"Bearer {token}"}

    # 尝试读取 A 到 Z 列，覆盖可能的同步偏移
    data_url = f"{DOMAIN_GLOBAL}/open-apis/sheets/v2/spreadsheets/{SS_TOKEN}/values/{DATA_SHEET_ID}!A1:Z500"
    data_res = requests.get(data_url, headers=headers).json()
    rows = data_res.get("data", {}).get("valueRange", {}).get("values", [])

    if not rows:
        print("❌ 错误：读取不到数据，请检查 DATA_SHEET_ID 或权限。")
        return

    # ---------------------------------------------------------
    # 🔍 核心诊断逻辑：在控制台打印前 3 行的数据索引
    # ---------------------------------------------------------
    print("\n" + "="*40)
    print("🔍 表格列索引诊断 (请对照下方结果确认索引号)")
    print("="*40)
    for i, row in enumerate(rows[:3]):
        print(f"\n[第 {i+1} 行数据 - 共 {len(row)} 列]:")
        for idx, val in enumerate(row):
            # 简化显示内容
            display_val = val[0].get('text') if isinstance(val, list) and val and isinstance(val[0], dict) else val
            print(f"  索引 [{idx}] : {str(display_val)[:50]}")
    print("="*40 + "\n")

    # --- ！！！请根据上方诊断结果修改这里的数字 ！！！ ---
    # 如果同步了多维表，索引很可能变了。目前默认使用上次你反馈的 +1 位逻辑。
    NAME_IDX = 1    # App 名称所在列的索引
    STATUS_IDX = 6  # Online 状态所在列的索引
    LINK_IDX = 14   # 链接所在列的索引
    # --------------------------------------------------

    down_list = []
    abnormal_names = []
    online_count = 0

    print(f"开始扫描数据（从第 2 行起）...")
    for row_idx, row in enumerate(rows[1:]):
        if not row: continue
        # 补齐长度防止索引越界
        while len(row) <= max(NAME_IDX, STATUS_IDX, LINK_IDX): row.append(None)
        
        app_name = str(row[NAME_IDX] or "未命名")
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
    # 结果回写
    # ---------------------------------------------------------
    if down_list and TG_BOT_TOKEN:
        msg = f"🚨 <b>Google Play 下架报警</b>\n\n" + "\n\n".join(down_list)
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", 
                      data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"})

    duration = round(time.time() - start_time, 2)
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    summary = f"监控:{online_count} | 异常:{len(down_list)}"
    ab_str = ", ".join(abnormal_names) if abnormal_names else "无"

    log_url = f"{DOMAIN_GLOBAL}/open-apis/sheets/v2/spreadsheets/{SS_TOKEN}/values_prepend"
    log_payload = {
        "valueRange": {
            "range": f"{LOG_SHEET_ID}!A2:E2", 
            "values": [[now_str, "监控完成", summary, f"{duration}s", ab_str]]
        }
    }
    
    try:
        res = requests.post(log_url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}, json=log_payload, timeout=20)
        if res.json().get("code") == 0:
            print(f"✅ 日志已回写，异常App: {ab_str}")
    except:
        print("❌ 日志写入时发生错误")

    print(f"\n🏁 任务圆满结束。统计结果: {summary}")

if __name__ == "__main__":
    main()
