# taoyuan-typhoon-monitor
taoyuan-typhoon-monitor
🌀 桃園颱風警報狀態監控系統

使用 GitHub Actions + Python + 中央氣象署 CWA OpenData + Redis + Telegram Bot 建立的桃園颱風警報監控系統。

系統會定期取得中央氣象署颱風警報資料，監控桃園市及北部鄰近海域，並透過 Redis 保存上一個警報狀態。

只有在警報內容或狀態發生變化時，才會透過 Telegram 發送通知，避免相同警報重複推播。

📋 系統功能

每小時自動執行 GitHub Actions

取得中央氣象署颱風警報資料

監控桃園市

監控臺灣北部海面

監控臺灣東北部海面

監控臺灣海峽北部

自動判斷目前是否存在有效颱風警報

使用 SHA-256 建立警報 Fingerprint

使用 Redis 保存上一個警報狀態

自動偵測警報內容變更

自動偵測警報狀態變更

Telegram 推播警報

避免相同警報重複通知

支援颱風警報解除通知

支援 GitHub Actions 手動執行

API Key、Redis URL、Telegram Token 全部使用 GitHub Secrets 管理

🏗️ 系統架構
┌─────────────────────────────┐
│       GitHub Actions        │
│                             │
│  每小時執行 / 手動執行       │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│        CWA OpenData         │
│                             │
│   中央氣象署颱風警報 API     │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│       Python Monitor        │
│                             │
│  1. 篩選監控區域             │
│  2. Normalize               │
│  3. 建立 Fingerprint         │
│  4. 比較上一個狀態            │
└──────────────┬──────────────┘
               │
       ┌───────┴────────┐
       │                │
       ▼                ▼
┌─────────────┐   ┌─────────────┐
│    Redis    │   │  Telegram   │
│             │   │             │
│ 保存狀態     │   │ 警報推播     │
└─────────────┘   └─────────────┘

📁 專案結構
taoyuan-typhoon-monitor/
│
├── .github/
│   └── workflows/
│       └── typhoon-monitor.yml
│
├── monitor.py
│
├── requirements.txt
│
└── README.md

🚀 安裝方式
1. 建立 GitHub Repository

建立一個新的 GitHub Repository，例如：

taoyuan-typhoon-monitor


將以下檔案放入 Repository：

monitor.py
requirements.txt
.github/workflows/typhoon-monitor.yml
README.md

🔑 2. 建立中央氣象署 API Key

本系統使用中央氣象署 OpenData API：

https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001


需要準備中央氣象署 OpenData API Key。

取得 API Key 後，不要直接寫入 Python 程式碼。

GitHub Actions 使用 Secret：

CWA_API_KEY

🗄️ 3. 建立 Redis

本系統需要 Redis 保存前一次執行的警報狀態。

推薦使用雲端 Redis，例如 Upstash。

建立 Redis Database 後，取得 Redis Connection URL。

格式通常類似：

rediss://default:YOUR_PASSWORD@YOUR_HOST:6379


例如：

rediss://default:xxxxxxxx@xxxxx.upstash.io:6379


這整串就是：

REDIS_URL


⚠️ Redis URL 通常包含密碼，不要提交到 GitHub Repository。

📱 4. 建立 Telegram Bot

使用 Telegram BotFather 建立 Bot。

取得：

TELEGRAM_BOT_TOKEN


例如：

1234567890:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx


接著取得 Telegram Chat ID：

TELEGRAM_CHAT_ID


例如：

8683161103


實際 Chat ID 請使用你自己的值。

🔐 5. 設定 GitHub Secrets

進入 GitHub Repository：

Settings
→ Secrets and variables
→ Actions
→ New repository secret


建立以下 4 個 Secrets：

CWA_API_KEY
REDIS_URL
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID


完整設定如下：

Secret	用途
CWA_API_KEY	中央氣象署 API Key
REDIS_URL	Redis 連線 URL
TELEGRAM_BOT_TOKEN	Telegram Bot Token
TELEGRAM_CHAT_ID	Telegram 接收通知的 Chat ID
⚙️ 6. GitHub Actions

Workflow 位於：

.github/workflows/typhoon-monitor.yml


目前設定為每小時執行：

on:
  schedule:
    - cron: "0 * * * *"


也支援手動執行：

workflow_dispatch:


因此可以從：

GitHub
→ Actions
→ 桃園颱風警報監控
→ Run workflow


手動執行測試。

🌦️ 監控區域

目前監控：

桃園市
臺灣北部海面
臺灣東北部海面
臺灣海峽北部


程式中定義於：

TARGET_AREAS = [
    "桃園市",
    "臺灣北部海面",
    "臺灣東北部海面",
    "臺灣海峽北部",
]


如果日後需要增加監控區域，可以修改這個列表。

🚨 警報類型

目前監控：

海上颱風警報
海上陸上颱風警報
解除颱風警報


程式中定義於：

TARGET_HEADLINES = [
    "海上颱風警報",
    "海上陸上颱風警報",
    "解除颱風警報",
]

🔄 通知邏輯

系統使用 Fingerprint 比較目前資料與 Redis 保存的上一個狀態。

流程：

取得 CWA 資料
      │
      ▼
篩選監控區域
      │
      ▼
整理警報資料
      │
      ▼
建立 SHA-256 Fingerprint
      │
      ▼
Redis 取得上一個狀態
      │
      ▼
比較 Fingerprint / Status
      │
      ├───────────────┐
      │               │
      ▼               ▼
    有變化           無變化
      │               │
      ▼               ▼
 Telegram            不通知
      │
      ▼
 Redis 儲存最新狀態

