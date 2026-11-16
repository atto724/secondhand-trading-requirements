# 二手交易系统（桌面版）

Python + Tkinter + SQLite，基于实验一需求和实验二 UML 实现。源码均为手写，未使用 GUI 设计工具生成代码。

## 从仓库根目录运行

```powershell
.\code\.venv\Scripts\python.exe .\code\main.py
```

缺少环境时：`python -m venv code/.venv`，再执行 `code/.venv/Scripts/python.exe -m pip install -r code/requirements.txt`。

## 独立演示

```powershell
.\code\.venv\Scripts\python.exe .\code\demo.py
```

演示账号：`demo_admin`、`demo_seller`、`demo_buyer`、`demo_other`，密码均为 `DemoPass123!`。这些账号只存在于 `code/data/demo_gallery`，不修改原来的 `code/data/trading.db`。演示图片采用用户提供的15张商品图，价格和成色是教学样例设定。

演示顺序：买家浏览并预约 → 卖家在“卖家预约”确认 → 卖家登记交付 → 买家确认完成。管理员在管理后台审核待审核示例，也可处理违规、争议、账号授权、更正成交和审计备份。

## 自己的数据

原账号和商品保留。新表和字段通过增量迁移加入。旧空草稿可以在“我的商品”补全或删除，未补全不能提交审核。图片已复制到数据目录，移动原图不会影响已保存副本。

创建首位管理员（密码交互输入，不使用固定默认密码）：

```powershell
.\code\.venv\Scripts\python.exe .\code\manage.py init-admin
```

后续管理员由已有管理员授权。所有管理员操作都重新检查数据库权限。

## 键盘

登录名 Enter 到密码，密码 Enter 登录；缺项时回到缺失字段。商品表单 Enter 到下一项，描述框 Enter 换行，Ctrl+Enter 保存；按钮和快捷键均检查全部必填项。Tab / Shift+Tab 切换焦点。子窗口 Escape 关闭。

## 验证与构建

运行仓库根目录 `build.ps1`，执行单元/集成测试、Black 格式检查、Pylint、wheel 和源码包构建。开发工具安装命令：

```powershell
.\code\.venv\Scripts\python.exe -m pip install -e './code[dev]'
.\build.ps1
```

也可以进入 code 运行 `python -m unittest discover -s tests -v`。构建产物位于 `code/dist`。wheel 需要 Python 和系统 Tk 支持，并非独立 exe。

## 数据与边界

- 付款、物流和线下交付不由程序执行；系统记录预约和交易结果。
- 手机号仅格式校验，未验证手机号归属，未接入真实短信。
- 这是本地教学桌面程序，数据库文件拥有者可直接访问本机文件；角色限制适用于应用服务调用，不构成多租户服务器安全边界。
- 商品与预约联动使用事务；图片文件用异常补偿清理。突然断电可能留下未引用文件，备份保留图片文件以保护历史快照。
- 超时任务和每日自动备份在程序开启时执行；自动备份要求管理员登录。关闭程序期间需部署人员配置外部计划任务，不能据此声称已实现全天备份 SLA。
- UTC 存储事件时间，统计日期按 UTC+8，结束日期包含在区间内。卖家成交率按区间首次发布商品样本计算，当前在售数单列。
- 不声称已通过原需求的 10 万商品 / 100 并发性能指标、浏览器兼容或网络加密部署验收。桌面版不提供浏览器和网络接口。

实验报告必须由学生独立书写；本 README 是程序操作说明，不是实验报告。

新版演示图库位于 `code/data/demo_gallery`：15件带图可浏览商品、1件带图待审核商品、1件带图草稿。旧的 `code/data/demo` 目录保留，不清空已有演示交易。分类采用已确认的10类，启动时迁移旧分类。
