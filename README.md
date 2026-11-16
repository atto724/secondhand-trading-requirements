# 二手交易平台

这是软件工程课程实验一、二、三及后续分析、测试共用的长期项目。

## 从哪里继续

- **先读交接上下文**：[docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md)
- **确认已作出的决定**：[docs/DECISIONS.md](docs/DECISIONS.md)
- **查找原件和聊天**：[docs/ARCHIVE_INDEX.md](docs/ARCHIVE_INDEX.md)
- **查看后续事项**：[docs/NEXT_STEPS.md](docs/NEXT_STEPS.md)
- **运行和审查程序**：[code/README.md](code/README.md)、[docs/REVIEW.md](docs/REVIEW.md)
- **需求与实现对应**：[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)

实际代码就在本目录的 code 中，不要另建副本继续开发。实验一需求原件 requirements.md、chat.txt 继续保留原样；实验三新增决定在决策记录中维护。

## 快速运行

在本目录打开 PowerShell：

```powershell
.\code\.venv\Scripts\python.exe .\code\demo.py
```

演示账号为 demo_admin、demo_seller、demo_buyer、demo_other；演示密码均为 DemoPass123!。新版图库位于 code/data/demo_gallery，15件带图公开商品覆盖10类；旧演示库保留。

运行原来的本地业务数据：

```powershell
.\code\.venv\Scripts\python.exe .\code\main.py
```

验证与构建：

```powershell
.\build.ps1
```

## 聊天与文件归类

侧边栏“二手交易平台”项目集中四段相关聊天：实验一初始需求、实验一后续Git交流、实验二设计、实验三实现。

archive/lab1 和 archive/lab2 保存用户提供的原始提交ZIP及解包副本。它们是历史原件，不随当前软件需求变更而改写。当前代码、UML和设计参考分别放在 code、UML、design_reference。

## 使用边界

实验三报告必须由学生独立书写，不允许AI代写或润色。本项目中的交接与操作文档属于开发资料，不是实验报告。

项目归类让相关聊天和代码更容易找到；不应假定新聊天已经读过所有旧聊天。新会话先读 AGENTS.md 和 PROJECT_CONTEXT.md，再核对真实代码与Git状态。
