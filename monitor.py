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

CWA_API_URL = (
    "https://opendata.cwa.gov.tw/"
    "api/v1/rest/datastore/W-C0034-001"
)

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
# Environment Variables
# ============================================================

CWA_API_KEY = os.environ.get("CWA_API_KEY")
REDIS_URL = os.environ.get("REDIS_URL")

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID"
)


# ============================================================
# Utility
# ============================================================

def value_to_string(value, default=""):
    """
    將 CWA API 回傳的各種資料型別安全轉換成字串。

    支援：
    - None
    - str
    - int / float / bool
    - dict
    - list

    CWA API 某些欄位可能不是單純 string，
    例如 web 可能回傳 dict，因此不能直接交給
    "\\n".join()。
    """

    if value is None:
        return default

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, dict):
        # 常見結構
        for key in (
            "value",
            "url",
            "href",
            "text",
        ):
            if key in value and value[key] is not None:
                return value_to_string(
                    value[key],
                    default,
                )

        # 找不到明確欄位時，轉成 JSON
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except Exception:
            return str(value)

    if isinstance(value, list):
        converted = [
            value_to_string(item)
            for item in value
        ]

        converted = [
            item for item in converted if item
        ]

        return "、".join(converted)

    return str(value)


def now_iso():
    """
    回傳 UTC ISO 8601 時間。
    """

    return datetime.now(
        timezone.utc
    ).isoformat()


