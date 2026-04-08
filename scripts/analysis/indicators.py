def sma(v,n):return sum(v[-n:])/n if len(v)>=n else None  # 简单移动平均

def rsi(v,n=14):  # 相对强弱指数
    if len(v)<n+1:return None
    d=[v[i]-v[i-1] for i in range(len(v)-n,len(v))]
    g=sum(x for x in d if x>0);l=-sum(x for x in d if x<0)
    if l==0:return 100.0
    rs=g/l
    return 100-100/(1+rs)

def atr(v,n=14):  # 平均真实波幅(用差分近似)
    if len(v)<n+1:return None
    d=[abs(v[i]-v[i-1]) for i in range(len(v)-n,len(v))]
    return sum(d)/n

def bollinger(v,n=20,k=2):  # 布林带(中轨/上轨/下轨)
    if len(v)<n:return None
    w=v[-n:];m=sum(w)/n
    var=sum((x-m)**2 for x in w)/n
    sd=var**0.5
    return m,m+k*sd,m-k*sd

def adx(v,n=14):  # 趋势强度指数
    if len(v)<n+1:return None
    d=[v[i]-v[i-1] for i in range(len(v)-n,len(v))]
    up=sum(x for x in d if x>0);dn=-sum(x for x in d if x<0)
    tr=sum(abs(x) for x in d)
    if tr==0:return 0.0
    dip=100*up/tr;dim=100*dn/tr
    return 100*abs(dip-dim)/(dip+dim) if dip+dim else 0.0
