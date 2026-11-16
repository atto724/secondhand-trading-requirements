# 审查运行方式

在仓库根目录执行：

```powershell
.\code\.venv\Scripts\python.exe .\code\demo.py
```

演示账号：demo_admin（管理员）、demo_seller（卖家）、demo_buyer（买家）、demo_other（另一位买家）。共同演示密码：DemoPass123!

演示目录为 code/data/demo_gallery，与之前的账号和商品分开。图片由用户提供，价格、成色和描述为教学样例设定。演示数据库不随提交包打包，运行时自动生成。

建议检查顺序：

1. 买家登录，筛选商品、查看图片和详情，发起预约；重复点击仍为原预约。
2. 卖家登录，在卖家预约中确认；登记实际交付后，买家再确认完成。
3. 卖家新建带图片商品，检查必填项、成色、运费、议价、Enter和Ctrl+Enter；保存草稿或提交审核。
4. 管理员审核通过或驳回；再回到买家检查商品是否公开。
5. 多人预约、双方取消、拒绝取消转争议、违规和账号禁用；检查状态与消息。
6. 管理员审计导出、备份以及恢复验证；普通用户不得进入后台。

使用原来的数据：

```powershell
.\code\.venv\Scripts\python.exe .\code\main.py
```

旧空草稿仍保留，可编辑补全或删除；提交审核会拒绝缺项。不要为了清理旧草稿删除整个数据库。

完整回归与构建：

```powershell
.\build.ps1
```

恢复备份到新目录（禁止覆盖已有目录）：

```powershell
.\code\.venv\Scripts\python.exe .\code\manage.py restore-backup '备份文件.zip' '全新恢复目录'
.\code\.venv\Scripts\python.exe .\code\main.py --data-dir '全新恢复目录'
```

Git：本次改动将在本地开发分支保存为可审查提交。审查与修改后再决定推送；git status、git diff、git log可以核对实际状态。

本包是审查版源码，未包含学生独立完成的实验报告，不是最终实验提交包。

新版演示图库位于 `code/data/demo_gallery`：15件带图可浏览商品、1件带图待审核商品、1件带图草稿。旧的 `code/data/demo` 目录保留，不清空已有演示交易。分类采用已确认的10类，启动时迁移旧分类。
