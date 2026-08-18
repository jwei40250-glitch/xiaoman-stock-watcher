
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests

st.set_page_config(page_title="小满盯盘器", page_icon="📈", layout="centered")

DEFAULT_WATCHLIST = {
    "002407": {"name": "多氟多", "low": 37.50, "high": 38.00},
    "603286": {"name": "日盈电子", "low": 43.00, "high": 44.00},
    "002384": {"name": "东山精密", "low": 213.00, "high": 217.00},
    "588950": {"name": "科创50ETF景顺", "low": 1.80, "high": 1.83},
}

def market_prefix(code):
    return "1." + code if code.startswith(("5","6","9")) else "0." + code

@st.cache_data(ttl=20)
def get_quote(code):
    secid = market_prefix(code)
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"
    }
    r = requests.get(url, params=params, timeout=8)
    r.raise_for_status()
    d = r.json().get("data") or {}
    scale = 1000 if code.startswith(("5",)) else 100
    # Eastmoney ETF prices commonly use 1/1000, stocks 1/100.
    return {
        "name": d.get("f58", code),
        "price": (d.get("f43") or 0) / scale,
        "high": (d.get("f44") or 0) / scale,
        "low": (d.get("f45") or 0) / scale,
        "open": (d.get("f46") or 0) / scale,
        "prev": (d.get("f60") or 0) / scale,
        "pct": (d.get("f170") or 0) / 100,
    }

@st.cache_data(ttl=300)
def get_history(code, days=80):
    secid = market_prefix(code)
    end = datetime.now().strftime("%Y%m%d")
    beg = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "klt": "101", "fqt": "1",
        "beg": beg, "end": end,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = (r.json().get("data") or {}).get("klines") or []
    rows = []
    for line in data:
        x = line.split(",")
        rows.append([x[0], float(x[2]), float(x[3]), float(x[4]), float(x[5]), float(x[6])])
    df = pd.DataFrame(rows, columns=["日期","收盘","最高","最低","成交量","成交额"])
    if not df.empty:
        for n in (5,10,20):
            df[f"MA{n}"] = df["收盘"].rolling(n).mean()
    return df.tail(days)

def signal(price, ma5, ma10, low, high):
    if price <= 0:
        return "⚪ 暂无行情", "行情接口暂未返回有效价格"
    if low <= price <= high:
        if ma10 and price >= ma10:
            return "🟡 进入关注区", "已到关注价位；先观察企稳，不代表自动买入"
        return "🟠 进入关注区但偏弱", "价格到位，但仍在MA10下方，优先等确认"
    if ma5 and ma10 and price > ma5 > ma10:
        return "🟢 短线偏强", "趋势偏强；避免因怕踏空而追涨"
    if ma10 and price < ma10:
        return "🔴 MA10下方", "短线偏弱；保留现金，等待重新企稳"
    return "⚪ 观察", "未触发预设条件"

if "watchlist" not in st.session_state:
    st.session_state.watchlist = DEFAULT_WATCHLIST.copy()

st.title("📈 小满盯盘器 v0.1")
st.caption("老板负责休息，程序负责盯。仅用于行情观察和模拟记录，不自动下单。")

tab1, tab2, tab3 = st.tabs(["👀 自选盯盘", "🧪 模拟账户", "⚙️ 设置"])

with tab1:
    if st.button("🔄 刷新行情", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    for code, cfg in st.session_state.watchlist.items():
        try:
            q = get_quote(code)
            hist = get_history(code)
            ma5 = float(hist["MA5"].iloc[-1]) if len(hist) >= 5 and pd.notna(hist["MA5"].iloc[-1]) else None
            ma10 = float(hist["MA10"].iloc[-1]) if len(hist) >= 10 and pd.notna(hist["MA10"].iloc[-1]) else None
            ma20 = float(hist["MA20"].iloc[-1]) if len(hist) >= 20 and pd.notna(hist["MA20"].iloc[-1]) else None
            status, note = signal(q["price"], ma5, ma10, cfg["low"], cfg["high"])

            with st.container(border=True):
                st.subheader(f'{cfg["name"]} · {code}')
                c1, c2 = st.columns(2)
                c1.metric("现价", f'{q["price"]:.3f}' if code.startswith("5") else f'{q["price"]:.2f}',
                          f'{q["pct"]:+.2f}%')
                c2.metric("关注区", f'{cfg["low"]} ~ {cfg["high"]}')
                st.write(f"**{status}**")
                st.caption(note)
                m1,m2,m3 = st.columns(3)
                m1.metric("MA5", "-" if ma5 is None else f"{ma5:.3f}")
                m2.metric("MA10", "-" if ma10 is None else f"{ma10:.3f}")
                m3.metric("MA20", "-" if ma20 is None else f"{ma20:.3f}")
                if not hist.empty:
                    chart = hist.set_index("日期")[["收盘","MA5","MA10","MA20"]].dropna(how="all")
                    st.line_chart(chart)
        except Exception as e:
            st.error(f"{cfg['name']} 行情读取失败：{e}")

with tab2:
    st.info("v0.1 先做手工模拟记账。v0.2 再加入策略自动回测和模拟成交。")
    capital = st.number_input("模拟初始资金（元）", min_value=1000, value=100000, step=1000)
    code = st.text_input("模拟股票代码", "002407")
    price = st.number_input("模拟成交价", min_value=0.001, value=37.50, step=0.01)
    qty = st.number_input("模拟数量", min_value=100, value=1000, step=100)
    st.write(f"模拟占用资金：**¥{price*qty:,.2f}**")
    st.progress(min((price*qty)/capital, 1.0), text=f"仓位约 {(price*qty)/capital:.1%}")

with tab3:
    st.write("### 添加 / 修改自选")
    code = st.text_input("代码", "002407", key="set_code").strip()
    name = st.text_input("名称", "多氟多")
    c1,c2 = st.columns(2)
    low = c1.number_input("关注区下限", value=37.50, step=0.01)
    high = c2.number_input("关注区上限", value=38.00, step=0.01)
    if st.button("保存到本次会话"):
        st.session_state.watchlist[code] = {"name": name, "low": float(low), "high": float(high)}
        st.success("已保存。")
    st.caption("Community Cloud重启后会恢复默认列表；v0.2会加入持久化保存。")

st.divider()
st.caption("⚠️ 这不是投资建议，也不是券商交易系统。免费公开行情可能延迟或临时不可用；任何真实交易请在券商App中自行确认。")
