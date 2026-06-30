#!/usr/bin/env python3
"""
公共训练器 — 支持单阶段 & 多阶段训练

  BaseTrainer               — 基础训练循环 (单阶段，GoldFormer 使用)
  MultiPhaseTrainer         — 多阶段训练 (GoldTrader-R1 使用)
  WorldModelLoss            — 预测损失 (方向 + 收益 + 波动率 + 环境)
"""

import math, time
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist
from torch.cuda.amp import GradScaler


# ============================================================
# 损失函数 — 世界模型 (预测)
# ============================================================

class WorldModelLoss(nn.Module):
    """
    多任务预测损失:
      L = λ_dir·BCE + λ_ret·GaussianNLL + λ_vol·MSE(future_realized_vol) + λ_regime·CE

    Y_vol 语义: future realized volatility (已修正) 或 historical vol (旧)
    """
    def __init__(self, lambda_dir=1.0, lambda_ret=0.5, lambda_vol=0.1, lambda_regime=0.3):
        super().__init__()
        self.bce = nn.BCEWithLogitsLoss()
        self.ld, self.lr, self.lv, self.lg = lambda_dir, lambda_ret, lambda_vol, lambda_regime

    def forward(self, pred, target):
        # 方向损失
        H = pred["dir_logits"].shape[-1]
        L_dir = sum(
            self.bce(pred["dir_logits"][:, h], target["Y_dir"][:, h])
            for h in range(H)
        ) / H

        # 收益率损失 (Gaussian NLL)
        rlv = pred["ret_logvar"].clamp(-3, 5)
        L_ret = 0.5 * (rlv + (target["Y_ret"] - pred["ret_mean"]) ** 2 / (rlv.exp() + 1e-8)).mean()

        # 波动率损失 (NaN-safe)
        vol_mask = ~torch.isnan(target["Y_vol"])
        if vol_mask.any():
            pred_std = torch.exp(0.5 * rlv)
            L_vol = F.mse_loss(pred_std[vol_mask], target["Y_vol"][vol_mask])
        else:
            L_vol = torch.tensor(0.0, device=rlv.device)

        # 环境分类 (跳过 dummy/占位 head，仅当输出类别 ≥2 时计算)
        has_regime = ("regime_logits" in pred and pred["regime_logits"].shape[-1] >= 2)
        L_regime = F.cross_entropy(pred["regime_logits"], target["Y_regime"]) \
            if has_regime else torch.tensor(0.0, device=rlv.device)

        total = self.ld * L_dir + self.lr * L_ret + self.lv * L_vol + self.lg * L_regime
        comps = {"L_dir": L_dir.item(), "L_ret": L_ret.item(),
                 "L_vol": L_vol.item(), "L_regime": L_regime.item()}
        return total, comps


# ============================================================
# BaseTrainer — 单阶段训练
# ============================================================

