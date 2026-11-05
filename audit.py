#!/usr/bin/env python3
"""
FlapJax treasury FLAPJAX outflows for one Central Time (UTC-5) day.

Usage:  python3 scripts/flapjax_day_audit.py 2026-11-02

Prints, for every FLAPJAX (BEP-20) Transfer out of the FlapJax treasury during that
COT day: tx hash, block, COT time, recipient, raw 18-decimal amount. Then reports,
per recipient, the current BSC/Base state used to decide whether a "first BNB funder"
can exist at all (an EOA with nonce 0 and balance 0 cannot have been funded and then
spent the BNB, because spending requires an outgoing tx).

No API key, no indexer. Public nodes only. Writes JSON next to this run for reuse.
"""
import datetime
import json
import sys
import time
import urllib.request

NODES = [
    "https://bsc.meowrpc.com",
    "https://bsc-rpc.publicnode.com",
    "https://rpc.48.club",
    "https://bsc.blockrazor.xyz",
]
TOKEN = "0x90c8889f428F9Ebb77BB8f15CAD3a50a9aC680df"
TREASURY = "0x7C34E9e21eE28A49Ff0b84B61774119E6633359f"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PAD_TREASURY = "0x" + "0" * 24 + TREASURY[2:].lower()
CHUNK = 20_000


def rpc(method, params, tries=5):
    last = None
    for attempt in range(tries):
        node = NODES[attempt % len(NODES)]
        try:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
            req = urllib.request.Request(node, data=body, headers={
                "content-type": "application/json", "user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/131"})
            with urllib.request.urlopen(req, timeout=40) as r:
                out = json.load(r)
            if "error" in out:
                raise RuntimeError(out["error"])
            if out.get("result") is None:
                raise RuntimeError("null result (node lacks that block range)")
            return out["result"]
        except Exception as e:  # rotate node, back off
            last = e
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"{method} failed: {last}")


def block_ts(block):
    return int(rpc("eth_getBlockByNumber", [hex(block), False])["timestamp"], 16)


def first_block_at_or_after(target_ts):
    lo, hi = 1, int(rpc("eth_blockNumber", []), 16)
    while lo < hi:
        mid = (lo + hi) // 2
        if block_ts(mid) < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def main(day):
    d = datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    t0 = int((d + datetime.timedelta(hours=5)).timestamp())          # 00:00 COT = 05:00Z
    t1 = int((d + datetime.timedelta(days=1, hours=5)).timestamp()) - 1
    b0 = first_block_at_or_after(t0)
    b1 = first_block_at_or_after(t1 + 1) - 1
    print(json.dumps({"day_cot": day, "first_block": b0, "last_block": b1,
                      "first_block_ts": t0, "last_block_ts": t1}))

    logs, cur = [], b0
    while cur <= b1:
        end = min(cur + CHUNK - 1, b1)
        logs += rpc("eth_getLogs", [{"fromBlock": hex(cur), "toBlock": hex(end),
                                     "address": TOKEN, "topics": [TRANSFER, PAD_TREASURY]}])
        cur = end + 1

    rows, total = [], 0
    for lg in logs:
        blk = int(lg["blockNumber"], 16)
        raw = int(lg["data"], 16)
        total += raw
        ts = block_ts(blk)
        cot = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc) - datetime.timedelta(hours=5)
        rows.append({"tx": lg["transactionHash"], "block": blk,
                     "time_cot": cot.strftime("%Y-%m-%d %H:%M:%S -05:00"),
                     "recipient": "0x" + lg["topics"][2][-40:], "amount_raw": str(raw)})

    print(json.dumps({"transfers": rows, "total_raw": str(total),
                      "distinct_recipients": len({r["recipient"] for r in rows})}, indent=1))

    for r in rows:
        a = r["recipient"]
        bal = int(rpc("eth_getBalance", [a, "latest"]), 16)
        nonce = int(rpc("eth_getTransactionCount", [a, "latest"]), 16)
        code = rpc("eth_getCode", [a, "latest"])
        held = int(rpc("eth_call", [{"to": TOKEN,
                                     "data": "0x70a08231" + "0" * 24 + a[2:].lower()}, "latest"]), 16)
        print(json.dumps({"recipient": a, "bnb_wei": bal, "bsc_nonce": nonce,
                          "code": code[:12], "flapjax_now_raw": str(held)}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-11-02")
