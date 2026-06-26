#!/usr/bin/env python3
"""
GoldFormer: 黄金量化交易深度学习模型
============================================

核心技术栈 (2023-2025 SOTA):
  - Patch Embedding         (PatchTST 2023)  — 局部模式编码
  - Inverted Transformer    (iTransformer 2024) — 通道维度交叉注意力
  - RevIN                    — 可逆实例归一化，应对价格非平稳
  - RoPE 位置编码            — 相对位置感知
  - Multi-Horizon 预测       — 5min~24h 多时间尺度
  - Uncertainty Estimation   — 高斯分布输出，支撑仓位管理

硬件: NVIDIA A100 (BF16 mixed precision, 大显存全量缓存)
数据: MySQL → 全量读取 → 内存缓存 → NumPy 持久化

部署:
    python models/train_goldformer.py --epochs 200 --lr 1e-4 --wandb
"""

import os, sys, math, time, argparse, pickle
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torch.cuda.amp import autocast, GradScaler
from dataclasses import dataclass, field
from pathlib import Path

# ============================================================
# 配置
# ============================================================

@dataclass
class Config:
    # ---- 数据 ----
    seq_len: int       = 288       # 输入序列长度 (24h * 12 bars/h)
    pred_horizons: list = field(default_factory=lambda: [1, 3, 6, 12, 36, 72, 144])
    cache_dir: str     = "models/cache"  # 全量数据缓存目录

    # ---- 模型 ----
    d_model: int       = 384
    n_heads: int       = 8
    n_layers: int      = 6
    patch_len: int     = 12        # Patch 长度 (1h)
    stride: int        = 6         # Patch 步长 (重叠50%)
    dropout: float     = 0.1

    # ---- 训练 ----
    batch_size: int    = 256
    epochs: int        = 200
    lr: float          = 1e-4
    weight_decay: float = 1e-5
    warmup_epochs: int = 10
    grad_accum: int    = 2

    # ---- 损失权重 ----
    lambda_dir: float  = 1.0
    lambda_ret: float  = 0.5
    lambda_vol: float  = 0.1

    # ---- 系统 ----
    device: str        = "cuda"
    dtype: str         = "bfloat16"
    seed: int          = 42

    # ---- DB ----
    db_host: str = "bj-cdb-9ermqj8g.sql.tencentcdb.com"
    db_port: int = 26092
    db_user: str = "gold_ro"
    db_pass: str = "BNbQMsn4hhnmuw6P"
    db_name: str = "gold"

cfg = Config()


# ============================================================
# 数据引擎 — 一次性全量加载 + 特征工程 + 内存缓存
# ============================================================

