import os
import json
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import redis


# ============================================================
# Configuration
# ============================================================

CWA_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001"

TARGET_AREAS = [
    "桃園市",
    "臺灣北部海面",
    "臺灣東北部海面",
    "臺灣海峽北部",
]

TARGET_HEADLINES = [
    "海上颱風警報",
    "海上陸上颱風警報",
    "解除颱風警報",
]

REDIS_KEY = "weather:typhoon:taoyuan"

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


# ============================================================
# Environment
# ============================================================

CWA_API_KEY = os.environ.get("CWA_API_KEY")
REDIS_URL = os.environ.get("REDIS_URL")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def require_environment():
    missing = []

    if not CWA_API_KEY:
        missing.append("CWA_API_KEY")

    if not REDIS_URL:
        missing.append("REDIS_URL")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# Time
# ============================================================

def format_time(value):
    if not value:
        return "未提供"

    try:
        # 支援 Z
        normalized = value.replace("Z", "+00:00")

        dt = datetime.fromisoformat(normalized)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dt = dt.astimezone(TAIPEI_TZ)

        return dt.strftime("%Y/%m/%d %H:%M")

    except Exception:
        return value


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# CWA API
# ============================================================

def fetch_cwa_data():
    headers = {
        "Authorization": CWA_API_KEY,
        "Accept": "application/json",
    }

    params = {
        "format": "JSON",
        "areaDesc": ",".join(TARGET_AREAS),
        "headline": ",".join(TARGET_HEADLINES),
    }

    response = requests.get(
        CWA_API_URL,
        headers=headers,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# CWA Normalization
# ============================================================

def is_target_area(info):
    areas = info.get("area", [])

    if not isinstance(areas, list):
        return False

    for area in areas:
        area_name = str(area.get("areaDesc", ""))

        if any(target in area_name for target in TARGET_AREAS):
            return True

    return False


def normalize_alert(info):
    areas = info.get("area", [])

    if not isinstance(areas, list):
        areas = []

    area_desc = "、".join(
        str(area.get("areaDesc"))
        for area in areas
        if area.get("areaDesc")
    )

    headline = info.get("headline") or "未提供"

    return {
        "event": info.get("event") or "颱風",
        "headline": headline,
        "description": info.get("description") or "未提供",
        "sender": info.get("senderName") or "中央氣象署",
        "web": info.get("web") or "",
        "areaDesc": area_desc,
        "effective": info.get("effective") or "",
        "onset": info.get("onset") or "",
        "expires": info.get("expires") or "",
        "status": (
            "resolved"
            if "解除" in headline
            else "active"
        ),
    }


def normalize_cwa_response(data):
    records = data.get("records", {})
    infos = records.get("info", [])

    if not isinstance(infos, list) or not infos:
        return {
            "valid": False,
            "reason": "沒有取得 CWA 颱風警報資料",
        }

    target_infos = [
        info
        for info in infos
        if isinstance(info, dict) and is_target_area(info)
    ]

    if not target_infos:
        return {
            "valid": False,
            "reason": "目前沒有符合桃園／北部海域條件的颱風警報",
        }

    alerts = [
        normalize_alert(info)
        for info in target_infos
    ]

    # 避免 API 回傳順序變化造成 fingerprint 改變
    alerts.sort(
        key=lambda x: (
            x.get("headline", ""),
            x.get("areaDesc", ""),
            x.get("effective", ""),
        )
    )

    fingerprint_source = json.dumps(
        alerts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    fingerprint = hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()

    has_active_alert = any(
        alert["status"] == "active"
        for alert in alerts
    )

    all_resolved = all(
        alert["status"] == "resolved"
        for alert in alerts
    )

    overall_status = (
        "resolved"
        if all_resolved
        else "active"
    )

    primary = alerts[0]

    message = build_message(primary)

    return {
        "valid": True,
        "status": overall_status,
        "hasActiveAlert": has_active_alert,
        "allResolved": all_resolved,
        "alertCount": len(alerts),
        "alerts": alerts,
        "fingerprint": fingerprint,
        "fingerprintSource": fingerprint_source,
        "message": message,
        "checkedAt": now_iso(),
    }


# ============================================================
# Telegram Message
# ============================================================

def build_message(alert):
    return "\n".join([
        "🌀 桃園颱風警報通知",
        "",
        f"📢 {alert.get('headline', '未提供')}",
        "",
        f"📍 地區：{alert.get('areaDesc', '未提供')}",
        f"🌪️ 事件：{alert.get('event', '颱風')}",
        "",
        "📝 說明：",
        alert.get("description", "未提供"),
        "",
        f"⏰ 開始時間：{format_time(alert.get('onset'))}",
        f"⏱️ 生效時間：{format_time(alert.get('effective'))}",
        f"🔚 結束時間：{format_time(alert.get('expires'))}",
        "",
        f"🏢 發布單位：{alert.get('sender', '中央氣象署')}",
        "",
        "🔗 中央氣象署詳細資訊：",
        alert.get("web") or "無",
    ])


# ============================================================
# Redis
# ============================================================

def get_redis():
    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=10,
    )


def get_previous_state(r):
    raw = r.get(REDIS_KEY)

    if not raw:
        return None

    try:
        return json.loads(raw)
    except Exception:
        print("WARNING: Redis state is invalid JSON")
        return None


# ============================================================
# State Comparison
# ============================================================

def compare_state(current, previous):
    has_previous_state = previous is not None

    if not previous:
        fingerprint_changed = True
        status_changed = True

        # 第一次執行：
        # active -> 通知
        # resolved -> 不通知
        should_notify = current["status"] == "active"

    else:
        fingerprint_changed = (
            previous.get("fingerprint")
            != current.get("fingerprint")
        )

        status_changed = (
            previous.get("status")
            != current.get("status")
        )

        should_notify = (
            fingerprint_changed
            or status_changed
        )

    return {
        "hasPreviousState": has_previous_state,
        "fingerprintChanged": fingerprint_changed,
        "statusChanged": status_changed,
        "shouldNotify": should_notify,
    }


def build_state(current, previous, should_notify):
    now = now_iso()

    return {
        "version": 1,
        "system": "桃園颱風警報狀態監控系統",
        "region": "桃園市",
        "monitoredAreas": TARGET_AREAS,
        "status": current["status"],
        "hasActiveAlert": current["hasActiveAlert"],
        "allResolved": current["allResolved"],
        "alertCount": current["alertCount"],
        "fingerprint": current["fingerprint"],
        "alerts": current["alerts"],
        "firstSeenAt": (
            previous.get("firstSeenAt")
            if previous
            else now
        ),
        "lastCheckedAt": now,
        "lastNotifiedAt": (
            now
            if should_notify
            else (
                previous.get("lastNotifiedAt")
                if previous
                else None
            )
        ),
    }


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API failed: {result}"
        )

    print("Telegram notification sent.")


