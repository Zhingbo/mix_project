import os
import pymysql

conn = pymysql.connect(
    host='8.141.5.5.67',
    user='root',
    password=os.getenv('DB_PASSWORD'),
    database='business_data',
    charset='utf8mb4'
)
cursor = conn.cursor()

# 更新为与 chain_needcomp 一致的名称
cursor.execute("UPDATE whitelist_company SET industry_name = CASE "
                "WHEN industry_name = '氢能' THEN '氢能产业' "
                "WHEN industry_name = '生物医药' THEN '生物医药' "
                "END")
affected = cursor.rowcount
conn.commit()

print(f'已更新 {affected} 条数据')

# 验证
cursor.execute('SELECT DISTINCT industry_name FROM whitelist_company')
print('更新后的产业链名称:')
for row in cursor.fetchall():
    print(f'  - {row[0]}')

cursor.execute('SELECT COUNT(*) FROM whitelist_company')
print(f'总记录数: {cursor.fetchone()[0]}')

cursor.close()
conn.close()
