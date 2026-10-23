import requests 

class GoogleSearcher:
    def __init__(self, url, headers,industry_name):
        self.url = url
        self.headers = headers
        self.industry_name = industry_name
    def google_search(self,limit=5,isNode=False,node=""):
        if isNode:
            # 如果是截点搜索
            querystring = {"query": "{}相关的{}产业链信息".format(self.industry_name,node).strip().replace('"',"").replace("\n","").replace("Observation",""), "limit": limit, "related_keywords": "true"}
        else:
            querystring = {"query":"{}的产业链相关信息".format(self.industry_name).strip().replace('"',"").replace("\n","").replace("Observation",""), "limit": limit, "related_keywords": "true"}
        print(f'正在搜索：{str(querystring)}')
        try:
            response = requests.get(self.url, headers=self.headers, params=querystring)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error during requests to {self.url}: {e}")
            return None

