# tw-quant — 台股觀察清單評分與紙上交易引擎(雲端版)

這個倉庫同時放著兩樣東西:

1. **唯讀檢視器**(`index.html`、`simple.html`、`app.js`、`app.css`、`vendor/`):由 GitHub Pages 直接提供的靜態網頁,只讀取倉庫根目錄的 JSON 快照。這部分**凍結不改**。
2. **引擎**(`engine/`、`state/`、`.github/workflows/engine.yml`):原本跑在家用電腦、後來隨主機損毀遺失的評分 / 紙上交易 / 預測 / 調參程式,依據最後一次快照反推規格(`docs/engine-spec.md`)重建,改成由 **GitHub Actions 排程執行**,把結果直接 commit 回倉庫,Pages 隨之更新。

> 免責:所有訊號與預測皆由公式機械式計算,必有誤差且會失準;帳戶為虛擬資金的紙上模擬,非投資建議。

## 目前狀態(2026-11-01 重建)

| 項目 | 狀態 |
|---|---|
| 最後一次原引擎快照 | `2026-10-31T14:15:22+08:00`(凍結副本在 `fixtures/snapshot-2026-10-31/`) |
| 參數版本 | **v10** = 影子對照 B 臂(risk-exit-consensus)基因,2026-11-01 手動採用(見下) |
| 影子 A/B 對照 | 已於第 55/60 交易日人工結案,裁決 B 勝出,`shadow.json` 封存不再更新 |
| AI 日報 / 個股解讀 | 需要 `ANTHROPIC_API_KEY`;未設定時引擎照常運作,只是不產生 AI 文字 |
| 新聞收集 | Google News RSS(每檔 8 則)+ 情緒評分(AI 可用時用 AI,否則用詞典規則) |
| 資料來源 | Yahoo Finance(日K / 60 分K / 報價 / 基本面)、TWSE(三大法人 T86、除權息、休市日) |

### 關於 v10 的兩個提醒

* 影子對照的 A 臂是 **v6 的權重**(`incumbent-v6`),不是當時正式運作的 v9。所以「B 贏 A」證明的是 B 優於 v6,v9 本身並未參加對照。v9 → v10 的差異主要在權重(均線排列加重到 1.85、RSI 加重到 0.78、KD 降到 0.24、布林加到 1.28)與出場參數(停損 8.30%、移動停利 20.61%)。
* 影子期間只有 55 個交易日、B 臂只平倉 2 筆,統計上樣本仍少。若要回退,執行一次 `adopt_manual` 寫入 v9 的參數字串(在 `engine/tuner.py` 的 `V9_PARAMS_JSON`)即可,歷史列會保留。

## 排程(台北時間)

| 時間 | 模式 | 內容 |
|---|---|---|
| 週一至週五 08:30 | `morning` | 晨會:夜盤 / TSM / 費半、宏觀新聞數,決定是否「風險覆蓋 caution」 |
| 週一至週五 09:00–13:30 每 30 分鐘 | `scan` | 報價、指標、評分、建議翻轉事件、自動交易(停損 / 移停 / 換股 / 進場)、新聞更新、烘焙快照;13:30 那一槽為「收盤定盤」 |
| 週一至週五 14:15 | `eod` | 完整日K校正、市場狀態、預測記錄 / 兌現、模型健康、月度積分、品質下降觸發調參、AI 日報與個股解讀、心跳 |
| 週六 10:00 | `tune` | 週檢討(AI)、walk-forward champion/challenger 調參、週六快照 |

原引擎盤中每 5 分鐘掃描一次;雲端改成每 30 分鐘(GitHub 排程的實際精度與配額限制),停損 / 移停因此可能晚一點觸發。每次執行都用台北時鐘決定該做什麼,非交易日(含 `state/calendar.json` 的休市日與「加權指數當天沒有新K棒」)的 `morning`/`scan` 直接略過。

## 第一次部署清單

