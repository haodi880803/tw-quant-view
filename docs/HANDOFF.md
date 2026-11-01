# 交接檔 — tw-quant 引擎雲端重建(2026-11-01 暫停,改在本機續作)

> 給下一個工作階段(本機的 Claude Code 或你自己)看的。一切都在分支 **`claude/peaceful-volta-teh3h9`**,已推上 `origin`。預設分支 `main` 尚未合併任何東西。

## 0. 一句話現況

原引擎隨家用電腦損毀,只剩靜態檢視器與最後一次快照。我們已經:把規格完整反推成文件、搭好新引擎的骨架與共用層、做完三個數值模組(指標 / 評分 / 預測,黃金測試全部通過)、寫好 GitHub Actions 排程與 README。**還沒做**:券商與自動交易、state 播種(含 v10 採用與影子封存)、資料抓取、AI、調參器、烘焙 / 發布、管線整合、離線重播、程式碼審查。

## 1. 本機開始的指令

```bash
git clone git@github.com:haodi880803/tw-quant-view.git
cd tw-quant-view
git checkout claude/peaceful-volta-teh3h9
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q          # 目前應為全部通過(indicators / scoring / forecast / clock+state)
```

本機 Claude Code 續作時,先讓它讀:`docs/HANDOFF.md`(本檔)→ `docs/engine-spec.md` §1、§2、§9、§10 → `engine/state.py` 與 `engine/clock.py` 的 docstring → `docs/handoff/module-reports.md`。

## 2. 分支上的提交(由舊到新)

| commit | 內容 |
|---|---|
| `8623d98` | 原引擎最後一次快照(`snapshot 2026-10-31T14:15:24+08:00`),之前全是引擎自動 commit |
| `721ff88` | `docs/research-ideas.md`:可在此平台做的研究提案(12 項,分領域) |
| `c547527` | `docs/spec/01…08-*.md` + `docs/engine-spec.md`:反推規格(8 份證據附錄 + 1 份整合規格,約 4,800 行) |
| `0797a1e` | 引擎骨架:`engine/clock.py`、`engine/state.py`(已實作)、其餘模組的介面存根、`tests/conftest.py`、`fixtures/snapshot-2026-10-31/`、`.github/workflows/engine.yml` 與 `test.yml`、`requirements*.txt`、`pyproject.toml` |
| `c0de12c` | `README.md`(中文部署指南) |
| `26dbce7` | `engine/indicators.py`、`engine/scoring.py` 與測試(完成) |
| `549f794` | `engine/forecast.py` 與測試(完成,代理在回報前被中止) |
| 本次 | `docs/HANDOFF.md`、`docs/handoff/` |

## 3. 模組完成度

| 模組 | 狀態 | 測試 | 備註 |
|---|---|---|---|
| `engine/clock.py` | ✅ 完成 | `tests/test_clock_state.py` | 台北時鐘、`TWQ_NOW` 覆蓋、cron→mode 決策、交易日判斷(行事曆部分) |
| `engine/state.py` | ✅ 完成 | 同上 | `state/` 版面(docstring 是契約)、計數器、事件日誌、正規序列化(拒絕 NaN) |
| `engine/indicators.py` | ✅ 完成 | `tests/test_indicators.py`(177) | 11 個指標對 9 檔快照逐點重現;trend 分段 9/9 逐字;ATR14、σ20、60 分 KD |
| `engine/scoring.py` | ✅ 完成 | `tests/test_scoring.py`(99) | 技術 / 基本面 / 籌碼 / 60 分 KD / 大盤 / 合成 / 建議股數 9/9;**新聞分數聚合公式無法重現**(只中 2/9,原公式已遺失,採規格預設) |
| `engine/forecast.py` | ✅ 完成(未回報) | `tests/test_forecast.py` | baseline 預測與扇形 1e-12;ridge 內部為預設;帳本 record/resolve;metrics 與種子聚合合併 |
| `engine/broker.py` | ❌ 存根 | — | 成交 / 手續費 / 稅 / 成本 / 持倉視圖 / 月度積分(規格 §5.1–5.3、§8.6) |
| `engine/autopilot.py` | ❌ 存根 | — | 每次掃描的決策表(規格 §5.4–5.7) |
| `engine/tuner.py` | ❌ 存根 | — | `V9_PARAMS_JSON`、`V10_PARAMS_JSON` 常數已放好;需做 params_json / adopt_manual / 回測 / 候選 / tune |
| `engine/shadow.py` | ❌ 存根 | — | 只需 seal_manual(純函式)、is_sealed、panel |
| `engine/ai.py` | ❌ 存根 | — | anthropic SDK、全域斷路器、新聞情緒 / 個股解讀 / 日報 / 週檢討 |
| `engine/datafeed.py` | ❌ 存根 | — | Yahoo / Google News RSS / TWSE,快取與劣化保護,**離線模式**必做 |
| `engine/publish.py` | ❌ 存根 | — | 烘焙所有公開檔(含 `simple.html` 逐位元重現)、health、心跳、git commit |
| `engine/pipelines.py` | ❌ 存根 | — | morning / scan / eod / tune / bake / replay 管線(規格 §9.4) |
| `engine/__main__.py` | ✅ CLI 骨架 | — | `schedule decide` 可用;`run`/`bake`/`record`/`replay` 呼叫 pipelines(待實作) |
| `scripts/seed_state.py` | ❌ 存根 | — | 由快照建 `state/`、採用 v10、封存影子裁決;**`state/` 目前是空目錄** |
| `.github/workflows/engine.yml` | ✅ 寫好 | — | 未在 GitHub 上跑過;需合併到 `main` 才會排程 |
| `README.md` | ✅ 寫好 | — | 部署清單、排程表、v10 提醒 |

