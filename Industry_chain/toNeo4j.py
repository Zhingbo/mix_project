import os



import csv
import logging
from neo4j import GraphDatabase

# 设置日志级别为 ERROR，忽略 WARNING 和 INFO 级别的日志
logging.basicConfig(level=logging.ERROR)

# 连接到 Neo4j 数据库
uri = "bolt://8.141.19.136:7801"
user = "neo4j"
password = os.getenv("NEO4J_PASSWORD")



# 导入新数据
def create_nodes(tx, nodes):
    for node in nodes:
        tx.run("MERGE (n:`%s` {name: $name})"%(LABEL), name=node)

def create_relationships(tx, relationships):
    for rel in relationships:
        source, target, relation_type = rel
        tx.run("""
            MATCH (a:`%s` {name: $source})
            OPTIONAL MATCH (b:`%s` {name: $target})
            MERGE (a)-[:`%s`]->(b)
            """%(LABEL, LABEL, relation_type),
            source=source, target=target)

if __name__ == "__main__":
    LABEL = "新能源汽车"

    driver = GraphDatabase.driver(uri, auth=(user, password))

    # 只删除标签为LABEL的节点及其关系
    with driver.session() as session:
        session.run(f"MATCH (n:`{LABEL}`) DETACH DELETE n")

    # 读取节点文件
    with open(f'resultTxt/new_nodes_{LABEL}.txt', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        nodes = [row[0] for row in reader]

    # 读取关系文件
    with open(f'resultTxt/new_relations_{LABEL}.txt', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        relationships = [row for row in reader]

    with driver.session() as session:
        # 创建节点
        session.write_transaction(create_nodes, nodes)
        # 创建关系
        session.write_transaction(create_relationships, relationships)

