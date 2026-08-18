import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import requests, re

st.set_page_config(page_title="小满盯盘器", page_icon="📈", layout="centered")

DEFAULT_WATCHLIST = {
    "002407": {"name": "多氟多", "low": 37.50, "high": 38.00},
    "603286": {"name": "日盈电子", "low": 43.00, "high": 44.00},
    "002384": {"name": "东山精密", "low": 213.00, "high": 217.00},
    "588950": {"name": "科创50ETF景顺", "low": 1.80, "high": 1.83},
}
HEADERS={"User-Agent":"Mozilla/5.0","Referer":"https://gu.qq.com/"}

def em_secid(code):
    return ("1." if code.startswith(("5","6","9")) else "0.") + code

def qq_symbol(code):
    return ("sh" if code.startswith(("5","6","9")) else "sz") + code

def f(x, default=0.0):
    try: return float(x)
    except: return default

@st.cache_data(ttl=15, show_spinner=False)
def quote_qq(code):
    r=requests.get("https://qt.gtimg.cn/q="+qq_symbol(code),headers=HEADERS,timeout=6)
    r.raise_for_status(); r.encoding="gbk"
    m=re.search(r'="(.*)"',r.text)
    if not m: raise ValueError("bad quote")
    x=m.group(1).split("~")
    if len(x)<35 or f(x[3])<=0: raise ValueError("empty quote")
    return {"name":x[1] or code,"price":f(x[3]),"prev":f(x[4]),"open":f(x[5]),
            "high":f(x[33]),"low":f(x[34]),"pct":f(x[32]),"source":"腾讯行情"}

@st.cache_data(ttl=20, show_spinner=False)
def quote_em(code):
    url="https://push2delay.eastmoney.com/api/qt/stock/get"
    params={"secid":em_secid(code),"fltt":"2","invt":"2",
            "fields":"f43,f44,f45,f46,f57,f58,f60,f170"}
    h=dict(HEADERS); h["Referer"]="https://quote.eastmoney.com/"
    r=requests.get(url,params=params,headers=h,timeout=6); r.raise_for_status()
    d=r.json().get("data") or {}
    if f(d.get("f43"))<=0: raise ValueError("empty quote")
    return {"name":d.get("f58") or code,"price":f(d.get("f43")),"prev":f(d.get("f60")),
            "open":f(d.get("f46")),"high":f(d.get("f44")),"low":f(d.get("f45")),
            "pct":f(d.get("f170")),"source":"东方财富备用"}

def get_quote(code):
    for fn in (quote_qq, quote_em):
        try: return fn(code)
        except: pass
    raise RuntimeError("quote unavailable")

@st.cache_data(ttl=300, show_spinner=False)
def get_history(code, days=80):
    end=datetime.now().strftime("%Y%m%d")
    beg=(datetime.now()-timedelta(days=days*3)).strftime("%Y%m%d")
    hosts=["push2his.eastmoney.com","7.push2his.eastmoney.com","33.push2his.eastmoney.com"]
    params={"secid":em_secid(code),"klt":"101","fqt":"1","beg":beg,"end":end,
            "lmt":str(days+25),"fields1":"f1,f2,f3,f4,f5,f6",
            "fields2":"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"}
    h=dict(HEADERS); h["Referer"]="https://quote.eastmoney.com/"
    for host in hosts:
        try:
            r=requests.get("https://"+host+"/api/qt/stock/kline/get",params=params,headers=h,timeout=7)
            r.raise_for_status()
            lines=(r.json().get("data") or {}).get("klines") or []
            if not lines: continue
            rows=[]
            for line in lines:
                x=line.split(",")
                rows.append([x[0],f(x[2]),f(x[3]),f(x[4]),f(x[5]),f(x[6])])
            df=pd.DataFrame(rows,columns=["日期","收盘","最高","最低","成交量","成交额"])
            for n in (5,10,20): df["MA"+str(n)]=df["收盘"].rolling(n).mean()
            return df.tail(days)
        except: pass
    return pd.DataFrame()

def signal(price,ma5,ma10,low,high):
    if low<=price<=high:
        if ma10 is not None and price<ma10: return "🟠 进入关注区但偏弱","价格到位，但仍在 MA10 下方，优先等确认"
        return "🟡 进入关注区","已到关注价位；先观察企稳，不代表自动买入"
    if ma5 is not None and ma10 is not None and price>ma5>ma10:
        return "🟢 短线偏强","趋势偏强；避免因怕踏空而追涨"
    if ma10 is not None and price<ma10:
        return "🔴 MA10下方","短线偏弱；保留现金，等待重新企稳"
    return "⚪ 观察","未触发预设条件"

