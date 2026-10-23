import os
import pandas as pd
from sqlalchemy import create_engine
from urllib.parse import quote_plus
import numpy as np

# MySQL 配置
mysql_config = {
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),  # 原始密码
    'host': '8.141.5.67',
    'database': 'business_data',
    'port': 3306
}

# Excel 文件路径
excel_path = r"C:\Users\13123\Desktop\daima\产业链\新建 XLSX 工作表 (2).xlsx"

# 使用 pymysql 驱动，密码用 quote_plus 编码
engine = create_engine(
    f"mysql+pymysql://{mysql_config['user']}:{quote_plus(mysql_config['password'])}@{mysql_config['host']}:{mysql_config['port']}/{mysql_config['database']}"
)

# 读取 Excel 文件
print("正在读取 Excel 文件...")
df = pd.read_excel(excel_path)

# 处理 NaN 值（MySQL 不支持）
df = df.replace({np.nan: None})

# 上传到 MySQL
print(f"正在上传 {len(df)} 条数据到 chain_needcomp0108 表...")
df.to_sql(
    name='chain_needcomp0108',
    con=engine,
    if_exists='replace',  # replace: 删除旧表重建, append: 追加, fail: 报错
    index=False,
    chunksize=1000
)

print("上传完成！")

# 验证
df_check = pd.read_sql("SELECT COUNT(*) AS cnt FROM chain_needcomp0108", engine)
print(f"表 chain_needcomp0108 当前共有 {df_check['cnt'][0]} 条记录")
