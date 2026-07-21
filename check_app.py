import requests
import os
import sys
import re
import time
import random
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# 配置
# ==========================================
SS_TOKEN = "X8vKsJvDfh4DQgt23m1cMPShn5f"
DATA_SHEET_ID = "df5ecd"
LOG_SHEET_ID = "u4ACeT"

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

DOMAIN_GLOBAL = "https://open.feishu.cn"

# ==========================================
# Session（非常重要）
# ==========================================
session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache"
})

# ==========================================
# 飞书 Token
# ==========================================
def get_tenant_token():

    print("📡 获取 tenant_access_token...")

    url = f"{DOMAIN_GLOBAL}/open-apis/auth/v3/tenant_access_token/internal"

    try:

        res = requests.post(
            url,
            json={
                "app_id": APP_ID,
                "app_secret": APP_SECRET
            },
            timeout=15
        ).json()

        if res.get("code") == 0:
            return res.get("tenant_access_token")

        print(f"❌ 鉴权失败: {res}")

    except Exception as e:
        print(f"💥 鉴权异常: {e}")

    return None

# ==========================================
# 飞书链接解析
# ==========================================
def parse_feishu_link(cell_data):

    if isinstance(cell_data, list) and len(cell_data) > 0:

        item = cell_data[0]

        if isinstance(item, dict):
            return item.get("link", "")

    return str(cell_data) if cell_data else ""

# ==========================================
# 核心检测
# ==========================================
def check_google_play(raw_link):

    link = parse_feishu_link(raw_link)

    if not link or "id=" not in link:
        return True, "跳过"

    try:

        pkg_match = re.search(r"id=([a-zA-Z0-9._]+)", link)

        if not pkg_match:
            return False, "ID解析失败"

        package_id = pkg_match.group(1)

        url = (
            f"https://play.google.com/store/apps/details"
            f"?id={package_id}&hl=pt_BR&gl=BR"
        )

        res = session.get(
            url,
            timeout=30,
            allow_redirects=True
        )

        content = res.text.lower()

        # ==========================================
        # 1. Google 风控检测
        # ==========================================
        bot_keywords = [
            "detected unusual traffic",
            "our systems have detected",
            "sorry...",
            "captcha",
            "不是机器人",
            "unusual traffic"
        ]

        if any(k in content for k in bot_keywords):

            print(f"⚠️ Google 风控页: {package_id}")

            return True, "Google风控"

        # ==========================================
        # 2. 在线特征（核心）
        # ==========================================
        online_features = [

            'property="og:title"',
            'itemprop="name"',
            'apps no google play',
            'data-item-id='
        ]

        online_hit = sum(
            1 for f in online_features if f in content
        )

        # ==========================================
        # 页面诊断
        # ==========================================
        print(
            f"🧪 {package_id} | "
            f"status={res.status_code} | "
            f"online_features={online_hit} | "
            f"len={len(content)}"
        )

        # ==========================================
        # 在线判断
        # ==========================================
        if online_hit >= 2:
            return True, "online"

        # ==========================================
        # 明确404特征
        # ==========================================
        hard_error_keywords = [
            "url was not found",
            "item not found",
            "找不到",
            "not found"
        ]

        if any(k in content for k in hard_error_keywords):

            return False, (
                "Play页面404，请手动访问链接确认应用状态，"
                "如无法访问建议及时暂停广告"
            )

        # ==========================================
        # 页面长度异常
        # ==========================================
        if len(content) < 50000:

            print(
                f"⚠️ 页面长度异常 | "
                f"pkg={package_id} | "
                f"len={len(content)}"
            )

            return False, (
                "Play页面异常，请手动访问链接确认应用状态，"
                "如页面无法正常打开建议及时暂停广告"
            )

        # ==========================================
        # 默认认为在线
        # ==========================================
        return True, "疑似在线"

    except requests.Timeout:

        return True, "请求超时(忽略)"

    except Exception as e:

        return True, f"检测异常:{str(e)[:50]}"

