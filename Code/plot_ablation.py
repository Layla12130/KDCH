import matplotlib.pyplot as plt
import numpy as np


def plot_ablation_results():
    # === 1. 实验数据 (基于您刚刚跑出来的结果) ===
    metrics = ['On-Time Delivery\n(OTD)', 'Accessory Sync\n(SyncAcc)', 'Profit Rate']

    # 数据 (单位: %)
    # Greedy-NoPlan 的结果 (基于 run_ablation_standalone.py 的输出)
    greedy_means = [73.3, 23.0, 18.5]

    # Proposed Scheme C 的结果 (基于论文基准)
    proposed_means = [100.0, 100.0, 24.5]

    # === 2. 绘图设置 ===
    x = np.arange(len(metrics))  # 标签位置
    width = 0.35  # 柱状图宽度

    # 使用学术风格的配色 (例如: 深蓝 vs 砖红，或 灰度)
    # 方案 A: 蓝/橙 (默认对比度高)
    color_greedy = '#D95319'  # 砖红色 (代表警告/不足)
    color_proposed = '#0072BD'  # 深蓝色 (代表稳健/优秀)

    fig, ax = plt.subplots(figsize=(8, 5))

    # 绘制柱子
    rects1 = ax.bar(x - width / 2, greedy_means, width, label='Greedy-NoPlan (Baseline)', color=color_greedy, alpha=0.8,
                    edgecolor='black')
    rects2 = ax.bar(x + width / 2, proposed_means, width, label='Proposed (Scheme C)', color=color_proposed, alpha=0.9,
                    edgecolor='black')

    # === 3. 图表美化 (Academic Style) ===
    ax.set_ylabel('Performance (%)', fontsize=12, fontweight='bold')
    # ax.set_title('Ablation Study: Impact of Planning Layer', fontsize=14, fontweight='bold', pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=11)
    ax.set_ylim(0, 115)  # 以此留出上方空间放图例和标签

    # 添加图例 (放在顶部，无边框)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2, frameon=False, fontsize=11)

    # 添加网格线 (仅Y轴，虚线，淡色)
    ax.yaxis.grid(True, linestyle='--', which='major', color='grey', alpha=0.25)
    ax.set_axisbelow(True)

    # === 4. 添加数值标签函数 ===
    def autolabel(rects):
        """在每个柱子上方显示具体数值"""
        for rect in rects:
            height = rect.get_height()
            ax.annotate(f'{height:.1f}%',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=10, fontweight='bold')

    autolabel(rects1)
    autolabel(rects2)

    # === 5. 特殊标注 (Highlight the Gap) ===
    # 在 SyncAcc 上方添加箭头，强调巨大的差距
    # SyncAcc 是第2组数据 (index 1)
    idx = 1
    # 计算箭头位置
    x_pos = x[idx]
    y_start = greedy_means[idx] + 5
    y_end = proposed_means[idx] - 5

    # 只有当差距很大时才画箭头
    if y_end > y_start:
        ax.annotate('', xy=(x_pos, y_end), xytext=(x_pos, y_start),
                    arrowprops=dict(arrowstyle='<->', color='black', lw=1.5))
    fig.tight_layout()

    # === 6. 保存与显示 ===
    save_path = 'ablation_study_chart.png'
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"[Success] Chart saved to {save_path}")
    plt.show()


if __name__ == "__main__":
    plot_ablation_results()