def format_time(value):
    """
    將 CWA 時間轉成 Asia/Taipei。
    """

    if not value:
        return "未提供"

    # 防止 value 是 dict
    value = value_to_string(value)

    if not value:
        return "未提供"

    try:
        normalized = value.replace(
            "Z",
            "+00:00",
        )

        dt = datetime.fromisoformat(
            normalized
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        dt = dt.astimezone(
            TAIPEI_TZ
        )

        return dt.strftime(
            "%Y/%m/%d %H:%M"
        )

    except Exception:
        return value


# ============================================================
# Environment Validation
# ============================================================

def require_environment():
    """
    確認 GitHub Secrets 是否完整。
    """

    missing = []

    if not CWA_API_KEY:
        missing.append(
            "CWA_API_KEY"
        )

    if not REDIS_URL:
        missing.append(
            "REDIS_URL"
        )

    if not TELEGRAM_BOT_TOKEN:
        missing.append(
            "TELEGRAM_BOT_TOKEN"
        )

    if not TELEGRAM_CHAT_ID:
        missing.append(
            "TELEGRAM_CHAT_ID"
        )

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# CWA API
# ============================================================

def fetch_cwa_data():
    """
    從中央氣象署取得颱風警報資料。
    """

    headers = {
        "Authorization": CWA_API_KEY,
        "Accept": "application/json",
    }

    params = {
        "format": "JSON",
        "areaDesc": ",".join(
            TARGET_AREAS
        ),
        "headline": ",".join(
            TARGET_HEADLINES
        ),
    }

    print("Requesting CWA API...")

    response = requests.get(
        CWA_API_URL,
        headers=headers,
        params=params,
        timeout=30,
    )

    print(
        f"CWA HTTP status: "
        f"{response.status_code}"
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            "CWA API response is not a JSON object"
        )

    return data


# ============================================================
# CWA Area Filtering
# ============================================================

def is_target_area(info):
    """
    判斷警報是否包含監控區域。
    """

    if not isinstance(info, dict):
        return False

    areas = info.get("area", [])

    if not isinstance(areas, list):
        return False

    for area in areas:

        if not isinstance(area, dict):
            continue

        area_name = value_to_string(
            area.get("areaDesc")
        )

        if any(
            target in area_name
            for target in TARGET_AREAS
        ):
            return True

    return False


# ============================================================
# Normalize Single Alert
# ============================================================

def normalize_alert(info):
    """
    將單筆 CWA 警報資料標準化。
    """

    if not isinstance(info, dict):
        raise ValueError(
            "Invalid CWA alert object"
        )

    areas = info.get(
        "area",
        []
    )

    if not isinstance(areas, list):
        areas = []

    area_names = []

    for area in areas:

        if not isinstance(area, dict):
            continue

        area_name = value_to_string(
            area.get("areaDesc")
        )

        if area_name:
            area_names.append(
                area_name
            )

    area_desc = "、".join(
        area_names
    )

    headline = value_to_string(
        info.get("headline"),
        "未提供",
    )

    description = value_to_string(
        info.get("description"),
        "未提供",
    )

    event = value_to_string(
        info.get("event"),
        "颱風",
    )

    sender = value_to_string(
        info.get("senderName"),
        "中央氣象署",
    )

    web = value_to_string(
        info.get("web"),
        "",
    )

    effective = value_to_string(
        info.get("effective"),
        "",
    )

    onset = value_to_string(
        info.get("onset"),
        "",
    )

    expires = value_to_string(
        info.get("expires"),
        "",
    )

    status = (
        "resolved"
        if "解除" in headline
        else "active"
    )

    return {
        "event": event,
        "headline": headline,
        "description": description,
        "sender": sender,
        "web": web,
        "areaDesc": area_desc,
        "effective": effective,
        "onset": onset,
        "expires": expires,
        "status": status,
    }


# ============================================================
# Telegram Message
# ============================================================

def build_message(alert):
    """
    建立 Telegram 通知內容。

    所有欄位再次經過 value_to_string，
    確保 join() 不會收到 dict / list。
    """

    headline = value_to_string(
        alert.get("headline"),
        "未提供",
    )

    area_desc = value_to_string(
        alert.get("areaDesc"),
        "未提供",
    )

    event = value_to_string(
        alert.get("event"),
        "颱風",
    )

    description = value_to_string(
        alert.get("description"),
        "未提供",
    )

    sender = value_to_string(
        alert.get("sender"),
        "中央氣象署",
    )

    web = value_to_string(
        alert.get("web"),
        "無",
    )

    onset = alert.get("onset")
    effective = alert.get("effective")
    expires = alert.get("expires")

    lines = [
        "🌀 桃園颱風警報通知",
        "",
        f"📢 {headline}",
        "",
        f"📍 地區：{area_desc}",
        f"🌪️ 事件：{event}",
        "",
        "📝 說明：",
        description,
        "",
        f"⏰ 開始時間：{format_time(onset)}",
        f"⏱️ 生效時間：{format_time(effective)}",
        f"🔚 結束時間：{format_time(expires)}",
        "",
        f"🏢 發布單位：{sender}",
        "",
        "🔗 中央氣象署詳細資訊：",
        web,
    ]

    # 最後保險：
    # 確保 lines 裡全部都是 str
    lines = [
        value_to_string(
            line,
            "",
        )
        for line in lines
    ]

    return "\n".join(lines)


# ============================================================
# Normalize CWA Response
# ============================================================

def normalize_cwa_response(data):
    """
    將 CWA API 完整 response 標準化。
    """

    if not isinstance(data, dict):
        return {
            "valid": False,
            "reason": "CWA API response 格式錯誤",
        }

    records = data.get(
        "records",
        {},
    )

    if not isinstance(records, dict):
        return {
            "valid": False,
            "reason": "CWA API records 格式錯誤",
        }

    infos = records.get(
        "info",
        [],
    )

    if not isinstance(infos, list):
        return {
            "valid": False,
            "reason": "CWA API info 格式錯誤",
        }

    if len(infos) == 0:
        return {
            "valid": False,
            "reason": "沒有取得 CWA 颱風警報資料",
        }

    target_infos = []

    for info in infos:

        if not isinstance(info, dict):
            continue

        if is_target_area(info):
            target_infos.append(info)

    if len(target_infos) == 0:
        return {
            "valid": False,
            "reason": (
                "目前沒有符合桃園／北部海域"
                "條件的颱風警報"
            ),
        }

    alerts = []

    for info in target_infos:

        try:
            alert = normalize_alert(info)
            alerts.append(alert)

        except Exception as error:
            print(
                "WARNING: Failed to normalize alert:",
                repr(error),
            )

    if len(alerts) == 0:
        return {
            "valid": False,
            "reason": "無法解析 CWA 警報資料",
        }

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    alerts.sort(
        key=lambda alert: (
            value_to_string(
                alert.get("headline")
            ),
            value_to_string(
                alert.get("areaDesc")
            ),
            value_to_string(
                alert.get("effective")
            ),
            value_to_string(
                alert.get("event")
            ),
        )
    )

    # --------------------------------------------------------
    # Fingerprint
    # --------------------------------------------------------

    fingerprint_source = json.dumps(
        alerts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    fingerprint = hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    has_active_alert = any(
        alert.get("status") == "active"
        for alert in alerts
    )

    all_resolved = all(
        alert.get("status") == "resolved"
        for alert in alerts
    )

    overall_status = (
        "resolved"
        if all_resolved
        else "active"
    )

    primary = alerts[0]

    message = build_message(
        primary
    )

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
# Redis
# ============================================================

def get_redis():
    """
    建立 Redis connection。
    """

    return redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=10,
    )


def get_previous_state(r):
    """
    從 Redis 取得上一個狀態。
    """

    print(
        f"Reading Redis key: "
        f"{REDIS_KEY}"
    )

    raw = r.get(
        REDIS_KEY
    )

    if not raw:
        print(
            "No previous Redis state."
        )

        return None

    try:

        previous = json.loads(
            raw
        )

        if not isinstance(
            previous,
            dict,
        ):
            print(
                "WARNING: Redis state "
                "is not an object."
            )

            return None

        return previous

    except json.JSONDecodeError as error:

        print(
            "WARNING: Redis state "
            f"is invalid JSON: {error}"
        )

        return None


# ============================================================
# Compare State
# ============================================================

def compare_state(
    current,
    previous,
):
    """
    比較目前警報與 Redis 上一次狀態。
    """

    has_previous_state = (
        previous is not None
    )

    if not previous:

        fingerprint_changed = True
        status_changed = True

        # 第一次執行：
        #
        # active
        #   -> 發送通知
        #
        # resolved
        #   -> 不發送解除通知
        should_notify = (
            current["status"]
            == "active"
        )

    else:

        previous_fingerprint = (
            previous.get(
                "fingerprint"
            )
        )

        current_fingerprint = (
            current.get(
                "fingerprint"
            )
        )

        previous_status = (
            previous.get(
                "status"
            )
        )

        current_status = (
            current.get(
                "status"
            )
        )

        fingerprint_changed = (
            previous_fingerprint
            != current_fingerprint
        )

        status_changed = (
            previous_status
            != current_status
        )

        should_notify = (
            fingerprint_changed
            or status_changed
        )

    return {
        "hasPreviousState": (
            has_previous_state
        ),
        "fingerprintChanged": (
            fingerprint_changed
        ),
        "statusChanged": (
            status_changed
        ),
        "shouldNotify": (
            should_notify
        ),
    }


# ============================================================
# Build Redis State
# ============================================================

def build_state(
    current,
    previous,
    should_notify,
):
    """
    建立要儲存在 Redis 的狀態。
    """

    now = now_iso()

    previous_first_seen = None
    previous_last_notified = None

    if previous:

        previous_first_seen = (
            previous.get(
                "firstSeenAt"
            )
        )

        previous_last_notified = (
            previous.get(
                "lastNotifiedAt"
            )
        )

    state = {
        "version": 1,

        "system": (
            "桃園颱風警報"
            "狀態監控系統"
        ),

        "region": "桃園市",

        "monitoredAreas": (
            TARGET_AREAS
        ),

        "status": current[
            "status"
        ],

        "hasActiveAlert": current[
            "hasActiveAlert"
        ],

        "allResolved": current[
            "allResolved"
        ],

        "alertCount": current[
            "alertCount"
        ],

        "fingerprint": current[
            "fingerprint"
        ],

        "alerts": current[
            "alerts"
        ],

        "firstSeenAt": (
            previous_first_seen
            or now
        ),

        "lastCheckedAt": now,

        "lastNotifiedAt": (
            now
            if should_notify
            else previous_last_notified
        ),
    }

    return state


def save_state(
    r,
    state,
):
    """
    將最新狀態寫入 Redis。
    """

    serialized = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    r.set(
        REDIS_KEY,
        serialized,
    )

    print(
        f"Redis state saved: "
        f"{REDIS_KEY}"
    )


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):
    """
    發送 Telegram 訊息。
    """

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    print(
        "Sending Telegram notification..."
    )

    response = requests.post(
        url,
        json=payload,
        timeout=30,
    )

    print(
        f"Telegram HTTP status: "
        f"{response.status_code}"
    )

    response.raise_for_status()

    try:
        result = response.json()
    except Exception as error:
        raise RuntimeError(
            "Telegram response is not JSON"
        ) from error

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram API failed: "
            + json.dumps(
                result,
                ensure_ascii=False,
            )
        )

    print(
        "Telegram notification sent."
    )


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 60)
    print(
        "桃園颱風警報狀態監控系統"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # Validate environment
    # --------------------------------------------------------

    require_environment()

    print(
        "Environment variables: OK"
    )

    # --------------------------------------------------------
    # CWA
    # --------------------------------------------------------

    print(
        "Fetching CWA data..."
    )

    data = fetch_cwa_data()

    print(
        "CWA data received."
    )

    # --------------------------------------------------------
    # Normalize
    # --------------------------------------------------------

    current = normalize_cwa_response(
        data
    )

    if not current.get("valid"):

        print(
            "No matching typhoon alert:"
        )

        print(
            current.get(
                "reason",
                "Unknown",
            )
        )

        # 沒有符合監控條件的資料，
        # 不修改 Redis 狀態。
        return

    # --------------------------------------------------------
    # Current Status
    # --------------------------------------------------------

    print(
        f"Current status: "
        f"{current['status']}"
    )

    print(
        f"Alert count: "
        f"{current['alertCount']}"
    )

    print(
        f"Has active alert: "
        f"{current['hasActiveAlert']}"
    )

    print(
        f"All resolved: "
        f"{current['allResolved']}"
    )

    print(
        f"Fingerprint: "
        f"{current['fingerprint']}"
    )

    # --------------------------------------------------------
    # Redis
    # --------------------------------------------------------

    r = get_redis()

    try:

        # 測試 Redis 連線
        r.ping()

        print(
            "Redis connection: OK"
        )

        previous = get_previous_state(
            r
        )

        # ----------------------------------------------------
        # Compare
        # ----------------------------------------------------

        comparison = compare_state(
            current,
            previous,
        )

        print(
            "Previous state exists: "
            f"{comparison['hasPreviousState']}"
        )

        print(
            "Fingerprint changed: "
            f"{comparison['fingerprintChanged']}"
        )

        print(
            "Status changed: "
            f"{comparison['statusChanged']}"
        )

        print(
            "Should notify: "
            f"{comparison['shouldNotify']}"
        )

        # ----------------------------------------------------
        # Build state
        # ----------------------------------------------------

        state = build_state(
            current,
            previous,
            comparison[
                "shouldNotify"
            ],
        )

        # ----------------------------------------------------
        # Telegram
        #
        # 先通知，再保存 Redis。
        #
        # 如果 Telegram 失敗：
        #   - 程式會 raise exception
        #   - Redis 不會更新
        #   - GitHub Actions 會顯示失敗
        #
        # 下一次執行仍會重新嘗試通知。
        # ----------------------------------------------------

        if comparison[
            "shouldNotify"
        ]:

            send_telegram(
                current["message"]
            )

        else:

            print(
                "No notification required."
            )

        # ----------------------------------------------------
        # Save Redis
        # ----------------------------------------------------

        save_state(
            r,
            state,
        )

        print(
            "Monitor completed successfully."
        )

    finally:

        try:
            r.close()

        except Exception:
            pass


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    try:

        main()

    except requests.RequestException as error:

        print(
            "ERROR: HTTP request failed:"
        )

        print(
            repr(error)
        )

        raise

    except redis.RedisError as error:

        print(
            "ERROR: Redis operation failed:"
        )

        print(
            repr(error)
        )

        raise

    except Exception as error:

        print(
            "ERROR: Monitor failed:"
        )

        print(
            repr(error)
        )

        raise