# ==========================================
# 二次确认机制
# ==========================================
def double_check(raw_link):

    first_live, first_desc = check_google_play(raw_link)

    if first_live:
        return True, first_desc

    print("🔄 二次确认中...")

    time.sleep(5)

    second_live, second_desc = check_google_play(raw_link)

    if second_live:
        return True, "二次恢复"

    return False, second_desc

# ==========================================
# Telegram
# ==========================================
def send_telegram(msg):

    if not TG_BOT_TOKEN:
        return

    try:

        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TG_CHAT_ID,
                "text": msg,
                "parse_mode": "HTML"
            },
            timeout=20
        )

    except Exception as e:
        print(f"TG发送失败: {e}")

# ==========================================
# 主任务
# ==========================================
def main():

    start_time = time.time()

    print(
        f"\n🎬 ===== Google Play 巴西监控开始 ===== "
        f"{datetime.now().strftime('%H:%M:%S')}\n"
    )

    token = get_tenant_token()

    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    # ==========================================
    # 读取飞书
    # ==========================================
    data_url = (
        f"{DOMAIN_GLOBAL}/open-apis/sheets/v2/"
        f"spreadsheets/{SS_TOKEN}/values/"
        f"{DATA_SHEET_ID}!A2:N500"
    )

    data_res = requests.get(
        data_url,
        headers=headers,
        timeout=30
    ).json()

    rows = (
        data_res.get("data", {})
        .get("valueRange", {})
        .get("values", [])
    )

    if not rows:

        print("❌ 表格为空")

        return

    down_list = []
    abnormal_names = []

    online_count = 0

    # ==========================================
    # 遍历检测
    # ==========================================
    for row in rows:

        if not row:
            continue

        while len(row) < 14:
            row.append(None)

        app_name = row[0] or "未命名"
        project_name = row[1] or "未填写项目"
        status = str(row[5] or "").strip().lower()
        raw_link = row[13]

        if status != "online":
            continue

        online_count += 1

        print(f"\n🔍 检查: {app_name}")

        is_live, desc = double_check(raw_link)

        if not is_live:

            clean_link = parse_feishu_link(raw_link)

            abnormal_names.append(app_name)

            down_list.append(
                f"（{project_name}）• {app_name}\n"
                f"原因: {desc}\n"
                f"{clean_link}"
            )

        # 随机等待（防风控）
        time.sleep(random.uniform(2.0, 4.0))

    # ==========================================
    # Telegram报警
    # ==========================================
    if down_list:

        msg = (
            f"📢📢 <b>Google Play 状态提醒🚨</b>\n\n"
            + "\n\n".join(down_list)
        )

        send_telegram(msg)

    # ==========================================
    # 写日志
    # ==========================================
    duration = round(time.time() - start_time, 2)

    now_str = datetime.now(
        timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M:%S")

    summary = (
        f"监控:{online_count} | "
        f"异常:{len(down_list)}"
    )

    abnormal_str = (
        ", ".join(abnormal_names)
        if abnormal_names else "无"
    )

    log_url = (
        f"{DOMAIN_GLOBAL}/open-apis/sheets/v2/"
        f"spreadsheets/{SS_TOKEN}/values_prepend"
    )

    log_payload = {
        "valueRange": {
            "range": f"{LOG_SHEET_ID}!A2:E2",
            "values": [[
                now_str,
                "监控完成",
                summary,
                f"{duration}s",
                abnormal_str
            ]]
        }
    }

    try:

        log_res = requests.post(
            log_url,
            headers=headers,
            json=log_payload,
            timeout=20
        ).json()

        if log_res.get("code") == 0:
            print("\n✅ 日志写入成功")
        else:
            print(f"\n❌ 日志失败: {log_res}")

    except Exception as e:
        print(f"\n💥 日志异常: {e}")

    print(
        f"\n🏁 完成 | "
        f"监控:{online_count} | "
        f"异常:{len(down_list)} | "
        f"耗时:{duration}s\n"
    )

# ==========================================
# 启动
# ==========================================
if __name__ == "__main__":
    main()
