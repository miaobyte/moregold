#!/usr/bin/env python3
"""
公共配置模块

BaseConfig           — 所有模型共享的基础配置
GoldFormerConfig     — GoldFormer 专属配置
GoldTraderR1Config   — GoldTrader-R1 专属配置

用法:
    from models.common import GoldFormerConfig, GoldTraderR1Config
    cfg = GoldTraderR1Config(d_model=512, seq_len=576)

环境变量 (数据库连接):
    GOLD_DB_HOST  — MySQL 主机地址
    GOLD_DB_PORT  — MySQL 端口
    GOLD_DB_USER  — MySQL 用户名
    GOLD_DB_PASS  — MySQL 密码
    GOLD_DB_NAME  — MySQL 数据库名
"""

import os
from dataclasses import dataclass, field


@dataclass
class BaseConfig:
    """所有模型共享的基础配置."""

    # ---- 数据 ----
    seq_len: int       = 576               # 输入序列长度
    pred_horizons: tuple = (1, 3, 6, 12, 24, 36, 72, 144)
    cache_dir: str     = "models/cache"
    n_features: int    = 22
    use_future_vol: bool = True            # ✅ True=未来已实现波动率, False=历史波动率(旧)

    # ---- 模型 ----
    d_model: int       = 512
    n_heads: int       = 8
    dropout: float     = 0.1
    patch_len: int     = 12
    stride: int        = 6

    # ---- 训练 ----
    batch_size: int    = 128
    epochs: int        = 200
    lr: float          = 1e-4
    weight_decay: float = 1e-5
    warmup_epochs: int = 10
    grad_accum: int    = 2

    # ---- 损失权重 ----
    lambda_dir: float  = 1.0
    lambda_ret: float  = 0.5
    lambda_vol: float  = 0.3
    lambda_regime: float = 0.3

    # ---- 系统 ----
    device: str        = "cuda"
    dtype: str         = "bfloat16"
    seed: int          = 42
    use_ema: bool      = True
    ema_decay: float   = 0.999
    label_smoothing: float = 0.05

    # ---- DB (从环境变量读取, 绝不硬编码) ----
    db_host: str = field(default_factory=lambda: os.environ.get("GOLD_DB_HOST", "localhost"))
    db_port: int = field(default_factory=lambda: int(os.environ.get("GOLD_DB_PORT", "3306")))
    db_user: str = field(default_factory=lambda: os.environ.get("GOLD_DB_USER", "root"))
    db_pass: str = field(default_factory=lambda: os.environ.get("GOLD_DB_PASS", ""))
    db_name: str = field(default_factory=lambda: os.environ.get("GOLD_DB_NAME", "gold"))

    @property
    def max_patches(self) -> int:
        return (self.seq_len - self.patch_len) // self.stride + 1

    @property
    def n_horizons(self) -> int:
        return len(self.pred_horizons)


@dataclass
class GoldFormerConfig(BaseConfig):
    """GoldFormer 专属配置 (兼容旧版)."""

    seq_len: int       = 288               # 24h
    n_features: int    = 17                # 仅基础特征
    d_model: int       = 384
    n_heads: int       = 8
    n_layers: int      = 6                 # ChannelAttn 层数
    dropout: float     = 0.1
    use_future_vol: bool = False           # 保持旧行为兼容 (⚠️ 不推荐)

    # 模型特定
    model_type: str = "goldformer"         # 用于 DataEngine 选择配置文件


@dataclass
class GoldTraderR1Config(BaseConfig):
    """GoldTrader-R1 SOTA 策略模型专属配置."""

    seq_len: int       = 576               # 48h
    n_features: int    = 22
    d_model: int       = 512
    d_state: int       = 128               # Mamba-2 状态维度
    n_heads: int       = 8
    n_mamba_layers: int = 4
    n_moe_layers: int   = 4
    n_experts: int     = 8
    top_k_experts: int  = 2
    n_regimes: int     = 5
    dropout: float     = 0.1
    use_future_vol: bool = True            # ✅ 修正标签

    # ---- 多阶段训练 ----
    epochs_p1: int     = 150               # Phase 1: 世界模型
    epochs_p2: int     = 80                # Phase 2: 模仿学习
    epochs_p3: int     = 50                # Phase 3: 决策感知
    lr_p1: float       = 1e-4
    lr_p2: float       = 5e-5
    lr_p3: float       = 2e-5

    # ---- 策略损失权重 ----
    alpha_dir: float   = 1.0
    beta_pos: float    = 0.5
    gamma_risk: float  = 0.3
    delta_cost: float  = 0.1
    lam_da: float      = 0.3

    # ---- 交易参数 ----
    max_hold_bars: int       = 576
    cost_per_trade_bps: float = 3.0
    min_risk_reward: float    = 1.5

    # 模型特定
    model_type: str = "goldtrader_r1"
