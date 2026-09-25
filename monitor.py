import os
import json
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import redis


# ============================================================
# 桃園颱風警報狀態監控系統
#
# GitHub Actions
#       ↓
# CWA OpenData API
#       ↓
# Normalize
#       ↓
# Fingerprint
#       ↓
# Upstash Redis
#       ↓
# 比較上一個狀態
#       ↓
# Telegram
#       ↓
# 儲存最新狀態
#
# Required Environment Variables:
#
# CWA_API_KEY
# REDIS_URL
# TELEGRAM_BOT_TOKEN
# TELEGRAM_CHAT_ID
#
# Upstash Redis URL example:
#
# rediss://default:xxxxx@xxxxx.upstash.io:6379
#
# ============================================================


# ============================================================
# Configuration
# ============================================================

CWA_API_URL = (
    "https://opendata.cwa.gov.tw/"
    "api/v1/rest/datastore/W-C0034-001"
)

REDIS_KEY = "weather:typhoon:taoyuan"

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

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


# ============================================================
# Environment Variables
# ============================================================

CWA_API_KEY = os.getenv(
    "CWA_API_KEY",
    "",
).strip()

REDIS_URL = os.getenv(
    "REDIS_URL",
    "",
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "",
).strip()


# ============================================================
# Utility
# ============================================================

def value_to_string(
    value,
    default="",
):
    """
    將 CWA API 各種資料型別安全轉換成 string。

    CWA 某些欄位可能是：
        string
        dict
        list
        number
        None

    避免：

        TypeError:
        sequence item expected str instance, dict found
    """

    if value is None:
        return default

    if isinstance(value, str):
        return value

    if isinstance(
        value,
        (int, float, bool),
    ):
        return str(value)

    if isinstance(value, dict):

        # 常見 CWA 結構
        for key in (
            "value",
            "url",
            "href",
            "text",
            "name",
        ):
            if (
                key in value
                and value[key] is not None
            ):
                return value_to_string(
                    value[key],
                    default,
                )

        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        except Exception:
            return str(value)

    if isinstance(value, list):

        result = []

        for item in value:

            converted = value_to_string(
                item,
                "",
            )

            if converted:
                result.append(
                    converted
                )

        return "、".join(result)

    return str(value)


def now_iso():
    """
    UTC ISO 8601。
    """

    return datetime.now(
        timezone.utc
    ).isoformat()


