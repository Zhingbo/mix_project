import pandas as pd

# 读取Excel文件
df = pd.read_excel('resultTxt/chain_info.xlsx')

# 确保chain_name列存在
if 'chain_name' not in df.columns:
    raise ValueError("The column 'chain_name' does not exist in the Excel file.")

# 按照chain_name分组
grouped = df.groupby('chain_name')

# 遍历分组，并将每个分组存储到新的Excel文件中
for chain_name, group_df in grouped:
    # 构建新的Excel文件名，使用chain_name作为文件名
    filename = f"chain_info/{chain_name}_info.xlsx"
    # 将分组数据写入新的Excel文件
    group_df.to_excel(filename, index=False)