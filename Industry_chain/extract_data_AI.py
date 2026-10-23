import os
import pymysql
import math

# 数据库连接参数
db_config = {
    'host': '10.0.2.87',
    'port': 3506,
    'user': 'root',
    'password': os.getenv('DB_PASSWORD_BI'),
    'database': 'liando_bi',
    'connect_timeout': 36000
}

# 连接数据库
conn = pymysql.connect(**db_config)
cursor = conn.cursor()

# SQL查询：获取园区附近5公里内所有企业的详细信息
def get_companies_info(lat, lon, radius_km):
    # 地球半径（千米）
    EARTH_RADIUS = 6371.0
    
    # 计算Haversine公式中的角度差
    def haversine(lat1, lon1, lat2, lon2):
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = EARTH_RADIUS * c
        return distance
    
    # SQL查询
    sql = """
    SELECT b.company_name, a.city, a.gm_first, a.gm_second, a.gm_third
    FROM tmp_dwd_online_final_all a
    INNER JOIN total_company_list b ON a.uniscid = b.credit_code
    WHERE haversine(%s, %s, a.lat, a.lon) <= %s
    """
    cursor.execute(sql, (lat, lon, radius_km))
    results = cursor.fetchall()
    return results

# 调用函数
lat = 30.6574  # 假设园区纬度
lon = 104.0668  # 假设园区经度
radius_km = 5  # 5公里范围
companies_info = get_companies_info(lat, lon, radius_km)

# 输出结果
for info in companies_info:
    print(f"{info[0]}（注册地{info[1]}, {info[2]}-{info[3]}-{info[4]}）")

# 关闭数据库连接
cursor.close()
conn.close()