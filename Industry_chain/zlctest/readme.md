# 1. 代码结构介绍
- main.py是项目的整体入口；
- GoogleSearcher.py是google搜索的类
- Crawler是一个爬虫类，可以使用 jina api进行爬取，也可以使用之前写的爬虫进行爬取，方法都封装好了；
- functions 是所有的方法类，可以直接通过这个py文件调用

# 2. 重要函数封装
- process_industry_data  这个方法把请求大模型的过程做了一个函数，直接把提示词等参数放进去，就可以直接获取大模型返回的结果，不用那么麻烦每次都写一堆了；
- tool_total_search  整体搜索函数，先搜索主节点，然后得出所有实体图，再分别搜索每个实体，同时增加外部资料（excel中指定的网站）
- tool_search  只支持搜索单个节点，需要注明是中心节点还是其他实体，因为搜索方法不同
- check_triples 检查三元组是否有断点，哪些节点需要继续补充
- modify_triples 补充三元组

