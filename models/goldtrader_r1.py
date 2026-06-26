#!/usr/bin/env python3
"""
GoldTrader-R1: 黄金量化交易 SOTA 策略模型 (使用公共模块)
==========================================================

SOTA 编码器层 (仅本文件):
  - Mamba2SSD / Mamba2Block / Mamba2Encoder  — 线性复杂度长程时序建模
  - MixtureOfExperts / MoEChannelAttnBlock    — MoE 通道注意力
  - GriffinLocalBlock                          — RG-LRU + 局部注意力
  - TimesNetBlock                              — 周期发现
  - KANLinear / KANStrategyHead               — 可学习激活函数策略头
  - TemporalCrossAttention                    — 决策可解释性
  - ActionHeads                                — 交易动作输出

公共模块 (from models.common):
  - GoldTraderR1Config, DataEngine, GoldDataset
  - RevIN, PatchEmbed, RoPE, CrossFusion
  - MultiPhaseTrainer, WorldModelLoss

部署:
    python models/goldtrader_r1.py --phase all --epochs 250
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
    GoldTraderR1Config,
    DataEngine,
    GoldDataset,
    RevIN,
    PatchEmbed,
    RoPE,
    CrossFusion,
    MultiPhaseTrainer,
    WorldModelLoss,
)


# ============================================================
# Mamba-2 SSD
# ============================================================

class Mamba2SSD(nn.Module):
    """Mamba-2 SSD 简化实现 (1D 因果卷积 + 指数衰减扫描)."""
    def __init__(self, d_model, d_state=128, n_heads=8):
        super().__init__()
        self.d_model, self.d_state, self.n_heads = d_model, d_state, n_heads
        self.in_proj = nn.Linear(d_model, d_model * 2)
        self.conv1d = nn.Conv1d(d_model, d_model, kernel_size=4, padding=3, groups=d_model, bias=False)
        self.A_log = nn.Parameter(torch.log(torch.rand(d_model, d_state) * 0.5 + 0.5))
        self.B_proj = nn.Linear(d_model, d_state, bias=False)
        self.C_proj = nn.Linear(d_model, d_state, bias=False)
        self.dt_proj = nn.Sequential(nn.Linear(d_model, d_state), nn.Softplus())
        self.out_proj = nn.Linear(d_model, d_model)
        self.gate = nn.Sequential(nn.Linear(d_model, d_model), nn.SiLU())

    def forward(self, x):
        B, L, D = x.shape
        xz = self.in_proj(x)
        x_main, z = xz.chunk(2, dim=-1)
        x_conv = self.conv1d(x_main.transpose(1, 2))[..., :L].transpose(1, 2)
        dt = self.dt_proj(x_conv)
        B_out, C_out = self.B_proj(x_conv), self.C_proj(x_conv)
        A = -torch.exp(self.A_log).mean(dim=-1)
        h = torch.zeros(B, D, device=x.device)
        outputs = []
        for t in range(L):
            decay = torch.exp(-dt[:, t].mean(dim=-1, keepdim=True) * F.softplus(A.unsqueeze(0)))
            h = decay * h + (1 - decay) * B_out[:, t].mean(dim=-1, keepdim=True) * x_conv[:, t]
            outputs.append((h * C_out[:, t].mean(dim=-1, keepdim=True)).unsqueeze(1))
        y = torch.cat(outputs, dim=1)
        return self.out_proj(y * self.gate(z))


class Mamba2Block(nn.Module):
    """Mamba-2: SSD → SwiGLU → Residual."""
    def __init__(self, d_model, d_state, n_heads, dropout=0.1):
        super().__init__()
        self.ssd = Mamba2SSD(d_model, d_state, n_heads)
        self.norm1 = nn.RMSNorm(d_model)
        self.gate_proj = nn.Linear(d_model, d_model * 2)
        self.down_proj = nn.Linear(d_model, d_model)
        self.norm2 = nn.RMSNorm(d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        r = x; x = self.norm1(x); x = self.ssd(x); x = r + self.dropout(x)
        r = x; x = self.norm2(x)
        gate, value = self.gate_proj(x).chunk(2, dim=-1)
        x = self.down_proj(F.silu(gate) * value)
        return r + self.dropout(x)


class Mamba2Encoder(nn.Module):
    def __init__(self, d_model, d_state=128, n_heads=8, n_layers=4, dropout=0.1):
        super().__init__()
        self.layers = nn.ModuleList([
            Mamba2Block(d_model, d_state, n_heads, dropout) for _ in range(n_layers)
        ])
    def forward(self, x):
        for layer in self.layers: x = layer(x)
        return x


# ============================================================
# Mixture of Experts
# ============================================================

class MixtureOfExperts(nn.Module):
    """MoE: 8 experts, Top-2 soft routing + shared expert."""
    def __init__(self, d_model, n_experts=8, top_k=2, dropout=0.1):
        super().__init__()
        self.n_experts, self.top_k = n_experts, top_k
        self.router = nn.Linear(d_model, n_experts, bias=False)
        self.experts = nn.ModuleList([
            nn.Sequential(nn.Linear(d_model, d_model * 4), nn.GELU(),
                          nn.Dropout(dropout), nn.Linear(d_model * 4, d_model), nn.Dropout(dropout))
            for _ in range(n_experts)
        ])
        self.shared_expert = nn.Sequential(
            nn.Linear(d_model, d_model * 2), nn.GELU(), nn.Linear(d_model * 2, d_model),
        )
        self.register_buffer("expert_bias", torch.zeros(n_experts))

    def forward(self, x):
        o_shape = x.shape
        xf = x.reshape(-1, o_shape[-1]) if x.dim() == 3 else x
        logits = self.router(xf) + self.expert_bias
        tk_logits, tk_idx = torch.topk(logits, self.top_k, dim=-1)
        tk_w = F.softmax(tk_logits, dim=-1)
        out = torch.zeros_like(xf)
        for k in range(self.top_k):
            for e in range(self.n_experts):
                mask = (tk_idx[:, k] == e)
                if mask.any(): out[mask] += tk_w[mask, k:k+1] * self.experts[e](xf[mask])
        out = out + self.shared_expert(xf)
        return out.reshape(o_shape)


# ============================================================
# MoE Channel Attention
# ============================================================

class MoEChannelAttnBlock(nn.Module):
    def __init__(self, d_model, n_heads=8, n_experts=8, top_k=2, dropout=0.1):
        super().__init__()
        self.attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.norm1 = nn.RMSNorm(d_model)
        self.moe = MixtureOfExperts(d_model, n_experts, top_k, dropout)
        self.norm2 = nn.RMSNorm(d_model)

    def forward(self, x):
        B, NP, C, D = x.shape
        x = x.permute(0, 2, 1, 3).reshape(B * C, NP, D)
        a, _ = self.attn(x, x, x); x = self.norm1(x + a)
        return self.norm2(x + self.moe(x)).reshape(B, C, NP, D).permute(0, 2, 1, 3)


# ============================================================
# Griffin Local Block
# ============================================================

class GriffinLocalBlock(nn.Module):
    """RG-LRU + 局部滑动窗口注意力."""
    def __init__(self, d_model, window_size=24, dropout=0.1):
        super().__init__()
        self.window_size = window_size
        self.a_param = nn.Parameter(torch.randn(d_model))
        self.gate = nn.Sequential(nn.Linear(d_model * 2, d_model), nn.Sigmoid())
        self.norm1 = nn.RMSNorm(d_model)
        self.local_attn = nn.MultiheadAttention(d_model, num_heads=4, dropout=dropout, batch_first=True)
        self.norm2 = nn.RMSNorm(d_model)

    def forward(self, x):
        B, NP, D = x.shape
        h = torch.zeros(B, D, device=x.device)
        outs = []
        for t in range(NP):
            g = self.gate(torch.cat([x[:, t], h], dim=-1))
            a = (-8.0 * F.softplus(self.a_param)).exp()
            h = a.unsqueeze(0) * h + (1 - a.unsqueeze(0)) * (g * x[:, t])
            outs.append(h.unsqueeze(1))
        x = self.norm1(x + torch.cat(outs, dim=1))
        mask = torch.ones(NP, NP, device=x.device).tril(0).triu(-self.window_size).masked_fill_(torch.ones(NP, NP, device=x.device).tril(0).triu(-self.window_size) == 0, float('-inf'))
        a_out, _ = self.local_attn(x, x, x, attn_mask=mask)
        return self.norm2(x + a_out)


# ============================================================
# TimesNet Block
# ============================================================

class TimesNetBlock(nn.Module):
    """简化 TimesNet: 2D 卷积周期发现."""
    def __init__(self, d_model, top_k=5):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 8, kernel_size=(3, 3), padding=(1, 1)), nn.GELU(),
            nn.Conv2d(8, 1, kernel_size=(3, 3), padding=(1, 1)),
        )
        self.proj = nn.Linear(d_model, d_model)

    def forward(self, x):
        B, C, NP, D = x.shape
        out = self.conv(x.mean(dim=1).unsqueeze(1)).squeeze(1)
        return self.proj(out.mean(dim=1))


# ============================================================
# KAN
# ============================================================

class KANLinear(nn.Module):
    def __init__(self, in_f, out_f, grid_size=5, spline_order=3):
        super().__init__()
        self.in_f, self.out_f, self.gs, self.so = in_f, out_f, grid_size, spline_order
        self.base_w = nn.Parameter(torch.randn(out_f, in_f) * 0.1)
        self.spline_w = nn.Parameter(torch.randn(out_f, in_f, grid_size + spline_order) * 0.1)
        self.spline_s = nn.Parameter(torch.ones(out_f, in_f))
        h = (grid_size + spline_order - 1) / grid_size
        self.register_buffer("grid", torch.linspace(-h, h, grid_size + 2 * spline_order + 1))

    def forward(self, x):
        base = F.linear(F.silu(x), self.base_w)
        basis = F.relu(1 - (x.unsqueeze(-1) - self.grid.unsqueeze(0).unsqueeze(0)).abs())
        spline = torch.einsum('bik,oik->bo', basis, self.spline_w * self.spline_s.unsqueeze(-1))
        return base + spline


class KANStrategyHead(nn.Module):
    def __init__(self, in_dim, hidden_dim, out_dim):
        super().__init__()
        self.kan1 = KANLinear(in_dim, hidden_dim)
        self.kan2 = KANLinear(hidden_dim, out_dim)
    def forward(self, x): return self.kan2(self.kan1(x))


# ============================================================
# Temporal Cross-Attention
# ============================================================

class TemporalCrossAttention(nn.Module):
    def __init__(self, d_model, n_heads=8, dropout=0.1):
        super().__init__()
        self.cross_attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.norm = nn.RMSNorm(d_model)

    def forward(self, ctx, hidden):
        out, aw = self.cross_attn(ctx.unsqueeze(1), hidden, hidden)
        return self.norm(ctx + out.squeeze(1)), aw


# ============================================================
# Action Heads
# ============================================================

class ActionHeads(nn.Module):
    def __init__(self, d_model):
        super().__init__()
        s = nn.Sequential(nn.Linear(d_model, d_model), nn.GELU(), nn.Dropout(0.1))
        self.dir_h = nn.Linear(d_model, 3)
        self.pos_h = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
        self.sl_h  = nn.Sequential(nn.Linear(d_model, 1), nn.Softplus())
        self.tp_h  = nn.Sequential(nn.Linear(d_model, 1), nn.Softplus())
        self._s = s

    def forward(self, x):
        h = self._s(x)
        return self.dir_h(h), self.pos_h(h), self.sl_h(h), self.tp_h(h)


# ============================================================
# GoldTrader-R1 完整模型
# ============================================================

class GoldTraderR1(nn.Module):
    """
    GoldTrader-R1: Mamba-2 + iTransformer/MoE + Griffin + KAN.

    使用 models.common 的 RevIN, PatchEmbed, RoPE, CrossFusion.
    """
    def __init__(self, cfg: GoldTraderR1Config):
        super().__init__()
        C, D = cfg.n_features, cfg.d_model
        NP, H = cfg.max_patches, cfg.n_horizons

        # ---- 公共层 ----
        self.revin = RevIN(C)
        self.patch_embed = PatchEmbed(D, cfg.patch_len, cfg.stride, cfg.dropout)
        self.rope = RoPE(D, max_len=NP + 100)

        # ---- SOTA 编码器 ----
        self.timesnet = TimesNetBlock(D)
        self.mamba_encoder = Mamba2Encoder(D, cfg.d_state, cfg.n_heads, cfg.n_mamba_layers, cfg.dropout)
        self.moe_blocks = nn.ModuleList([
            MoEChannelAttnBlock(D, cfg.n_heads, cfg.n_experts, cfg.top_k_experts, cfg.dropout)
            for _ in range(cfg.n_moe_layers)
        ])
        self.griffin_block = GriffinLocalBlock(D, window_size=24, dropout=cfg.dropout)
        self.encoder_fusion = nn.Sequential(
            nn.Linear(D * 3, D * 2), nn.GELU(), nn.Dropout(cfg.dropout),
            nn.Linear(D * 2, D),
        )

        # ---- 预测 Heads ----
        self.pool = nn.Sequential(nn.RMSNorm(D), nn.Linear(D, D), nn.GELU())
        self.h_dir  = nn.Linear(D, H)
        self.h_ret  = nn.Linear(D, H)
        self.h_lvar = nn.Linear(D, H)
        self.regime_head = nn.Sequential(
            nn.Linear(D, D // 2), nn.GELU(), nn.Linear(D // 2, cfg.n_regimes),
        )
        self.uncertainty_head = nn.Sequential(
            nn.Linear(D, D // 2), nn.GELU(), nn.Linear(D // 2, H * 2),
        )

        # ---- 决策上下文 ----
        self.pred_proj = nn.Linear(H * 4, D)
        self.regime_embed = nn.Embedding(cfg.n_regimes, D)
        self.macro_encoder = nn.Sequential(nn.Linear(5, D // 2), nn.GELU(), nn.Linear(D // 2, D))
        self.decision_context = nn.Sequential(
            nn.Linear(D * 4, D * 2), nn.GELU(), nn.Dropout(cfg.dropout),
            nn.Linear(D * 2, D), nn.RMSNorm(D),
        )
        self.temporal_cross_attn = TemporalCrossAttention(D, cfg.n_heads)
        self.portfolio_encoder = nn.Sequential(
            nn.Linear(6, D // 2), nn.GELU(), nn.Linear(D // 2, D),
        )

        # ---- KAN 策略头 ----
        self.decision_fusion = nn.Sequential(nn.Linear(D * 2, D), nn.GELU(), nn.RMSNorm(D))
        self.kan_dir = KANStrategyHead(D, D // 4, 3)
        self.kan_pos = KANStrategyHead(D, D // 4, 1)
        self.kan_sl  = KANStrategyHead(D, D // 4, 1)
        self.kan_tp  = KANStrategyHead(D, D // 4, 1)
        self.action_heads = ActionHeads(D)

    def encode(self, features):
        x = self.revin(features, "norm")
        x = self.patch_embed(x); x = self.rope(x)
        B, C, NP, D = x.shape
        tn_feat = self.timesnet(x)

        x_m = self.mamba_encoder(x.mean(dim=1))
        x_i = x.permute(0, 2, 1, 3)
        for blk in self.moe_blocks: x_i = blk(x_i)
        x_i = x_i.mean(dim=2)
        x_g = self.griffin_block(x.mean(dim=1))

        hidden = self.encoder_fusion(torch.cat([x_m, x_i, x_g], dim=-1))
        pooled = self.pool(hidden.mean(dim=1)) + tn_feat
        return hidden, pooled

    def forward(self, features, portfolio_state=None, macro_state=None):
        hidden, pooled = self.encode(features)
        dir_logits = self.h_dir(pooled)
        ret_mean   = self.h_ret(pooled)
        ret_logvar = self.h_lvar(pooled)
        regime_logits = self.regime_head(pooled)
        uncertainty   = self.uncertainty_head(pooled)

        preds = torch.cat([dir_logits, ret_mean, ret_logvar, uncertainty], dim=-1)
        pred_emb = self.pred_proj(preds)
        regime_emb = self.regime_embed(regime_logits.argmax(dim=-1))
        macro_emb = self.macro_encoder(macro_state) if macro_state is not None else \
                    torch.zeros(features.size(0), self.pred_proj.out_features // 4, device=features.device)

        ctx = self.decision_context(torch.cat([pred_emb, regime_emb, pooled, macro_emb], dim=-1))
        ctx, attn = self.temporal_cross_attn(ctx, hidden)

        ps = portfolio_state if portfolio_state is not None else \
             torch.zeros(features.size(0), 6, device=features.device)
        ph = self.decision_fusion(torch.cat([ctx, self.portfolio_encoder(ps)], dim=-1))

        d_a, p_a, s_a, t_a = self.action_heads(ph)
        d_k = self.kan_dir(ph); p_k = torch.sigmoid(self.kan_pos(ph))
        s_k = F.softplus(self.kan_sl(ph)) + 0.5; t_k = F.softplus(self.kan_tp(ph)) + 1.0

        return {
            "dir_logits": dir_logits, "ret_mean": ret_mean, "ret_logvar": ret_logvar,
            "regime_logits": regime_logits, "uncertainty": uncertainty,
            "dir_action": d_k, "position": p_k, "stop_loss": s_k, "take_profit": t_k,
            "dir_action_mlp": d_a, "position_mlp": p_a, "stop_loss_mlp": s_a, "take_profit_mlp": t_a,
            "attention_weights": attn, "pooled_embedding": pooled, "hidden_states": hidden,
        }

    @torch.no_grad()
    def trade(self, features, portfolio_state=None, macro_state=None):
        self.eval()
        out = self.forward(features, portfolio_state, macro_state)
        dp = F.softmax(out["dir_action"], dim=-1)
        am = {-1: "SHORT", 0: "FLAT", 1: "LONG"}
        rn = ["RANGING_LOWVOL", "RANGING_HIGHVOL", "TRENDING_UP", "TRENDING_DOWN", "CRISIS"]
        return {
            "action": am.get(dp.argmax(dim=-1).item() - 1, "UNKNOWN"),
            "action_probs": dp.cpu().numpy(),
            "position_pct": out["position"].item() * 100,
            "stop_loss_atr": out["stop_loss"].item(),
            "take_profit_atr": out["take_profit"].item(),
            "regime": rn[out["regime_logits"].argmax().item()],
            "confidence": dp.max().item(),
            "uncertainty": out["uncertainty"].mean().item(),
        }


# ============================================================
# 策略损失
# ============================================================

class PolicyLoss(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.a, self.b, self.g, self.d = cfg.alpha_dir, cfg.beta_pos, cfg.gamma_risk, cfg.delta_cost
        self.cpf = cfg.cost_per_trade_bps / 10000

    def forward(self, act, labels):
        L_dir = F.cross_entropy(act["dir_action"], labels["direction"])
        L_pos = F.huber_loss(act["position"].squeeze(-1), labels["position"])
        L_risk = F.mse_loss(act["stop_loss"].squeeze(-1), labels["stop_loss"]) + \
                 F.mse_loss(act["take_profit"].squeeze(-1), labels["take_profit"])
        flipped = (labels.get("prev_direction", torch.zeros_like(labels["direction"])) !=
                   (act["dir_action"].argmax(-1) - 1)).float()
        return self.a*L_dir + self.b*L_pos + self.g*L_risk + self.d*flipped.mean()*self.cpf, \
               {"L_dir": L_dir.item(), "L_pos": L_pos.item(), "L_risk": L_risk.item()}


class DecisionAwareLoss(nn.Module):
    def __init__(self, lam_da=0.3): super().__init__(); self.lam = lam_da
    def forward(self, pred, actions, fut_ret):
        od = (fut_ret[:, 0] > 0).long()
        return self.lam * (F.cross_entropy(actions["dir_action"], od) +
                           F.huber_loss(actions["position"].squeeze(-1), torch.sigmoid(fut_ret[:, 0] * 20)))


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GoldTrader-R1 训练")
    parser.add_argument("--epochs", type=int, default=250)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--d-model", type=int, default=512)
    parser.add_argument("--seq-len", type=int, default=576)
    parser.add_argument("--phase", type=str, default="all",
                        choices=["p1", "p2", "p3", "all", "phase1", "phase2", "phase3"])
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--force-reload", action="store_true")
    args = parser.parse_args()

    cfg = GoldTraderR1Config()
    cfg.seq_len = args.seq_len; cfg.d_model = args.d_model
    cfg.batch_size = args.batch_size
    cfg.lr_p1 = cfg.lr_p2 = cfg.lr_p3 = args.lr
    cfg.epochs_p1 = args.epochs
    cfg.device = args.device if torch.cuda.is_available() else "cpu"
    cfg.dtype = "float16" if args.fp16 else "bfloat16"

    torch.manual_seed(cfg.seed); np.random.seed(cfg.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(cfg.seed)

    print("🥇 GoldTrader-R1 — Mamba-2 + iTransformer/MoE + Griffin + KAN (公共模块版)")
    print(f"   seq={cfg.seq_len} | d={cfg.d_model} | features={cfg.n_features}")
    print(f"   mamba_layers={cfg.n_mamba_layers} | moe_layers={cfg.n_moe_layers} | experts={cfg.n_experts}")
    print(f"   use_future_vol={cfg.use_future_vol} ✅")

    # ---- 数据 ----
    print(f"\n{'='*60}")
    engine = DataEngine(cfg, force_reload=args.force_reload, cache_name="goldtrader_r1_features.npz")
    tr_ds = GoldDataset(engine, "train", phase=args.phase, seq_len=cfg.seq_len)
    va_ds = GoldDataset(engine, "val",   phase=args.phase, seq_len=cfg.seq_len)
    te_ds = GoldDataset(engine, "test",  phase=args.phase, seq_len=cfg.seq_len)

    tr_ldr = DataLoader(tr_ds, cfg.batch_size, shuffle=True,  num_workers=4, pin_memory=True, drop_last=True)
    va_ldr = DataLoader(va_ds, cfg.batch_size, shuffle=False, num_workers=2, pin_memory=True)
    te_ldr = DataLoader(te_ds, cfg.batch_size, shuffle=False, num_workers=2, pin_memory=True)

    # ---- 模型 ----
    model = GoldTraderR1(cfg).to(cfg.device)
    np = sum(p.numel() for p in model.parameters())
    print(f"\n🧠 GoldTrader-R1: {np:,} 参数 ({np/1e6:.1f}M)\n")

    # ---- 训练 ----
    w_loss = WorldModelLoss(cfg.lambda_dir, cfg.lambda_ret, cfg.lambda_vol, cfg.lambda_regime)
    p_loss = PolicyLoss(cfg)
    da_loss = DecisionAwareLoss(cfg.lam_da)

    trainer = MultiPhaseTrainer(model, cfg, tr_ldr, va_ldr, te_ldr,
                                loss_fn=w_loss, policy_loss_fn=p_loss, da_loss_fn=da_loss)
    trainer.fit(phase=args.phase, verbose=True)
    trainer.save("models/goldtrader_r1_best.pt")
    print("\n✅ GoldTrader-R1 训练完成!")


if __name__ == "__main__":
    main()
