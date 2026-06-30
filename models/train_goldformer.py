#!/usr/bin/env python3
"""
GoldFormer: 黄金量化交易深度学习模型 (重构版 — 使用公共模块)
==============================================================

核心技术栈 (2023-2025):
  - RevIN      — 可逆实例归一化
  - PatchEmbed — Patch 时序编码 (PatchTST 2023)
  - RoPE       — 旋转位置编码
  - iTransformer — 通道维度交叉注意力 (ICLR 2024)
  - Multi-Horizon 预测 — 5min~24h 多时间尺度

部署:
    python models/train_goldformer.py --epochs 200 --lr 1e-4
"""

import os, sys, time, argparse
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

# ---- 公共模块 ----
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.common import (
    GoldFormerConfig,
    DataEngine,
    GoldDataset,
    GoldFormerEncoder,
    BaseTrainer,
    WorldModelLoss,
)


# ============================================================
# GoldFormer 模型
# ============================================================

class GoldFormer(nn.Module):
    """
    GoldFormer 预测模型.

    输入: (B, 17, 288)
    输出: dir_logits, ret_mean, ret_logvar — each (B, H)
    """
    def __init__(self, cfg: GoldFormerConfig):
        super().__init__()
        self.encoder = GoldFormerEncoder(cfg)
        D = cfg.d_model
        H = cfg.n_horizons

        self.h_dir  = nn.Linear(D, H)   # 方向 logits
        self.h_ret  = nn.Linear(D, H)   # 收益率均值
        self.h_lvar = nn.Linear(D, H)   # 对数方差

    def forward(self, x):
        _, pooled = self.encoder(x)
        return {
            "dir_logits": self.h_dir(pooled),
            "ret_mean":   self.h_ret(pooled),
            "ret_logvar": self.h_lvar(pooled),
            "regime_logits": torch.zeros(x.size(0), 1, device=x.device),  # 占位
        }

    @torch.no_grad()
    def predict(self, x):
        self.eval()
        out = self.forward(x)
        return (
            torch.sigmoid(out["dir_logits"]),
            out["ret_mean"],
            torch.exp(0.5 * out["ret_logvar"].clamp(-10, 10)),
        )


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GoldFormer 训练")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--d-model", type=int, default=384)
    parser.add_argument("--n-layers", type=int, default=6)
    parser.add_argument("--seq-len", type=int, default=288)
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--force-reload", action="store_true")
    parser.add_argument("--use-future-vol", action="store_true",
                        help="使用未来已实现波动率标签 (推荐)")
    args = parser.parse_args()

    # ---- Config ----
    cfg = GoldFormerConfig()
    cfg.epochs = args.epochs
    cfg.lr = args.lr
    cfg.batch_size = args.batch_size
    cfg.d_model = args.d_model
    cfg.n_layers = args.n_layers
    cfg.seq_len = args.seq_len
    cfg.device = args.device if torch.cuda.is_available() else "cpu"
    cfg.dtype = "float16" if args.fp16 else "bfloat16"
    if args.use_future_vol:
        cfg.use_future_vol = True

    torch.manual_seed(cfg.seed); np.random.seed(cfg.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(cfg.seed)

    print("🥇 GoldFormer — PatchEmbed + iTransformer + RevIN + RoPE (公共模块版)")
    print(f"   seq={cfg.seq_len} | d={cfg.d_model} | layers={cfg.n_layers} | heads={cfg.n_heads}")
    print(f"   horizons: {cfg.pred_horizons}")
    print(f"   use_future_vol={cfg.use_future_vol}")

    # ---- 数据 ----
    print(f"\n{'='*60}")
    engine = DataEngine(cfg, force_reload=args.force_reload, cache_name="goldformer_features.npz")

    tr_ds = GoldDataset(engine, "train", seq_len=cfg.seq_len)
    va_ds = GoldDataset(engine, "val", seq_len=cfg.seq_len)
    te_ds = GoldDataset(engine, "test", seq_len=cfg.seq_len)

    tr_ldr = DataLoader(tr_ds, cfg.batch_size, shuffle=True, num_workers=0, pin_memory=False, drop_last=True)
    va_ldr = DataLoader(va_ds, cfg.batch_size, shuffle=False, num_workers=0, pin_memory=False)
    te_ldr = DataLoader(te_ds, cfg.batch_size, shuffle=False, num_workers=0, pin_memory=False)

    # ---- 模型 ----
    model = GoldFormer(cfg).to(cfg.device)
    print(f"\n🧠 GoldFormer: {sum(p.numel() for p in model.parameters()):,} 参数\n")

    # ---- 训练 ----
    trainer = BaseTrainer(model, cfg, tr_ldr, va_ldr, te_ldr)
    trainer.fit()
    trainer.save("models/goldformer_best.pt")
    print("\n✅ 完成!")


if __name__ == "__main__":
    main()