# ============================================================
# Main
# ============================================================

def main():
    require_environment()

    print("=" * 60)
    print("桃園颱風警報狀態監控系統")
    print("=" * 60)

    print("Fetching CWA data...")

    data = fetch_cwa_data()

    current = normalize_cwa_response(data)

    if not current.get("valid"):
        print(
            "No matching typhoon alert:",
            current.get("reason"),
        )
        return

    print(
        f"Current status: {current['status']}"
    )

    print(
        f"Alert count: {current['alertCount']}"
    )

    print(
        f"Fingerprint: {current['fingerprint']}"
    )

    r = get_redis()

    try:
        previous = get_previous_state(r)

        comparison = compare_state(
            current,
            previous,
        )

        print(
            f"Previous state exists: "
            f"{comparison['hasPreviousState']}"
        )

        print(
            f"Fingerprint changed: "
            f"{comparison['fingerprintChanged']}"
        )

        print(
            f"Status changed: "
            f"{comparison['statusChanged']}"
        )

        print(
            f"Should notify: "
            f"{comparison['shouldNotify']}"
        )

        state = build_state(
            current,
            previous,
            comparison["shouldNotify"],
        )

        # 先通知，再保存狀態。
        #
        # 如果 Telegram 發送失敗：
        # raise exception
        # GitHub Actions 會顯示失敗，
        # Redis 不會被更新成「已通知」狀態。
        if comparison["shouldNotify"]:
            print("Sending Telegram notification...")
            send_telegram(current["message"])
        else:
            print("No notification required.")

        r.set(
            REDIS_KEY,
            json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

        print("Redis state saved.")
        print("Monitor completed successfully.")

    finally:
        try:
            r.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
