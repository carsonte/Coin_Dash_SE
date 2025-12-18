Coin Dash 路 AI 鑷富鍐崇瓥 SE
=========================

姒傝
----
Coin Dash 鏄竴濂楀鍛ㄦ湡鏁板瓧璐у竵/榛勯噾鐨勮嚜鍔ㄥ寲浜ゆ槗鍐崇瓥閾撅紝鏍稿績鎬濊矾鏄€淎I 鍏ㄦ潈 + 澶氭ā鍨嬪鍛樹細 + 鏁版嵁涓庢墽琛屽畨鍏ㄥ甫鈥濄€傜郴缁熻礋璐ｆ暟鎹绾裤€佺壒寰佹彁鍙栥€佸喅绛栬褰曘€佺焊鐩?瀹炵洏鍚屾涓庨€氱煡锛涙ā鍨嬪彧浜у嚭鏂瑰悜/浠锋牸/椋庢帶 JSON锛岄伩鍏嶆墜宸ヨ鍒欏共鎵般€?

杩戞湡鏇存柊
--------
- 澶氭ā鍨嬪鍛樹細锛氶粯璁ゅ紑鍚?`enable_multi_model_committee`锛孌eepSeek + gpt-4o-mini锛圓izex锛? Qwen 鍏卞悓鎶曠エ锛汥eepSeek 鏉冮噸鏈€楂橈紙0.5锛夛紝gpt-4o-mini 0.3锛孮wen 0.2锛屽彲鍦ㄥ紑鍏冲叧闂椂鍥為€€鍒板崟 DeepSeek銆?
- 鍓嶇疆鍙屾ā鍨嬮棬鍗紙B1锛夛細gpt-4o-mini 0.6 + Qwen 0.4 蹇€熷垽瀹氣€滆涓嶈璧?DeepSeek鈥濓紝鍐茬獊鎴栦綆缃俊搴︾洿鎺?`no-trade`锛岀悊鐢变細鍐欏叆鍐崇瓥鍏冧俊鎭€?
- 棰勮繃婊ゆ敼涓?Qwen锛歚ai/filter_adapter.py` 浣跨敤 Qwen 杞婚噺鍒ゅ畾鏄惁鍊煎緱杩涘叆鍚庣画閾捐矾锛堝け璐ヨ嚜鍔ㄦ斁琛岋級锛岄厤缃娇鐢?`QWEN_API_KEY/QWEN_API_BASE/QWEN_MODEL`锛屽苟鏀寔 fallback 閰嶇疆锛坄glm_fallback`锛夈€?
- LLM 瀹㈡埛绔細鏂板 `call_gpt4omini`锛圓izex锛変笌 `call_qwen`锛沗scripts/smoke_llm_clients_smoke.py` 鎻愪緵杩為€氭€у啋鐑燂紱缂?Key 鏃舵祴璇曡嚜鍔ㄨ烦杩囥€?
- 鍐崇瓥鎸佷箙鍖栵細`ai_decisions` 璁板綍澧炲姞 `model_name/committee_id/weight/is_final`锛屼細钀戒笁鏉℃ā鍨嬭褰?+ 涓€鏉″鍛樹細鏈€缁堢粨鏋滐紙鎴栧墠缃鍛樹細鎬荤粨锛夈€?
- 閫氱煡锛氶涔﹀崱鐗囨帹閫佸け璐ヤ細璁板綍 warning锛屼究浜庢帓闅滐紱鍙戦€佹椂鏄惧紡浣跨敤 UTF-8銆?
- MT5 琛屾儏婧愶細榛樿鍚敤 `mt5_api`锛?price /ohlc锛夛紝tick_volume 鏇挎崲 volume锛屾椂闂存埑鎸夌瀵归綈銆?
- 娴嬭瘯鐜扮姸锛歚python -m pytest --disable-warnings` 鍏ㄩ噺閫氳繃锛涜嫢闇€鍔犺浇 .env锛屽彲鐢?`python -m dotenv run -- python -m pytest tests/test_llm_clients_smoke.py --disable-warnings --maxfail=1` 杩愯 LLM 鍐掔儫銆?
- Performance: live/review closes now record to performance tables; StateManager base equity comes from backtest.initial_equity and persists.