class BaseTrainer:
    """
    单阶段训练器 (GoldFormer 使用).

    用法:
        trainer = BaseTrainer(model, cfg, train_loader, val_loader, test_loader)
        trainer.fit()
        trainer.save("models/goldformer_best.pt")
    """

    def __init__(self, model, cfg, train_ldr, val_ldr, test_ldr,
                 loss_fn=None, lr: float = None, epochs: int = None,
                 ddp: bool = False, sampler=None):
        self.model = model
        self.cfg = cfg
        self.train_ldr = train_ldr
        self.val_ldr = val_ldr
        self.test_ldr = test_ldr
        self.ddp = ddp
        self.sampler = sampler  # DistributedSampler (only used when ddp=True)

        self.loss_fn = loss_fn or WorldModelLoss(
            cfg.lambda_dir, cfg.lambda_ret, cfg.lambda_vol, cfg.lambda_regime
        )
        self.lr = lr or cfg.lr
        self.epochs = epochs or cfg.epochs

        self.opt = torch.optim.AdamW(self._unwrap_model().parameters(), lr=self.lr, weight_decay=cfg.weight_decay)
        self.scaler = GradScaler(enabled=(cfg.dtype == "float16"))

        total_steps = len(train_ldr) * self.epochs // cfg.grad_accum
        warmup_steps = len(train_ldr) * cfg.warmup_epochs // cfg.grad_accum
        def lr_fn(s):
            if s < warmup_steps: return s / max(1, warmup_steps)
            return 0.5 * (1 + math.cos(math.pi * (s - warmup_steps) / max(1, total_steps - warmup_steps)))
        self.scheduler = torch.optim.lr_scheduler.LambdaLR(self.opt, lr_fn)

        self.best_val = float("inf")
        self.best_state = None

    def _unwrap_model(self):
        """Returns the raw model (unwrapped from DDP if needed)."""
        return self.model.module if self.ddp else self.model

    def _is_master(self):
        return (not self.ddp) or (dist.get_rank() == 0)

    def _amp_ctx(self):
        dt = torch.bfloat16 if self.cfg.dtype == "bfloat16" else torch.float32
        device = "cuda" if torch.cuda.is_available() else "cpu"
        return torch.amp.autocast(device, dtype=dt)

    def _prepare_target(self, yd, yr, yv, yg):
        return {"Y_dir": yd, "Y_ret": yr, "Y_vol": yv, "Y_regime": yg}

    def train_epoch(self, epoch: int = 0, log_interval: int = 200):
        self.model.train()
        if self.sampler is not None:
            self.sampler.set_epoch(epoch)
        tl, comps = 0.0, {}
        self.opt.zero_grad()
        n_batches = len(self.train_ldr)
        t_start = time.time()
        for i, batch in enumerate(self.train_ldr):
            x, yd, yr, yv, yg = [b.to(self.cfg.device) for b in batch]
            with self._amp_ctx():
                pred = self.model(x)
                loss, c = self.loss_fn(pred, self._prepare_target(yd, yr, yv, yg))
                loss = loss / self.cfg.grad_accum
            self.scaler.scale(loss).backward()
            if (i + 1) % self.cfg.grad_accum == 0:
                self.scaler.unscale_(self.opt)
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                self.scaler.step(self.opt); self.scaler.update()
                self.opt.zero_grad(); self.scheduler.step()
            tl += loss.item() * self.cfg.grad_accum
            for k in c: comps[k] = comps.get(k, 0) + c[k]
            # 进度日志 (首个 batch 和每 N 个 batch 打印，仅 master)
            if self._is_master() and (i == 0 or (i + 1) % log_interval == 0):
                elapsed = time.time() - t_start
                speed = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (n_batches - i - 1) / speed if speed > 0 else 0
                print(f"    batch {i+1:>5d}/{n_batches} ({100*(i+1)/n_batches:.0f}%) | "
                      f"loss={tl/(i+1):.4f} | {speed:.0f} bat/s | ETA {eta:.0f}s", flush=True)
        n = len(self.train_ldr)
        return tl / n, {k: v / n for k, v in comps.items()}

    @torch.no_grad()
    def evaluate(self, ldr, tag="val"):
        self.model.eval()
        tl, cor, tot = 0.0, 0, 0
        for batch in ldr:
            x, yd, yr, yv, yg = [b.to(self.cfg.device) for b in batch]
            with self._amp_ctx():
                pred = self.model(x)
                loss, _ = self.loss_fn(pred, self._prepare_target(yd, yr, yv, yg))
            tl += loss.item()
            # 评估短尺度方向准确率
            pred_dir = (torch.sigmoid(pred["dir_logits"][:, 0]) > 0.5).float()
            cor += (pred_dir == yd[:, 0]).sum().item(); tot += yd.size(0)
        avg_loss = tl / len(ldr)
        acc = cor / max(tot, 1)
        if self._is_master():
            print(f"  📊 {tag}: loss={avg_loss:.6f}  acc(short)={acc:.2%}")
        return avg_loss, acc

    def fit(self, verbose=True, patience: int = 30, min_delta: float = 1e-5):
        """
        patience:  连续 N 个 epoch val_loss 不创新低则早停
        min_delta: val_loss 改善低于此值视为无改善
        """
        if verbose:
            n_params = sum(p.numel() for p in self._unwrap_model().parameters())
            print(f"\n{'='*60}\n🚀 训练启动 ({self.cfg.model_type})")
            print(f"  参数: {n_params:,} | 设备: {self.cfg.device} | 精度: {self.cfg.dtype}")
            print(f"  batch={self.cfg.batch_size} | seq_len={self.cfg.seq_len} | features={self.cfg.n_features}")
            print(f"  use_future_vol={self.cfg.use_future_vol}")
            print(f"  max_epochs={self.epochs} | patience={patience} | min_delta={min_delta}")
            if self.ddp:
                print(f"  🔗 DDP: {dist.get_world_size()} GPUs")
            print(f"{'='*60}")

        no_improve = 0
        final_epoch = self.epochs
        for ep in range(1, self.epochs + 1):
            t0 = time.time()
            tl, comps = self.train_epoch(epoch=ep)
            vl, va = self.evaluate(self.val_ldr, "val")
            if self._is_master():
                comps_str = " ".join(f"{k}={v:.4f}" for k, v in comps.items())
                print(f"  Ep {ep:3d} | train={tl:.6f} val={vl:.6f} acc={va:.2%} "
                      f"lr={self.scheduler.get_last_lr()[0]:.2e} | {comps_str} | {time.time()-t0:.1f}s")

            improved = vl < self.best_val - min_delta
            if improved:
                self.best_val = vl
                self.best_state = {k: v.cpu().clone() for k, v in self._unwrap_model().state_dict().items()}
                no_improve = 0
                if self._is_master():
                    print(f"  ✅ best (vl={vl:.6f})")
            else:
                no_improve += 1
                if no_improve >= patience:
                    if self._is_master():
                        print(f"  ⏹ 早停! {patience} 轮无改善 (best_vl={self.best_val:.6f})")
                    final_epoch = ep
                    break

        self._unwrap_model().load_state_dict(self.best_state)
        if self._is_master():
            print(f"\n🏁 训练完成 | epoch={final_epoch}/{self.epochs} | best_val_loss={self.best_val:.6f}")
            self.evaluate(self.test_ldr, "test")
        if self.ddp:
            dist.barrier()
        return self.best_val

    def save(self, path):
        state = self.best_state if self.best_state is not None else \
                {k: v.cpu().clone() for k, v in self._unwrap_model().state_dict().items()}
        torch.save({"state": state, "cfg": self.cfg, "val_loss": self.best_val}, path)
        print(f"  💾 模型已保存: {path}")


