import networkx as nx

def read_triples(file_path):
    G = nx.DiGraph()
    with open(file_path, 'r') as file:
        for line in file:
            start, end, relation = line.strip().split(',')
            G.add_edge(start, end, relation_type=relation)
    return G

def find_isolated_nodes(G):
    isolated_nodes = [node for node in G.nodes() if G.in_degree(node) == 0 and G.out_degree(node) == 0]
    print(isolated_nodes)
    return isolated_nodes

def add_relations(G, isolated_nodes):
    for node in isolated_nodes:
        for neighbor in G.neighbors(node):
            # 假设反向关系也是'is-a'
            G.add_edge(node, neighbor, relation_type='part-of')

G = read_triples('relations_新能源汽车.txt')
isolated_nodes = find_isolated_nodes(G)
print(add_relations(G, isolated_nodes))

def print_graph(G):
    for u, v, attr in G.edges(data=True):  # 注意这里的修改
        print(f"{u} -{attr['relation_type']}-> {v}")

print_graph(G)