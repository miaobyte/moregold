#!/usr/bin/env python3
"""
models.common — 公共模块，GoldFormer 和 GoldTrader-R1 共享.

用法:
    from models.common import (
        BaseConfig, GoldFormerConfig, GoldTraderR1Config,
        DataEngine, GoldDataset,
        RevIN, PatchEmbed, RoPE, ChannelAttnBlock, CrossFusion, GoldFormerEncoder,
        BaseTrainer, MultiPhaseTrainer, WorldModelLoss,
    )
"""

from .config import BaseConfig, GoldFormerConfig, GoldTraderR1Config
from .data_engine import DataEngine
from .dataset import GoldDataset
from .layers import (
    RevIN, PatchEmbed, RoPE, ChannelAttnBlock, CrossFusion,
    GoldFormerEncoder,
)
from .trainer import (
    BaseTrainer, MultiPhaseTrainer, WorldModelLoss,
)

__all__ = [
    "BaseConfig", "GoldFormerConfig", "GoldTraderR1Config",
    "DataEngine", "GoldDataset",
    "RevIN", "PatchEmbed", "RoPE", "ChannelAttnBlock", "CrossFusion",
    "GoldFormerEncoder",
    "BaseTrainer", "MultiPhaseTrainer", "WorldModelLoss",
]
