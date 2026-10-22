# MongoDB问卷系统

大作业一——基于MongoDB的问卷系统开发。第一阶段使用FastAPI、PyMongo及同源HTML/CSS/JavaScript，支持注册登录、问卷创建与发布、四类题型、条件跳转、草稿恢复、提交及统计。

## 工程入口

- [完整安装、运行、测试及历史数据恢复说明](outputs/survey-system/README.md)
- [项目完成报告：架构、数据库、API、测试与人工验收](outputs/survey-system/docs/项目完成报告.md)
- [AI使用记录与设计决策](outputs/survey-system/docs/AI使用记录.md)
- [MongoDB Schema](outputs/survey-system/docs/mongodb-schema.json)
- [后端与网页源码](outputs/survey-system/app/)、[全部测试](outputs/survey-system/tests/)、[合成历史数据](outputs/survey-system/data/phase1-history-v1/)

## 本地运行

先安装Python（已验证3.13.7）和MongoDB Community Server（已验证6.0.27）。PowerShell中执行：

```powershell
git clone https://github.com/keytolovelhm/-MongoDB-.git
Set-Location -LiteralPath './-MongoDB-/outputs/survey-system'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_local.py --mongod 'C:\Program Files\MongoDB\Server\6.0\bin\mongod.exe'
```

将`--mongod`改为本机实际路径；已加入PATH时可省略。保持终端运行，在浏览器访问 http://127.0.0.1:8000 。前后端由同一服务提供，无需单独构建网页。启动器会初始化四集合、验证器和索引。

已有MongoDB服务、端口配置、完整测试命令及常见启动问题见[工程README](outputs/survey-system/README.md)。`.env`由配置工具生成，包含私有密钥，应与运行数据一同留在本机。

## 目录与版本

工程保留在`outputs/survey-system/`；其中`app/`为运行源码，`tests/`为回归用例，`scripts/`为配置、数据库和测试工具，`docs/`为两份正式文档、Schema及验收证据，`data/`为可恢复的合成历史基线。

本仓库提供第一阶段脱敏源码快照，保留远程初始提交，公开基线标签为`phase1-public-v1.0.0`。原始开发历史、阶段标签和未经脱敏的证据仅在本地原工程保留。业务API版本为1.0.0；后续开发以当前公开提交及版本1合成历史数据为基础。仓库不包含私有配置、真实数据库、依赖安装目录或第二阶段实现。
