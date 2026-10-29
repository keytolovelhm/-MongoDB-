# MongoDB问卷系统

课程项目第二阶段，沿用第一阶段FastAPI、PyMongo及同源网页，扩展独立题目、不可变版本、跨账号共享、问卷固定快照、使用情况、个人题库、跨问卷统计及旧题显式关联。

- [安装、运行、演示及测试](outputs/survey-system/README.md)
- [项目实验报告：第一阶段基础与第二阶段演化](outputs/survey-system/docs/项目完成报告.md)
- [MongoDB设计、D10—D14与Q01—Q09](outputs/survey-system/docs/第二阶段需求分析与数据库设计.md)
- [AI使用记录与真实贡献](outputs/survey-system/docs/AI使用记录.md)
- [MongoDB Schema](outputs/survey-system/docs/mongodb-schema.json)

## Windows本地运行

安装Python（已验证3.13.7）和MongoDB Community Server（已验证6.0.27），PowerShell执行：

```powershell
git clone https://github.com/keytolovelhm/-MongoDB-.git
Set-Location -LiteralPath './-MongoDB-/outputs/survey-system'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_local.py --mongod 'C:\Program Files\MongoDB\Server\6.0\bin\mongod.exe'
```

按实际安装位置调整mongod路径，终端保持运行，访问 http://127.0.0.1:8000 。网页无需单独构建。启动器使用独立MongoDB端口27030和网页8000，创建十集合、验证器和索引，不清空原数据。私有.env自动生成并保留在本地。

## 版本与验证

API版本2.0.0，第一阶段原四集合扩展为十集合。已发布问卷仍按内嵌快照解释，原版本1合成数据及固定统计保持不变。公开第一阶段标签phase1-public-v1.0.0保留，第二阶段使用phase2-public-v2.0.0，在原main历史上正常提交，不改写旧版本。

后端169项通过，整体行覆盖率95.02%，library_stats.py行覆盖率100%。HTTP6项、第一阶段DOM18项和第二阶段DOM16项均引用各自实际执行日期，详情见报告第10.6节。本轮人工抽样验收已结束，版本/快照、Java提交统计、7份合并及两类抑制、共享撤销等操作及截图见第10.7节；未执行项目不记人工通过，k=5仍为建议参数。

工程位于outputs/survey-system，保留源码、测试、配置样例、Schema、三个核心文档及可恢复合成历史数据。9账号/4问卷/12正式答卷的演示脚本及预期见工程README。私有配置、真实数据库、安装目录、运行缓存和大体积归档不上传。
