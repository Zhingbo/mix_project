import os
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from utils.logger import get_logger
from database.industrial_chain.industry_structure_db import (
    store_industry_structure,
    get_node_id_by_name,
    clear_industry_structure
)

logger = get_logger(__name__)

class IndustryStructureService:
    """产业链结构服务，负责处理产业链结构数据的解析和存储"""
    
    @staticmethod
    async def parse_and_store_structure(industry_name, user_id, pid, record_id=None, nodes=None, relations=None):
        """
        解析并存储产业链结构数据

        Args:
            industry_name: 产业链名称
            user_id: 用户ID
            pid: 进程ID
            record_id: 产业链记录ID，对应industrial_chain_meta表的id
            nodes: 节点列表（可选，如果未提供则从文件读取）
            relations: 关系列表（可选，如果未提供则从文件读取）

        Returns:
            是否成功
        """
        try:
            user_folder = f"user_{user_id}_pid_{pid}"

            # 如果没有提供nodes和relations，尝试从文件读取
            if nodes is None or relations is None:
                logger.info(f"从文件读取产业链结构数据: {industry_name}")
                nodes_file = f"resultTxt/{user_folder}/nodes_{industry_name}.txt"
                relations_file = f"resultTxt/{user_folder}/relations_{industry_name}.txt"

                # 验证文件是否存在
                if not os.path.exists(nodes_file) or not os.path.exists(relations_file):
                    logger.error(f"节点或关系文件不存在: {nodes_file} 或 {relations_file}")
                    return False

                # 读取节点和关系文件
                with open(nodes_file, 'r', encoding='utf-8') as f:
                    nodes = [line.strip() for line in f.readlines() if line.strip()]

                with open(relations_file, 'r', encoding='utf-8') as f:
                    relations = [line.strip() for line in f.readlines() if line.strip()]
            else:
                logger.info(f"使用传入的产业链结构数据: {industry_name}, 节点数: {len(nodes)}, 关系数: {len(relations)}")

            # 解析关系中的节点ID
            node_ids = {}
            node_relations = []

            for relation in relations:
                match = re.match(r'(.*)-(\d+),(.*)-(\d+),(.*)', relation)
                if match:
                    child_node = match.group(1)
                    child_id = match.group(2)
                    parent_node = match.group(3)
                    parent_id = match.group(4)
                    relation_type = match.group(5)

                    node_ids[child_node] = child_id
                    node_ids[parent_node] = parent_id

                    node_relations.append({
                        'child': child_node,
                        'parent': parent_node,
                        'type': relation_type
                    })

            # 存储节点和关系
            await IndustryStructureService._store_nodes_with_level(
                industry_name, node_relations, node_ids, nodes, record_id
            )

            # 将关系文件保存为备份，便于将来处理
            backup_relations_file = f"resultTxt/{user_folder}/relations_{industry_name}_backup.txt"
            with open(backup_relations_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(relations))

            # 将节点文件保存为备份，便于将来处理
            backup_nodes_file = f"resultTxt/{user_folder}/nodes_{industry_name}_backup.txt"
            with open(backup_nodes_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(nodes))

            return True

        except Exception as e:
            logger.error(f"解析并存储产业链结构数据时出错: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return False

    @staticmethod
    async def _store_nodes_with_level(industry_name, node_relations, node_ids, all_nodes, record_id=None):
        """存储带层级的节点数据"""
        # 构建节点层级映射
        node_levels = {}
        
        # 初始化所有节点的层级为-1（未定义）
        for node in all_nodes:
            node_levels[node] = -1
        
        # 设置中心节点层级为0
        node_levels[industry_name] = 0
        
        # 标记"上游"、"中游"、"下游"节点层级为1
        for node in ["上游", "中游", "下游"]:
            if node in node_levels:
                node_levels[node] = 1
        
        # 根据关系递归设置其他节点的层级
        is_updated = True
        while is_updated:
            is_updated = False
            for relation in node_relations:
                child = relation['child']
                parent = relation['parent']
                
                # 如果父节点层级已定义且子节点层级未定义或需要更新
                if node_levels.get(parent, -1) >= 0 and node_levels.get(child, -1) == -1:
                    node_levels[child] = node_levels[parent] + 1
                    is_updated = True
        
        # 将未定义层级的节点设为1（默认）
        for node in node_levels:
            if node_levels[node] == -1:
                node_levels[node] = 1
        
        # 构建父子关系映射
        parent_map = {}
        for relation in node_relations:
            child = relation['child']
            parent = relation['parent']
            parent_map[child] = parent
        
        # 先存储没有父节点的根节点（产业链名称）
        root_node_id = await store_industry_structure(
            chain_name=industry_name,
            node_name=industry_name,
            parent_node=None,
            parent_id=None,
            node_level=0,
            chain_id=record_id
        )
        
        # 存储节点ID映射表
        stored_node_ids = {industry_name: root_node_id}
        
        # 按层级顺序存储其他节点，这样父节点总是先于子节点存储
        nodes_by_level = {}
        for node in all_nodes:
            if node == industry_name:  # 跳过已存储的根节点
                continue
            
            level = node_levels.get(node, 1)
            # 只保留等级0-3的节点，跳过等级4及以上的节点
            if level > 3:
                continue
            if level not in nodes_by_level:
                nodes_by_level[level] = []
            nodes_by_level[level].append(node)
        
        # 按层级从小到大存储节点
        for level in sorted(nodes_by_level.keys()):
            for node in nodes_by_level[level]:
                parent = parent_map.get(node)
                parent_db_id = stored_node_ids.get(parent) if parent else None
                
                node_db_id = await store_industry_structure(
                    chain_name=industry_name,
                    node_name=node,
                    parent_node=parent,
                    parent_id=parent_db_id,
                    node_level=level,
                    chain_id=record_id
                )
                
                # 保存节点ID，供子节点使用
                stored_node_ids[node] = node_db_id
        
        # 记录存储的节点和关系数量
        logger.info(f"为产业链 {industry_name} 存储了 {len(stored_node_ids)} 个节点")
        
        return stored_node_ids
    
    @staticmethod
    async def get_structure_from_db(industry_name: str) -> Dict[str, Any]:
        """
        从数据库获取产业链的结构数据
        
        Args:
            industry_name: 产业链名称
            
        Returns:
            包含节点和关系的字典 {nodes: [...], relations: [...], industry_name: str}
        """
        try:
            conn = None
            from pymysql.cursors import DictCursor
            from database.industrial_chain.connection import get_connection
            
            conn = await get_connection()
            cursor = conn.cursor(DictCursor)
            
            # 首先获取该产业链最新的record_id（chain_id）
            record_id_sql = """
            SELECT chain_id
            FROM industrial_chain_structure
            WHERE chain_name = %s AND chain_id IS NOT NULL AND chain_id > 0
            ORDER BY id DESC
            LIMIT 1
            """
            cursor.execute(record_id_sql, (industry_name,))
            record_id_result = cursor.fetchone()

            # 如果找到record_id，使用它来过滤；否则只按status过滤
            if record_id_result and record_id_result.get('chain_id'):
                latest_record_id = record_id_result['chain_id']
                nodes_sql = """
                SELECT id, nodes, node_level, parent_id
                FROM industrial_chain_structure
                WHERE chain_name = %s AND nodes IS NOT NULL AND status = 1 AND chain_id = %s
                ORDER BY node_level, id
                """
                cursor.execute(nodes_sql, (industry_name, latest_record_id))
                logger.info(f"查询产业链 {industry_name} 使用 record_id={latest_record_id}")
            else:
                # 没有找到record_id，使用原查询（向后兼容）
                nodes_sql = """
                SELECT id, nodes, node_level, parent_id
                FROM industrial_chain_structure
                WHERE chain_name = %s AND nodes IS NOT NULL AND status = 1
                ORDER BY node_level, id
                """
                cursor.execute(nodes_sql, (industry_name,))
            nodes_data = cursor.fetchall()
            
            if not nodes_data:
                logger.warning(f"未找到产业链 {industry_name} 的节点数据")
                return {"nodes": [], "relations": [], "industry_name": industry_name}
            
            # 提取节点名称和ID映射
            # 修改节点数据构建部分
            nodes = []
            node_id_map = {}
            node_parent_map = {}
            
            for node in nodes_data:
                node_name = node['nodes']
                node_id = node['id']
                parent_id = node['parent_id']
                node_level = node['node_level']
                
                # 构建完整的节点对象
                node_dict = {
                    'id': f"node_{node_id}",
                    'label': node_name,
                    'node_level': node_level,
                    'type': 'category'
                }
                nodes.append(node_dict)
                
                node_id_map[node_id] = node_name
                if parent_id:
                    node_parent_map[node_id] = parent_id
            
            # 构建relations列表
            relations = []
            for node_id, parent_id in node_parent_map.items():
                if node_id in node_id_map and parent_id in node_id_map:
                    child_name = node_id_map[node_id]
                    parent_name = node_id_map[parent_id]

                    # 默认使用part-of关系类型，也可以从数据库查询实际类型
                    relation_str = f"{child_name}-{node_id},{parent_name}-{parent_id},part-of"
                    relations.append(relation_str)

            # 为一级节点（node_level = 1）添加与根节点的关系
            # 根节点的node_level = 0
            root_node_id = None
            for node in nodes_data:
                if node['node_level'] == 0:
                    root_node_id = node['id']
                    break

            if root_node_id:
                root_node_name = node_id_map.get(root_node_id)
                for node in nodes_data:
                    if node['parent_id'] is None and node['node_level'] == 1:
                        node_id = node['id']
                        node_name = node['nodes']
                        # 添加一级节点与根节点的关系
                        relation_str = f"{node_name}-{node_id},{root_node_name}-{root_node_id},part-of"
                        relations.append(relation_str)
            
            return {
                "nodes": nodes,
                "relations": relations,
                "industry_name": industry_name  # 添加产业名称字段
            }
            
        except Exception as e:
            logger.error(f"从数据库获取产业链结构数据时出错: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return {"nodes": [], "relations": [], "industry_name": industry_name}
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    async def export_structure(industry_name: str, export_format: str = "json") -> Dict[str, Any]:
        """
        导出产业链结构数据
        
        Args:
            industry_name: 产业链名称
            export_format: 导出格式 (json, excel, graphml, csv)
            
        Returns:
            包含导出数据或文件路径的字典
        """
        try:
            # 获取结构数据
            structure_data = await IndustryStructureService.get_structure_from_db(industry_name)
            
            if not structure_data['nodes']:
                return {
                    "status": "error",
                    "message": f"未找到产业链 {industry_name} 的数据"
                }
            
            # 根据格式导出
            if export_format.lower() == "json":
                return await IndustryStructureService._export_to_json(industry_name, structure_data)
            elif export_format.lower() == "excel":
                return await IndustryStructureService._export_to_excel(industry_name, structure_data)
            elif export_format.lower() == "graphml":
                return await IndustryStructureService._export_to_graphml(industry_name, structure_data)
            elif export_format.lower() == "csv":
                return await IndustryStructureService._export_to_csv(industry_name, structure_data)
            else:
                return {
                    "status": "error",
                    "message": f"不支持的导出格式: {export_format}"
                }
                
        except Exception as e:
            logger.error(f"导出产业链结构数据时出错: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": f"导出失败: {str(e)}"
            }
    
    @staticmethod
    async def _export_to_json(industry_name: str, structure_data: Dict[str, Any]) -> Dict[str, Any]:
        """导出为JSON格式"""
        try:
            # 创建导出目录
            export_dir = "exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # 构建完整的导出数据
            export_data = {
                "industry_name": industry_name,
                "export_time": json.dumps(datetime.now(), default=str, ensure_ascii=False),
                "nodes_count": len(structure_data['nodes']),
                "relations_count": len(structure_data['relations']),
                "nodes": structure_data['nodes'],
                "relations": structure_data['relations']
            }
            
            # 保存文件
            filename = f"{industry_name}_structure.json"
            filepath = os.path.join(export_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            return {
                "status": "success",
                "message": "JSON导出成功",
                "file_path": filepath,
                "download_url": f"/api/industrial/download/{filename}"
            }
            
        except Exception as e:
            logger.error(f"JSON导出失败: {e}")
            raise
    
    @staticmethod
    async def _export_to_excel(industry_name: str, structure_data: Dict[str, Any]) -> Dict[str, Any]:
        """导出为Excel格式"""
        try:
            import pandas as pd
            from datetime import datetime
            
            # 创建导出目录
            export_dir = "exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # 准备节点数据
            nodes_df = pd.DataFrame(structure_data['nodes'])
            
            # 准备关系数据
            relations_data = []
            for relation in structure_data['relations']:
                # 解析关系字符串: "child-id,parent-id,type"
                parts = relation.split(',')
                if len(parts) >= 3:
                    child_info = parts[0].split('-')
                    parent_info = parts[1].split('-')
                    relation_type = parts[2]
                    
                    relations_data.append({
                        'child_node': child_info[0] if child_info else '',
                        'child_id': child_info[1] if len(child_info) > 1 else '',
                        'parent_node': parent_info[0] if parent_info else '',
                        'parent_id': parent_info[1] if len(parent_info) > 1 else '',
                        'relation_type': relation_type
                    })
            
            relations_df = pd.DataFrame(relations_data)
            
            # 创建概要信息
            summary_data = {
                '产业链名称': [industry_name],
                '导出时间': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
                '节点数量': [len(structure_data['nodes'])],
                '关系数量': [len(structure_data['relations'])]
            }
            summary_df = pd.DataFrame(summary_data)
            
            # 保存到Excel文件
            filename = f"{industry_name}_structure.xlsx"
            filepath = os.path.join(export_dir, filename)
            
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                summary_df.to_excel(writer, sheet_name='概要信息', index=False)
                nodes_df.to_excel(writer, sheet_name='节点数据', index=False)
                relations_df.to_excel(writer, sheet_name='关系数据', index=False)
            
            return {
                "status": "success",
                "message": "Excel导出成功",
                "file_path": filepath,
                "download_url": f"/api/industrial/download/{filename}"
            }
            
        except Exception as e:
            logger.error(f"Excel导出失败: {e}")
            raise
    
    @staticmethod
    async def _export_to_graphml(industry_name: str, structure_data: Dict[str, Any]) -> Dict[str, Any]:
        """导出为GraphML格式（用于图分析软件）"""
        try:
            # 创建导出目录
            export_dir = "exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # 构建GraphML内容
            graphml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns
         http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">
'''
            
            # 定义属性
            graphml_content += '''  <key id="label" for="node" attr.name="label" attr.type="string"/>
'''
            graphml_content += '''  <key id="level" for="node" attr.name="level" attr.type="int"/>
'''
            graphml_content += '''  <key id="type" for="edge" attr.name="type" attr.type="string"/>
'''
            
            # 开始图定义
            graphml_content += f'''  <graph id="{industry_name}" edgedefault="directed">\n'''
            
            # 添加节点
            for node in structure_data['nodes']:
                node_id = node['id']
                label = node['label']
                level = node.get('node_level', 0)
                
                graphml_content += f'''    <node id="{node_id}">\n'''
                graphml_content += f'''      <data key="label">{label}</data>\n'''
                graphml_content += f'''      <data key="level">{level}</data>\n'''
                graphml_content += f'''    </node>\n'''
            
            # 添加边
            edge_id = 0
            for relation in structure_data['relations']:
                parts = relation.split(',')
                if len(parts) >= 3:
                    child_info = parts[0].split('-')
                    parent_info = parts[1].split('-')
                    relation_type = parts[2]
                    
                    if len(child_info) > 1 and len(parent_info) > 1:
                        child_id = f"node_{child_info[1]}"
                        parent_id = f"node_{parent_info[1]}"
                        
                        graphml_content += f'''    <edge id="e{edge_id}" source="{parent_id}" target="{child_id}">\n'''
                        graphml_content += f'''      <data key="type">{relation_type}</data>\n'''
                        graphml_content += f'''    </edge>\n'''
                        edge_id += 1
            
            # 结束图定义
            graphml_content += '''  </graph>\n'''
            graphml_content += '''</graphml>'''
            
            # 保存文件
            filename = f"{industry_name}_structure.graphml"
            filepath = os.path.join(export_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(graphml_content)
            
            return {
                "status": "success",
                "message": "GraphML导出成功",
                "file_path": filepath,
                "download_url": f"/api/industrial/download/{filename}"
            }
            
        except Exception as e:
            logger.error(f"GraphML导出失败: {e}")
            raise
    
    @staticmethod
    async def _export_to_csv(industry_name: str, structure_data: Dict[str, Any]) -> Dict[str, Any]:
        """导出为CSV格式"""
        try:
            import pandas as pd
            from datetime import datetime
            
            # 创建导出目录
            export_dir = "exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # 准备节点数据
            nodes_df = pd.DataFrame(structure_data['nodes'])
            
            # 准备关系数据
            relations_data = []
            for relation in structure_data['relations']:
                parts = relation.split(',')
                if len(parts) >= 3:
                    child_info = parts[0].split('-')
                    parent_info = parts[1].split('-')
                    relation_type = parts[2]
                    
                    relations_data.append({
                        'child_node': child_info[0] if child_info else '',
                        'child_id': child_info[1] if len(child_info) > 1 else '',
                        'parent_node': parent_info[0] if parent_info else '',
                        'parent_id': parent_info[1] if len(parent_info) > 1 else '',
                        'relation_type': relation_type
                    })
            
            relations_df = pd.DataFrame(relations_data)
            
            # 保存节点CSV
            nodes_filename = f"{industry_name}_nodes.csv"
            nodes_filepath = os.path.join(export_dir, nodes_filename)
            nodes_df.to_csv(nodes_filepath, index=False, encoding='utf-8-sig')
            
            # 保存关系CSV
            relations_filename = f"{industry_name}_relations.csv"
            relations_filepath = os.path.join(export_dir, relations_filename)
            relations_df.to_csv(relations_filepath, index=False, encoding='utf-8-sig')
            
            return {
                "status": "success",
                "message": "CSV导出成功",
                "files": [
                    {
                        "name": "节点数据",
                        "path": nodes_filepath,
                        "download_url": f"/api/industrial/download/{nodes_filename}"
                    },
                    {
                        "name": "关系数据", 
                        "path": relations_filepath,
                        "download_url": f"/api/industrial/download/{relations_filename}"
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"CSV导出失败: {e}")
            raise
    
    @staticmethod
    async def get_industry_info(industry_name: str) -> Dict[str, Any]:
        """
        获取产业链基本信息
        
        Args:
            industry_name: 产业链名称
            
        Returns:
            包含产业链基本信息的字典
        """
        try:
            structure_data = await IndustryStructureService.get_structure_from_db(industry_name)
            return {
                "industry_name": industry_name,
                "total_nodes": len(structure_data.get("nodes", [])),
                "total_relations": len(structure_data.get("relations", [])),
                "status": "active" if structure_data.get("nodes") else "empty"
            }
        except Exception as e:
            logger.error(f"获取产业链信息失败: {e}")
            return {
                "industry_name": industry_name,
                "total_nodes": 0,
                "total_relations": 0,
                "status": "error"
            }
    
    @staticmethod
    async def get_industry_nodes(industry_name: str) -> List[str]:
        """
        获取产业链节点列表
        
        Args:
            industry_name: 产业链名称
            
        Returns:
            节点名称列表
        """
        try:
            structure_data = await IndustryStructureService.get_structure_from_db(industry_name)
            nodes = structure_data.get("nodes", [])
            return [node.get("label", "") for node in nodes if node.get("label")]
        except Exception as e:
            logger.error(f"获取产业链节点失败: {e}")
            return []
    
    @staticmethod
    async def get_industry_relations(industry_name: str) -> List[str]:
        """
        获取产业链关系列表
        
        Args:
            industry_name: 产业链名称
            
        Returns:
            关系字符串列表
        """
        try:
            structure_data = await IndustryStructureService.get_structure_from_db(industry_name)
            return structure_data.get("relations", [])
        except Exception as e:
            logger.error(f"获取产业链关系失败: {e}")
            return []
    