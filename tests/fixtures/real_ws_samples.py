"""REAL SAMPLE, SSI WebSocket 2026-11-17.

Frames copied unchanged (credentials masked, none present) from data/smoke/ws_20261117T090521.jsonl, a real
connection to wss://stream.ssi.com.vn/ws/v3. They exist ONLY to test frame structure. Do not present them as market
data and do not use them for any analysis.
"""

# REAL SAMPLE, SSI WebSocket 2026-11-17: SUBSCRIBE ack, received_at 2026-11-17T09:05:22.187+07:00
SUBSCRIBE_ACK = '{"method":"SUBSCRIBE","channel":"DATA","status":"ok","message":"Subscribed to 10 topic(s)"}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: LIST_SUBSCRIPTION reply, received_at 2026-11-17T09:05:22.258+07:00
LIST_SUBSCRIPTION_REPLY = '{"trading":"","data":"quote.VIC;trade.VIC;market.VIC;quote.HPG;trade.HPG;market.HPG;quote.FPT;trade.FPT;market.FPT;market.flag"}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: quote HPG, received_at 2026-11-17T09:05:24.012+07:00
QUOTE_HPG = '{"channel":"DATA","topic":"quote.HPG","data":{"s":"HPG","t":"2026/11/17 09:05:26","bids":[["20850","179700"],["20800","280400"],["20750","63500"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]],"asks":[["20950","3700"],["21000","6700"],["21050","21700"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]]}}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: quote HPG (a later one), received_at 2026-11-17T09:05:41.871+07:00
QUOTE_HPG_LATER = '{"channel":"DATA","topic":"quote.HPG","data":{"s":"HPG","t":"2026/11/17 09:05:44","bids":[["20850","182500"],["20800","280400"],["20750","64000"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]],"asks":[["20950","3700"],["21000","6700"],["21050","21700"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]]}}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: quote FPT, received_at 2026-11-17T09:05:26.642+07:00
QUOTE_FPT = '{"channel":"DATA","topic":"quote.FPT","data":{"s":"FPT","t":"2026/11/17 09:05:29","bids":[["49400","2000"],["49350","300"],["49300","25600"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]],"asks":[["49450","1400"],["49500","600"],["49600","300"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]]}}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: quote VIC, received_at 2026-11-17T09:05:28.234+07:00
QUOTE_VIC = '{"channel":"DATA","topic":"quote.VIC","data":{"s":"VIC","t":"2026/11/17 09:05:30","bids":[["247200","100"],["247000","1100"],["246000","1000"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]],"asks":[["247800","4500"],["248000","1500"],["248500","300"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"],["0","0"]]}}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: trade FPT, with milliseconds in t, received_at 2026-11-17T09:15:00.268+07:00
TRADE_FPT_MS = '{"channel":"DATA","topic":"trade.FPT","data":{"s":"FPT","t":"2026/11/17 09:15:00.005","p":"49400","q":"100","a":"49400","si":"B","o":"49400","h":"49400","l":"49400","v":"100"}}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: trade HPG, received_at 2026-11-17T09:15:03.055+07:00
TRADE_HPG = '{"channel":"DATA","topic":"trade.HPG","data":{"s":"HPG","t":"2026/11/17 09:15:00.005","p":"20950","q":"400","a":"20950","si":"S","o":"20950","h":"20950","l":"20950","v":"400"}}'

# REAL SAMPLE, SSI WebSocket 2026-11-17: market.FLAG (session flag; upper-case topic), received_at 2026-11-17T09:14:57.924+07:00
MARKET_FLAG_UPPER = '{"channel":"DATA","topic":"market.FLAG","data":{"b":"HOSE","t":"2026/11/17 09:15:00","f":"LO"}}'

ALL_FRAMES = [SUBSCRIBE_ACK, LIST_SUBSCRIPTION_REPLY, QUOTE_HPG, QUOTE_HPG_LATER, QUOTE_FPT, QUOTE_VIC, TRADE_FPT_MS, TRADE_HPG, MARKET_FLAG_UPPER]
