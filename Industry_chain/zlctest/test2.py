import os

import requests
url = 'https://r.jina.ai/https://bg.qianzhan.com/trends/detail/506/240524-cba718dc.html'
headers = {'Authorization': 'Bearer ' + os.getenv('JINA_API_KEY_C')}
response = requests.get(url, headers=headers)
print(response.text)