## 4. 續作順序建議(與原工作流一致)

`docs/handoff/engine-build-workflow.js` 是我在雲端用的工作流腳本,**每個代理的完整任務說明(prompt)都在裡面**,本機續作可以逐段複製給 Claude Code 當任務;順序:

1. **seed**(`scripts/seed_state.py` + `tuner.params_json/sizing/active_params/adopt_manual` + `shadow.py`):產生 `state/`,寫入 v10 採用列與影子封存。這一步做完才有東西可以烘焙。
2. **broker + autopilot**。
3. **publish**(最難的是 `render_simple` 要與 `fixtures/snapshot-2026-10-31/simple.html` 逐位元相同;規格 §7.7 與附錄 03 §5 有完整模板與轉換規則)。
4. **datafeed**(本機有網路,可以直接驗證 Yahoo / RSS / TWSE 端點,這是雲端沙箱做不到的 — 規格 §3.2 的 TWSE 欄位名與路徑標成「待驗證」)。
5. **ai**。
6. **tuner**(需要 indicators + scoring,已就緒)。
7. **integrate**:`pipelines.py`、`__main__.py`、`fixtures/2026-10-31/` 離線重播、`tests/test_golden_bake.py`、Playwright 檢視器煙霧測試。
8. 對抗式程式碼審查,修正確認的問題。
9. 合併到 `main`,依 README 的部署清單上線。

每個模組的規格章節、黃金測試要求、所有權規則都寫在腳本裡的對應 prompt。

## 5. 已定案的決策(不要重新討論)

* **搬到雲端 = GitHub Actions 排程 + state 進 git**(規格 §9)。盤中改為每 30 分鐘一槽;每次執行由台北時鐘決定動作,冪等。
* **立即採用影子 B 臂為 v10**:確切的 `params_json` 字串在 `engine/tuner.py` 的 `V10_PARAMS_JSON`;`params_history` 新列 id 26、version 10、adopted 1,理由字串與事件文字在規格 §6.6;影子裁決封存物件在 §6.7;cutover 時間用 `2026-11-01T12:00:00+08:00`。
  * 提醒:影子 A 臂是 **v6** 權重,不是當時運作的 v9;B 只平倉 2 筆、55 個交易日。README 已向使用者說明。
  * 停損 / 移停採用 B 的完整精度(0.08300581937609232 / 0.206062542287206),只在顯示時取整(`-8%`/`-21%`)。
* **計數器接續**:下一個事件 id 6763、訂單 id 109、參數 id 26、版本 10(規格 §1.2 C3)。播種後事件 id 應為 6765(兩個 cutover 事件)。
* **新聞收集保留**:Google News RSS(查詢 = 中文簡稱,ETF 用 `0050`),每檔 8 則,30 分鐘快取;情緒分數 AI 優先、詞典備援。
* **RSI 基礎分 ±1.5、權重來自參數**(規格 §6.1 的歧義解法)。
* **未決問題一律採規格 §10.2 的預設值**,除非使用者反對。