鍐崇瓥娴佺▼锛堜笉璁蹭唬鐮侊級
------------------
1. 鏁版嵁涓庣壒寰侊細绠＄嚎鎸?30m/1h/4h/1d 閲囨牱琛屾儏锛岀敓鎴愬鍛ㄦ湡鐗瑰緛銆佺粨鏋勩€佽秼鍔裤€佸競鍦烘ā寮忔爣绛撅紝骞堕檮杩戞湡 OHLC 鐗囨銆?
2. 棰勮繃婊わ紙Qwen锛夛細蹇€熷垽鏂綋娆¤鎯呮槸鍚﹀€煎緱娣卞害鎺ㄧ悊銆傚け璐ラ粯璁ゆ斁琛岋紱鏄庣‘缁欏嚭 `should_call_deepseek=False` 鏃惰烦杩囨湰杞€?
3. 鍓嶇疆闂ㄥ崼锛圔1锛夛細gpt-4o-mini + Qwen 灏忓鍛樹細鎶曠エ鏄惁璋冪敤 DeepSeek锛屽啿绐佹垨缃俊搴︿笉瓒崇洿鎺ヨ繑鍥?`no-trade`锛屽悓鏃跺啓鍏?`committee_front` 鍏冧俊鎭€?
4. 娣卞害鍐崇瓥涓庣粓灞€濮斿憳浼氾細DeepSeek 浜у嚭缁撴瀯鍖栨墽琛屾柟妗堬紱鑻ュ紑鍚妯″瀷濮斿憳浼氾紝鍐嶇敱 DeepSeek + gpt-4o-mini + Qwen 澶嶆牳鎶曠エ锛岃緭鍑烘渶缁堟柟鍚?缃俊搴?鍐茬獊绛夌骇銆?
5. 瀹夊叏妫€鏌ワ細鍩虹鍚堟硶鎬т笌瀹夊叏鍏滃簳锛堜环鏍奸『搴忋€丷R 涓嬮檺绛夛級銆?
6. 鎵ц涓庡悓姝ワ細鍐欏叆 StateManager锛屾帹閫侀涔﹀崱鐗囷紝璁板綍鍏变韩璁板繂锛涚焊鐩?瀹炵洏鎸夐厤缃悓姝ユ寔浠撲笌澶嶈瘎銆?
7. 鍥炴祴锛氫笌瀹炵洏鍏辩敤鍚屼竴鍐崇瓥閾撅紙鍚杩囨护/鍓嶇疆闂ㄥ崼/濮斿憳浼氾級锛岀敤妯℃嫙鎾悎缁熻缁╂晥銆?