def format_time(value):
    """
    CWA 時間轉換為 Asia/Taipei。
    """

    if not value:
        return "未提供"

    value = value_to_string(
        value,
        "",
    )

    if not value:
        return "未提供"

    try:

        normalized = value.strip()

        if normalized.endswith("Z"):
            normalized = (
                normalized[:-1]
                + "+00:00"
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
    檢查 GitHub Actions Secrets。
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

    # --------------------------------------------------------
    # Upstash Redis URL validation
    # --------------------------------------------------------

    if not (
        REDIS_URL.startswith(
            "redis://"
        )
        or
        REDIS_URL.startswith(
            "rediss://"
        )
        or
        REDIS_URL.startswith(
            "unix://"
        )
    ):

        raise ValueError(
            "Invalid REDIS_URL. "
            "Upstash Redis should normally use "
            "rediss://..."
        )


# ============================================================
# CWA API
# ============================================================

def fetch_cwa_data():
    """
    取得中央氣象署颱風警報資料。
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

    print(
        "Requesting CWA API..."
    )

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

    if not isinstance(
        data,
        dict,
    ):

        raise RuntimeError(
            "CWA API response is not "
            "a JSON object."
        )

    return data


# ============================================================
# Area Filtering
# ============================================================

def is_target_area(info):
    """
    判斷是否為桃園／北部海域相關警報。
    """

    if not isinstance(
        info,
        dict,
    ):
        return False

    areas = info.get(
        "area",
        [],
    )

    if not isinstance(
        areas,
        list,
    ):
        return False

    for area in areas:

        if not isinstance(
            area,
            dict,
        ):
            continue

        area_name = value_to_string(
            area.get(
                "areaDesc"
            ),
            "",
        )

        for target in TARGET_AREAS:

            if target in area_name:
                return True

    return False


# ============================================================
# Normalize Alert
# ============================================================

def normalize_alert(info):
    """
    將單筆 CWA alert 轉成穩定格式。
    """

    if not isinstance(
        info,
        dict,
    ):

        raise ValueError(
            "Invalid CWA alert object."
        )

    areas = info.get(
        "area",
        [],
    )

    if not isinstance(
        areas,
        list,
    ):
        areas = []

    area_names = []

    for area in areas:

        if not isinstance(
            area,
            dict,
        ):
            continue

        area_name = value_to_string(
            area.get(
                "areaDesc"
            ),
            "",
        )

        if area_name:
            area_names.append(
                area_name
            )

    # 移除重複區域
    area_names = list(
        dict.fromkeys(
            area_names
        )
    )

    area_desc = "、".join(
        area_names
    )

    headline = value_to_string(
        info.get(
            "headline"
        ),
        "未提供",
    )

    description = value_to_string(
        info.get(
            "description"
        ),
        "未提供",
    )

    event = value_to_string(
        info.get(
            "event"
        ),
        "颱風",
    )

    sender = value_to_string(
        info.get(
            "senderName"
        ),
        "中央氣象署",
    )

    web = value_to_string(
        info.get(
            "web"
        ),
        "",
    )

    effective = value_to_string(
        info.get(
            "effective"
        ),
        "",
    )

    onset = value_to_string(
        info.get(
            "onset"
        ),
        "",
    )

    expires = value_to_string(
        info.get(
            "expires"
        ),
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
# Build Telegram Message
# ============================================================

def build_message(alert):
    """
    建立 Telegram 訊息。

    所有欄位最後再次轉 string，
    確保 join() 絕對不會遇到 dict。
    """

    headline = value_to_string(
        alert.get(
            "headline"
        ),
        "未提供",
    )

    area_desc = value_to_string(
        alert.get(
            "areaDesc"
        ),
        "未提供",
    )

    event = value_to_string(
        alert.get(
            "event"
        ),
        "颱風",
    )

    description = value_to_string(
        alert.get(
            "description"
        ),
        "未提供",
    )

    sender = value_to_string(
        alert.get(
            "sender"
        ),
        "中央氣象署",
    )

    web = value_to_string(
        alert.get(
            "web"
        ),
        "無",
    )

    onset = alert.get(
        "onset"
    )

    effective = alert.get(
        "effective"
    )

    expires = alert.get(
        "expires"
    )

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
        f"⏰ 開始時間："
        f"{format_time(onset)}",
        f"⏱️ 生效時間："
        f"{format_time(effective)}",
        f"🔚 結束時間："
        f"{format_time(expires)}",
        "",
        f"🏢 發布單位：{sender}",
        "",
        "🔗 中央氣象署詳細資訊：",
        web,
    ]

    # 最後安全轉換
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
    CWA response → normalized state。
    """

    if not isinstance(
        data,
        dict,
    ):

        return {
            "valid": False,
            "reason": (
                "CWA API response "
                "格式錯誤"
            ),
        }

    records = data.get(
        "records",
        {},
    )

    if not isinstance(
        records,
        dict,
    ):

        return {
            "valid": False,
            "reason": (
                "CWA API records "
                "格式錯誤"
            ),
        }

    infos = records.get(
        "info",
        [],
    )

    if not isinstance(
        infos,
        list,
    ):

        return {
            "valid": False,
            "reason": (
                "CWA API info "
                "格式錯誤"
            ),
        }

    if not infos:

        return {
            "valid": False,
            "reason": (
                "沒有取得 CWA "
                "颱風警報資料"
            ),
        }

    target_infos = []

    for info in infos:

        if is_target_area(info):

            target_infos.append(
                info
            )

    if not target_infos:

        return {
            "valid": False,
            "reason": (
                "目前沒有符合桃園／"
                "北部海域條件的颱風警報"
            ),
        }

    alerts = []

    for info in target_infos:

        try:

            alert = normalize_alert(
                info
            )

            alerts.append(
                alert
            )

        except Exception as error:

            print(
                "WARNING: Failed to "
                "normalize alert:"
            )

            print(
                repr(error)
            )

    if not alerts:

        return {
            "valid": False,
            "reason": (
                "無法解析 CWA "
                "警報資料"
            ),
        }

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    alerts.sort(
        key=lambda alert: (
            value_to_string(
                alert.get(
                    "headline"
                )
            ),

            value_to_string(
                alert.get(
                    "areaDesc"
                )
            ),

            value_to_string(
                alert.get(
                    "effective"
                )
            ),

            value_to_string(
                alert.get(
                    "event"
                )
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
        fingerprint_source.encode(
            "utf-8"
        )
    ).hexdigest()

    # --------------------------------------------------------
    # Overall Status
    # --------------------------------------------------------

    has_active_alert = any(
        alert.get(
            "status"
        ) == "active"
        for alert in alerts
    )

    all_resolved = all(
        alert.get(
            "status"
        ) == "resolved"
        for alert in alerts
    )

    if all_resolved:

        overall_status = (
            "resolved"
        )

    else:

        overall_status = (
            "active"
        )

    # --------------------------------------------------------
    # Primary Alert
    # --------------------------------------------------------

    primary = alerts[0]

    message = build_message(
        primary
    )

    return {
        "valid": True,

        "status": overall_status,

        "hasActiveAlert": (
            has_active_alert
        ),

        "allResolved": (
            all_resolved
        ),

        "alertCount": len(
            alerts
        ),

        "alerts": alerts,

        "fingerprint": fingerprint,

        "fingerprintSource": (
            fingerprint_source
        ),

        "message": message,

        "checkedAt": now_iso(),
    }


# ============================================================
# Upstash Redis
# ============================================================

def get_redis():
    """
    建立 Redis client。

    Upstash 通常使用：

        rediss://default:PASSWORD@HOST:6379

    redis-py 可以直接使用 from_url()。
    """

    if not REDIS_URL:

        raise RuntimeError(
            "REDIS_URL is not configured."
        )

    redis_url = REDIS_URL.strip()

    # --------------------------------------------------------
    # URL Scheme
    # --------------------------------------------------------

    if redis_url.startswith(
        "rediss://"
    ):

        print(
            "Redis URL scheme: rediss://"
        )

    elif redis_url.startswith(
        "redis://"
    ):

        print(
            "Redis URL scheme: redis://"
        )

    elif redis_url.startswith(
        "unix://"
    ):

        print(
            "Redis URL scheme: unix://"
        )

    else:

        raise ValueError(
            "Invalid REDIS_URL. "
            "Expected redis://, "
            "rediss://, or unix://. "
            "For Upstash use rediss://..."
        )

    try:

        client = redis.Redis.from_url(
            redis_url,

            decode_responses=True,

            socket_timeout=10,

            socket_connect_timeout=10,

            retry_on_timeout=True,
        )

    except Exception as error:

        raise RuntimeError(
            "Failed to create Redis client: "
            f"{error}"
        ) from error

    return client


def get_previous_state(
    redis_client,
):
    """
    取得 Redis 上一次狀態。
    """

    print(
        f"Reading Redis key: "
        f"{REDIS_KEY}"
    )

    raw = redis_client.get(
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

    except json.JSONDecodeError as error:

        print(
            "WARNING: Redis state "
            "is invalid JSON:"
        )

        print(
            repr(error)
        )

        return None

    if not isinstance(
        previous,
        dict,
    ):

        print(
            "WARNING: Redis state "
            "is not a JSON object."
        )

        return None

    return previous


def save_state(
    redis_client,
    state,
):
    """
    儲存最新 Redis state。
    """

    serialized = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    redis_client.set(
        REDIS_KEY,
        serialized,
    )

    print(
        f"Redis state saved: "
        f"{REDIS_KEY}"
    )


# ============================================================
# Compare State
# ============================================================

def compare_state(
    current,
    previous,
):
    """
    比較 CWA 目前狀態與 Redis 舊狀態。
    """

    has_previous_state = (
        previous is not None
    )

    # --------------------------------------------------------
    # First Run
    # --------------------------------------------------------

    if not has_previous_state:

        fingerprint_changed = True

        status_changed = True

        # 第一次執行：
        #
        # active
        #   → 通知
        #
        # resolved
        #   → 不通知
        #
        should_notify = (
            current.get(
                "status"
            ) == "active"
        )

    # --------------------------------------------------------
    # Existing State
    # --------------------------------------------------------

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
    建立要寫入 Redis 的 state。
    """

    now = now_iso()

    if previous:

        first_seen_at = (
            previous.get(
                "firstSeenAt"
            )
            or now
        )

        last_notified_at = (
            previous.get(
                "lastNotifiedAt"
            )
        )

    else:

        first_seen_at = now

        last_notified_at = None

    if should_notify:

        last_notified_at = now

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

        "status": current.get(
            "status"
        ),

        "hasActiveAlert": current.get(
            "hasActiveAlert"
        ),

        "allResolved": current.get(
            "allResolved"
        ),

        "alertCount": current.get(
            "alertCount"
        ),

        "fingerprint": current.get(
            "fingerprint"
        ),

        "alerts": current.get(
            "alerts",
            [],
        ),

        "firstSeenAt": (
            first_seen_at
        ),

        "lastCheckedAt": now,

        "lastNotifiedAt": (
            last_notified_at
        ),
    }

    return state


# ============================================================
# Telegram
# ============================================================

def send_telegram(
    message,
):
    """
    Telegram Bot API。
    """

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN "
            "is not configured."
        )

    if not TELEGRAM_CHAT_ID:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID "
            "is not configured."
        )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,

        "text": value_to_string(
            message,
            "",
        ),

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
            "Telegram response "
            "is not JSON."
        ) from error

    if not result.get(
        "ok",
        False,
    ):

        # 不輸出 bot token
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
    # Environment
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

    if not current.get(
        "valid",
        False,
    ):

        print(
            "No matching typhoon alert."
        )

        print(
            current.get(
                "reason",
                "Unknown",
            )
        )

        # 沒有符合條件的警報時，
        # 不修改 Redis。
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
        "Has active alert: "
        f"{current['hasActiveAlert']}"
    )

    print(
        "All resolved: "
        f"{current['allResolved']}"
    )

    print(
        "Fingerprint: "
        f"{current['fingerprint']}"
    )

    # --------------------------------------------------------
    # Redis
    # --------------------------------------------------------

    redis_client = get_redis()

    try:

        print(
            "Testing Redis connection..."
        )

        redis_client.ping()

        print(
            "Redis connection: OK"
        )

        # ----------------------------------------------------
        # Previous State
        # ----------------------------------------------------

        previous = get_previous_state(
            redis_client
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
        # Telegram
        #
        # Telegram 成功之後才寫 Redis。
        #
        # 如果 Telegram 發送失敗：
        #
        #   GitHub Actions = failed
        #   Redis = 保留舊狀態
        #
        # 下一次執行仍會重新通知。
        # ----------------------------------------------------

        if comparison[
            "shouldNotify"
        ]:

            send_telegram(
                current[
                    "message"
                ]
            )

        else:

            print(
                "No notification required."
            )

        # ----------------------------------------------------
        # Build + Save State
        # ----------------------------------------------------

        state = build_state(
            current,
            previous,
            comparison[
                "shouldNotify"
            ],
        )

        save_state(
            redis_client,
            state,
        )

        print(
            "Monitor completed successfully."
        )

    finally:

        try:

            redis_client.close()

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
