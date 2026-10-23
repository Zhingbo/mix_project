用法：

  ! bash /root/mix_project_commit.sh "修复导出逻辑"

  不带参数则用时间戳作为提交信息。流程是：

  1. 校验 gh 账号是 Zhingbo
  2. git add -A，无改动直接退出
  3. 敏感文件检查：.env、settings_show*.yaml、auth_config.py、*.pem/key/p12/pfx、私钥等一旦被暂存就中止
  4. 大文件检查：单个文件 >95MB 中止，并提示加到 .gitignore
  5. 提交（带 Co-Authored-By）并 git push origin main