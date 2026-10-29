import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import PercentFormatter
import matplotlib.patches as patches
import matplotlib.colors as mcolors
import os

# 設定支援中文的字體 (優先使用微軟正黑體 UI)
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei UI', 'Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

def create_pareto_chart(data, categories_col, values_col, output_filename='pareto_chart_styled.png'):
    df = pd.DataFrame(data)
    # 不過濾數值為 0 的項目，保留所有要因分析類別
    df = df.sort_values(by=values_col, ascending=False).reset_index(drop=True)
    
    df['cummulative_percent'] = df[values_col].cumsum() / df[values_col].sum() * 100

    # 建立圖表，增加高度以容納下方文字與圖例
    fig, ax1 = plt.subplots(figsize=(14, 9.5))
    fig.patch.set_facecolor('#F8F9FA')
    ax1.set_facecolor('white')
    
    # 隱藏上與右的邊框
    ax1.spines['top'].set_visible(False)
    
    # Y1 軸設定 (缺失次數) - 改為最大700
    ax1.set_ylim(0, 700)
    ax1.set_xlim(-0.5, len(df) - 0.5)
    ax1.set_yticks(range(0, 701, 100))
    ax1.tick_params(axis='y', colors='#333333', labelsize=14)
    
    # 依據數值高低產生漸層色 (紫橘色系：由深紫色過渡到亮橘黃色)
    import numpy as np
    import matplotlib.cm as cm
    
    # 使用 plasma 色票，產生對比強烈的紫橘漸變
    colors = cm.plasma(np.linspace(0.15, 0.85, len(df)))
    
    bars = ax1.bar(df[categories_col], df[values_col], color=colors, 
                   edgecolor='white', linewidth=1.5, width=0.6, zorder=2)
    
    # X 軸標籤旋轉
    ax1.set_xticks(range(len(df)))
    ax1.set_xticklabels(df[categories_col], rotation=35, ha='right', fontsize=14, color='#333333', fontweight='bold')
    
    # 標示長條圖數值 
    for i, bar in enumerate(bars):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2., height + 5,
                 f'{int(height)}',
                 ha='center', va='bottom', fontsize=13, color=colors[i], fontweight='bold')

    # Y2 軸設定 (累積百分比)
    ax2 = ax1.twinx()
    ax2.spines['top'].set_visible(False)
    ax2.set_ylim(0, 105)
    ax2.set_yticks(range(0, 101, 10))
    ax2.yaxis.set_major_formatter(PercentFormatter())
    ax2.tick_params(axis='y', colors='#333333', labelsize=14)
    
    # 繪製累積折線圖
    line_color = '#4CAF50' # 綠色
    
    # 為了讓折線圖從 0% 開始，在 X=-0.5 增加起始點
    x_line = [-0.5] + list(range(len(df)))
    y_line = [0] + df['cummulative_percent'].tolist()
    
    ax2.plot(x_line, y_line, color=line_color, 
             marker='o', ms=6, linewidth=2.5, zorder=3)
    
    # 標示 0% 的點
    ax2.annotate('0.00%', 
                 (-0.5, 0),
                 textcoords="offset points", 
                 xytext=(-15, 10), 
                 ha='center', 
                 fontsize=13, 
                 color=line_color,
                 fontweight='bold')
                 
    # 標示其他累積百分比數值
    for i, (category, percent) in enumerate(zip(df[categories_col], df['cummulative_percent'])):
        text_color = '#D32F2F' if percent >= 99.9 else line_color
        
        # 統一將文字放在資料點的左上方，避免和斜線重疊
        x_offset = -12
        y_offset = 12 
            
        ax2.annotate(f'{percent:.2f}%', 
                     (category, percent),
                     textcoords="offset points", 
                     xytext=(x_offset, y_offset), 
                     ha='center', 
                     fontsize=13, 
                     color=text_color,
                     fontweight='bold')
                     
    # 計算 80% 交叉點的精確 X 座標
    x_cross = None
    for i in range(len(y_line) - 1):
        if y_line[i] <= 80 <= y_line[i+1]:
            # 內插法計算 X 座標
            x_cross = x_line[i] + (80 - y_line[i]) * (x_line[i+1] - x_line[i]) / (y_line[i+1] - y_line[i])
            break
            
    if x_cross is not None:
        # 畫 80% 的水平虛線 (只從交叉點往右畫到圖表邊緣)
        ax2.plot([x_cross, len(df) - 0.5], [80, 80], color='#D32F2F', linestyle='--', linewidth=1.5, alpha=0.7, zorder=1)
        # 畫交叉點的紅點
        ax2.plot(x_cross, 80, marker='o', color='#D32F2F', ms=8, zorder=4)
        # 畫垂直虛線 (從 Y=0 到 Y=80)
        ax2.plot([x_cross, x_cross], [0, 80], color='#D32F2F', linestyle='--', linewidth=1.5, alpha=0.7, zorder=1)
        # 添加 80.00% 的紅底白字標籤
        bbox_props = dict(boxstyle="round,pad=0.4", fc="#D32F2F", ec="#D32F2F", lw=1)
        ax2.text(x_cross + 0.15, 75, "80.00%", ha="left", va="center", size=13, color="white", fontweight='bold', bbox=bbox_props)
        
        # 標示「改善重點」：前三項即可達到 82%，包覆前三項 (X=2.5)
        highlight_end_x = 2.5
        ax1.axvspan(-0.5, highlight_end_x, color='#FFF59D', alpha=0.3, zorder=0)
        
        # 加上「改善重點」的浮水印背景文字 (墊在長條圖後方)
        center_x = (-0.5 + highlight_end_x) / 2.0
        ax1.text(center_x, 350, '改 善 重 點', ha='center', va='center', fontsize=55, 
                 color='#F57F17', alpha=0.25, fontweight='bold', rotation=25, zorder=1)

    # 頂部標題列裝飾 (改為圓角、漸層感邊框的現代風格)
    fig.text(0.5, 0.94, '   改 善 前 柏 拉 圖   ', ha='center', va='center', fontsize=30, color='white', fontweight='bold',
             bbox=dict(facecolor='#1976D2', edgecolor='#0D47A1', linewidth=2, boxstyle='round,pad=0.4,rounding_size=0.5'))
             
    # 左上角 Y1 標籤
    fig.text(0.12, 0.88, '缺失次數 (次)', ha='center', va='center', fontsize=14, color='white', fontweight='bold',
             bbox=dict(facecolor='#0D47A1', edgecolor='none', pad=6, boxstyle='round,pad=0.4'))
             
    # 左上角 總數標籤
    fig.text(0.12, 0.83, '總數: 703', ha='center', va='center', fontsize=13, color='white', fontweight='bold',
             bbox=dict(facecolor='#E64A19', edgecolor='none', pad=5, boxstyle='round,pad=0.4'))
             
    # 右上角 Y2 標籤
    fig.text(0.88, 0.88, '累積百分比 (%)', ha='center', va='center', fontsize=14, color='white', fontweight='bold',
             bbox=dict(facecolor='#4CAF50', edgecolor='none', pad=6, boxstyle='round,pad=0.4'))

    # 圖例 (Legend) - 將其再往下移，避免與放大後的字體重疊
    from matplotlib.lines import Line2D
    legend_elements = [
        patches.Patch(facecolor=colors[0], edgecolor='none', label='缺失次數 (次)'),
        Line2D([0], [0], color=line_color, marker='o', lw=2.5, label='累積百分比 (%)')
    ]
    ax1.legend(handles=legend_elements, loc='lower center', bbox_to_anchor=(0.5, -0.65), 
               ncol=2, frameon=True, fontsize=15, fancybox=True, shadow=True, borderpad=0.8)

    # 底部提示文字
    footer_text = '前三項缺失（累積 82.11%）為改善重點，建議優先針對這些項目進行改善，以達到事半功倍的效果。'
    fig.text(0.5, 0.02, footer_text, ha='center', va='center', fontsize=14, color='#333333', fontweight='bold',
             bbox=dict(facecolor='#F0F4F8', edgecolor='#DDDDDD', boxstyle='round,pad=0.7'))

    # 調整邊界 - 大幅增加 bottom 空間
    plt.subplots_adjust(top=0.84, bottom=0.45, left=0.08, right=0.92)
    
    # 儲存圖片
    plt.savefig(output_filename, dpi=300, facecolor=fig.get_facecolor())
    print(f'已生成高度客製化圖表：{os.path.abspath(output_filename)}')
    plt.close()

if __name__ == '__main__':
    data = {
        '要因分析': [
            '人員執行力不佳', '未做好事前準備', '未協助執行檢查', '未能及時填傳送系統',
            '未遵守搭乘規定', '檢查單遺失與開單疑慮', '手機訊號不佳', '病房網路連線異常',
            '未確實點班及校正', '流程不熟悉', '未確實交班與報修', '機器修繕時間長', '故障未完成修繕'
        ],
        '缺失數': [
            177, 156, 135, 72, 
            11, 7, 5, 3, 
            2, 1, 1, 0, 0
        ]
    }
    create_pareto_chart(data, '要因分析', '缺失數', 'QCC_pareto_chart_before_new.png')