🔔 通知規則
第一次執行

如果第一次執行時：

目前 = active


會發送 Telegram：

✅ 發送通知


如果第一次執行時：

目前 = resolved


則只建立 Redis 初始狀態：

❌ 不發送解除通知

相同警報

例如第一次：

海上颱風警報


下一小時仍然完全相同：

海上颱風警報


則：

Fingerprint 相同
Status 相同
↓
不通知

警報內容更新

例如：

原本：
海上颱風警報

更新：
海上陸上颱風警報


Fingerprint 發生變化：

Fingerprint changed = true


因此：

📱 發送 Telegram

警戒區域變更

例如：

原本：
臺灣北部海面

更新：
臺灣北部海面、桃園市


警報內容發生變化：

Fingerprint changed = true


因此：

📱 發送 Telegram

解除警報

當 CWA 回傳：

解除颱風警報


系統狀態會變成：

resolved


如果上一個狀態是：

active


則：

Status changed = true


因此：

📱 發送解除通知


之後如果下一次取得完全相同的解除資料：

Fingerprint 相同
Status 相同


則：

❌ 不重複通知

🧠 Redis 狀態

Redis Key：

weather:typhoon:taoyuan


保存內容包含：

{
  "version": 1,
  "system": "桃園颱風警報狀態監控系統",
  "region": "桃園市",
  "monitoredAreas": [
    "桃園市",
    "臺灣北部海面",
    "臺灣東北部海面",
    "臺灣海峽北部"
  ],
  "status": "active",
  "hasActiveAlert": true,
  "allResolved": false,
  "alertCount": 1,
  "fingerprint": "SHA256...",
  "alerts": [],
  "firstSeenAt": "2026-09-25T00:00:00+00:00",
  "lastCheckedAt": "2026-09-25T01:00:00+00:00",
  "lastNotifiedAt": "2026-09-25T00:00:00+00:00"
}

🧬 Fingerprint

Fingerprint 使用 SHA-256 建立。

計算內容包含標準化後的警報資料，例如：

headline
areaDesc
effective
onset
expires
event
description
sender
web
status


產生類似：

7a8c2c8d8f........


的 SHA-256 Hash。

這可以避免 API 回傳資料順序改變時造成不必要的通知。

📱 Telegram 通知範例

發生新的颱風警報時：

🌀 桃園颱風警報通知

📢 海上陸上颱風警報

📍 地區：桃園市、臺灣北部海面
🌪️ 事件：颱風

📝 說明：
中央氣象署發布的颱風警報內容...

⏰ 開始時間：2026/09/25 08:00
⏱️ 生效時間：2026/09/25 08:00
🔚 結束時間：未提供

🏢 發布單位：中央氣象署

🔗 中央氣象署詳細資訊：
https://...

🧪 測試
手動執行 GitHub Actions

進入：

GitHub
→ Actions
→ 桃園颱風警報監控
→ Run workflow


查看執行結果。

成功時應該看到類似：

桃園颱風警報狀態監控系統
============================================================
Fetching CWA data...
Current status: active
Alert count: 1
Fingerprint: 7a8c...
Previous state exists: False
Fingerprint changed: True
Status changed: True
Should notify: True
Sending Telegram notification...
Telegram notification sent.
Redis state saved.
Monitor completed successfully.

🧪 測試通知去重

第一次執行：

Previous state exists: False
Should notify: True


會發送 Telegram。

第二次執行，如果 CWA 資料完全相同：

Previous state exists: True
Fingerprint changed: False
Status changed: False
Should notify: False


不會發送 Telegram。

❗ 常見問題
GitHub Actions 無法連線 Redis

確認：

REDIS_URL


是否為可以從 Internet 存取的 Redis。

例如：

rediss://default:password@hostname:6379


不要使用：

redis://192.168.x.x:6379


因為 GitHub Actions 無法直接存取你家中的區域網路 Redis。

Telegram 沒收到訊息

確認：

TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID


是否正確。

另外確認 Telegram Bot 已經被加入目標聊天室，並且具備發送訊息的權限。

CWA API 錯誤

確認：

CWA_API_KEY


是否正確，以及 API Key 是否仍然有效。

🔒 安全性

請不要將以下資訊直接提交到 Git：

CWA_API_KEY
REDIS_URL
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID


推薦全部使用 GitHub Secrets。

不要建立：

.env


並將秘密內容 commit 到 Repository。

如果本機測試需要 .env，建議加入：

.env


到 .gitignore。

📄 License

此專案主要用於個人天氣警報監控與通知用途。

資料來源為中央氣象署 OpenData。

實際警報內容、發布時間與警戒範圍應以中央氣象署正式發布資訊為準。

⚠️ 注意事項

本系統屬於自動化資訊通知工具，不保證 GitHub Actions、Internet、Redis、Telegram 或第三方 API 永遠即時或可用。

GitHub Actions 的排程工作可能因平台負載而延遲執行。

如遇颱風或其他重大天氣事件，請以中央氣象署官方發布資訊及政府相關單位公告為準。

📌 TODO

未來可以考慮加入：

 每 10 分鐘監控模式

 GitHub Actions concurrency 防止重複執行

 Redis Distributed Lock

 Telegram API Retry

 Telegram Markdown / HTML 格式

 多個 Telegram Chat ID

 Discord Webhook

 LINE Notify 替代方案

 豪雨特報

 大雨特報

 強風特報

 地震監控

 CWA API 錯誤重試

 GitHub Actions 執行失敗通知

 警報歷史紀錄

 Web Dashboard

 Docker 版本

 每日監控健康狀態通知
