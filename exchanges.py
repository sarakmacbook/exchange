import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs
import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
           "Accept": "application/json", "Content-Type": "application/json"}

@dataclass
class Merchant:
    exchange: str; merchant_id: str; nickname: str = ""; asset: str = "USDT"; fiat: str = "USD"; url: str = ""
    @property
    def key(self): return f"{self.exchange}:{self.merchant_id}:{self.asset}:{self.fiat}"

# ---------- URL -> Merchant (paste any public merchant profile link) ----------
def parse_url(url: str, asset: str, fiat: str):
    p = urlparse(url.strip()); host = p.netloc.lower(); qs = parse_qs(p.query)
    if "binance" in host and qs.get("advertiserNo"):
        return Merchant("binance", qs["advertiserNo"][0], asset=asset, fiat=fiat, url=url)
    if "bybit" in host:
        m = re.search(r"/profile/(\d+)(?:/([A-Z]+)/([A-Z]+))?", p.path)
        if m: return Merchant("bybit", m.group(1), asset=m.group(2) or asset, fiat=m.group(3) or fiat, url=url)
    if "okx" in host and qs.get("publicUserId"):
        return Merchant("okx", qs["publicUserId"][0], asset=asset, fiat=fiat, url=url)
    if "bitget" in host:
        m = re.search(r"/merchant/([\w\-]+)", p.path)
        mid = m.group(1) if m else qs.get("userId", [None])[0]
        if mid: return Merchant("bitget", mid, asset=asset, fiat=fiat, url=url)
    return None

# ---------- Fetch: returns {"sell": price|None, "buy": price|None, "error": str|None} ----------
# "sell" = merchant SELLS (you buy) = best selling price ; "buy" = merchant BUYS (you sell)
async def fetch(c: httpx.AsyncClient, m: Merchant) -> dict:
    try:
        fn = {"binance": _binance, "bybit": _bybit, "okx": _okx, "bitget": _bitget}[m.exchange]
        return {"sell": await fn(c, m, "sell"), "buy": await fn(c, m, "buy"), "error": None}
    except Exception as e:
        return {"sell": None, "buy": None, "error": str(e)[:80]}

def _best(prices, side):
    return (min if side == "sell" else max)(prices) if prices else None

async def _binance(c, m, side):
    tt = "BUY" if side == "sell" else "SELL"          # taker view
    prices = []
    for page in (1, 2, 3):
        r = await c.post("https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                         json={"asset": m.asset, "fiat": m.fiat, "tradeType": tt, "page": page, "rows": 20, "payTypes": []})
        data = r.json().get("data") or []
        for a in data:
            if a["advertiser"]["userNo"] == m.merchant_id:
                m.nickname = m.nickname or a["advertiser"]["nickName"]; prices.append(float(a["adv"]["price"]))
        if len(data) < 20: break
    return _best(prices, side)

async def _bybit(c, m, side):
    r = await c.post("https://api2.bybit.com/fiat/otc/item/online",
                     json={"userId": m.merchant_id, "tokenId": m.asset, "currencyId": m.fiat, "payment": [],
                           "side": "1" if side == "sell" else "0", "size": "50", "page": "1", "amount": ""})
    items = (r.json().get("result") or {}).get("items") or []
    if items: m.nickname = m.nickname or items[0].get("nickName", "")
    return _best([float(i["price"]) for i in items], side)

async def _okx(c, m, side):
    r = await c.get("https://www.okx.com/v3/c2c/tradingOrders/books",
                    params={"quoteCurrency": m.fiat, "baseCurrency": m.asset, "side": side, "paymentMethod": "all",
                            "userType": "all", "showTrade": "false", "receivingAds": "false"})
    ads = [a for a in (r.json().get("data") or {}).get(side, []) if a.get("publicUserId") == m.merchant_id]
    if ads: m.nickname = m.nickname or ads[0].get("nickName", "")
    return _best([float(a["price"]) for a in ads], side)

async def _bitget(c, m, side):
    r = await c.post("https://www.bitget.com/v1/p2p/pub/adv/queryAdvList",
                     json={"side": 1 if side == "sell" else 2, "pageNo": 1, "pageSize": 50,
                           "coinCode": m.asset, "fiatCode": m.fiat, "languageType": 6})
    ads = [a for a in (r.json().get("data") or {}).get("dataList", []) if str(a.get("userId")) == m.merchant_id]
    if ads: m.nickname = m.nickname or ads[0].get("nickName", "")
    return _best([float(a["price"]) for a in ads], side)