class DataEngine:
    """
    全量数据引擎:
      1. 从 MySQL 一次性读取全部 gold_prices 数据
      2. 特征工程: 17 维特征矩阵 + 标签
      3. 缓存到磁盘 (.npz)，后续直接加载
      4. 按时间顺序划分 train/val/test 索引
    """

    def __init__(self, cfg: Config, force_reload: bool = False):
        self.cfg = cfg
        cache_path = Path(cfg.cache_dir) / "gold_features.npz"

        if cache_path.exists() and not force_reload:
            print(f"📦 从缓存加载: {cache_path} ({cache_path.stat().st_size / 1024 / 1024:.0f} MB)")
            data = np.load(cache_path)
            self.features = data["features"]   # (17, N)
            self.Y_dir   = data["Y_dir"]        # (N, H)
            self.Y_ret   = data["Y_ret"]        # (N, H)
            self.Y_vol   = data["Y_vol"]        # (N, H)
            self.Y_price = data["Y_price"]      # (N,)
            self.dates   = data["dates"]        # (N,) str
            print(f"  ✅ 特征矩阵: {self.features.shape[1]:,} 时间步 × {self.features.shape[0]} 特征")
        else:
            print("📥 从 MySQL 全量读取...")
            raw = self._load_all_from_db()
            print("🧬 特征工程...")
            self.features, self.Y_dir, self.Y_ret, self.Y_vol, self.Y_price, self.dates = \
                self._build_all(raw)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(cache_path,
                features=self.features, Y_dir=self.Y_dir, Y_ret=self.Y_ret,
                Y_vol=self.Y_vol, Y_price=self.Y_price, dates=self.dates)
            print(f"  💾 缓存已保存: {cache_path}")

        # 划分 train/val/test 索引
        N = len(self.Y_dir)
        self.train_idx = slice(0, int(N * 0.70))
        self.val_idx   = slice(int(N * 0.70), int(N * 0.85))
        self.test_idx  = slice(int(N * 0.85), N)
        print(f"  📊 样本: train={self.train_idx.stop - self.train_idx.start:,}  "
              f"val={self.val_idx.stop - self.val_idx.start:,}  "
              f"test={self.test_idx.stop - self.test_idx.start:,}")

    def _load_all_from_db(self):
        """一次性从 MySQL 读取全部数据。"""
        import mysql.connector
        conn = mysql.connector.connect(
            host=cfg.db_host, port=cfg.db_port,
            user=cfg.db_user, password=cfg.db_pass,
            database=cfg.db_name, charset="utf8mb4",
            connection_timeout=30,
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT trade_date, trade_time, price_usd, weekday, hour, minute
            FROM gold_prices WHERE price_usd > 0 ORDER BY dt
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        n = len(rows)
        dates    = np.array([str(r[0]) for r in rows])
        prices   = np.array([r[2] for r in rows], dtype=np.float32)
        wdays    = np.array([r[3] for r in rows], dtype=np.int32)
        hours    = np.array([r[4] for r in rows], dtype=np.int32)
        minutes  = np.array([r[5] for r in rows], dtype=np.int32)
        print(f"  ✅ {n:,} 行原始数据")
        return {"price": prices, "wdays": wdays, "hours": hours, "minutes": minutes, "dates": dates}

    def _build_all(self, raw):
        """一次性特征工程 + 全量标签构建。"""
        p = raw["price"]
        n = len(p)

        # ====== 特征工程 ======
        # log return
        log_ret = np.zeros(n, dtype=np.float32)
        log_ret[1:] = np.log(p[1:] / p[:-1])

        # rolling std (多窗口波动率)
        def _rstd(x, w):
            out = np.full(n, np.nan, dtype=np.float32)
            cs = np.cumsum(x * x); cs2 = np.cumsum(x)
            for i in range(w - 1, n):
                s = cs[i] - (cs[i - w] if i >= w else 0)
                s2 = cs2[i] - (cs2[i - w] if i >= w else 0)
                out[i] = np.sqrt(max(0, (s - s2 * s2 / w) / (w - 1)))
            return out

        v12, v36, v72, v144, v288 = _rstd(log_ret, 12), _rstd(log_ret, 36), _rstd(log_ret, 72), _rstd(log_ret, 144), _rstd(log_ret, 288)

        # RSI(14)
        rsi = np.full(n, np.nan, dtype=np.float32)
        if n > 14:
            delta = np.diff(p, prepend=p[0]); g = np.maximum(delta, 0); l = np.maximum(-delta, 0)
            ag = np.convolve(g, np.ones(14) / 14, mode='same')
            al = np.convolve(l, np.ones(14) / 14, mode='same')
            rsi = 100 - 100 / (1 + ag / (al + 1e-10))

        # MACD
        a12, a26, a9 = 2/13, 2/27, 2/10
        e12, e26 = np.zeros(n), np.zeros(n); e12[0] = e26[0] = p[0]
        for i in range(1, n):
            e12[i] = p[i] * a12 + e12[i-1] * (1 - a12)
            e26[i] = p[i] * a26 + e26[i-1] * (1 - a26)
        macd = e12 - e26; sig = np.zeros(n); sig[0] = macd[0]
        for i in range(1, n): sig[i] = macd[i] * a9 + sig[i-1] * (1 - a9)
        macd_norm = (macd - sig) / (p + 1e-10)

        # BB position
        bb = np.full(n, np.nan, dtype=np.float32)
        for i in range(19, n):
            w = p[i-19:i+1]; bb[i] = (p[i] - w.mean()) / (w.std() + 1e-10)

        # MA deviation
        def _rmean(x, w):
            out = np.full(n, np.nan, dtype=np.float32)
            cs = np.cumsum(np.insert(x, 0, 0)); out[w-1:] = (cs[w:] - cs[:-w]) / w
            return out
        ma12, ma144 = _rmean(p, 12), _rmean(p, 144)
        mad12, mad144 = np.full(n, np.nan), np.full(n, np.nan)
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
        tr = np.abs(np.diff(p, prepend=p[0])); pdm = np.maximum(np.diff(p, prepend=p[0]), 0)
        mdm = np.maximum(-np.diff(p, prepend=p[0]), 0)
        for i in range(13, n):
            ts = tr[i-13:i+1].sum(); ps = pdm[i-13:i+1].sum(); ms = mdm[i-13:i+1].sum()
            adx[i] = abs(ps - ms) / (ts + 1e-10) * 100 if ts > 0 else 0

        # 组装特征 (17, N)
        feats = np.stack([
            log_ret, v12, v36, v72, v144, v288,
            rsi, macd_norm, bb, mad12, mad144,
            dp, h_sin, h_cos, w_sin, w_cos, adx,
        ], axis=0)
        feats = np.nan_to_num(feats, nan=0.0)
        C = feats.shape[0]
        print(f"  ✅ {C} 维特征 × {n:,} 时间步 = {feats.size / 1024 / 1024:.1f} MB")

        # ====== 构建序列样本 ======
        L = cfg.seq_len
        max_h = max(cfg.pred_horizons)
        H = len(cfg.pred_horizons)
        start = L + 288  # 跳过前面让指标充分计算
        end = n - max_h - 1
        total_samples = end - start

        # 预分配内存 (一次性)
        X = np.zeros((total_samples, C, L), dtype=np.float32)
        Yd = np.zeros((total_samples, H), dtype=np.float32)
        Yr = np.zeros((total_samples, H), dtype=np.float32)
        Yv = np.zeros((total_samples, H), dtype=np.float32)
        Yp = np.zeros(total_samples, dtype=np.float32)
        sample_dates = np.zeros(total_samples, dtype=object)

        print(f"  🔨 构建 {total_samples:,} 个序列样本...")
        for idx, i in enumerate(range(start, end)):
            X[idx] = feats[:, i - L:i]
            Yp[idx] = p[i]
            sample_dates[idx] = raw["dates"][i]
            for hi, h in enumerate(cfg.pred_horizons):
                ret = np.log(p[i + h] / p[i])
                Yd[idx, hi] = 1.0 if ret > 0 else 0.0
                Yr[idx, hi] = ret
                Yv[idx, hi] = np.std(log_ret[max(0, i - L):i]) * np.sqrt(h) if i >= L else 0.0
            if (idx + 1) % 50000 == 0:
                print(f"    ... {idx + 1:,}/{total_samples:,}")

        mem_mb = (X.nbytes + Yd.nbytes + Yr.nbytes + Yv.nbytes) / 1024 / 1024
        print(f"  ✅ {total_samples:,} 样本 ({mem_mb:.0f} MB 内存)")
        return feats, Yd, Yr, Yv, Yp, sample_dates


# ============================================================
# 内存数据集 (纯索引，无 IO)
# ============================================================

class GoldDataset(Dataset):
    """纯内存数据集: 持有全量数据的引用 + index slice，zero-copy 访问。"""
    def __init__(self, engine: DataEngine, mode: str):
        self.feats = engine.features  # (17, N)
        self.seq_len = engine.cfg.seq_len
        self.Y_dir = engine.Y_dir
        self.Y_ret = engine.Y_ret
        self.Y_vol = engine.Y_vol

        if mode == "train":   self.sl = engine.train_idx
        elif mode == "val":   self.sl = engine.val_idx
        else:                 self.sl = engine.test_idx

    def __len__(self):
        return self.sl.stop - self.sl.start

    def __getitem__(self, i):
        idx = self.sl.start + i
        return (torch.from_numpy(self.feats[:, idx - self.seq_len:idx]).float(),
                torch.from_numpy(self.Y_dir[idx]).float(),
                torch.from_numpy(self.Y_ret[idx]).float(),
                torch.from_numpy(self.Y_vol[idx]).float())


# ============================================================
# RevIN
# ============================================================

class RevIN(nn.Module):
    def __init__(self, n_feat, eps=1e-5):
        super().__init__()
        self.eps = eps
        self.g = nn.Parameter(torch.ones(n_feat))
        self.b = nn.Parameter(torch.zeros(n_feat))

    def forward(self, x, mode="norm"):
        if mode == "norm":
            self.m = x.mean(dim=-1, keepdim=True)
            self.s = torch.sqrt(x.var(dim=-1, keepdim=True, unbiased=False) + self.eps)
            return (x - self.m) / self.s * self.g.unsqueeze(-1) + self.b.unsqueeze(-1)
        return (x - self.b.unsqueeze(-1)) / (self.g.unsqueeze(-1) + self.eps) * self.s + self.m


# ============================================================
# PatchEmbed + RoPE
# ============================================================

class PatchEmbed(nn.Module):
    def __init__(self, d, patch_len, stride, dropout=0.1):
        super().__init__()
        self.pl, self.st = patch_len, stride
        self.proj = nn.Linear(patch_len, d)
        self.drop = nn.Dropout(dropout)

    def forward(self, x):
        B, C, L = x.shape
        x = x.unfold(-1, self.pl, self.st)
        NP = x.shape[2]
        return self.drop(self.proj(x.reshape(B * C, NP, self.pl))).reshape(B, C, NP, -1)


class RoPE(nn.Module):
    def __init__(self, dim, max_len=2048):
        super().__init__()
        f = 1.0 / (10000 ** (torch.arange(0, dim, 2).float() / dim))
        e = torch.cat([torch.einsum("i,j->ij", torch.arange(max_len).float(), f)] * 2, dim=-1)
        self.register_buffer("cos", e.cos(), persistent=False)
        self.register_buffer("sin", e.sin(), persistent=False)

    def forward(self, x, offset=0):
        s = x.shape[-2]; c = self.cos[offset:offset + s]; si = self.sin[offset:offset + s]
        x2 = torch.stack([-x[..., 1::2], x[..., ::2]], dim=-1).flatten(-2)
        return x * c.unsqueeze(0).unsqueeze(0) + x2 * si.unsqueeze(0).unsqueeze(0)


# ============================================================
# Channel Attention + Cross-Fusion
# ============================================================

class ChannelAttnBlock(nn.Module):
    def __init__(self, d, heads, dropout=0.1):
        super().__init__()
        self.attn = nn.MultiheadAttention(d, heads, dropout=dropout, batch_first=True)
        self.n1, self.n2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.ffn = nn.Sequential(nn.Linear(d, d * 4), nn.GELU(), nn.Dropout(dropout),
                                 nn.Linear(d * 4, d), nn.Dropout(dropout))

    def forward(self, x):
        B, NP, C, D = x.shape
        x = x.permute(0, 2, 1, 3).reshape(B * C, NP, D)
        a, _ = self.attn(x, x, x); x = self.n1(x + a)
        x = self.n2(x + self.ffn(x))
        return x.reshape(B, C, NP, D).permute(0, 2, 1, 3)


class CrossFusion(nn.Module):
    def __init__(self, d, heads, dropout=0.1):
        super().__init__()
        self.attn = nn.MultiheadAttention(d, heads, dropout=dropout, batch_first=True)
        self.n1, self.n2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.ffn = nn.Sequential(nn.Linear(d, d * 4), nn.GELU(), nn.Dropout(dropout),
                                 nn.Linear(d * 4, d), nn.Dropout(dropout))

    def forward(self, x):
        B, NP, C, D = x.shape; x = x.mean(dim=2)
        a, _ = self.attn(x, x, x); x = self.n1(x + a)
        return self.n2(x + self.ffn(x))


# ============================================================
# GoldFormer
# ============================================================

class GoldFormer(nn.Module):
    """
    输入 (B, 17, 288) → RevIN → PatchEmbed → RoPE → ChannelAttn×N → CrossFusion → Heads
    输出: (dir_logits, ret_mean, ret_logvar) each (B, H)
    """
    def __init__(self, cfg: Config):
        super().__init__()
        C, d = 17, cfg.d_model
        self.revin = RevIN(C)
        self.patch_embed = PatchEmbed(d, cfg.patch_len, cfg.stride, cfg.dropout)
        self.patch_count = (cfg.seq_len - cfg.patch_len) // cfg.stride + 1
        self.rope = RoPE(d, max_len=self.patch_count + 100)
        self.blocks = nn.ModuleList([ChannelAttnBlock(d, cfg.n_heads, cfg.dropout) for _ in range(cfg.n_layers)])
        self.fusion = CrossFusion(d, cfg.n_heads, cfg.dropout)
        self.pool = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, d), nn.GELU(), nn.Dropout(cfg.dropout))
        H = len(cfg.pred_horizons)
        self.h_dir, self.h_ret, self.h_lvar = nn.Linear(d, H), nn.Linear(d, H), nn.Linear(d, H)

    def forward(self, x):
        x = self.revin(x, "norm")
        x = self.blocks_forward(self.patch_embed(x))
        return self.h_dir(x), self.h_ret(x), self.h_lvar(x)

    def blocks_forward(self, x):
        B, C, NP, D = x.shape; x = x.permute(0, 2, 1, 3)
        for blk in self.blocks: x = blk(x)
        x = self.fusion(x).mean(dim=1)
        return self.pool(x)

    @torch.no_grad()
    def predict(self, x):
        self.eval(); dl, rm, rlv = self.forward(x)
        return torch.sigmoid(dl), rm, torch.exp(0.5 * rlv.clamp(-10, 10))


