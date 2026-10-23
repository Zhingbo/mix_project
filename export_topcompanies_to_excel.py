import os
import pymysql
import pandas as pd
from datetime import datetime

db_config = {
    'host': '8.141.5.67',
    'port': 3306,
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4'
}

conn = pymysql.connect(**db_config)

# 导出 industry_chain_topcompanies0108
df_0108 = pd.read_sql("SELECT * FROM industry_chain_topcompanies0108", conn)
print(f"industry_chain_topcompanies0108: {len(df_0108)} 条记录")

# 导出 industry_chain_topcompanies1230
df_1230 = pd.read_sql("SELECT * FROM industry_chain_topcompanies1230", conn)
print(f"industry_chain_topcompanies1230: {len(df_1230)} 条记录")

conn.close()

# 保存到Excel
output_file = f"topcompanies_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
    df_0108.to_excel(writer, sheet_name='topcompanies0108', index=False)
    df_1230.to_excel(writer, sheet_name='topcompanies1230', index=False)

print(f"\n导出完成: {output_file}")
