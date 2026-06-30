#!/usr/bin/env python3
"""
公共数据集 — 纯内存、zero-copy 访问
"""

import torch
from torch.utils.data import Dataset


class GoldDataset(Dataset):
    """
    纯内存数据集: 持有 DataEngine 的引用 + index slice，zero-copy 访问.

    Args:
        engine:    DataEngine 实例
        mode:      "train" | "val" | "test"
        phase:     "p1" (预测) | "p2" (策略) — 影响返回的标签
        seq_len:   可选覆盖 DataEngine 的 cfg.seq_len
    """

    def __init__(self, engine, mode: str, phase: str = "p1", seq_len: int = None):
        self.engine = engine
        self.feats = engine.features
        self.seq_len = seq_len or engine.cfg.seq_len
        self.start_offset = engine.start_offset
        self.Y_dir = engine.Y_dir
        self.Y_ret = engine.Y_ret
        self.Y_vol = engine.Y_vol
        self.Y_regime = engine.Y_regime
        self.phase = phase

        if mode == "train":
            self.sl = engine.train_idx
        elif mode == "val":
            self.sl = engine.val_idx
        else:
            self.sl = engine.test_idx

    def __len__(self):
        return self.sl.stop - self.sl.start

    def __getitem__(self, i):
        # 样本索引 → 原始特征时间索引 (关键偏移修正)
        idx = self.sl.start + i
        raw_idx = idx + self.start_offset
        x  = torch.from_numpy(self.feats[:, raw_idx - self.seq_len:raw_idx]).float().contiguous()
        yd = torch.from_numpy(self.Y_dir[idx]).float()
        yr = torch.from_numpy(self.Y_ret[idx]).float()
        yv = torch.from_numpy(self.Y_vol[idx]).float()
        yg = torch.tensor(self.Y_regime[idx], dtype=torch.long)
        return x, yd, yr, yv, yg
