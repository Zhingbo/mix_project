import pymysql

class MySQLConnection:
    def __init__(self, host, user, password, database, port=3306):
        self.connection = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.Cursor
        )

    def query(self, sql):
        with self.connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

    def execute(self, sql, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            self.connection.commit()

    def batch_insert(self, table, data):
        placeholders = ', '.join(['%s'] * len(data[0]))
        sql = f"INSERT INTO {table} VALUES ({placeholders})"
        with self.connection.cursor() as cursor:
            cursor.executemany(sql, data)
            self.connection.commit()

    def close(self):
        self.connection.close()

# 使用示例
# if __name__ == "__main__":
#     host = "10.0.2.87"
#     user = "root"
#     password = os.getenv("DB_PASSWORD_BI")
#     database = "liando_bi"
#     port = 3506  # 如果不是默认端口，修改这里
#
#     # 创建连接
#     mysql = MySQLConnection(host, user, password, database, port)
#     sql = '''
#         SELECT instance_id, company_id, record_url, duration, call_date, employee_name
#         FROM liando_bi.call_instance where call_date like '2024-08%'
#         and record_url is not null and record_url<>'' and record_url<>'-'
#         limit 100
#     '''
#     rows = mysql.query(sql)
#     print(rows)


    # 读取数据
    # query = "SELECT * FROM your_table;"
    # result = mysql.read_data(query)
    # for row in result:
    #     print(row)
    #
    # # 批量插入数据
    # table = "your_table"
    # data = [
    #     (1, 'Alice', 'alice@example.com'),
    #     (2, 'Bob', 'bob@example.com'),
    #     # ... 更多数据
    # ]
    # mysql.insert_data(table, data)
    #
    # # 关闭连接
    # mysql.close_connection()