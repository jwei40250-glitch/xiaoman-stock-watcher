import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests, time

st.set_page_config(page_title="小满盯盘器 v3.0", page_icon="📈", layout="centered")
TOTAL_BUDGET = 50000
DEFAULT_WATCHLIST = {
    "002407":{"name":"多氟多","low":37.50,"high":38.00},
    "603286":{"name":"日盈电子","low":43.00,"high":44.00},
    "002384":{"name":"东山精密","low":213.00,"high":217.00},
    "588950":{"name":"科创50ETF景顺","low":1.80,"high":1.83},
}
HEADERS={"User-Agent":"Mozilla/5.0","Referer":"https://quote.eastmoney.com/"}

def secid(code):
    return ("1." if code.startswith(("5","6","9")) else "0.")+code

def scale(code): return 1000 if code.startswith("5") else 100

def fetch(url, params, timeout=8):
    err=None
    for i in range(3):
        try:
            r=requests.get(url,params=params,headers=HEADERS,timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            err=e; time.sleep(.5*(i+1))
    raise err

@st.cache_data(ttl=20,show_spinner=False)
def quote(code):
    p={"secid":secid(code),"fields":"f43,f44,f45,f46,f57,f58,f60,f170"}
    err=None
    for host in ["https://push2.eastmoney.com","https://push2delay.eastmoney.com"]:
        try:
            d=(fetch(host+"/api/qt/stock/get",p).get("data") or {})
            if d:
                s=scale(code)
                return {"price":(d.get("f43") or 0)/s,"pct":(d.get("f170") or 0)/100}
        except Exception as e: err=e
    raise RuntimeError(f"行情接口暂不可用：{err}")

@st.cache_data(ttl=300,show_spinner=False)
def history(code,days=120):
    end=datetime.now().strftime("%Y%m%d")
    beg=(datetime.now()-timedelta(days=days*2)).strftime("%Y%m%d")
    p={"secid":secid(code),"klt":"101","fqt":"1","beg":beg,"end":end,
       "fields1":"f1,f2,f3,f4,f5,f6",
       "fields2":"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"}
    j=fetch("https://push2his.eastmoney.com/api/qt/stock/kline/get",p,10)
    lines=(j.get("data") or {}).get("klines") or []
    rows=[]
    for line in lines:
        x=line.split(",")
        rows.append([x[0],float(x[2]),float(x[3]),float(x[4]),float(x[5]),float(x[6])])
    df=pd.DataFrame(rows,columns=["日期","收盘","最高","最低","成交量","成交额"])
    for n in (5,10,20,60): df[f"MA{n}"]=df["收盘"].rolling(n).mean()
    delta=df["收盘"].diff()
    gain=delta.clip(lower=0).rolling(14).mean()
    loss=(-delta.clip(upper=0)).rolling(14).mean()
    rs=gain/loss.replace(0,np.nan)
    df["RSI14"]=100-(100/(1+rs))
    ema12=df["收盘"].ewm(span=12,adjust=False).mean()
    ema26=df["收盘"].ewm(span=26,adjust=False).mean()
    dif=ema12-ema26
    dea=dif.ewm(span=9,adjust=False).mean()
    df["MACD"]=(dif-dea)*2
    return df.tail(days)

def last(df,col):
    if df.empty or col not in df: return None
    v=df[col].iloc[-1]
    return None if pd.isna(v) else float(v)

def rating(price,df,low,high):
    score=50; why=[]
    ma5,ma10,ma20,ma60=[last(df,f"MA{x}") for x in (5,10,20,60)]
    rsi,macd=last(df,"RSI14"),last(df,"MACD")
    if ma5 and ma10:
        if price>ma5>ma10: score+=12; why.append("价格站上MA5，且MA5高于MA10")
        elif price<ma10: score-=12; why.append("价格在MA10下方")
    if ma20: score += 8 if price>ma20 else -8
    if ma60: score += 6 if price>ma60 else -6
    if rsi is not None:
        if 45<=rsi<=65: score+=8; why.append("RSI处于相对健康区间")
        elif rsi>=75: score-=8; why.append("RSI偏热，注意追高")
        elif rsi<=30: score+=3; why.append("RSI偏低，观察是否止跌")
    if macd is not None: score += 8 if macd>0 else -5
    if low<=price<=high: score+=5; why.append("已进入预设关注区")
    score=max(0,min(100,score))
    label="🟢 偏强" if score>=75 else "🟡 中性偏强" if score>=60 else "⚪ 中性" if score>=45 else "🔴 偏弱"
    return score,label,why

def batches(budget,price):
    rows=[]
    for i,w in enumerate((.3,.3,.4),1):
        cash=budget*w
        qty=int(cash//(price*100))*100 if price>0 else 0
        rows.append({"批次":f"第{i}笔","比例":f"{w:.0%}","预算":round(cash,2),
                     "参考数量":qty,"参考金额":round(qty*price,2)})
    return rows

if "watchlist" not in st.session_state: st.session_state.watchlist=DEFAULT_WATCHLIST.copy()
if "trades" not in st.session_state: st.session_state.trades=[]

st.title("📈 小满盯盘器 v3.0")
st.caption("老板负责休息，小满负责盯。行情观察 + 模拟决策，不自动下真实订单。")
t1,t2,t3,t4=st.tabs(["👀 盯盘","💰 5万计划","🧪 模拟账户","⚙️ 设置"])

with t1:
    if st.button("🔄 刷新行情",use_container_width=True):
        st.cache_data.clear(); st.rerun()
    for code,cfg in st.session_state.watchlist.items():
        with st.container(border=True):
            st.subheader(f"{cfg['name']} · {code}")
            try:
                q=quote(code); df=history(code)
                score,label,why=rating(q["price"],df,cfg["low"],cfg["high"])
                a,b,c=st.columns(3)
                dec=3 if code.startswith("5") else 2
                a.metric("现价",f"{q['price']:.{dec}f}",f"{q['pct']:+.2f}%")
                b.metric("关注区",f"{cfg['low']}~{cfg['high']}")
                c.metric("评分",f"{score}/100")
                st.write(f"### {label}")
                if q["price"]<cfg["low"]: st.info("低于关注区：先观察止跌，不因为便宜自动买。")
                elif q["price"]<=cfg["high"]: st.warning("进入关注区：重点观察，但不是自动买入信号。")
                else: st.caption("尚未进入关注区，避免怕踏空而追价。")
                cols=st.columns(4)
                for col,box in zip(("MA5","MA10","MA20","RSI14"),cols):
                    v=last(df,col); box.metric(col,"-" if v is None else f"{v:.2f}")
                with st.expander("评分依据"):
                    for x in why: st.write("•",x)
                    st.caption("规则评分不是收益预测。")
                st.line_chart(df.set_index("日期")[["收盘","MA5","MA10","MA20","MA60"]].dropna(how="all"))
            except Exception as e:
                st.error(str(e))
                st.caption("接口故障时请以券商App行情为准。")

with t2:
    st.subheader("💰 5万元资金计划")
    code=st.selectbox("标的",list(st.session_state.watchlist),
        format_func=lambda x:f"{st.session_state.watchlist[x]['name']} · {x}")
    cfg=st.session_state.watchlist[code]
    p=st.number_input("计划参考价",min_value=.001,value=float(cfg["low"]),step=.01)
    alloc=st.slider("该标的最多分配总资金",10,100,40,5)
    budget=TOTAL_BUDGET*alloc/100
    st.metric("最高计划资金",f"¥{budget:,.0f}")
    st.dataframe(pd.DataFrame(batches(budget,p)),use_container_width=True,hide_index=True)
    st.caption("默认三笔30% / 30% / 40%，仅作仓位计算。")

with t3:
    st.subheader("🧪 模拟账户")
    capital=st.number_input("模拟初始资金",min_value=1000,value=50000,step=1000)
    code=st.selectbox("标的",list(st.session_state.watchlist),key="sim",
        format_func=lambda x:f"{st.session_state.watchlist[x]['name']} · {x}")
    side=st.radio("方向",["模拟买入","模拟卖出"],horizontal=True)
    p=st.number_input("成交价",min_value=.001,value=float(st.session_state.watchlist[code]["low"]),step=.01)
    qty=st.number_input("数量",min_value=100,value=100,step=100)
    amount=p*qty
    st.write(f"本笔金额：**¥{amount:,.2f}** ｜ 占初始资金：**{amount/capital:.1%}**")
    if st.button("记录模拟交易",use_container_width=True):
        st.session_state.trades.append({"时间":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "代码":code,"名称":st.session_state.watchlist[code]["name"],"方向":side,
            "价格":p,"数量":qty,"金额":amount})
        st.success("已记录。")
    if st.session_state.trades:
        st.dataframe(pd.DataFrame(st.session_state.trades),use_container_width=True,hide_index=True)

with t4:
    st.subheader("⚙️ 自选设置")
    code=st.text_input("代码","002407").strip()
    name=st.text_input("名称","多氟多")
    a,b=st.columns(2)
    low=a.number_input("关注区下限",value=37.50,step=.01)
    high=b.number_input("关注区上限",value=38.00,step=.01)
    if st.button("保存自选"):
        if not code or low>high: st.error("请检查代码和关注区。")
        else:
            st.session_state.watchlist[code]={"name":name or code,"low":float(low),"high":float(high)}
            st.success("已保存到本次会话。")
    st.dataframe(pd.DataFrame([{"代码":k,"名称":v["name"],"下限":v["low"],"上限":v["high"]}
        for k,v in st.session_state.watchlist.items()]),use_container_width=True,hide_index=True)

st.divider()
st.caption("⚠️ 仅作行情观察、技术指标、仓位计算和模拟记录，不构成投资建议；不连接券商、不自动下单。")
