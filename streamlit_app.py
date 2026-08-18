import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import requests
import re

st.set_page_config(page_title="小满盯盘器 v3.2", page_icon="📈", layout="centered")

DEFAULT_WATCHLIST = {
    "002407": {"name": "多氟多", "low": 37.50, "high": 38.00},
    "603286": {"name": "日盈电子", "low": 43.00, "high": 44.00},
    "002384": {"name": "东山精密", "low": 213.00, "high": 217.00},
    "588950": {"name": "科创50ETF景顺", "low": 1.80, "high": 1.83},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
    "Referer": "https://gu.qq.com/",
}

def market_prefix(code):
    return "1." + code if code.startswith(("5", "6", "9")) else "0." + code

def tx_symbol(code):
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code

@st.cache_data(ttl=15, show_spinner=False)
def get_quote_tencent(code):
    url = f"https://qt.gtimg.cn/q={tx_symbol(code)}"
    r = requests.get(url, headers=HEADERS, timeout=8)
    r.raise_for_status()
    r.encoding = "gbk"
    txt = r.text
    m = re.search(r'="(.*)"', txt)
    if not m:
        raise ValueError("腾讯行情返回格式异常")
    x = m.group(1).split("~")
    if len(x) < 45:
        raise ValueError("腾讯行情字段不足")
    price = float(x[3] or 0)
    prev = float(x[4] or 0)
    pct = ((price / prev - 1) * 100) if prev else 0
    return {"name": x[1] or code, "price": price, "prev": prev, "pct": pct, "source": "腾讯行情"}

@st.cache_data(ttl=15, show_spinner=False)
def get_quote_eastmoney(code):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {"secid": market_prefix(code), "fields": "f43,f57,f58,f60,f170"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=8)
    r.raise_for_status()
    d = r.json().get("data") or {}
    scale = 1000 if code.startswith("5") else 100
    return {
        "name": d.get("f58") or code,
        "price": (d.get("f43") or 0) / scale,
        "prev": (d.get("f60") or 0) / scale,
        "pct": (d.get("f170") or 0) / 100,
        "source": "东方财富备用",
    }

def get_quote(code):
    errors = []
    for fn in (get_quote_tencent, get_quote_eastmoney):
        try:
            q = fn(code)
            if q["price"] > 0:
                return q
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError("；".join(errors) or "实时行情不可用")

@st.cache_data(ttl=300, show_spinner=False)
def get_history_tencent(code, days=100):
    symbol = tx_symbol(code)
    # 腾讯日K接口：前复权日线
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "param": f"{symbol},day,,,{days},qfq",
        "_var": "kline_dayqfq",
    }
    r = requests.get(url, params=params, headers=HEADERS, timeout=10)
    r.raise_for_status()
    txt = r.text
    # 响应可能带 var xxx= 前缀
    if "=" in txt and not txt.lstrip().startswith("{"):
        txt = txt.split("=", 1)[1].strip().rstrip(";")
    data = requests.models.complexjson.loads(txt)
    node = (data.get("data") or {}).get(symbol) or {}
    lines = node.get("qfqday") or node.get("day") or []
    rows = []
    for x in lines:
        if len(x) >= 6:
            rows.append([x[0], float(x[2]), float(x[3]), float(x[4]), float(x[5])])
    if not rows:
        raise ValueError("腾讯历史K线为空")
    df = pd.DataFrame(rows, columns=["日期", "收盘", "最高", "最低", "成交量"])
    return prepare_history(df, days)

