import requests
import os
import sys
import re
import time
from datetime import datetime, timedelta, timezone

# 强制输出立即显示
sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# 1. 核心配置
# ==========================================
SS_TOKEN = "X8vKsJvDfh4DQgt23m1cMPShn5f"
DATA_SHEET_ID = "df5ecd" # 大表
LOG_SHEET_ID = "u4ACeT"  # 日志表 (Sheet 2)

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# 统一使用全球网关
DOMAIN_GLOBAL = "https://open.feishu.cn"

# ==========================================
# 2. 鉴权：获取租户凭证
# ==========================================
def get_tenant_token():
    print(f"📡 正在获取企业自建应用凭证 (tenant_access_token)...")
    url = f"{DOMAIN_GLOBAL}/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    try:
        res = requests.post(url, json=payload, timeout=10).json()
        if res.get("code") == 0:
            return res.get("tenant_access_token")
        print(f"❌ 鉴权失败: {res.get('msg')}")
    except Exception as e:
        print(f"💥 鉴权接口异常: {e}")
    return None

def parse_feishu_link(cell_data):
    """提取飞书单元格中的纯链接字符串"""
    if isinstance(cell_data, list) and len(cell_data) > 0:
        item = cell_data[0]
        if isinstance(item, dict) and 'link' in item:
            return item['link']
    return str(cell_data) if cell_data else ""

# ==========================================
# 3. 核心检测逻辑 (针对巴西区优化)
# ==========================================
def check_google_play(raw_link):
    link = parse_feishu_link(raw_link)
    if not link or "id=" not in link: return True, "跳过"
    try:
        pkg_match = re.search(r"id=([a-zA-Z0-9._]+)", link)
        if not pkg_match: return False, "ID错误"
        package_id = pkg_match.group(1)
        
        test_url = f"https://play.google.com/store/apps/details?id={package_id}&hl=pt&gl=BR"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
        }
        res = requests.get(test_url, timeout=25, headers=headers, allow_redirects=True)
        if res.status_code == 404: return False, "404"
            
        content = res.text
        error_keywords = ["Não encontrado", "não foi encontrado", "URL was not found", "在此服务器上找不到"]
        for kw in error_keywords:
            if kw in content: return False, "下架报错"
        
        if 'itemprop="name"' in content or 'data-pwa-category="App"' in content:
            return True, "online"
        return False, "特征缺失"
    except:
        return False, "检测异常"

# ==========================================
# 4. 主任务
# ==========================================
def main():
    start_time = time.time()
    print(f"🎬 === Google Play 巴西区监控开始 ({datetime.now().strftime('%H:%M:%S')}) ===")
    
    token = get_tenant_token()
    if not token: return
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    # 读取大表
    data_url = f"{DOMAIN_GLOBAL}/open-apis/sheets/v2/spreadsheets/{SS_TOKEN}/values/{DATA_SHEET_ID}!A2:N500"
    data_res = requests.get(data_url, headers=headers).json()
    rows = data_res.get("data", {}).get("valueRange", {}).get("values", [])

    if not rows: return

    down_list = []
    abnormal_app_names = [] # 记录下架的 App 名字
    online_count = 0
    
    for row in rows:
        if not row: continue
        while len(row) < 14: row.append(None)
        
        app_name, status, raw_link = row[0] or "未命名", row[5] or "", row[13]

        if isinstance(status, str) and status.strip().lower() == "online":
            online_count += 1
            print(f"🔍 检查: {app_name}...")
            time.sleep(1.5)
            
            is_live, desc = check_google_play(raw_link)
            if not is_live:
                clean_link = parse_feishu_link(raw_link)
                abnormal_app_names.append(app_name) # 收集名字用于 E 列
                down_list.append(f"• {app_name} (原因: {desc})\n链接: {clean_link}")

    # 1. Telegram 报警
    if down_list and TG_BOT_TOKEN:
        msg = f"🚨 <b>Google Play 下架报警</b>\n\n" + "\n\n".join(down_list)
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", 
                      data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"})

    # 2. 倒序插入日志 (对齐官方 values_prepend 文档)
    duration = round(time.time() - start_time, 2)
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    summary = f"监控:{online_count} | 异常:{len(down_list)}"
    abnormal_names_str = ", ".join(abnormal_app_names) if abnormal_app_names else "无"

    # [核心修改] 使用文档要求的 values_prepend 路径
    log_url = f"{DOMAIN_GLOBAL}/open-apis/sheets/v2/spreadsheets/{SS_TOKEN}/values_prepend"
    
    # 设定范围为 A2:E2。该接口会在 A2 上方“插入”新行，实现倒序排列。
    log_payload = {
        "valueRange": {
            "range": f"{LOG_SHEET_ID}!A2:E2", 
            "values": [
                [now_str, "监控完成", summary, f"{duration}s", abnormal_names_str]
            ]
        }
    }
    
    print(f"📝 正在通过 values_prepend 倒序插入日志到 {LOG_SHEET_ID}...")
    try:
        response = requests.post(log_url, headers=headers, json=log_payload, timeout=20)
        log_res = response.json()
        if log_res.get("code") == 0:
            print(f"✅ 日志已成功插入标题下方第一行。异常名单: {abnormal_names_str}")
        else:
            print(f"❌ 写入失败: {log_res.get('msg')}")
    except Exception as e:
        print(f"💥 写入崩溃: {e}")

    print(f"🏁 任务圆满结束。")

if __name__ == "__main__":
    main()
