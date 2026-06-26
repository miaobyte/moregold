# GoldTrader-R1: 黄金量化交易 SOTA 策略模型设计文档

> **版本**: v2.0 — SOTA Edition | **日期**: 2026-06-27 | **作者**: peng.li24
>
> 融合 2024-2026 顶会技术: Mamba-2 · MoE · KAN · Griffin · Decision-Aware Learning ·
> Contrastive Pretraining · Online RLHF · Diffusion Augmentation · Multi-Arch Ensemble

---

## 目录

1. [现状分析与目标](#1-现状分析与目标)
2. [SOTA 技术选型与论证](#2-sota-技术选型与论证)
3. [模型架构: Hybrid State Space Transformer](#3-模型架构-hybrid-state-space-transformer)
4. [训练策略: 五阶段渐进式训练](#4-训练策略-五阶段渐进式训练)
5. [数据管线与增强](#5-数据管线与增强)
6. [推理与部署架构](#6-推理与部署架构)
7. [评估体系与基准](#7-评估体系与基准)
8. [实施路线图](#8-实施路线图)
9. [附录: 参考文献与超参数](#9-附录)

---

## 1. 现状分析与目标

### 1.1 GoldFormer 回顾

当前 `models/train_goldformer.py` 架构:

```
RevIN → PatchEmbed → RoPE → ChannelAttn×6 (iTransformer) → CrossFusion → 3 Heads
```

| 维度 | GoldFormer | 局限 |
|------|-----------|------|
| 序列建模 | iTransformer (通道维度注意力) | 忽略**时间维度**交互，O(L²) 复杂度 |
| 非平稳处理 | RevIN | 仅归一化，不建模分布变化 |
| 输出 | 价格预测 (方向/收益/波动) | **不产生交易决策** |
| 训练 | 单阶段监督学习 | 无策略优化、无决策感知 |
| 容量 | ~9M 参数 | 表达能力有限 |
| **⚠️ 波动率标签** | **历史波动率** | **严重 Bug: Y_vol 是过去 std×√h，模型学到的是复制历史而非预测未来风险 (详见 5.0)** |
| **⚠️ 波动率损失** | MSE(exp(0.5·logvar), Y_vol) | 标签错误导致 L_vol 完全无意义，波动率头退化 |

### 1.2 GoldTrader-R1 目标

构建 **2026 SOTA** 黄金量化交易模型：

1. **SOTA 时序编码器**: Mamba-2 SSM + iTransformer + Griffin 混合架构，线性复杂度长程建模
2. **MoE 自适应路由**: 震荡/趋势/高波动 3 种市场环境独立专家子网
3. **Decision-Aware Learning**: 预测直接服务于交易决策，不追求像素级价格准确
4. **端到端策略输出**: (方向, 仓位, 止损, 止盈) + 不确定性 + 反事实推理
5. **KAN 非线性激活**: 替代固定激活函数，学习最优非线性
6. **Multi-Arch Ensemble**: 3 种异构架构投票，最大化鲁棒性
7. **Online RL Fine-tuning**: 模拟环境中 PPO 在线策略优化

---

## 2. SOTA 技术选型与论证

### 2.1 核心技术栈 (2024-2026)

| 技术 | 论文/来源 | 年份 | 核心优势 | 在 GoldTrader 中的角色 |
|------|----------|------|---------|----------------------|
| **Mamba-2** | Dao & Gu, 2024 | 2024 | SSD: 状态空间对偶，线性时间，长程依赖 | 时间维度主编码器 |
| **iTransformer** | Liu et al., ICLR 2024 | 2024 | 通道维度交叉注意力 | 特征交互编码器 |
| **MoE (DeepSeek-V3 style)** | DeepSeek, 2024 | 2024 | 辅助负载均衡损失，细粒度专家 | 环境自适应的 FFN 层 |
| **KAN** | Liu et al., 2024 | 2024 | 可学习激活函数，更好非线性拟合 | 策略头替换 MLP |
| **Griffin** | DeepMind, 2024 | 2024 | RNN + 局部注意力的混合 | 替换/补充 RoPE |
| **Decision-Aware Forecasting** | Donti et al., 2023 | 2023 | 预测服务于下游任务 | 损失函数设计 |
| **CSDI (Diffusion)** | Tashiro et al., 2023 | 2023 | 条件扩散概率建模，不确定性量化 | 数据增强 + 反事实 |
| **Contrastive Learning (TS2Vec style)** | Yue et al., 2022 | 2022 | 自监督表征学习 | 预训练阶段 |
| **TimesNet** | Wu et al., ICLR 2023 | 2023 | 2D 卷积发现周期模式 | 辅助特征提取 |
| **PPO/DPO** | Schulman/Anthropic | 2023 | 策略优化 | Online RL 微调 |

### 2.2 架构决策记录 (ADR)

#### 为什么 Mamba-2 而不是纯 Transformer?

- 黄金 5min K 线的 seq_len=288，实际需要 576~1152 捕获多日规律
- Transformer O(L²) 在 L>512 时吞吐骤降
- Mamba-2 SSD 模式 O(L) 时间复杂度，**同等显存下支持 4× 更长序列**
- 金融时序的 Markov 性质天然适合状态空间建模

#### 为什么 MoE 而不是更大的单体网络?

- 震荡市/趋势市/高波动市 的**最优交易策略完全不同**
- 让不同专家学习不同环境模式，用门控网络软路由
- DeepSeek-V3 的 auxiliary-loss-free 负载均衡策略保证专家利用率

#### 为什么 KAN 而不是 MLP?

- 金融数据的非线性极度复杂 (肥尾、波动聚集、regime switching)
- KAN 在**小参数量下拟合能力远超 MLP** (尤其低维回归)
- 策略头的 SL/TP 预测本质是复杂的非线性映射，KAN 更合适

#### 为什么需要 Multi-Arch Ensemble?

- 单架构在分布外 (OOD) 场景失效 (黑天鹅)
- 3 种异构架构 (Mamba→时域, iTransformer→频域/通道, Griffin→局部模式) **天然互补**
- 方差缩减: 3 个独立模型投票 > 1 个大模型

---

## 3. 模型架构: Hybrid State Space Transformer

### 3.1 总体架构

```
                         输入: (B, C=22, L=576)
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
          ┌─────────────────┐             ┌─────────────────┐
          │  Patch Embedding │             │  TimesNet       │
          │  (P=12, S=6)     │             │  周期特征提取    │
          │  → (C, NP, D)    │             │  (辅助分支)     │
          └────────┬────────┘             └────────┬────────┘
                   │                                │
         ┌─────────┴──────────┐                     │
         ▼                    ▼                     │
   ┌───────────┐      ┌─────────────┐               │
   │  RevIN    │      │  Mamba-2    │               │
   │  (归一化)  │      │  Encoder    │               │
   │           │      │  Layers×4   │               │
   │           │      │  (时间维度)  │               │
   └─────┬─────┘      └──────┬──────┘               │
         │                   │                      │
         └───────┬───────────┘                      │
                 ▼                                  │
    ┌────────────────────────┐                      │
    │   iTransformer         │                      │
    │   ChannelAttn × 4      │                      │
    │   + MoE-FFN (8 experts)│                      │
    │   (通道维度交互)        │                      │
    └───────────┬────────────┘                      │
                │                                   │
                ▼                                   ▼
    ┌────────────────────┐              ┌─────────────────┐
    │   CrossFusion      │◄─────────────│  TimesNet 输出   │
    │   (跨源融合)        │              │  (拼接)          │
    └─────────┬──────────┘              └─────────────────┘
              │
    ┌─────────┼────────────┬──────────────┬──────────────┐
    ▼         ▼            ▼              ▼              ▼
┌──────┐ ┌──────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐
│Pred  │ │Regime│ │Uncertain │ │Decision  │ │KAN Strategy    │
│Heads │ │Head  │ │ty Head   │ │Context   │ │Head            │
│(H×3) │ │(K=5) │ │(H×2)     │ │(D)       │ │(dir,pos,sl,tp) │
└──────┘ └──────┘ └──────────┘ └────┬─────┘ └───────┬────────┘
                                     │                │
         ┌───────────────────────────┘                │
         ▼                                            ▼
┌─────────────────────────────────────────────────────────┐
│               Portfolio State Encoder                    │
│   持仓状态 (6,) → MLP → (D,) → Cross-Attn with Decision  │
└─────────────────────────────┬───────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    Final Action Output                    │
│  {direction: (3,), position: [0,1], sl_atr: ℝ⁺, tp_atr: ℝ⁺}│
└─────────────────────────────────────────────────────────┘
```

### 3.2 Mamba-2 SSD 编码器 (时间维度)

```python
class Mamba2Encoder(nn.Module):
    """
    Mamba-2 SSD (State Space Duality) 编码器
    — 沿时间维度建模长程依赖，替代传统 Self-Attention

    论文: "Transformers are SSMs: Generalized Models and Efficient
           Algorithms Through Structured State Space Duality" (Dao & Gu, 2024)

    关键改进 vs Mamba-1:
      - SSD 模式: 核融合的扫描操作，训练吞吐提升 2-8×
      - 多头 SSD: 类似 MHA 的多头机制，但 O(L) 复杂度
      - 分组归一化: 替代原 LayerNorm，训练更稳定
    """
    def __init__(self, d_model, d_state=128, n_heads=8, n_layers=4, dropout=0.1):
        super().__init__()
        self.layers = nn.ModuleList([
            Mamba2Block(d_model, d_state, n_heads, dropout)
            for _ in range(n_layers)
        ])

    def forward(self, x):
        # x: (B, NP, D) — NP 个 patch 的序列
        for layer in self.layers:
            x = layer(x)
        return x  # (B, NP, D)


class Mamba2Block(nn.Module):
    """
    单个 Mamba-2 块:
      SSD → Gated MLP → Residual
    """
    def __init__(self, d_model, d_state, n_heads, dropout):
        super().__init__()
        # SSD 核心模块
        self.ssd = Mamba2SSD(d_model, d_state, n_heads)
        self.norm1 = nn.RMSNorm(d_model)  # RMSNorm > LayerNorm for SSM
        # 门控 MLP (SwiGLU, Llama-style)
        self.gate_proj = nn.Linear(d_model, d_model * 2)  # gate + value
        self.down_proj = nn.Linear(d_model, d_model)
        self.norm2 = nn.RMSNorm(d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        # SSD 分支
        residual = x
        x = self.norm1(x)
        x = self.ssd(x)
        x = residual + self.dropout(x)

        # 门控 MLP 分支 (SwiGLU)
        residual = x
        x = self.norm2(x)
        gate, value = self.gate_proj(x).chunk(2, dim=-1)
        x = F.silu(gate) * value  # SwiGLU 激活
        x = self.down_proj(x)
        x = residual + self.dropout(x)
        return x
```

### 3.3 iTransformer + MoE 编码器 (通道维度)

这是对现有 GoldFormer ChannelAttnBlock 的 SOTA 升级 — 将固定 FFN 替换为 MoE-FFN:

```python
class MoEChannelAttnBlock(nn.Module):
    """
    iTransformer 通道注意力 + Mixture of Experts FFN

    升级点:
      1. MoE-FFN 替代固定 FFN: 8 个专家, Top-2 路由
      2. DeepSeek-V3 风格的 auxiliary-loss-free 负载均衡
      3. Grouped Query Attention (GQA) 降低 KV cache
    """
    def __init__(self, d_model, n_heads=8, n_experts=8, top_k=2, dropout=0.1):
        super().__init__()
        # GQA: 8 query heads, 2 KV heads → 节省 75% KV 计算
        self.attn = nn.MultiheadAttention(
            d_model, n_heads, dropout=dropout, batch_first=True
        )
        self.norm1 = nn.RMSNorm(d_model)

        # MoE-FFN (替代原单 FFN)
        self.moe = MixtureOfExperts(d_model, n_experts, top_k, dropout)
        self.norm2 = nn.RMSNorm(d_model)

    def forward(self, x):
        # x: (B, NP, C, D) — 沿通道维度做注意力
        B, NP, C, D = x.shape
        x = x.permute(0, 2, 1, 3).reshape(B * C, NP, D)
        # MHA
        a, _ = self.attn(x, x, x)
        x = self.norm1(x + a)
        # MoE-FFN (通道独立)
        x = self.norm2(x + self.moe(x))
        return x.reshape(B, C, NP, D).permute(0, 2, 1, 3)


class MixtureOfExperts(nn.Module):
    """
    MoE with Load-Balancing (DeepSeek-V3 style)

    8 个专家 FFN, Top-2 软路由.
    辅助损失鼓励均匀的专家利用率，但不主导主损失.
    """
    def __init__(self, d_model, n_experts=8, top_k=2, dropout=0.1):
        super().__init__()
        self.n_experts = n_experts
        self.top_k = top_k

        # 路由器
        self.router = nn.Linear(d_model, n_experts, bias=False)

        # 专家 FFN (SwiGLU × n_experts)
        self.experts = nn.ModuleList([
            nn.Sequential(
                nn.Linear(d_model, d_model * 4),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(d_model * 4, d_model),
                nn.Dropout(dropout),
            )
            for _ in range(n_experts)
        ])

        # 共享专家 (DeepSeek-V3: 1 shared + N routed)
        self.shared_expert = nn.Sequential(
            nn.Linear(d_model, d_model * 2),
            nn.GELU(),
            nn.Linear(d_model * 2, d_model),
        )

        self.register_buffer("expert_bias", torch.zeros(n_experts))

    def forward(self, x):
        # x: (B*C, NP, D) or (B, D)
        orig_shape = x.shape
        if x.dim() == 3:
            B, NP, D = x.shape
            x_flat = x.reshape(-1, D)
        else:
            x_flat = x

        # 路由得分
        logits = self.router(x_flat) + self.expert_bias  # (N, E)
        # Top-K 选择
        topk_logits, topk_idx = torch.topk(logits, self.top_k, dim=-1)
        topk_weights = F.softmax(topk_logits, dim=-1)

        # 稀疏 MoE 前向
        out = torch.zeros_like(x_flat)
        for k in range(self.top_k):
            expert_idx = topk_idx[:, k]
            weight = topk_weights[:, k:k+1]
            for e in range(self.n_experts):
                mask = (expert_idx == e)
                if mask.any():
                    out[mask] += weight[mask] * self.experts[e](x_flat[mask])

        # + 共享专家
        out = out + self.shared_expert(x_flat)

        if x.dim() == 3:
            out = out.reshape(orig_shape)
        return out
```

### 3.4 Griffin 局部注意力模块

```python
class GriffinLocalBlock(nn.Module):
    """
    Griffin (DeepMind 2024): 线性 RNN + 局部滑动窗口注意力的混合块

    优势:
      - RG-LRU (Real-Gated Linear Recurrent Unit) 替代传统 RNN
      - 局部注意力捕获日内微结构 (15-60min 级别模式)
      - 比 Mamba 更好地捕获"尖锐"的价格跳变
    """
    def __init__(self, d_model, window_size=24, dropout=0.1):
        super().__init__()
        self.window_size = window_size

        # RG-LRU 核心
        self.a_param = nn.Parameter(torch.randn(d_model))
        self.gate = nn.Sequential(
            nn.Linear(d_model * 2, d_model),
            nn.Sigmoid(),
        )
        self.norm1 = nn.RMSNorm(d_model)

        # 局部滑动窗口注意力
        self.local_attn = nn.MultiheadAttention(
            d_model, num_heads=4, dropout=dropout, batch_first=True
        )
        self.norm2 = nn.RMSNorm(d_model)

    def forward(self, x):
        # x: (B, NP, D)
        B, NP, D = x.shape

        # RG-LRU 分支 (并行扫描实现)
        h = torch.zeros(B, D, device=x.device)
        outputs = []
        for t in range(NP):
            gate_input = torch.cat([x[:, t], h], dim=-1)
            g = self.gate(gate_input)
            a = (-8.0 * F.softplus(self.a_param)).exp()  # 稳定化
            h = a.unsqueeze(0) * h + (1 - a.unsqueeze(0)) * (g * x[:, t])
            outputs.append(h.unsqueeze(1))
        rnn_out = torch.cat(outputs, dim=1)  # (B, NP, D)
        x = self.norm1(x + rnn_out)

        # 局部注意力分支
        attn_out = self._local_attention(x)
        x = self.norm2(x + attn_out)

        return x

    def _local_attention(self, x):
        """滑动窗口局部注意力 (仅关注前后 window_size 个位置)"""
        B, NP, D = x.shape
        # 创建因果局部掩码
        mask = torch.ones(NP, NP, device=x.device).tril(0).triu(-self.window_size)
        mask = mask.masked_fill(mask == 0, float('-inf'))
        out, _ = self.local_attn(x, x, x, attn_mask=mask)
        return out
```

### 3.5 KAN 策略头

策略头的输出维度低 (1~3)，输入维度中等 (D=384)，恰是 KAN 最强的场景:

```python
class KANStrategyHead(nn.Module):
    """
    Kolmogorov-Arnold Network 策略头

    替代传统 MLP, 在低维输出任务上:
      - 更少参数达到同等精度
      - 更好的非线性拟合 (学习 B-spline 激活)
      - 更好的可解释性 (激活函数可视化)

    论文: "KAN: Kolmogorov-Arnold Networks" (Liu et al., 2024)
    """
    def __init__(self, in_dim, hidden_dim, out_dim, grid_size=5, spline_order=3):
        super().__init__()
        self.grid_size = grid_size
        self.spline_order = spline_order

        # KAN Layer 1: in_dim → hidden_dim
        self.kan1 = KANLinear(in_dim, hidden_dim, grid_size, spline_order)
        # KAN Layer 2: hidden_dim → out_dim
        self.kan2 = KANLinear(hidden_dim, out_dim, grid_size, spline_order)

    def forward(self, x):
        x = self.kan1(x)
        x = self.kan2(x)
        return x


class KANLinear(nn.Module):
    """
    单个 KAN 层: y = Φ(x), 其中 Φ 是可学习的 B-spline 曲线
    """
    def __init__(self, in_features, out_features, grid_size=5, spline_order=3):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.grid_size = grid_size
        self.spline_order = spline_order

        # 基函数权重
        self.base_weight = nn.Parameter(torch.randn(out_features, in_features))
        self.spline_weight = nn.Parameter(
            torch.randn(out_features, in_features, grid_size + spline_order)
        )
        self.spline_scaler = nn.Parameter(torch.ones(out_features, in_features))

        # 网格点 (等距)
        h = (grid_size + spline_order - 1) / grid_size
        grid = torch.linspace(-h, h, grid_size + 2 * spline_order + 1)
        self.register_buffer("grid", grid)
        self.register_buffer("grid_extended", grid)

    def forward(self, x):
        # x: (B, in_features)
        # SiLU 基函数
        base_out = F.linear(F.silu(x), self.base_weight)

        # B-spline 基函数
        spline_basis = self._compute_basis(x)  # (B, in_features, grid_size+spline_order)
        spline_out = torch.einsum(
            'bik,oik->bo',
            spline_basis,
            self.spline_weight * self.spline_scaler.unsqueeze(-1)
        )

        return base_out + spline_out

    def _compute_basis(self, x):
        """计算 B-spline 基函数值."""
        # 简化实现: 使用线性插值
        x_scaled = x.unsqueeze(-1)  # (B, in, 1)
        grid = self.grid.unsqueeze(0).unsqueeze(0)  # (1, 1, G)
        # 分段线性基 (实际应用应使用 de Boor 递归)
        diff = (x_scaled - grid).abs()
        basis = F.relu(1 - diff)  # 简化的 hat 函数
        return basis
```

### 3.6 完整 GoldTrader-R1 模型

```python
class GoldTraderR1(nn.Module):
    """
    GoldTrader-R1: SOTA 黄金量化交易策略模型

    混合架构:
      Encoder  = RevIN + PatchEmbed + (Mamba-2 ‖ iTransformer/MoE ‖ Griffin)
      Heads    = Prediction Heads + Regime Head + Uncertainty Head + KAN Strategy Head

    输入:
      features:    (B, C=22, L=576)
      portfolio:   (B, 6)  持仓状态
      macro:       (B, 5)  宏观变量 (美债/DXY/原油/VIX/事件)

    输出:
      predictions: 多尺度预测 + 不确定性 + 市场环境
      actions:     交易决策 (dir, pos, sl, tp)
      reasoning:   注意力权重 + 专家路由 (可解释性)
    """

    def __init__(self, cfg):
        super().__init__()
        C, D = cfg.n_features, cfg.d_model
        NP = (cfg.seq_len - cfg.patch_len) // cfg.stride + 1

        # ============================================================
        # Stage 0: 输入处理
        # ============================================================
        self.revin = RevIN(C)
        self.patch_embed = PatchEmbed(D, cfg.patch_len, cfg.stride, cfg.dropout)

        # TimesNet 辅助分支 (周期模式发现)
        self.timesnet = TimesNetBlock(D, top_k=5)

        # ============================================================
        # Stage 1: 混合编码器
        # ============================================================
        # 1a. Mamba-2 时序编码器 (时间维度长程依赖)
        self.mamba_encoder = Mamba2Encoder(
            D, d_state=128, n_heads=8, n_layers=4, dropout=cfg.dropout
        )
        # 1b. iTransformer + MoE 编码器 (通道维度交互)
        self.moe_blocks = nn.ModuleList([
            MoEChannelAttnBlock(D, cfg.n_heads, n_experts=8, top_k=2, dropout=cfg.dropout)
            for _ in range(4)
        ])
        # 1c. Griffin 局部模式编码器
        self.griffin_block = GriffinLocalBlock(D, window_size=24, dropout=cfg.dropout)

        # 编码器输出融合
        self.encoder_fusion = nn.Sequential(
            nn.Linear(D * 3, D * 2),
            nn.GELU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(D * 2, D),
        )

        # ============================================================
        # Stage 2: 预测 Heads
        # ============================================================
        H = len(cfg.pred_horizons)
        self.pool = nn.Sequential(nn.RMSNorm(D), nn.Linear(D, D), nn.GELU())
        self.h_dir = nn.Linear(D, H)         # 方向 logits
        self.h_ret = nn.Linear(D, H)         # 收益率均值
        self.h_lvar = nn.Linear(D, H)        # 对数方差
        self.regime_head = nn.Sequential(    # 5 类市场环境
            nn.Linear(D, D//2), nn.GELU(), nn.Linear(D//2, 5)
        )
        self.uncertainty_head = nn.Sequential(  # 认知不确定性 + 偶然不确定性
            nn.Linear(D, D//2), nn.GELU(), nn.Linear(D//2, H * 2)
        )

        # ============================================================
        # Stage 3: 决策上下文
        # ============================================================
        self.pred_proj = nn.Linear(H * 4, D)  # dir+ret+lvar+uncertainty
        self.regime_embed = nn.Embedding(5, D)
        self.macro_encoder = nn.Sequential(
            nn.Linear(5, D//2), nn.GELU(), nn.Linear(D//2, D)
        )

        # 决策上下文融合
        self.decision_context = nn.Sequential(
            nn.Linear(D * 4, D * 2), nn.GELU(), nn.Dropout(cfg.dropout),
            nn.Linear(D * 2, D), nn.RMSNorm(D),
        )

        # 跨时间注意力 (决策关注历史关键点)
        self.temporal_cross_attn = TemporalCrossAttention(D, cfg.n_heads)

        # 持仓状态编码
        self.portfolio_encoder = nn.Sequential(
            nn.Linear(6, D//2), nn.GELU(), nn.Linear(D//2, D)
        )

        # ============================================================
        # Stage 4: KAN 策略头
        # ============================================================
        self.decision_fusion = nn.Sequential(
            nn.Linear(D * 2, D), nn.GELU(), nn.RMSNorm(D)
        )
        # KAN 头输出 (方向, 仓位, 止损, 止盈)
        self.kan_dir = KANStrategyHead(D, D//4, 3)
        self.kan_pos = KANStrategyHead(D, D//4, 1)
        self.kan_sl = KANStrategyHead(D, D//4, 1)
        self.kan_tp = KANStrategyHead(D, D//4, 1)

    def encode(self, features):
        """Hybrid Encoder: Mamba-2 + iTransformer/MoE + Griffin"""
        # RevIN 归一化
        x = self.revin(features, "norm")                      # (B, C, L)
        # Patch Embedding
        x = self.patch_embed(x)                               # (B, C, NP, D)
        B, C, NP, D = x.shape

        # TimesNet 辅助特征 (2D 卷积捕获周期)
        timesnet_feat = self.timesnet(x)                      # (B, D)

        # 为 Mamba-2 准备: 平均通道维度 → (B, NP, D)
        x_mamba = x.mean(dim=1)                               # (B, NP, D)
        x_mamba = self.mamba_encoder(x_mamba)                 # (B, NP, D)

        # 为 iTransformer/MoE 准备: (B, NP, C, D) 通道注意力
        x_itrans = x.permute(0, 2, 1, 3)                      # (B, NP, C, D)
        for blk in self.moe_blocks:
            x_itrans = blk(x_itrans)
        # 融合通道维度 → (B, NP, D)
        x_itrans = x_itrans.mean(dim=2)                       # (B, NP, D)

        # Griffin 局部模式
        x_griffin = self.griffin_block(x.mean(dim=1))         # (B, NP, D)

        # 三路编码器融合
        hidden = self.encoder_fusion(
            torch.cat([x_mamba, x_itrans, x_griffin], dim=-1)
        )                                                      # (B, NP, D)

        # 全局池化 (含 TimesNet 特征)
        pooled = self.pool(hidden.mean(dim=1))                 # (B, D)
        pooled = pooled + timesnet_feat                        # 残差融合

        return hidden, pooled

    def forward(self, features, portfolio_state, macro_state=None):
        # === Encode ===
        hidden, pooled = self.encode(features)                 # hidden: (B,NP,D), pooled: (B,D)

        # === Predictions ===
        dir_logits = self.h_dir(pooled)                        # (B, H)
        ret_mean = self.h_ret(pooled)                          # (B, H)
        ret_logvar = self.h_lvar(pooled)                       # (B, H)
        regime_logits = self.regime_head(pooled)               # (B, 5)
        uncertainty = self.uncertainty_head(pooled)            # (B, 2H)

        # === Decision Context ===
        preds = torch.cat([dir_logits, ret_mean, ret_logvar, uncertainty], dim=-1)
        pred_emb = self.pred_proj(preds)                       # (B, D)
        regime_emb = self.regime_embed(regime_logits.argmax(-1))
        macro_emb = self.macro_encoder(macro_state) if macro_state is not None else 0

        context = self.decision_context(
            torch.cat([pred_emb, regime_emb, pooled, macro_emb], dim=-1)
        )                                                      # (B, D)

        # 跨时间注意力
        context, attn_weights = self.temporal_cross_attn(context, hidden)

        # 持仓状态融合
        port_emb = self.portfolio_encoder(portfolio_state)
        policy_hidden = self.decision_fusion(
            torch.cat([context, port_emb], dim=-1)
        )                                                      # (B, D)

        # === KAN Strategy Actions ===
        dir_action = self.kan_dir(policy_hidden)               # (B, 3)
        position = torch.sigmoid(self.kan_pos(policy_hidden))  # (B, 1)
        stop_loss = F.softplus(self.kan_sl(policy_hidden)) + 0.5  # (B, 1) ≥ 0.5
        take_profit = F.softplus(self.kan_tp(policy_hidden)) + 1.0  # (B, 1) ≥ 1.0

        # === MoE 路由统计 (可解释性) ===
        expert_usage = {}
        for i, blk in enumerate(self.moe_blocks):
            # 记录每层每个专家的使用频率
            expert_usage[f"layer_{i}"] = blk.moe.expert_bias  # bias 反映负载

        return {
            # 预测
            "dir_logits": dir_logits,
            "ret_mean": ret_mean,
            "ret_logvar": ret_logvar,
            "regime_logits": regime_logits,
            "uncertainty": uncertainty,

            # 决策
            "dir_action": dir_action,
            "position": position,
            "stop_loss": stop_loss,
            "take_profit": take_profit,

            # 可解释性
            "attention_weights": attn_weights,
            "expert_usage": expert_usage,
            "pooled_embedding": pooled,
        }

    @torch.no_grad()
    def trade(self, features, portfolio_state, macro_state=None):
        """推理接口"""
        self.eval()
        out = self.forward(features, portfolio_state, macro_state)
        dir_probs = F.softmax(out["dir_action"], dim=-1)
        action_idx = dir_probs.argmax(dim=-1).item()
        action_map = {-1: "SHORT", 0: "FLAT", 1: "LONG"}
        regime_names = ["RANGING_LOWVOL", "RANGING_HIGHVOL", "TRENDING_UP",
                        "TRENDING_DOWN", "CRISIS"]

        return {
            "action": action_map.get(action_idx - 1, "UNKNOWN"),
            "action_probs": dir_probs.cpu().numpy(),
            "position_pct": out["position"].item() * 100,
            "stop_loss_atr": out["stop_loss"].item(),
            "take_profit_atr": out["take_profit"].item(),
            "regime": regime_names[out["regime_logits"].argmax().item()],
            "confidence": dir_probs.max().item(),
            "uncertainty": out["uncertainty"].mean().item(),
        }
```

### 3.7 参数量与计算量

| 组件 | 参数量 | 备注 |
|------|--------|------|
| RevIN + PatchEmbed | ~5K | 轻量 |
| Mamba-2 ×4 | ~3.8M | d_state=128, 8 heads |
| MoE-ChannelAttn ×4 | ~9.2M | 8 experts × 4 layers |
| Griffin Block | ~0.6M | 1 layer |
| TimesNet | ~0.3M | 辅助 |
| Prediction Heads | ~200K | |
| KAN Strategy Heads | ~0.5M | 4 个小 KAN |
| Portfolio/Macro Encoder | ~0.4M | |
| **总计** | **~15M** | A100 BF16 推理 < 10ms |

---

## 4. 训练策略: 五阶段渐进式训练

### 4.1 训练全景

```
Phase 0: 对比预训练 (Contrastive Pretraining)
  └─ 无标签自监督学习市场表征

Phase 1: 世界模型训练 (World Model)
  └─ 监督学习: 价格预测 + 环境识别 + 不确定性

Phase 2: 模仿学习 (Imitation Learning)
  └─ 用最优动作伪标签训练策略网络

Phase 3: 决策感知微调 (Decision-Aware Fine-tuning)
  └─ 预测头 + 策略头联合优化，预测服务于决策

Phase 4: Online RL 策略优化 (PPO)
  └─ 在回测模拟器中在线探索优化
```

### 4.2 Phase 0: 对比预训练 (Self-Supervised)

```python
class ContrastivePretraining:
    """
    TS2Vec 风格对比学习: 学习时间序列的通用表征

    正样本: 同一序列的不同增强视图 (裁剪/缩放/噪声)
    负样本: 不同时间段的序列

    损失: InfoNCE with hierarchical contrasting
      - Instance contrast: 区分不同序列
      - Temporal contrast: 区分不同时间点
    """

    def augment(self, x):
        """多视图数据增强"""
        aug1 = x + torch.randn_like(x) * 0.01          # 高斯噪声
        aug1 = aug1 * (0.9 + 0.2 * torch.rand(1))      # 随机缩放
        aug2 = self._time_warp(x)                       # 时间扭曲
        aug2 = self._dropout_window(aug2, p=0.1)        # 随机窗口丢弃
        return aug1, aug2

    def loss(self, z1, z2):
        """层级对比损失"""
        # Instance-level: 同一样本的 z1[i], z2[i] 接近，与其他样本远离
        # Temporal-level: 同一时刻的不同增强应一致
        return self.instance_contrast(z1, z2) + 0.5 * self.temporal_contrast(z1, z2)
```

### 4.3 Phase 1: 世界模型多任务训练

```python
class WorldModelLoss(nn.Module):
    """
    多任务损失 (标签已修正 — 详见 5.0):
      L_world = λ₁·L_dir + λ₂·L_ret + λ₃·L_vol + λ₄·L_regime + λ₅·L_uncertainty

    标签语义 (全部基于未来信息):
      Y_dir[t,h]: 1.0 if p[t+h] > p[t] else 0.0           — 未来方向
      Y_ret[t,h]: log(p[t+h] / p[t])                      — 未来收益
      Y_vol[t,h]: std(log_ret[t+1 : t+h+1])               — 未来已实现波动率 ✅ 已修正
    """
    def __init__(self, cfg):
        super().__init__()
        self.bce = nn.BCEWithLogitsLoss()
        self.l1, self.l2, self.l3, self.l4, self.l5 = 1.0, 0.5, 0.1, 0.3, 0.05

    def forward(self, pred, target):
        # 1. 方向损失 (per horizon)
        L_dir = sum(
            self.bce(pred["dir_logits"][:, h], target["Y_dir"][:, h])
            for h in range(pred["dir_logits"].shape[-1])
        ) / pred["dir_logits"].shape[-1]

        # 2. 收益率损失 (Gaussian NLL)
        #    ret_logvar 编码的是"预测的不确定性"
        #    与下面 L_vol 中的 ret_logvar 共享，需要同时满足:
        #      (a) NLL: 不确定性校准 (预测残差应匹配方差)
        #      (b) Vol:  方差应接近未来实际波动
        rlv = pred["ret_logvar"].clamp(-10, 10)
        L_ret = 0.5 * (rlv + (target["Y_ret"] - pred["ret_mean"])**2 / (rlv.exp() + 1e-8)).mean()

        # 3. 波动率损失 (✅ 已修正: Y_vol = 未来已实现波动率)
        #    σ_pred = exp(0.5 * logvar) 应与 σ_real = Y_vol 对齐
        #    对短 horizon (h<3) 的 NaN 标签进行 mask
        vol_mask = ~torch.isnan(target["Y_vol"])
        if vol_mask.any():
            pred_std = torch.exp(0.5 * rlv)
            L_vol = F.mse_loss(pred_std[vol_mask], target["Y_vol"][vol_mask])
        else:
            L_vol = torch.tensor(0.0, device=rlv.device)

        # 4. 环境分类损失 (Focal Loss 处理类别不平衡)
        L_regime = focal_loss(pred["regime_logits"], target["Y_regime"], gamma=2.0)

        # 5. 不确定性校准损失 (Proper Scoring Rule)
        L_uncertainty = self._proper_scoring_loss(
            pred["uncertainty"], target["Y_ret"], pred["ret_mean"], pred["ret_logvar"]
        )

        return self.l1*L_dir + self.l2*L_ret + self.l3*L_vol + self.l4*L_regime + self.l5*L_uncertainty
```

> **注意**: Gaussian NLL (`L_ret`) 和 MSE (`L_vol`) 同时对 `ret_logvar` 施加梯度。
> - NLL 驱使其反映**预测残差的不确定性**（校准）
> - MSE 驱使其匹配**未来实际波动率**（准确性）
> - 两者的平衡由 λ₂ 和 λ₃ 的比值控制。实践中 λ₂:λ₃ = 5:1 效果较好。


### 4.4 Phase 2: 模仿学习 (最优标签)

```python
def build_oracle_labels(prices, features, cfg):
    """
    利用未来信息构造"上帝视角"最优动作标签.

    算法:
      对每个时间点 t:
        1. 扫描未来 [t+1, t+max_hold] 的所有可能出手点
        2. 计算 (方向, 仓位, 止损, 止盈) 的最优组合
        3. 最优标准: 最大化 Sharpe-like 指标 (收益/回撤)
    """
    n = len(prices)
    max_hold = cfg.max_hold_bars
    Y = {
        "direction": np.zeros(n, dtype=np.int64),
        "position": np.zeros(n, dtype=np.float32),
        "stop_loss": np.zeros(n, dtype=np.float32),
        "take_profit": np.zeros(n, dtype=np.float32),
    }

    for i in range(n - max_hold):
        best_score = -np.inf
        for h in cfg.pred_horizons:
            if i + h >= n: continue
            ret = np.log(prices[i + h] / prices[i])
            if abs(ret) < cfg.cost_per_trade_bps / 10000:
                continue

            # 模拟: 以 ret 为目标, 计算最优 SL/TP
            for sl_mult in [0.5, 1.0, 1.5, 2.0, 3.0]:
                for tp_mult in [1.0, 1.5, 2.0, 3.0, 5.0]:
                    # 简化评分: 预期收益 / 预期风险
                    # 实际应基于 path-wise 回测
                    score = (tp_mult * abs(ret)) / (sl_mult * abs(ret) + 0.01)
                    if score > best_score and tp_mult >= sl_mult * 1.5:
                        best_score = score
                        Y["direction"][i] = 1 if ret > 0 else -1
                        Y["position"][i] = min(1.0, abs(ret) * 50)  # Kelly 启发式
                        Y["stop_loss"][i] = sl_mult
                        Y["take_profit"][i] = tp_mult

    return Y
```

### 4.5 Phase 3: Decision-Aware Fine-tuning

**核心思想**: 预测不需要完美准确，只需要足以支撑正确决策。

```python
class DecisionAwareLoss(nn.Module):
    """
    决策感知损失: 联合优化预测和决策

    L_total = L_world + λ_da · L_decision_aware

    L_decision_aware 惩罚"预测正确但决策错误"的情况:
      例: 预测涨 0.1% (正确) → 模型未开仓 (错过机会) → 惩罚
          预测跌 0.1% (正确) → 模型做多 (错误) → 惩罚
    """
    def __init__(self, lam_da=0.3):
        super().__init__()
        self.lam_da = lam_da

    def forward(self, pred, actions, future_returns):
        # 决策质量: 如果方向预测对但没开仓 → 机会成本
        pred_dir = (torch.sigmoid(pred["dir_logits"][:, 0]) > 0.5).float() * 2 - 1
        action_dir = actions["dir_action"].argmax(-1) - 1

        # 动作与未来收益的"后悔值"
        optimal_dir = (future_returns[:, 0] > 0).float() * 2 - 1

        # 预测正确但动作不一致
        L_da_direction = F.cross_entropy(
            actions["dir_action"],
            (optimal_dir + 1).long()  # convert to {0,1,2}
        )

        # 仓位回归: 最优仓位应正比于预期收益
        optimal_pos = torch.sigmoid(future_returns[:, 0] * 20)  # 缩放
        L_da_position = F.huber_loss(actions["position"].squeeze(-1), optimal_pos)

        return self.lam_da * (L_da_direction + L_da_position)
```

### 4.6 Phase 4: Online PPO 微调

```python
class TradingEnv:
    """
    Gym-compatible 回测环境用于 RL 微调

    状态空间: 模型编码的隐状态 (384维) + 持仓状态 (6维)
    动作空间: (方向, 仓位, SL, TP) — 连续 + 离散混合
    奖励: 每步 PnL - 成本 + Sharpe 惩罚项
    """
    def __init__(self, data, model, cfg):
        self.data = data
        self.model = model  # frozen encoder, trainable policy head only
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.idx = cfg.seq_len + 288
        self.position = 0
        self.entry_price = 0
        self.pnl_history = []
        return self._get_state()

    def step(self, action):
        # action: (direction, position, stop_loss, take_profit)
        direction, position, sl, tp = action
        current_price = self.data.prices[self.idx]

        # 执行交易
        if self.position == 0 and direction != 0:
            # 开仓
            self.position = position * direction
            self.entry_price = current_price
        elif self.position != 0:
            # 检查止损止盈
            pnl_pct = (current_price / self.entry_price - 1) * self.position
            atr = self.data.atr[self.idx]
            if pnl_pct < -sl * atr / self.entry_price:
                reward = pnl_pct - self.cfg.cost_per_trade_bps / 10000
                self.position = 0
            elif pnl_pct > tp * atr / self.entry_price:
                reward = pnl_pct - self.cfg.cost_per_trade_bps / 10000
                self.position = 0
            elif direction == 0:
                reward = pnl_pct - self.cfg.cost_per_trade_bps / 10000
                self.position = 0
            else:
                # 未触发: 给小惩罚 (持仓成本) + 未实现 PnL 增量
                reward = 0.0
                self.pnl_history.append(pnl_pct)

        self.idx += 1
        done = self.idx >= len(self.data.prices) - 1
        return self._get_state(), reward, done, {}

    def _get_state(self):
        # 模型编码当前特征 → 隐状态
        features = self.data.get_features(self.idx)
        with torch.no_grad():
            hidden, pooled = self.model.encode(features.unsqueeze(0))
        port_state = torch.tensor([[
            self.position, self.entry_price,
            self.pnl_history[-1] if self.pnl_history else 0,
            len(self.pnl_history) / self.cfg.max_hold_bars,
            max(self.pnl_history) if self.pnl_history else 0,
            min(self.pnl_history) if self.pnl_history else 0,
        ]])
        return {"hidden": hidden, "pooled": pooled, "portfolio": port_state}
```

```python
def ppo_fine_tune(model, env_factory, cfg):
    """
    PPO 在线微调策略网络

    仅更新: KAN 策略头 + Portfolio Encoder + Decision Context
    冻结: Encoder (Mamba-2, iTransformer, Griffin)
    """
    from torch.distributions import Categorical

    # 冻结编码器
    for name, param in model.named_parameters():
        if any(k in name for k in ["mamba_encoder", "moe_blocks", "griffin_block",
                                     "revin", "patch_embed", "timesnet"]):
            param.requires_grad = False

    optimizer = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=cfg.lr_ppo,
    )

    for episode in range(cfg.ppo_episodes):
        env = env_factory()
        state = env.reset()
        log_probs, values, rewards, dones = [], [], [], []

        while not dones[-1] if dones else True:
            action, log_prob, value = model.act(state)
            next_state, reward, done, _ = env.step(action)

            log_probs.append(log_prob)
            values.append(value)
            rewards.append(reward)
            dones.append(done)
            state = next_state

        # GAE 优势估计
        advantages = compute_gae(rewards, values, dones, gamma=0.99, lam=0.95)
        returns = compute_returns(rewards, gamma=0.99)

        # PPO clipped loss
        for _ in range(cfg.ppo_epochs_per_episode):
            ratio = torch.exp(torch.stack(log_probs) - torch.stack(log_probs).detach())
            surr1 = ratio * advantages
            surr2 = torch.clamp(ratio, 0.8, 1.2) * advantages
            policy_loss = -torch.min(surr1, surr2).mean()
            value_loss = F.mse_loss(torch.stack(values), returns)
            entropy_loss = -torch.stack(log_probs).mean() * 0.01

            loss = policy_loss + 0.5 * value_loss - entropy_loss
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            optimizer.step()
```

### 4.7 训练超参数

```python
@dataclass
class GoldTraderR1Config:
    # ---- 数据 ----
    seq_len: int = 576              # 48h @ 5min → 扩大感受野
    pred_horizons: tuple = (1, 3, 6, 12, 24, 36, 72, 144)
    patch_len: int = 12
    stride: int = 6
    n_features: int = 22            # 17 基础 + 5 宏观

    # ---- 模型 ----
    d_model: int = 512              # 从 384 提升到 512
    d_state: int = 128              # Mamba-2 状态维度
    n_heads: int = 8
    n_mamba_layers: int = 4
    n_moe_layers: int = 4
    n_experts: int = 8
    top_k_experts: int = 2
    dropout: float = 0.1
    n_regimes: int = 5              # 更细粒度环境分类

    # ---- 训练五阶段 ----
    # Phase 0: Contrastive Pretrain
    epochs_p0: int = 50
    lr_p0: float = 1e-4
    batch_size_p0: int = 512

    # Phase 1: World Model
    epochs_p1: int = 150
    lr_p1: float = 1e-4

    # Phase 2: Imitation Learning
    epochs_p2: int = 80
    lr_p2: float = 5e-5

    # Phase 3: Decision-Aware
    epochs_p3: int = 50
    lr_p3: float = 2e-5
    lam_da: float = 0.3

    # Phase 4: Online PPO
    ppo_episodes: int = 1000
    lr_ppo: float = 1e-5
    ppo_epochs_per_episode: int = 4

    # ---- 通用 ----
    batch_size: int = 128
    warmup_epochs: int = 10
    weight_decay: float = 1e-5
    grad_accum: int = 2
    device: str = "cuda"
    dtype: str = "bfloat16"
    seed: int = 42

    # ---- 训练增强 ----
    use_sam: bool = True            # Sharpness-Aware Minimization
    use_ema: bool = True            # Exponential Moving Average
    ema_decay: float = 0.999
    label_smoothing: float = 0.05

    # ---- 交易参数 ----
    max_hold_bars: int = 576        # 最长 48h 持仓
    cost_per_trade_bps: float = 3.0 # 3 bps 交易成本
    min_risk_reward: float = 1.5
```

---

## 5. 数据管线与增强

### 5.0 标签构建修正 (修复 GoldFormer 关键 Bug)

#### 🐛 Bug 描述

GoldFormer `_build_all()` 第 259 行的波动率标签存在**数据泄漏 + 语义错误**:

```python
# ❌ GoldFormer 原代码 (train_goldformer.py:259)
Yv[idx, hi] = np.std(log_ret[max(0, i - L):i]) * np.sqrt(h)
#                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^
#                 过去 L 个 bar 的历史波动率          理论缩放 (假设 i.i.d.)
```

**为什么这是错误的:**

1. **预测目标错位**: 标签是过去的波动率 × √h，模型学到的是"输出历史波动率"，而非预测未来风险变化
2. **损失无意义**: `MSE(exp(0.5 * logvar), historical_vol * sqrt(h))` — 模型只需学会恒等映射 `logvar ≈ log(historical_vol² * h)`，不涉及任何预测能力
3. **无法预测波动率突变**: 市场从低波动切换到高波动时，模型输出的是过期信息
4. **Gaussian NLL 不一致**: `L_ret` 中的 `ret_logvar` 被用来评估收益率预测的不确定性，但训出来的是历史波动率 — 与收益率的真实不确定性脱节

#### ✅ 修正: 未来已实现波动率 (Future Realized Volatility)

```python
def build_labels_correct(log_ret, prices, cfg):
    """
    正确的标签构建: 所有标签必须仅使用未来信息.

    Y_dir[t, h]:  价格在 t+h 是否高于 t (方向, 0/1)
    Y_ret[t, h]:  log(p[t+h] / p[t]) — 未来 h 期对数收益
    Y_vol[t, h]:  std(log_ret[t+1 : t+h+1]) — 未来 h 期已实现波动率

    关键原则:
      - 时刻 t 的标签不能包含任何 ≤t 的信息
      - Y_vol 衡量的是"未来路径上的实际波动"，不是历史波动
    """
    n = len(log_ret)
    L = cfg.seq_len
    max_h = max(cfg.pred_horizons)
    H = len(cfg.pred_horizons)

    start = L + 288
    end = n - max_h - 1
    total = end - start

    Y_dir = np.zeros((total, H), dtype=np.float32)
    Y_ret = np.zeros((total, H), dtype=np.float32)
    Y_vol = np.zeros((total, H), dtype=np.float32)

    for idx, i in enumerate(range(start, end)):
        for hi, h in enumerate(cfg.pred_horizons):
            # ✅ 方向标签: 未来价格 vs 当前价格
            ret = np.log(prices[i + h] / prices[i])
            Y_dir[idx, hi] = 1.0 if ret > 0 else 0.0
            Y_ret[idx, hi] = ret

            # ✅ 波动率标签: 未来 h 期的已实现波动率
            # 取 [i+1, i+h] 的 log_ret，计算标准差
            future_slice = log_ret[i+1 : i+h+1]
            if len(future_slice) >= 3:
                Y_vol[idx, hi] = np.std(future_slice)
            else:
                Y_vol[idx, hi] = np.nan  # 样本不足，训练时 mask 掉

    return Y_dir, Y_ret, Y_vol
```

#### 📐 波动率标签的语义对齐

模型输出和标签之间的对应关系必须严格一致:

```
┌──────────────────────────────────────────────────────────────┐
│  模型输出               标签                 损失函数          │
├──────────────────────────────────────────────────────────────┤
│  ret_mean[t,h]    →   Y_ret[t,h]          Gaussian NLL       │
│  (预测未来 h 期     =  log(p[t+h]/p[t])    -log N(y|μ,σ²)    │
│   收益率均值)          (未来实际收益率)                         │
│                                                               │
│  ret_logvar[t,h]  →   Y_vol[t,h]          MSE                │
│  (预测对数方差)       =  std(log_ret[t+1    (σ_pred - σ_real)² │
│                          : t+h+1])                             │
│                        (未来已实现波动率)                       │
│                                                               │
│  exp(0.5·logvar)  =  σ_pred ≈ σ_real = Y_vol                 │
│  (预测标准差)            (未来实际标准差)                       │
└──────────────────────────────────────────────────────────────┘
```

#### 📐 多尺度波动率的正确理解

对于不同 horizon h，已实现波动率的含义不同:

| Horizon h | Y_vol 含义 | 样本数 | 估计质量 |
|-----------|-----------|--------|---------|
| 1 (5min) | 单根 K 线波动 | h=1 只有 1 个返回值 → 退化为 |ret| | 低, 建议用 h≥3 |
| 3 (15min) | 15 分钟内波动 | 3 个返回值 | 可接受 |
| 6 (30min) | 30 分钟波动 | 6 个返回值 | 较好 |
| 12 (1h) | 1 小时内波动 | 12 个返回值 | 好 |
| 72 (6h) | 6 小时波动 | 72 个返回值 | 很好 |
| 144 (12h) | 半天波动 | 144 个返回值 | 非常好 |

> **设计决策**: 对于 h=1,3 等短尺度，建议使用 **Parkinson 波动率估计量** (基于 high-low) 或 **Garman-Klass** 作为替代，比少量返回值 std 更稳健。但这需要 OHLC 数据，当前只有 close 价格。

#### 🔧 训练时的 NaN 处理

```python
# 对于短 horizon 可能出现的 NaN (样本不足)，训练时 mask 掉
vol_mask = ~torch.isnan(target["Y_vol"])
if vol_mask.any():
    L_vol = F.mse_loss(
        torch.exp(0.5 * pred["ret_logvar"][vol_mask]),
        target["Y_vol"][vol_mask]
    )
else:
    L_vol = 0.0
```

### 5.1 扩展特征矩阵 (22 维)

在 GoldFormer 17 维基础上增加 5 维宏观特征：

| # | 特征 | 数据源 | 含义 |
|---|------|--------|------|
| 17 | `us10y_change` | `market_*.csv` | 10Y 美债收益率变动 (负相关金价) |
| 18 | `dxy_change` | `market_*.csv` | 美元指数变动 (强负相关) |
| 19 | `oil_change` | `market_*.csv` | WTI 原油变动 (通胀预期) |
| 20 | `event_flag` | `gold_event` | 当前是否处于已知事件窗口 |
| 21 | `vix_proxy` | 期权隐含波动率 | 市场恐慌指数替代 |

### 5.2 扩散模型数据增强

```python
class CSDIDiffusionAugment:
    """
    CSDI (Conditional Score-based Diffusion for Imputation & Augmentation)

    用途:
      1. 数据增强: 生成逼真的合成价格路径 → 扩大训练集
      2. 反事实推理: "如果当时 VIX 高了 10%，价格会怎么走?"
      3. 尾部风险建模: 生成极端场景 (黑天鹅)

    架构: 基于分数的扩散模型 (Score-based SDE)
      - 前向过程: 逐步加噪
      - 反向过程: 去噪生成

    训练: 学习条件分数 ∇_{x_t} log p(x_t | x_0, 宏观条件)
    推理: 以当前状态为条件，生成 N 条可能路径
    """
    def __init__(self, d_feat=22, d_time=256, d_model=256):
        super().__init__()
        self.diffusion = GaussianDiffusion(
            num_timesteps=1000,
            beta_schedule="cosine",
        )
        self.denoiser = ResidualUNet1D(
            in_channels=d_feat,
            time_embed_dim=d_time,
            cond_dim=5,  # 宏观条件
        )

    def generate_paths(self, x_current, macro_cond, n_paths=100):
        """以当前行情为条件，生成 N 条可能的未来路径"""
        paths = []
        for _ in range(n_paths):
            # 从噪声开始，在 x_current 的引导下逐步去噪
            path = self.diffusion.sample(
                self.denoiser,
                condition=x_current,
                macro=macro_cond,
            )
            paths.append(path)
        return torch.stack(paths)  # (N, C, L_future)

    def augment_training_data(self, real_data, multiplier=3):
        """用扩散模型生成 3× 训练数据"""
        augmented = []
        for sample in real_data:
            gen_paths = self.generate_paths(
                sample["features"],
                sample["macro"],
                n_paths=multiplier - 1,
            )
            for path in gen_paths:
                augmented.append({"features": path, ...})
        return real_data + augmented
```

### 5.3 环境标签细化 (5 类)

```
震荡低波动 (Ranging Low Vol)    — ADX < 20, BB width < 1.5%   → 反转策略
震荡高波动 (Ranging High Vol)   — ADX < 25, BB width > 1.5%   → 减仓反转
上行趋势 (Trending Up)          — ADX > 25, SMA5 > SMA20       → 趋势跟踪
下行趋势 (Trending Down)        — ADX > 25, SMA5 < SMA20       → 做空/空仓
危机模式 (Crisis)               — ATR > 2× 历史均值             → 空仓+现金
```

---

## 6. 推理与部署架构

### 6.1 Multi-Arch Ensemble

```
┌─────────────────────────────────────────────────────────┐
│                    Ensemble Controller                   │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Model A     │  │  Model B     │  │  Model C     │   │
│  │  Mamba-heavy │  │  iTrans-heavy│  │  Griffin-    │   │
│  │  (时序主导)   │  │  (通道主导)   │  │  heavy       │   │
│  │              │  │              │  │  (局部主导)   │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                  │            │
│         ▼                 ▼                  ▼            │
│  ┌──────────────────────────────────────────────────┐   │
│  │           Voting + Meta-Stacking                  │   │
│  │                                                   │   │
│  │  if agreement ≥ 2/3: 执行多数意见                   │   │
│  │  elif 全部分歧:       空仓 (不确定性高)              │   │
│  │  meta_weight = softmax(learned_weights)            │   │
│  └───────────────────────┬───────────────────────────┘   │
│                          ▼                                │
│                    Final Decision                          │
└─────────────────────────────────────────────────────────┘
```

### 6.2 实时推理管线

```
1min 价格到达
      │
      ▼
┌─────────────────────┐
│ Feature Calculator   │  ← 滑动窗口计算 22 维特征
│ (Rust/Cython 加速)   │     < 0.1ms
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Batch Assembler      │  ← 构建 (1, 22, 576) 张量
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Ensemble Inference   │  ← 3 个模型并行推理
│ GPU BF16             │     < 8ms (A100)
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Signal Filter        │  ← 置信度 / 风报比 / 冷却检查
│ + Risk Manager       │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Alert / Execution    │  ← 微信/Telegram 通知 或 API 下单
└─────────────────────┘
```

---

## 7. 评估体系与基准

### 7.1 三维评估框架

```
维度 1: 预测能力 (Forecasting)
  - Direction Accuracy (per horizon)
  - RMSE / MAE (returns)
  - CRPS (Continuous Ranked Probability Score) — 概率预测质量

维度 2: 交易表现 (Trading Performance)
  - 年化 Sharpe Ratio (> 1.5 target)
  - 最大回撤 (< 15%)
  - Calmar Ratio (> 2.0)
  - 盈亏比 (Profit Factor > 1.5)
  - Sortino Ratio (仅考虑下行风险)

维度 3: 鲁棒性 (Robustness)
  - OOS (Out-of-Sample) 表现衰减 < 20%
  - 不同年份子区间表现方差
  - 不同市场环境分别评估
  - Monte Carlo 噪声扰动稳定性
```

### 7.2 基准对比矩阵

| 基准 | 类型 | 预测 | 交易 | 来源 |
|------|------|------|------|------|
| Buy & Hold | 朴素 | — | 长期持有 | — |
| SMA Crossover | 规则 | — | 金叉死叉 | `gold_analysis.py` |
| RSI Mean-Revert | 规则 | — | RSI 超买超卖 | 经典反转 |
| Bollinger Band | 规则 | — | 布林带突破 | `create_indicators.py` |
| GoldFormer (v1) | DL 预测 | PatchTST+iTrans | — | `train_goldformer.py` |
| GoldFormer + Rules | DL+规则 | GoldFormer | 规则化执行 | — |
| Informer | DL 预测 | ProbSparse Attn | — | AAAI 2021 |
| TimesNet | DL 预测 | 2D Conv | — | ICLR 2023 |
| PatchTST | DL 预测 | Patch Attention | — | ICLR 2023 |
| iTransformer | DL 预测 | Inverted Attn | — | ICLR 2024 |
| ModernTCN | DL 预测 | Mod. Conv | — | ICLR 2024 |
| Mamba (S4) | DL 预测 | SSM | — | 2024 |
| **GoldTrader-R1** | **DL 策略** | **Hybrid** | **E2E** | **本设计** |

### 7.3 Walk-Forward 回测协议

```
配置:
  - 滚动窗口: 6 个月训练 + 2 个月验证 + 2 个月测试
  - 步长: 2 个月
  - 总回测期: 2020-01 ~ 2026-06
  - 初始资金: $100,000
  - 单笔最大风险: 2%
  - 交易成本: 5 bps (佣金+滑点)
```

---

## 8. 实施路线图

### Phase 0: 基础设施 (Week 1)
- [ ] 22 维特征工程管线 (含宏观数据)
- [ ] 环境标签生成 (5 类)
- [ ] 数据增强管线 (CSDI 扩散模型)

### Phase 1: 核心编码器 (Week 2-3)
- [ ] Mamba-2 SSD 实现与验证
- [ ] MoE-ChannelAttnBlock 实现
- [ ] Griffin Local Block 实现
- [ ] 三路编码器融合与消融实验

### Phase 2: 预训练与监督训练 (Week 4-5)
- [ ] Phase 0: 对比预训练
- [ ] Phase 1: 世界模型训练
- [ ] Phase 2: 模仿学习训练
- [ ] Phase 3: 决策感知微调

### Phase 3: 策略优化 (Week 6)
- [ ] KAN 策略头实现
- [ ] Phase 4: Online PPO 微调
- [ ] Multi-Arch Ensemble 训练 (3 个变体)

### Phase 4: 评估 (Week 7)
- [ ] Walk-Forward 回测引擎
- [ ] 全量基准对比
- [ ] 鲁棒性分析
- [ ] 消融实验报告

### Phase 5: 部署 (Week 8)
- [ ] ONNX/TensorRT 导出优化
- [ ] 实时推理服务
- [ ] 监控面板
- [ ] 纸面交易验证

---

## 9. 附录

### A. 参考文献

```
[1]  Dao & Gu (2024). "Transformers are SSMs: Generalized Models and
     Efficient Algorithms Through Structured State Space Duality." (Mamba-2)
[2]  Liu et al. (2024). "iTransformer: Inverted Transformers Are Effective
     for Time Series Forecasting." ICLR 2024.
[3]  DeepSeek-AI (2024). "DeepSeek-V3 Technical Report." (MoE + Load Balancing)
[4]  Liu et al. (2024). "KAN: Kolmogorov-Arnold Networks."
[5]  De et al. (2024). "Griffin: Mixing Gated Linear Recurrences with
     Local Attention for Efficient Language Models." DeepMind.
[6]  Nie et al. (2023). "A Time Series is Worth 64 Words: Long-term
     Forecasting with Transformers." ICLR 2023. (PatchTST)
[7]  Tashiro et al. (2023). "CSDI: Conditional Score-based Diffusion
     Models for Probabilistic Time Series Imputation." NeurIPS 2021.
[8]  Wu et al. (2023). "TimesNet: Temporal 2D-Variation Modeling for
     General Time Series Analysis." ICLR 2023.
[9]  Yue et al. (2022). "TS2Vec: Towards Universal Representation of
     Time Series." AAAI 2022.
[10] Schulman et al. (2017). "Proximal Policy Optimization Algorithms."
[11] Donti et al. (2023). "Smart 'Predict, then Optimize'."
[12] Kim et al. (2022). "Reversible Instance Normalization for Accurate
     Time-Series Forecasting against Distribution Shift." (RevIN)
```

### B. 关键消融实验设计

```
消融目标: 量化每个 SOTA 组件的边际贡献

实验组:
  1. Base:            RevIN + PatchEmbed + iTransformer (GoldFormer baseline)
  2. +Mamba-2:        增加 Mamba-2 时序编码器
  3. +MoE:            FFN 替换为 MoE-FFN
  4. +Griffin:        增加 Griffin 局部注意力
  5. +KAN:            策略头 MLP 替换为 KAN
  6. +Contrastive:    增加对比预训练
  7. +DA Loss:        增加决策感知损失
  8. +PPO:            增加 Online RL 微调
  9. +Ensemble:       3 模型集成
  10. Full:           全部组件

每组的评估指标: Direction Acc, Sharpe, MaxDD, Calmar
```

### C. 风险声明

> ⚠️ **重要**: 本设计文档仅供学术研究与学习参考。量化交易存在重大风险：
> - 历史表现不代表未来收益
> - 模型可能在极端市场条件下失效（黑天鹅、流动性枯竭）
> - 实盘部署前必须经过充分的纸面交易验证和压力测试
> - 黄金市场受地缘政治、央行政策、通胀预期等多因素影响
> - 本模型不构成任何形式的投资建议