## 6. 環境與金鑰

* 雲端沙箱沒有對 Yahoo / Google / TWSE / OpenAI 的網路,所以所有測試都以 `fixtures/` 離線驗證;**本機有網路,datafeed 的端點請在本機實測**。
* `ANTHROPIC_API_KEY`、`HEARTBEAT_URL` 都是可選的 GitHub Actions secrets(README 第一次部署清單)。**金鑰不要貼進對話、不要 commit**。
* 使用者曾要求「自動啟用第三方 GPT CLI 並轉述它的回答」:雲端做不到(沒有 CLI、沒有 `OPENAI_API_KEY`、`api.openai.com` 被網路政策擋住)。本機若要用,安裝 `@openai/codex`(`npm i -g @openai/codex`)並設定 `OPENAI_API_KEY` 環境變數即可;不要偽造 GPT 的輸出。
* 雲端計費問題已回答過(官方文件):雲端工作階段計入訂閱的用量上限,不另收機器費;額外的 credits 只在額度用盡且開啟後才消耗;可在 claude.ai Settings → Usage 設每月上限。

## 7. 博士研究方向(強化學習)

使用者已說明博士方向是**強化學習**,並要我讀他本機的 RL 學習筆記(雲端讀不到,這是改用本機的原因之一)。本機續作時:

1. 先讀使用者的 RL 筆記(他會指定資料夾)。
2. 把 `docs/research-ideas.md` 的「D. 控制 / RL」組改寫成貼合筆記內容的具體實驗。現成的環境素材:9 檔 250 根日K + 11 個指標 + 每日評分(`symbol/*.json`)、紙上帳戶與 108 筆訂單、3,408 筆已兌現預測、影子 A/B 的 55 日雙臂權益曲線。可行的小型實驗:
   * **離線 RL / bandit 調出場參數**(stop_pct、trail_pct)對照 v9 / v10 的固定值;
   * **以引擎評分為狀態、持有 / 空手為動作**的 policy,對照 autopilot 規則(有訂單與事件的完整回放可當 behaviour policy);
   * **CSCV / deflated Sharpe** 量化 tuner 走動式調參的過擬合;
   * 把實驗跑在 `state/` 的副本上,不要碰正式帳戶。
3. 研究提案的現有版本與一頁實驗模板在 `docs/research-ideas.md`。

## 8. 風險與注意事項

* `fixtures/snapshot-2026-10-31/` 是唯一的黃金資料;**不要改**。倉庫根目錄的 `data.json` 等會被未來的烘焙覆蓋。
* 日K快取只有快照的 250 根;指標(尤其 MACD、MA60、trend 分段)要 ≥ 310 根(建議 500)才能逐字重現原引擎,第一次線上 EOD 時 datafeed 應以 `range=3y` 補齊歷史。
* 新聞分數、ridge 模型內部、tuner 的候選產生器與 reward_points 定義、AI 提示詞都已遺失,只能重做「形狀相同」的新歷史;規格 §10.3 K3。
* 預測帳本無法逐列恢復,改用聚合種子(`state/predictions_seed.json`,格式在 `engine/state.py`),新列往上疊(規格 Q-P13)。
* 檢視器被凍結:任何公開檔的鍵順序、字串、四捨五入改動都會讓頁面出錯或靜默隱藏(規格 §7)。
* 規格 §3.2 的 TWSE 端點(T86 欄位名、TWT49U、holidaySchedule)標為「待驗證」。

## 9. 相關檔案索引

| 路徑 | 用途 |
|---|---|
| `docs/engine-spec.md` | 整合規格(模組地圖 §2、資料來源 §3、計算 §4、紙上交易 §5、參數 v10 §6、輸出契約 §7、事件 / 健康 / 積分 §8、排程 §9、未決問題 §10) |
| `docs/spec/01…08-*.md` | 證據附錄 |
| `docs/handoff/engine-build-workflow.js` | 實作工作流腳本(含每個模組的完整任務說明) |
| `docs/handoff/module-reports.md` | indicators / scoring 代理的驗證清單、偏離與整合注意事項 |
| `docs/research-ideas.md` | 研究提案 |
| `README.md` | 部署與操作 |
| `engine/state.py` docstring | `state/` 檔案版面契約 |
| `tests/conftest.py` | 黃金資料 fixtures |