1. **合併到預設分支 `main`**。GitHub 排程只在預設分支上執行;60 天沒有任何 commit 會被自動停用(引擎自己的 snapshot commit 會維持活性)。
2. **GitHub Pages**:Settings → Pages → Source 選 `Deploy from a branch`,分支 `main`,目錄 `/ (root)`。引擎用 `GITHUB_TOKEN` 推送時 Pages 仍會重建(首次部署請確認 `index.html` 右上角「資料時間」有更新;若沒有,再改用 `actions/deploy-pages`)。
3. **Secrets(可選)**:Settings → Secrets and variables → Actions → New repository secret
   * `ANTHROPIC_API_KEY`:啟用 AI 日報 / 個股解讀 / 新聞情緒 / 週檢討。
   * `HEARTBEAT_URL`:healthchecks 類型的心跳網址;每日 EOD 送 `GET <url>`(正常)或 `GET <url>/fail`(有紅燈),建議設定 36 小時寬限。
   兩者都沒有時引擎照常運作。**不要把金鑰貼進對話或 commit 到倉庫**。
4. **手動試跑**:Actions → `tw-quant engine` → Run workflow → `mode: bake`、`dry_run: true`。下載產出的 artifact,與目前的 `data.json` 比對。接著在平日 14:15 之後跑一次 `mode: eod`(不勾 dry_run)。
5. 之後交給排程即可。每個交易日約 12 次 commit(訊息 `snapshot <ISO 時間>`,作者 `tw-quant <tw-quant@localhost>`)。

## 本機 / 離線操作

```bash
pip install -r requirements-dev.txt
python -m pytest                     # 黃金測試:用 2026-10-31 快照驗證指標、訊號、券商、烘焙等
```

```bash
# 離線重播(不碰網路、不 commit),用 fixtures/<日期>/ 的資料
TWQ_OFFLINE=1 TWQ_AS_OF=2026-10-31 TWQ_NOW=2026-10-31T14:15:22+08:00 TWQ_DRY_RUN=1 \
python -m engine run --mode bake
```

```bash
# 從 state/ 重新烘焙所有公開檔案(修復用)
python -m engine bake
```

常用環境變數:`TWQ_NOW`(覆蓋時鐘)、`TWQ_OFFLINE=1`、`TWQ_AS_OF`、`TWQ_DRY_RUN=1`、`TWQ_STATE_DIR`、`TWQ_NIGHT_SYMBOL`(夜盤來源,未設定時晨會顯示「夜盤 無資料」)。

## 目錄

```
engine/          引擎套件(clock, state, datafeed, indicators, scoring, forecast, broker,
                 autopilot, tuner, shadow, ai, publish, pipelines, __main__)
state/           引擎狀態,全部 commit 進 git(紙上帳戶、訂單 / 事件 / 預測帳本、參數與歷史、
                 行事曆、資料快取、AI 產出、封存的影子面板)。放 state/KILL 檔即全面封鎖下單。
scripts/seed_state.py   由 2026-10-31 快照建立 state/、採用 v10、封存影子裁決(已執行過,可重複執行)
fixtures/        snapshot-2026-10-31(黃金資料)與離線重播用的資料夾
tests/           pytest 黃金測試
docs/engine-spec.md     重建規格(含所有公式、字串、鍵順序與未決問題的預設值)
docs/spec/       規格的證據附錄(01–08)
docs/research-ideas.md  可在此平台上做的研究 / 實驗提案
```

## 公開檔案的契約

`data.json`、`symbol/<代碼>.json`、`orders.json`、`events.json`、`model-health.json`、`shadow.json`、`simple.html` 的鍵順序、型別、列舉字串、四捨五入與序列化方式都寫在 `docs/engine-spec.md` §7,測試會以 2026-10-31 的快照逐字驗證。事件 / 訂單 / 參數的 id 從快照接續(6763 / 109 / 26),瀏覽器端的去重依賴這點。
