#!/usr/bin/env python3
"""
公共网络层 — GoldFormer & GoldTrader-R1 共享

  RevIN              — 可逆实例归一化
  PatchEmbed         — Patch 嵌入 (PatchTST 2023)
  RoPE               — 旋转位置编码
  ChannelAttnBlock   — 通道维度交叉注意力 (iTransformer 2024)
  CrossFusion        — 跨通道信息融合
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


# ============================================================
# RevIN — 可逆实例归一化
# ============================================================

class RevIN(nn.Module):
    """Reversible Instance Normalization (Kim et al., 2022)."""
    def __init__(self, n_feat: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.g = nn.Parameter(torch.ones(n_feat))
        self.b = nn.Parameter(torch.zeros(n_feat))

    def forward(self, x, mode: str = "norm"):
        if mode == "norm":
            self.m = x.mean(dim=-1, keepdim=True)
            self.s = torch.sqrt(x.var(dim=-1, keepdim=True, unbiased=False) + self.eps)
            return (x - self.m) / self.s * self.g.unsqueeze(-1) + self.b.unsqueeze(-1)
        # mode == "denorm"
        return (x - self.b.unsqueeze(-1)) / (self.g.unsqueeze(-1) + self.eps) * self.s + self.m


# ============================================================
# PatchEmbed
# ============================================================

class PatchEmbed(nn.Module):
    """Patch Embedding (PatchTST, Nie et al. 2023)."""
    def __init__(self, d_model: int, patch_len: int, stride: int, dropout: float = 0.1):
        super().__init__()
        self.patch_len = patch_len
        self.stride = stride
        self.proj = nn.Linear(patch_len, d_model)
        self.drop = nn.Dropout(dropout)

    def forward(self, x):
        # x: (B, C, L) → (B, C, NP, d_model)
        B, C, _ = x.shape
        x = x.unfold(-1, self.patch_len, self.stride)
        NP = x.shape[2]
        return self.drop(self.proj(x.reshape(B * C, NP, self.patch_len))).reshape(B, C, NP, -1)

    @property
    def patch_count(self, seq_len: int) -> int:
        return (seq_len - self.patch_len) // self.stride + 1


# ============================================================
# RoPE — 旋转位置编码
# ============================================================

class RoPE(nn.Module):
    """Rotary Position Embedding (Su et al., 2023)."""
    def __init__(self, dim: int, max_len: int = 2048):
        super().__init__()
        f = 1.0 / (10000 ** (torch.arange(0, dim, 2).float() / dim))
        e = torch.cat([torch.einsum("i,j->ij", torch.arange(max_len).float(), f)] * 2, dim=-1)
        self.register_buffer("cos", e.cos(), persistent=False)
        self.register_buffer("sin", e.sin(), persistent=False)

    def forward(self, x, offset: int = 0):
        s = x.shape[-2]
        c = self.cos[offset:offset + s]
        si = self.sin[offset:offset + s]
        x2 = torch.stack([-x[..., 1::2], x[..., ::2]], dim=-1).flatten(-2)
        return x * c.unsqueeze(0).unsqueeze(0) + x2 * si.unsqueeze(0).unsqueeze(0)


# ============================================================
# ChannelAttnBlock — iTransformer 核心块
# ============================================================

class ChannelAttnBlock(nn.Module):
    """
    通道维度交叉注意力块 (iTransformer, Liu et al. ICLR 2024).

    沿 C (通道/特征) 维度做 MHA，捕获特征间交互.
    """
    def __init__(self, d_model: int, n_heads: int = 8, dropout: float = 0.1):
        super().__init__()
        self.attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model), nn.Dropout(dropout),
        )

    def forward(self, x):
        # x: (B, NP, C, D)
        B, NP, C, D = x.shape
        x = x.permute(0, 2, 1, 3).reshape(B * C, NP, D)
        a, _ = self.attn(x, x, x)
        x = self.norm1(x + a)
        x = self.norm2(x + self.ffn(x))
        return x.reshape(B, C, NP, D).permute(0, 2, 1, 3)


# ============================================================
# CrossFusion — 跨通道融合
# ============================================================

class CrossFusion(nn.Module):
    """跨通道信息融合: 将 (B, NP, C, D) → (B, NP, D)."""
    def __init__(self, d_model: int, n_heads: int = 8, dropout: float = 0.1):
        super().__init__()
        self.attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model), nn.Dropout(dropout),
        )

    def forward(self, x):
        # x: (B, NP, C, D)
        B, NP, C, D = x.shape
        x = x.mean(dim=2)  # (B, NP, D)
        a, _ = self.attn(x, x, x)
        x = self.norm1(x + a)
        return self.norm2(x + self.ffn(x))


# ============================================================
# GoldFormer Encoder (将上述层串联)
# ============================================================

class GoldFormerEncoder(nn.Module):
    """
    GoldFormer 编码器: RevIN → PatchEmbed → RoPE → ChannelAttn×N → CrossFusion.

    返回:
      hidden:  (B, NP, D)  序列隐状态
      pooled:  (B, D)      全局池化
    """
    def __init__(self, cfg):
        super().__init__()
        C, D = cfg.n_features, cfg.d_model
        NP = cfg.max_patches

        self.revin = RevIN(C)
        self.patch_embed = PatchEmbed(D, cfg.patch_len, cfg.stride, cfg.dropout)
        self.rope = RoPE(D, max_len=NP + 100)
        self.blocks = nn.ModuleList([
            ChannelAttnBlock(D, cfg.n_heads, cfg.dropout)
            for _ in range(cfg.n_layers)
        ])
        self.fusion = CrossFusion(D, cfg.n_heads, cfg.dropout)
        self.pool = nn.Sequential(
            nn.LayerNorm(D), nn.Linear(D, D), nn.GELU(), nn.Dropout(cfg.dropout),
        )

    def forward(self, x):
        x = self.revin(x, "norm")          # (B, C, L)
        x = self.patch_embed(x)            # (B, C, NP, D)
        x = self.rope(x)
        B, C, NP, D = x.shape
        x = x.permute(0, 2, 1, 3)         # (B, NP, C, D)
        for blk in self.blocks:
            x = blk(x)
        hidden = self.fusion(x)             # (B, NP, D)
        pooled = self.pool(hidden.mean(dim=1))  # (B, D)
        return hidden, pooled