閰嶇疆瑕佺偣
--------
- 鐜鍙橀噺锛氬鍒?`.env.example` 鍒?`.env`锛岃嚦灏戣缃? 
  - DeepSeek锛歚DEEPSEEK_API_KEY`锛堝彲閫?`DEEPSEEK_API_BASE`锛? 
  - gpt-4o-mini锛圓izex锛夛細`AIZEX_API_KEY`锛宍AIZEX_API_BASE`锛圓izex 鎺у埗鍙扮粰鍑虹殑 base锛? 
  - Qwen锛歚QWEN_API_KEY`锛宍QWEN_API_BASE`锛堥粯璁?`https://api.ezworkapi.top/v1/chat/completions`锛夛紝`QWEN_MODEL`锛堥粯璁?`qwen-turbo-2025-07-15`锛? 
  - 椋炰功锛歚LARK_WEBHOOK`锛堝彲閫?`LARK_SIGNING_SECRET`锛? 
  - 鏁版嵁婧愶細濡備娇鐢?MT5锛岄厤缃?`data.mt5_api.base_url`锛岀鍙风敤 MT5 鍚堢害鍚嶏紙`BTCUSDm`/`ETHUSDm`/`XAUUSDm`锛?
- 寮€鍏筹細`enable_multi_model_committee` 鎺у埗鏄惁浣跨敤涓夋ā鍨嬪鍛樹細锛涢杩囨护寮€鍏冲湪 `config/config.yaml` 鐨?`glm_filter.enabled`锛堝凡鍒囧埌 Qwen 瀹炵幇锛屼絾淇濈暀瀛楁鍚嶅吋瀹癸級銆?
- CLI 绀轰緥锛? 
  - 鍥炴祴锛歚python -m coin_dash.cli backtest --symbol BTCUSDm --csv data/sample/BTCUSDT_30m_2025-10_11.csv --deepseek`  
  - 瀹炴椂鍗曟锛歚python -m coin_dash.cli live --symbols BTCUSDm`  
  - 寰幆瀹炴椂锛歚python -m coin_dash.cli live --symbols BTCUSDm,ETHUSDm --loop`  
  - 椋炰功鍗＄墖鑷锛歚python -m coin_dash.cli cards-test --symbol BTCUSDm`  
  - 涓€閿钩浠擄細`python -m coin_dash.cli close-all --symbols BTCUSDm,ETHUSDm`

鐩綍閫熻
--------
- `coin_dash/data/` 鏁版嵁鎷夊彇涓庨噸閲囨牱
- `coin_dash/features/` 澶氬懆鏈熺壒寰併€佺粨鏋勩€佽秼鍔裤€佸競鍦烘ā寮?
- `coin_dash/ai/` DeepSeek 閫傞厤銆侀杩囨护锛圦wen锛夈€佸妯″瀷濮斿憳浼?
- `coin_dash/runtime/orchestrator.py` 瀹炴椂璋冨害銆佷俊鍙?澶嶈瘎/绾哥洏/閫氱煡
- `coin_dash/backtest/engine.py` 鍥炴祴涓诲惊鐜?
- `coin_dash/exec/paper.py` 绾哥洏鎾悎
- `coin_dash/notify/lark.py` 椋炰功鍗＄墖
- `coin_dash/state_manager.py` 鐘舵€佷笌缁╂晥
- `coin_dash/db/` 鏁版嵁搴撳瓨鍙栦笌鍐崇瓥鎸佷箙鍖?
- `scripts/smoke_llm_clients.py` LLM 杩為€氭€у啋鐑熻剼鏈?

娴嬭瘯
----
- 鍏ㄩ噺锛歚python -m pytest --disable-warnings`锛堝綋鍓?15 椤癸細13 閫氳繃锛? 鏉?LLM 鍐掔儫鍦ㄧ己 Key 鏃惰烦杩囷級
- LLM 鍐掔儫锛堝姞杞?.env锛夛細`python -m dotenv run -- python -m pytest tests/test_llm_clients_smoke.py --disable-warnings --maxfail=1`
- 鍐掔儫鑴氭湰锛歚python -m dotenv run -- python scripts/smoke_llm_clients.py`

娉ㄦ剰
----
- 妯″瀷鍐崇瓥鐩存帴褰卞搷浜ゆ槗锛岃鑷鍋氬ソ椋庨櫓鎺у埗涓庨搴﹂檺鍒躲€?
- 鏁版嵁缂哄彛/鏃犳晥浠锋牸浼氳杩囨护锛涢杩囨护澶辫触浼氭斁琛?DeepSeek銆?
- 绾哥洏鎸佷箙鍖栨殏鏈法杩涚▼淇濈暀锛屽闇€闀挎湡杩愯璇疯嚜琛屾墿灞曘€?

鏇村鏂囨。
--------
- `config/config.yaml`锛氬叧閿弬鏁扮ず渚?
- `docs/glm_filter.md`锛氶杩囨护缁撴瀯璇存槑锛堝瓧娈靛悕娌跨敤鏃хО锛岀幇鐢?Qwen 鎻愪緵锛?

Position policy
---------------
- 瀹炵洏/鍥炴祴鍧囬檺鍒跺悓涓€甯佺鍚屾椂浠呬繚鐣欎竴鍗曪細鍙戠幇宸叉湁鎸佷粨/淇″彿浼氳烦杩囨柊寮€浠擄紝閬垮厤澶氬崟鍙犲姞銆?

Testing status
--------------
- 褰撳墠 16 椤规祴璇曞叏閮ㄩ€氳繃锛歱ython -m pytest --disable-warnings锛圠LM 鍐掔儫鍦ㄧ己 Key 鏃惰嚜鍔ㄨ烦杩囷級銆?
