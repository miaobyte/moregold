#!/usr/bin/env python3
"""
公共数据引擎

支持:
  - 从 MySQL 全量读取 gold_prices
  - 特征工程: 17 基础 + 5 宏观 = 22 维
  - ✅ 修正标签: Y_vol = 未来已实现波动率 (use_future_vol=True)
  - 环境标签: 5 类市场 regime
  - .npz 磁盘缓存
"""

import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict


class DataEngine:
    """
    全量数据引擎.

    参数:
      cfg:  BaseConfig 子类 (包含 n_features, seq_len, pred_horizons 等)
      force_reload:  强制重新从 DB 加载 (忽略缓存)
      cache_name:    自定义缓存文件名 (None=自动生成)
    """

    def __init__(self, cfg, force_reload: bool = False, cache_name: Optional[str] = None):
        self.cfg = cfg
        self.feature_count = cfg.n_features

        if cache_name is None:
            cache_name = f"{cfg.model_type}_features.npz"
        cache_path = Path(cfg.cache_dir) / cache_name

        if cache_path.exists() and not force_reload:
            self._load_cache(cache_path)
        else:
            self._build_from_db(cache_path)
        self._split_indices()

    def _load_cache(self, cache_path):
        print(f"📦 从缓存加载: {cache_path} ({cache_path.stat().st_size / 1024 / 1024:.0f} MB)")
        data = np.load(cache_path, allow_pickle=True)
        self.features  = data["features"]
        self.Y_dir     = data["Y_dir"]
        self.Y_ret     = data["Y_ret"]
        self.Y_vol     = data["Y_vol"]
        self.Y_regime  = data.get("Y_regime", np.zeros(len(self.Y_dir), dtype=np.int64))
        self.Y_price   = data["Y_price"]
        self.dates     = data["dates"]
        print(f"  ✅ 特征矩阵: {self.features.shape[1]:,} 时间步 × {self.features.shape[0]} 特征")

    def _build_from_db(self, cache_path):
        print("📥 从 MySQL 全量读取...")
        raw = self._load_all_from_db()
        print("🧬 特征工程...")
        self.features, labels_dict, self.Y_price, self.dates = self._build_features(raw)
        self.Y_dir    = labels_dict["Y_dir"]
        self.Y_ret    = labels_dict["Y_ret"]
        self.Y_vol    = labels_dict["Y_vol"]
        self.Y_regime = labels_dict["Y_regime"]
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_path,
            features=self.features,
            Y_dir=self.Y_dir, Y_ret=self.Y_ret, Y_vol=self.Y_vol,
            Y_regime=self.Y_regime, Y_price=self.Y_price, dates=self.dates)
        print(f"  💾 缓存已保存: {cache_path}")

    def _split_indices(self):
        N = len(self.Y_dir)
        self.train_idx = slice(0, int(N * 0.70))
        self.val_idx   = slice(int(N * 0.70), int(N * 0.85))
        self.test_idx  = slice(int(N * 0.85), N)
        # 样本索引 → 原始时间索引的偏移量
        self.start_offset = self.cfg.seq_len + 288
        print(f"  📊 样本: train={self.train_idx.stop - self.train_idx.start:,}  "
              f"val={self.val_idx.stop - self.val_idx.start:,}  "
              f"test={self.test_idx.stop - self.test_idx.start:,}")

    # ================================================================
    # DB 加载
    # ================================================================

    def _load_all_from_db(self):
        import mysql.connector
        conn = mysql.connector.connect(
            host=self.cfg.db_host, port=self.cfg.db_port,
            user=self.cfg.db_user, password=self.cfg.db_pass,
            database=self.cfg.db_name, charset="utf8mb4", connection_timeout=30,
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT trade_date, trade_time, price_usd, weekday, hour, minute
            FROM gold_prices WHERE price_usd > 0 AND minute % 5 = 0
            ORDER BY dt
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        n = len(rows)
        dates   = np.array([str(r[0]) for r in rows])
        prices  = np.array([r[2] for r in rows], dtype=np.float32)
        wdays   = np.array([r[3] for r in rows], dtype=np.int32)
        hours   = np.array([r[4] for r in rows], dtype=np.int32)
        minutes = np.array([r[5] for r in rows], dtype=np.int32)
        print(f"  ✅ {n:,} 行原始数据")
        return {"price": prices, "wdays": wdays, "hours": hours, "minutes": minutes, "dates": dates}

    # ================================================================
    # 特征工程
    # ================================================================

    def _build_features(self, raw):
        p = raw["price"]
        n = len(p)

        # rolling std
        def _rstd(x, w):
            out = np.full(n, np.nan, dtype=np.float32)
            cs = np.cumsum(x * x); cs2 = np.cumsum(x)
            for i in range(w - 1, n):
                s = cs[i] - (cs[i - w] if i >= w else 0)
                s2 = cs2[i] - (cs2[i - w] if i >= w else 0)
                out[i] = np.sqrt(max(0, (s - s2 * s2 / w) / (w - 1)))
            return out

        def _rmean(x, w):
            out = np.full(n, np.nan, dtype=np.float32)
            cs = np.cumsum(np.insert(x, 0, 0))
            out[w-1:] = (cs[w:] - cs[:-w]) / w
            return out

        def _ema(x, alpha):
            out = np.zeros(n, dtype=np.float32); out[0] = x[0]
            for i in range(1, n): out[i] = x[i] * alpha + out[i-1] * (1 - alpha)
            return out

        # log return
        log_ret = np.zeros(n, dtype=np.float32)
        log_ret[1:] = np.log(p[1:] / p[:-1])

        # 多窗口波动率
        v12, v36, v72, v144, v288 = _rstd(log_ret, 12), _rstd(log_ret, 36), _rstd(log_ret, 72), _rstd(log_ret, 144), _rstd(log_ret, 288)

        # RSI(14)
        rsi = np.full(n, np.nan, dtype=np.float32)
        if n > 14:
            delta = np.diff(p, prepend=p[0])
            g = np.maximum(delta, 0); l = np.maximum(-delta, 0)
            ag = np.convolve(g, np.ones(14) / 14, mode='same')
            al = np.convolve(l, np.ones(14) / 14, mode='same')
            rsi = 100 - 100 / (1 + ag / (al + 1e-10))

        # MACD
        e12, e26 = _ema(p, 2/13), _ema(p, 2/27)
        macd = e12 - e26; sig = _ema(macd, 2/10)
        macd_norm = (macd - sig) / (p + 1e-10)

        # BB position
        bb = np.full(n, np.nan, dtype=np.float32)
        for i in range(19, n):
            w = p[i-19:i+1]; bb[i] = (p[i] - w.mean()) / (w.std() + 1e-10)

        # MA deviation
        ma12, ma144 = _rmean(p, 12), _rmean(p, 144)
        mad12 = np.full(n, np.nan); mad144 = np.full(n, np.nan)
        for i in range(11, n): mad12[i] = (p[i] - ma12[i]) / (ma12[i] + 1e-10)
        for i in range(143, n): mad144[i] = (p[i] - ma144[i]) / (ma144[i] + 1e-10)

        # Time features
        dp = np.array([(h * 60 + m) / 1440.0 for h, m in zip(raw["hours"], raw["minutes"])], dtype=np.float32)
        h_sin = np.sin(2 * np.pi * raw["hours"] / 24.0).astype(np.float32)
        h_cos = np.cos(2 * np.pi * raw["hours"] / 24.0).astype(np.float32)
        w_sin = np.sin(2 * np.pi * raw["wdays"] / 7.0).astype(np.float32)
        w_cos = np.cos(2 * np.pi * raw["wdays"] / 7.0).astype(np.float32)

        # ADX simplified
        adx = np.full(n, np.nan, dtype=np.float32)
        tr = np.abs(np.diff(p, prepend=p[0]))
        pdm = np.maximum(np.diff(p, prepend=p[0]), 0)
        mdm = np.maximum(-np.diff(p, prepend=p[0]), 0)
        for i in range(13, n):
            ts = tr[i-13:i+1].sum(); ps = pdm[i-13:i+1].sum(); ms = mdm[i-13:i+1].sum()
            adx[i] = abs(ps - ms) / (ts + 1e-10) * 100 if ts > 0 else 0

        # ---- 基础 17 维 ----
        base_feats = [
            log_ret, v12, v36, v72, v144, v288,
            rsi, macd_norm, bb, mad12, mad144,
            dp, h_sin, h_cos, w_sin, w_cos, adx,
        ]

        # ---- 宏观 5 维 (placeholder; Phase 2 接入真实 macro 数据) ----
        if self.feature_count >= 22:
            macro_feats = [np.zeros(n, dtype=np.float32) for _ in range(5)]
        else:
            macro_feats = []

        # 组装特征
        all_feats = base_feats + macro_feats
        feats = np.stack(all_feats[:self.feature_count], axis=0)
        feats = np.nan_to_num(feats, nan=0.0)
        C = feats.shape[0]
        print(f"  ✅ {C} 维特征 × {n:,} 时间步 = {feats.size / 1024 / 1024:.1f} MB")

        # ====== 构建序列样本 ======
        L = self.cfg.seq_len
        max_h = max(self.cfg.pred_horizons)
        H = len(self.cfg.pred_horizons)
        start = L + 288
        end = n - max_h - 1
        total = end - start

        X  = np.zeros((total, C, L), dtype=np.float32)
        Yd = np.zeros((total, H), dtype=np.float32)
        Yr = np.zeros((total, H), dtype=np.float32)
        Yv = np.zeros((total, H), dtype=np.float32)
        Yg = np.zeros(total, dtype=np.int64)
        Yp = np.zeros(total, dtype=np.float32)
        sample_dates = np.zeros(total, dtype=object)

        vol_mode = "future" if self.cfg.use_future_vol else "historical"
        print(f"  🔨 构建 {total:,} 个序列样本 (vol_label={vol_mode})...")
        for idx, i in enumerate(range(start, end)):
            X[idx] = feats[:, i - L:i]
            Yp[idx] = p[i]
            sample_dates[idx] = raw["dates"][i]
            for hi, h in enumerate(self.cfg.pred_horizons):
                ret = np.log(p[i + h] / p[i])
                Yd[idx, hi] = 1.0 if ret > 0 else 0.0
                Yr[idx, hi] = ret

                if self.cfg.use_future_vol:
                    # ✅ 修正: 未来 h 期已实现波动率
                    future_slice = log_ret[i+1 : i+h+1]
                    Yv[idx, hi] = np.std(future_slice) if len(future_slice) >= 3 else np.nan
                else:
                    # 旧行为: 历史波动率 × √h (不推荐)
                    Yv[idx, hi] = np.std(log_ret[max(0, i - L):i]) * np.sqrt(h) if i >= L else 0.0

            Yg[idx] = self._classify_regime(adx[i], bb[i], v72[i])

            if (idx + 1) % 50000 == 0:
                print(f"    ... {idx + 1:,}/{total:,}")

        nan_ratio = np.isnan(Yv).mean()
        if nan_ratio > 0:
            print(f"  ⚠️ Y_vol NaN 比例: {nan_ratio:.2%} (短 horizon 样本不足, 训练时 mask)")

        labels_dict = {"Y_dir": Yd, "Y_ret": Yr, "Y_vol": Yv, "Y_regime": Yg}
        mem_mb = (X.nbytes + Yd.nbytes + Yr.nbytes + Yv.nbytes) / 1024 / 1024
        print(f"  ✅ {total:,} 样本 ({mem_mb:.0f} MB 内存)")
        return feats, labels_dict, Yp, sample_dates

    def _classify_regime(self, adx_val: float, bb_val: float, atr_val: float) -> int:
        """5 类市场环境分类 (ADX + BB + ATR)."""
        if np.isnan(adx_val):
            return 0
        if atr_val > 2.0 * 0.001 or not np.isnan(atr_val) and atr_val > 0.003:
            return 4   # 危机
        if adx_val > 25:
            return 2   # 趋势 (方向进一步细分需额外信息)
        if not np.isnan(bb_val) and abs(bb_val) > 1.5:
            return 1   # 震荡高波动
        return 0       # 震荡低波动