if "watchlist" not in st.session_state:
    st.session_state.watchlist={k:v.copy() for k,v in DEFAULT_WATCHLIST.items()}

st.title("📈 小满盯盘器 v3.1")
st.caption("老板负责休息，小满负责盯。实时行情双源容错；只观察和模拟，不自动下真实订单。")
tab1,tab2,tab3,tab4=st.tabs(["👀 盯盘","💰 5万计划","🧪 模拟账户","⚙️ 设置"])

with tab1:
    if st.button("🔄 刷新行情",use_container_width=True):
        st.cache_data.clear(); st.rerun()
    for code,cfg in st.session_state.watchlist.items():
        with st.container(border=True):
            st.subheader(f'{cfg["name"]} · {code}')
            try:
                q=get_quote(code); hist=get_history(code)
                def ma(n):
                    col="MA"+str(n)
                    return float(hist[col].iloc[-1]) if not hist.empty and col in hist and pd.notna(hist[col].iloc[-1]) else None
                ma5,ma10,ma20=ma(5),ma(10),ma(20)
                status,note=signal(q["price"],ma5,ma10,cfg["low"],cfg["high"])
                c1,c2=st.columns(2); digits=3 if code.startswith("5") else 2
                c1.metric("现价",f'{q["price"]:.{digits}f}',f'{q["pct"]:+.2f}%')
                c2.metric("关注区",f'{cfg["low"]} ~ {cfg["high"]}')
                st.caption("数据源："+q["source"]); st.write("**"+status+"**"); st.caption(note)
                if not hist.empty:
                    a,b,c=st.columns(3)
                    a.metric("MA5","-" if ma5 is None else f"{ma5:.3f}")
                    b.metric("MA10","-" if ma10 is None else f"{ma10:.3f}")
                    c.metric("MA20","-" if ma20 is None else f"{ma20:.3f}")
                    st.line_chart(hist.set_index("日期")[["收盘","MA5","MA10","MA20"]])
                else:
                    st.info("实时行情正常；历史 K 线暂不可用，均线暂不显示。")
            except:
                st.warning("行情源暂时繁忙，稍后点“刷新行情”重试。")
                st.caption("真实交易请以券商 App 为准。")

with tab2:
    st.write("### 💰 5万元仓位计划")
    total=st.number_input("计划总资金（元）",min_value=1000,value=50000,step=1000)
    reserve=st.slider("预留现金",0,100,30,5)
    usable=total*(1-reserve/100)
    st.metric("可计划使用",f"¥{usable:,.0f}",f"预留 ¥{total-usable:,.0f}")
    names=list(st.session_state.watchlist.items()); default=int(100/max(len(names),1)); weights={}
    for code,cfg in names:
        weights[code]=st.slider(f'{cfg["name"]} · {code} 权重',0,100,default,5,key="w_"+code)
    if sum(weights.values())>100: st.warning("当前权重合计超过100%，请调低。")
    else:
        rows=[{"标的":cfg["name"],"代码":code,"计划金额":round(usable*weights[code]/100,2),
               "关注区":f'{cfg["low"]} ~ {cfg["high"]}'} for code,cfg in names]
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    st.caption("这是资金规划工具，不构成买入建议，也不会自动下单。")

with tab3:
    st.info("手工模拟记账区：不会连接券商，也不会产生真实交易。")
    capital=st.number_input("模拟初始资金（元）",min_value=1000,value=50000,step=1000)
    st.text_input("模拟股票代码","002407")
    price=st.number_input("模拟成交价",min_value=0.001,value=37.50,step=0.01)
    qty=st.number_input("模拟数量",min_value=100,value=1000,step=100)
    occupied=price*qty
    st.write(f"模拟占用资金：**¥{occupied:,.2f}**")
    st.progress(min(occupied/capital,1.0),text=f"仓位约 {occupied/capital:.1%}")

with tab4:
    st.write("### 添加 / 修改自选")
    code=st.text_input("代码","002407",key="set_code").strip()
    name=st.text_input("名称","多氟多")
    c1,c2=st.columns(2)
    low=c1.number_input("关注区下限",value=37.50,step=0.01)
    high=c2.number_input("关注区上限",value=38.00,step=0.01)
    if st.button("保存到本次会话"):
        st.session_state.watchlist[code]={"name":name,"low":float(low),"high":float(high)}
        st.success("已保存。")
    st.caption("Community Cloud 重启后会恢复默认列表。")

st.divider()
st.caption("⚠️ 免费公开行情可能延迟或临时不可用；任何真实交易请在券商 App 中自行确认。")