@st.cache_data(ttl=300, show_spinner=False)
def get_history_eastmoney(code, days=100):
    end = datetime.now().strftime("%Y%m%d")
    beg = (datetime.now() - timedelta(days=days * 3)).strftime("%Y%m%d")
    hosts = [
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    ]
    params = {
        "secid": market_prefix(code), "klt": "101", "fqt": "1",
        "beg": beg, "end": end,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    last = None
    for url in hosts:
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            r.raise_for_status()
            lines = (r.json().get("data") or {}).get("klines") or []
            rows = []
            for line in lines:
                x = line.split(",")
                rows.append([x[0], float(x[2]), float(x[3]), float(x[4]), float(x[5])])
            if rows:
                return prepare_history(pd.DataFrame(rows, columns=["日期","收盘","最高","最低","成交量"]), days)
        except Exception as e:
            last = e
    raise RuntimeError(str(last) if last else "东方财富历史K线为空")

def prepare_history(df, days):
    df = df.drop_duplicates("日期").sort_values("日期")
    for n in (5, 10, 20):
        df[f"MA{n}"] = df["收盘"].rolling(n).mean()
    return df.tail(days)

def get_history(code, days=80):
    errors = []
    for fn, src in ((get_history_tencent, "腾讯K线"), (get_history_eastmoney, "东方财富K线")):
        try:
            df = fn(code, max(days, 40))
            if not df.empty:
                return df.tail(days), src
        except Exception as e:
            errors.append(f"{src}: {e}")
    return pd.DataFrame(), " / ".join(errors)

def signal(price, ma5, ma10, low, high):
    if price <= 0:
        return "⚪ 暂无行情", "行情接口暂未返回有效价格"
    if low <= price <= high:
        if ma10 is not None and price >= ma10:
            return "🟡 进入关注区", "价格进入关注区，并位于 MA10 上方；继续观察确认。"
        return "🟠 进入关注区但偏弱", "价格已到关注区；若仍在 MA10 下方，优先等待企稳。"
    if ma5 is not None and ma10 is not None and price > ma5 > ma10:
        return "🟢 短线偏强", "短线结构偏强；避免因怕踏空而追涨。"
    if ma10 is not None and price < ma10:
        return "🔴 MA10下方", "短线偏弱；等待重新企稳。"
    return "⚪ 观察", "暂未触发预设条件。"

if "watchlist" not in st.session_state:
    st.session_state.watchlist = DEFAULT_WATCHLIST.copy()

st.title("📈 小满盯盘器 v3.2")
st.caption("老板负责休息，小满负责盯。实时行情双源容错 + 历史K线双源容错；只观察和模拟，不自动下真实订单。")

tab1, tab2, tab3, tab4 = st.tabs(["👀 盯盘", "💰 5万计划", "🧪 模拟账户", "⚙️ 设置"])

with tab1:
    if st.button("🔄 刷新行情", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    for code, cfg in st.session_state.watchlist.items():
        with st.container(border=True):
            st.subheader(f'{cfg["name"]} · {code}')
            try:
                q = get_quote(code)
                hist, hist_source = get_history(code)
                ma5 = ma10 = ma20 = None
                if not hist.empty:
                    last = hist.iloc[-1]
                    ma5 = float(last["MA5"]) if pd.notna(last["MA5"]) else None
                    ma10 = float(last["MA10"]) if pd.notna(last["MA10"]) else None
                    ma20 = float(last["MA20"]) if pd.notna(last["MA20"]) else None

                c1, c2 = st.columns(2)
                fmt = "{:.3f}" if code.startswith("5") else "{:.2f}"
                c1.metric("现价", fmt.format(q["price"]), f'{q["pct"]:+.2f}%')
                c2.metric("关注区", f'{cfg["low"]} ~ {cfg["high"]}')
                st.caption(f'实时数据源：{q["source"]}')

                status, note = signal(q["price"], ma5, ma10, cfg["low"], cfg["high"])
                st.write(f"### {status}")
                st.caption(note)

                if not hist.empty:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("MA5", "-" if ma5 is None else fmt.format(ma5))
                    m2.metric("MA10", "-" if ma10 is None else fmt.format(ma10))
                    m3.metric("MA20", "-" if ma20 is None else fmt.format(ma20))
                    st.caption(f"历史数据源：{hist_source}")
                    chart = hist.set_index("日期")[["收盘","MA5","MA10","MA20"]]
                    st.line_chart(chart, use_container_width=True)
                else:
                    st.info("实时行情正常；历史K线两个数据源当前都不可用，稍后刷新即可，不影响现价盯盘。")
                    with st.expander("查看历史接口状态"):
                        st.caption(hist_source)
            except Exception as e:
                st.error(f"实时行情读取失败：{e}")
                st.caption("请以券商 App 行情为准。")

with tab2:
    st.subheader("💰 5万元仓位计划")
    st.caption("这是仓位计算器，不是自动交易策略。")
    total = st.number_input("计划总资金（元）", min_value=1000, value=50000, step=1000)
    reserve = st.slider("预留现金", 0, 80, 30, 5)
    usable = total * (100-reserve)/100
    st.metric("可计划使用", f"¥{usable:,.0f}", f"预留 ¥{total-usable:,.0f}")
    st.progress((100-reserve)/100, text=f"计划最高仓位 {(100-reserve)}%")
    st.write("**参考分批：** 首笔 30% → 确认后 20% → 再确认 20%，其余保持现金。")
    st.caption("具体买卖仍由你在券商 App 自行决定和确认。")

with tab3:
    st.info("模拟账户只做计算和记录，不连接券商。")
    capital = st.number_input("模拟初始资金（元）", min_value=1000, value=50000, step=1000)
    sim_code = st.text_input("股票代码", "002407")
    price = st.number_input("模拟成交价", min_value=0.001, value=37.50, step=0.01)
    qty = st.number_input("模拟数量", min_value=100, value=500, step=100)
    used = price * qty
    st.metric("模拟占用资金", f"¥{used:,.2f}")
    st.progress(min(used/capital, 1.0), text=f"仓位约 {used/capital:.1%}")

with tab4:
    st.write("### 添加 / 修改自选")
    code = st.text_input("代码", "002407", key="set_code").strip()
    name = st.text_input("名称", "多氟多")
    c1, c2 = st.columns(2)
    low = c1.number_input("关注区下限", value=37.50, step=0.01)
    high = c2.number_input("关注区上限", value=38.00, step=0.01)
    if st.button("保存到本次会话", use_container_width=True):
        st.session_state.watchlist[code] = {"name": name, "low": float(low), "high": float(high)}
        st.success("已保存。")
    st.caption("Community Cloud 重启后恢复默认列表。")

st.divider()
st.caption("⚠️ 仅供行情观察、仓位计算和模拟记录，不构成投资建议。免费公开行情可能延迟或临时不可用；真实交易请以券商 App 为准。")
