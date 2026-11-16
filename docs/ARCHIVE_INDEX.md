# 聊天与文件归档索引

归档日期：2026-11-16。项目根目录为 C:/Users/12822/Documents/secondhand-trading-requirements。

## 应用中的聊天

以下四段原始聊天已移入“二手交易平台”项目，均保持可继续交流，未执行关闭或隐藏聊天的归档操作。

| 阶段 | 原聊天标题 | 聊天编号 |
|---|---|---|
| 实验一：初始需求整理，2026-10-21 | 整理需求分析实验材料 | 01a15e99-31e7-7440-a6fe-c49fbe42ee11 |
| 实验一：后续核对与Git上传，2026-10-29 | 整理需求分析实验材料 | 01a185dc-5854-7062-a837-024d96213077 |
| 实验二：UML与界面设计 | 实验二：软件设计与建模 一、 实验目的 掌握面向对象的设计方法 熟练使用UML图描述面向对象的设计思路 掌握UI设计工… | 01a1af55-5dac-7cc2-8adc-984134b79579 |
| 实验三：实现、运行与审查 | 完成实验三软件实现与构建 | 01a1d2ff-a8cd-7a20-9d69-d669a7be4656 |

两个同名实验一聊天是不同阶段，不要当作重复项删除。完整历史仍在应用原聊天中；这里保存的是索引和交接摘要，不是完整聊天导出。新会话需要细节时读取对应聊天，不能把摘要当作已读完全部历史。

## 正式原件

| 内容 | 仓库内位置 | 维护方式 |
|---|---|---|
| 实验一原始提交ZIP | archive/lab1/实验1_241220141_冯爱丽.zip | 与用户提供文件字节一致，不覆盖 |
| 实验一原始提交内容 | archive/lab1/submitted/ | report.pdf、requirements.md、chat.txt |
| 实验二原始提交ZIP | archive/lab2/实验2_241220141_冯爱丽.zip | 与用户提供文件字节一致，不覆盖 |
| 实验二原始提交内容 | archive/lab2/submitted/ | 实验报告.pdf、UML、UI界面；忽略包内.git链接文件 |
| 原件校验 | archive/MANIFEST.json | SHA-256校验值 |
| 四张界面可编辑参考底稿 | archive/lab2/editable_reference/ | 设计过程SVG参考，不冒充正式提交图 |

历史提醒：实验一后续聊天明确要求继续使用10月21日最终版本，不能用后续修订包替代lab1-final。不要移动、删除或覆盖固定标签。

## 当前工作资料

| 内容 | 位置 |
|---|---|
| 原始需求与访谈记录 | 根目录requirements.md、chat.txt |
| 当前实现 | code/ |
| 原始UML副本 | UML/ |
| 原始UI设计参考图 | design_reference/ |
| 用户提供的15张演示商品图 | code/demo_assets/ |
| 最新实现对应与限制 | docs/IMPLEMENTATION.md |
| 审查运行说明 | docs/REVIEW.md |
| 测试、构建、性能、源码统计 | verification/ |
| 构建脚本与开发辅助工具 | build.ps1、tools/ |
| 当前可运行构建包 | code/dist/；可由build.ps1重新生成 |
| 最近审查ZIP | C:/Users/12822/Documents/Codex/2026-11-13/git-uml-1500-gui-c-c/outputs/二手交易系统_审查版.zip |

## 运行数据

code/data/trading.db为原业务库；code/data/demo为旧演示库；code/data/demo_gallery为新带图演示库。运行数据和备份不应加入公开Git，也不混入课程源码提交包。项目资料归档不会删除或移动这些目录。