# ============================================================
# MultiPhaseTrainer — 多阶段训练 (GoldTrader-R1)
# ============================================================

class MultiPhaseTrainer(BaseTrainer):
    """
    多阶段训练器.

    Phase 1: 世界模型训练 (预测 + 环境识别)
    Phase 2: 策略网络训练 (模仿学习)
    Phase 3: 决策感知联合微调

    通过 freeze/unfreeze 参数组控制各阶段可训练参数.
    """

    def __init__(self, model, cfg, train_ldr, val_ldr, test_ldr,
                 loss_fn=None, policy_loss_fn=None, da_loss_fn=None,
                 ddp: bool = False, sampler=None):
        super().__init__(model, cfg, train_ldr, val_ldr, test_ldr, loss_fn,
                         ddp=ddp, sampler=sampler)

        self.policy_loss_fn = policy_loss_fn
        self.da_loss_fn = da_loss_fn

        # 参数分组
        self.encoder_params = self._get_params(["revin", "patch_embed", "rope",
            "mamba_encoder", "moe_blocks", "griffin_block", "timesnet", "encoder_fusion"])
        self.pred_params = self._get_params(["pool", "h_dir", "h_ret", "h_lvar",
            "regime_head", "uncertainty_head"])
        self.policy_params = self._get_params(["pred_proj", "regime_embed", "macro_encoder",
            "decision_context", "temporal_cross_attn", "portfolio_encoder",
            "decision_fusion", "kan_dir", "kan_pos", "kan_sl", "kan_tp", "action_heads"])

    def _get_params(self, name_patterns):
        params = set()
        for n, p in self.model.named_parameters():
            if any(pat in n for pat in name_patterns):
                params.add(p)
        return params

    def _set_trainable(self, encoder=False, pred=False, policy=False):
        for n, p in self.model.named_parameters():
            in_encoder = any(pat in n for pat in ["revin", "patch_embed", "rope",
                "mamba_encoder", "moe_blocks", "griffin_block", "timesnet", "encoder_fusion"])
            in_pred = any(pat in n for pat in ["pool", "h_dir", "h_ret", "h_lvar",
                "regime_head", "uncertainty_head"])
            in_policy = any(pat in n for pat in ["pred_proj", "regime_embed", "macro_encoder",
                "decision_context", "temporal_cross_attn", "portfolio_encoder",
                "decision_fusion", "kan_dir", "kan_pos", "kan_sl", "kan_tp", "action_heads"])
            p.requires_grad = (in_encoder and encoder) or (in_pred and pred) or (in_policy and policy)

    def _rebuild_optimizer(self, lr):
        self.opt = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, self._unwrap_model().parameters()),
            lr=lr, weight_decay=self.cfg.weight_decay,
        )
        self.scaler = GradScaler(enabled=(self.cfg.dtype == "float16"))

    def fit_phase1(self):
        """世界模型训练."""
        if self._is_master():
            print(f"\n{'='*60}\n🧬 Phase 1: 世界模型训练 (预测 + 环境识别)\n{'='*60}")
        self._set_trainable(encoder=True, pred=True, policy=False)
        self._rebuild_optimizer(self.cfg.lr_p1)
        self.best_val = float("inf")
        epochs = getattr(self.cfg, 'epochs_p1', self.epochs)

        for ep in range(1, epochs + 1):
            t0 = time.time()
            tl, comps = self.train_epoch(epoch=ep)
            vl, va = self.evaluate(self.val_ldr, "val")
            if self._is_master():
                print(f"  Ep {ep:3d} | train={tl:.6f} val={vl:.6f} acc={va:.2%} "
                      f"L_dir={comps.get('L_dir',0):.4f} L_ret={comps.get('L_ret',0):.4f} "
                      f"L_vol={comps.get('L_vol',0):.6f} L_regime={comps.get('L_regime',0):.4f} "
                      f"| {time.time()-t0:.1f}s")
            if vl < self.best_val:
                self.best_val = vl
                self.best_state = {k: v.cpu().clone() for k, v in self._unwrap_model().state_dict().items()}
        self._unwrap_model().load_state_dict(self.best_state)
        if self._is_master():
            print(f"  🏁 Phase 1 最佳 val_loss={self.best_val:.6f}")
        if self.ddp:
            dist.barrier()

    def fit_phase2(self):
        """模仿学习 — 策略网络."""
        if self._is_master():
            print(f"\n{'='*60}\n🎯 Phase 2: 模仿学习 (策略网络)\n{'='*60}")
        self._set_trainable(encoder=False, pred=False, policy=True)
        self._rebuild_optimizer(self.cfg.lr_p2)
        self.best_val = float("inf")
        epochs = getattr(self.cfg, 'epochs_p2', self.epochs // 2)

        for ep in range(1, epochs + 1):
            t0 = time.time()
            self.model.train()
            if self.sampler is not None:
                self.sampler.set_epoch(ep)
            tl = 0.0
            n_batches = len(self.train_ldr)
            self.opt.zero_grad()
            for i, batch in enumerate(self.train_ldr):
                x, yd, yr, yv, yg = [b.to(self.cfg.device) for b in batch]
                with self._amp_ctx():
                    pred = self.model(x)
                    if self.policy_loss_fn is not None:
                        optimal_dir = (yd[:, 0] > 0.5).long()
                        labels = {
                            "direction": optimal_dir,
                            "position": torch.clamp(yr[:, 0].abs() * 20, 0, 1),
                            "stop_loss": torch.ones_like(yr[:, 0]) * 1.5,
                            "take_profit": torch.ones_like(yr[:, 0]) * 3.0,
                            "prev_direction": torch.zeros_like(optimal_dir),
                        }
                        loss, _ = self.policy_loss_fn(pred, labels)
                    else:
                        loss, _ = self.loss_fn(pred, self._prepare_target(yd, yr, yv, yg))
                    loss = loss / self.cfg.grad_accum
                self.scaler.scale(loss).backward()
                if (i + 1) % self.cfg.grad_accum == 0:
                    self.scaler.unscale_(self.opt)
                    nn.utils.clip_grad_norm_(self._unwrap_model().parameters(), 1.0)
                    self.scaler.step(self.opt); self.scaler.update()
                    self.opt.zero_grad()
                tl += loss.item() * self.cfg.grad_accum
                if self._is_master() and (i == 0 or (i + 1) % 200 == 0):
                    elapsed = time.time() - t0
                    speed = (i + 1) / elapsed if elapsed > 0 else 0
                    eta = (n_batches - i - 1) / speed if speed > 0 else 0
                    print(f"    batch {i+1:>5d}/{n_batches} ({100*(i+1)/n_batches:.0f}%) | "
                          f"loss={tl/(i+1):.4f} | {speed:.0f} bat/s | ETA {eta:.0f}s", flush=True)
            tl /= len(self.train_ldr)
            vl, _ = self.evaluate(self.val_ldr, "val")
            if self._is_master():
                print(f"  Ep {ep:3d} | train={tl:.6f} val={vl:.6f} | {time.time()-t0:.1f}s")
            if vl < self.best_val:
                self.best_val = vl
                self.best_state = {k: v.cpu().clone() for k, v in self._unwrap_model().state_dict().items()}
        self._unwrap_model().load_state_dict(self.best_state)
        if self._is_master():
            print(f"  🏁 Phase 2 最佳 val_loss={self.best_val:.6f}")
        if self.ddp:
            dist.barrier()

    def fit_phase3(self):
        """决策感知联合微调."""
        if self._is_master():
            print(f"\n{'='*60}\n🔗 Phase 3: 决策感知联合微调\n{'='*60}")
        self._set_trainable(encoder=True, pred=True, policy=True)
        self._rebuild_optimizer(self.cfg.lr_p3)
        self.best_val = float("inf")
        epochs = getattr(self.cfg, 'epochs_p3', self.epochs // 4)

        for ep in range(1, epochs + 1):
            t0 = time.time()
            self.model.train()
            if self.sampler is not None:
                self.sampler.set_epoch(ep)
            tl = 0.0
            n_batches = len(self.train_ldr)
            self.opt.zero_grad()
            for i, batch in enumerate(self.train_ldr):
                x, yd, yr, yv, yg = [b.to(self.cfg.device) for b in batch]
                with self._amp_ctx():
                    pred = self.model(x)
                    w_loss, _ = self.loss_fn(pred, self._prepare_target(yd, yr, yv, yg))
                    if self.da_loss_fn is not None:
                        da_loss = self.da_loss_fn(pred, pred, yr)
                        loss = (w_loss + da_loss) / self.cfg.grad_accum
                    else:
                        loss = w_loss / self.cfg.grad_accum
                self.scaler.scale(loss).backward()
                if (i + 1) % self.cfg.grad_accum == 0:
                    self.scaler.unscale_(self.opt)
                    nn.utils.clip_grad_norm_(self._unwrap_model().parameters(), 1.0)
                    self.scaler.step(self.opt); self.scaler.update()
                    self.opt.zero_grad()
                tl += loss.item() * self.cfg.grad_accum
                if self._is_master() and (i == 0 or (i + 1) % 200 == 0):
                    elapsed = time.time() - t0
                    speed = (i + 1) / elapsed if elapsed > 0 else 0
                    eta = (n_batches - i - 1) / speed if speed > 0 else 0
                    print(f"    batch {i+1:>5d}/{n_batches} ({100*(i+1)/n_batches:.0f}%) | "
                          f"loss={tl/(i+1):.4f} | {speed:.0f} bat/s | ETA {eta:.0f}s", flush=True)
            tl /= len(self.train_ldr)
            vl, _ = self.evaluate(self.val_ldr, "val")
            if self._is_master():
                print(f"  Ep {ep:3d} | train={tl:.6f} val={vl:.6f} | {time.time()-t0:.1f}s")
            if vl < self.best_val:
                self.best_val = vl
                self.best_state = {k: v.cpu().clone() for k, v in self._unwrap_model().state_dict().items()}
        self._unwrap_model().load_state_dict(self.best_state)
        if self._is_master():
            print(f"  🏁 Phase 3 最佳 val_loss={self.best_val:.6f}")
        if self.ddp:
            dist.barrier()

    def fit(self, phase="all", verbose=True):
        if verbose:
            n_params = sum(p.numel() for p in self._unwrap_model().parameters())
            print(f"\n{'='*60}\n🚀 GoldTrader-R1 多阶段训练")
            print(f"  参数: {n_params:,} ({n_params/1e6:.1f}M) | 设备: {self.cfg.device}")
            if self.ddp:
                print(f"  🔗 DDP: {dist.get_world_size()} GPUs")
            print(f"  phase={phase}")
            print(f"{'='*60}")

        if phase in ("p1", "phase1", "all"):
            self.fit_phase1()
        if phase in ("p2", "phase2", "all"):
            self.fit_phase2()
        if phase in ("p3", "phase3", "all"):
            self.fit_phase3()

        if self._is_master():
            print(f"\n✅ 训练完成! 最终最佳 val_loss={self.best_val:.6f}")
            self.evaluate(self.test_ldr, "test")
        if self.ddp:
            dist.barrier()
        return self.best_val