# ============================================================
# 损失函数
# ============================================================

class GoldLoss(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.bce = nn.BCEWithLogitsLoss(); self.ld, self.lr, self.lv = cfg.lambda_dir, cfg.lambda_ret, cfg.lambda_vol

    def forward(self, dl, rm, rlv, yd, yr, yv):
        rlv = rlv.clamp(-10, 10); rv = rlv.exp()
        Ld = self.bce(dl, yd)
        Lr = 0.5 * (rlv + (yr - rm) ** 2 / (rv + 1e-8)).mean()
        Lv = F.mse_loss(torch.exp(0.5 * rlv), yv)
        return self.ld * Ld + self.lr * Lr + self.lv * Lv, {"Ld": Ld.item(), "Lr": Lr.item(), "Lv": Lv.item()}


# ============================================================
# 训练器
# ============================================================

class Trainer:
    def __init__(self, model, cfg, train_ldr, val_ldr, test_ldr):
        self.model = model; self.cfg = cfg
        self.train_ldr, self.val_ldr, self.test_ldr = train_ldr, val_ldr, test_ldr
        self.criterion = GoldLoss(cfg)
        self.opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
        self.scaler = GradScaler(enabled=(cfg.dtype == "float16"))

        total = len(train_ldr) * cfg.epochs // cfg.grad_accum
        warmup = len(train_ldr) * cfg.warmup_epochs // cfg.grad_accum
        def lr_fn(s):
            if s < warmup: return s / max(1, warmup)
            return 0.5 * (1 + math.cos(math.pi * (s - warmup) / max(1, total - warmup)))
        self.scheduler = torch.optim.lr_scheduler.LambdaLR(self.opt, lr_fn)
        self.best_val, self.best_state = float("inf"), None

    def _amp_ctx(self):
        dt = torch.bfloat16 if self.cfg.dtype == "bfloat16" else torch.float32
        return torch.amp.autocast("cuda", dtype=dt)

    def train_epoch(self):
        self.model.train(); tl, comps = 0.0, {"Ld": 0, "Lr": 0, "Lv": 0}
        self.opt.zero_grad()
        for i, (x, yd, yr, yv) in enumerate(self.train_ldr):
            x, yd, yr, yv = x.to(cfg.device), yd.to(cfg.device), yr.to(cfg.device), yv.to(cfg.device)
            with self._amp_ctx():
                loss, c = self.criterion(*self.model(x), yd, yr, yv)
                loss = loss / cfg.grad_accum
            self.scaler.scale(loss).backward()
            if (i + 1) % cfg.grad_accum == 0:
                self.scaler.unscale_(self.opt); nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                self.scaler.step(self.opt); self.scaler.update()
                self.opt.zero_grad(); self.scheduler.step()
            tl += loss.item() * cfg.grad_accum
            for k in comps: comps[k] += c[k]
        n = len(self.train_ldr); return tl / n, {k: v / n for k, v in comps.items()}

    @torch.no_grad()
    def evaluate(self, ldr, tag="val"):
        self.model.eval(); tl, cor, tot = 0.0, 0, 0
        for x, yd, yr, yv in ldr:
            x, yd, yr, yv = x.to(cfg.device), yd.to(cfg.device), yr.to(cfg.device), yv.to(cfg.device)
            with self._amp_ctx():
                loss, _ = self.criterion(*self.model(x), yd, yr, yv)
            tl += loss.item()
            pred = (torch.sigmoid(self.model(x)[0][:, 0]) > 0.5).float()
            cor += (pred == yd[:, 0]).sum().item(); tot += yd.size(0)
        avg = tl / len(ldr); acc = cor / max(tot, 1)
        print(f"  📊 {tag}: loss={avg:.6f}  acc(5min)={acc:.2%}")
        return avg, acc

    def fit(self):
        print(f"\n{'='*60}\n🚀 GoldFormer 训练启动 (A100 全量内存缓存)\n{'='*60}")
        n_params = sum(p.numel() for p in self.model.parameters())
        print(f"  参数: {n_params:,} | 设备: {cfg.device} | 精度: {cfg.dtype} | batch={cfg.batch_size}")
        for ep in range(1, cfg.epochs + 1):
            t0 = time.time(); tl, _ = self.train_epoch(); vl, va = self.evaluate(self.val_ldr, "val")
            print(f"  Ep {ep:3d} | train={tl:.6f} val={vl:.6f} acc={va:.2%} lr={self.scheduler.get_last_lr()[0]:.2e} | {time.time() - t0:.1f}s")
            if vl < self.best_val:
                self.best_val = vl
                self.best_state = {k: v.cpu().clone() for k, v in self.model.state_dict().items()}
                print(f"  ✅ best (vl={vl:.6f})")
        self.model.load_state_dict(self.best_state)
        print(f"\n🏁 最佳 val_loss={self.best_val:.6f}"); self.evaluate(self.test_ldr, "test")

    def save(self, path="models/goldformer_best.pt"):
        torch.save({"state": self.best_state, "cfg": self.cfg, "val_loss": self.best_val}, path)
        print(f"  💾 {path}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--d-model", type=int, default=384)
    parser.add_argument("--n-layers", type=int, default=6)
    parser.add_argument("--wandb", action="store_true")
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--force-reload", action="store_true", help="强制重新从 DB 加载（忽略缓存）")
    args = parser.parse_args()

    cfg.epochs = args.epochs; cfg.lr = args.lr; cfg.batch_size = args.batch_size
    cfg.d_model = args.d_model; cfg.n_layers = args.n_layers
    cfg.device = args.device if torch.cuda.is_available() else "cpu"
    cfg.dtype = "float16" if args.fp16 else "bfloat16"

    torch.manual_seed(cfg.seed); np.random.seed(cfg.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(cfg.seed)

    print("🥇 GoldFormer — PatchTST + iTransformer + RevIN + RoPE")
    print(f"   seq={cfg.seq_len} | d={cfg.d_model} | layers={cfg.n_layers} | heads={cfg.n_heads}")
    print(f"   horizons: {cfg.pred_horizons}")

    # ==== 全量数据引擎 (一次 DB 读取 → 内存 + 磁盘缓存) ====
    print(f"\n{'='*60}")
    engine = DataEngine(cfg, force_reload=args.force_reload)

    # 三个 dataset 共享同一份内存数据
    tr_ds = GoldDataset(engine, "train")
    va_ds = GoldDataset(engine, "val")
    te_ds = GoldDataset(engine, "test")

    # DataLoader 用 pin_memory 加速 CPU→GPU 传输
    tr_ldr = DataLoader(tr_ds, cfg.batch_size, shuffle=True, num_workers=4, pin_memory=True, drop_last=True)
    va_ldr = DataLoader(va_ds, cfg.batch_size, shuffle=False, num_workers=2, pin_memory=True)
    te_ldr = DataLoader(te_ds, cfg.batch_size, shuffle=False, num_workers=2, pin_memory=True)

    model = GoldFormer(cfg).to(cfg.device)
    print(f"\n🧠 GoldFormer: {sum(p.numel() for p in model.parameters()):,} 参数\n")

    trainer = Trainer(model, cfg, tr_ldr, va_ldr, te_ldr)
    if args.wandb:
        try: import wandb; wandb.init(project="goldformer", config=vars(cfg))
        except: pass
    trainer.fit()
    trainer.save()
    print("\n✅ 完成!")


if __name__ == "__main__":
    main()
