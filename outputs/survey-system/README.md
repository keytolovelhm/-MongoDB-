# MongoDB问卷系统

第一阶段实现注册登录、问卷管理、四类题型、条件跳转、草稿恢复、匿名及多次填写、提交和统计。后端使用FastAPI与PyMongo，网页无需单独构建。

## 文档与目录

| 文件或目录 | 用途 |
| --- | --- |
| [项目完成报告](docs/项目完成报告.md) | 系统、数据库、API与关键逻辑设计，测试用例及结果，AI使用说明和需求覆盖 |
| [AI使用记录](docs/AI使用记录.md) | 连续Prompt与生成/修改记录、使用总结、学生设计决策、代码审查和问题处理 |
| app/、run.py、run_local.py | 后端、网页与启动入口 |
| docs/mongodb-schema.json | 四集合验证器 |
| tests/、scripts/ | 测试用例、配置/初始化/测试和恢复工具 |
| data/phase1-history-v1/ | 版本1合成历史数据及独立预期统计 |
| docs/test-results/、docs/evidence/ | 脱敏测试记录和人工验收截图副本 |

本工程以本地第一阶段最终基线`phase1-submit-20261022-r1`为来源，整理为脱敏源码快照，保留有效测试和必要证据。原开发历史及阶段标签仅在本地原工程保留，未发布到本仓库。运行代码保持在`outputs/survey-system/`。

## 环境与安装

运行环境为 Windows、Python 3.13.7、MongoDB 6.0.27 standalone。精确 Python 依赖及测试依赖在 requirements.txt。网页无需 Node.js 构建；Node.js 24和jsdom仅用于可选的前端DOM测试。

先安装64位Python（已验证3.13.7）和MongoDB Community Server的`mongod.exe`。MongoDB Shell/Compass不能代替数据库服务程序。安装参考[Python虚拟环境文档](https://docs.python.org/3.13/library/venv.html)和[MongoDB Windows官方安装文档](https://www.mongodb.com/docs/v8.0/tutorial/install-mongodb-on-windows/)。当前仅实测MongoDB 6.0.27；其他版本须在本机执行回归确认。网页不需要安装Node.js。

用PowerShell克隆仓库并进入工程目录（路径包含中文或空格时用单引号）：

```powershell
git clone https://github.com/keytolovelhm/-MongoDB-.git
Set-Location -LiteralPath './-MongoDB-/outputs/survey-system'
python --version
Get-Command mongod -ErrorAction SilentlyContinue
```

若`python`未找到或打开商店，使用已安装的`py -3.13`替代下面第一条命令中的`python`，或用`& 'Python完整路径\python.exe'`。若`mongod`查询无输出，使用下文的`--mongod`完整路径方式，不必修改PATH。以下命令使用项目虚拟环境，不要求激活脚本或调整执行策略；首次安装依赖需要联网。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe run_local.py
```

run_local.py 需要 mongod 在 PATH 中；也可指定已安装的程序路径，例如：

```powershell
.\.venv\Scripts\python.exe run_local.py --mongod 'D:\MongoDB\Server\6.0\bin\mongod.exe'
```

启动器会生成私有.env，启动独立的 MongoDB 27030 和网页8000，运行数据放在本项目.runtime/mongo，不修改已有 MongoDB 服务。看到“Application startup complete”后，打开 http://127.0.0.1:8000 。终端保持运行，结束时按 Ctrl+C；启动器通过serverStatus.pid确认归属，只关闭自己创建的数据库进程。若端口占用，可用 `--port 8001 --db-port 27033`。不要同时用两个启动器打开同一数据目录；第二个实例同时指定独立`--data-dir .runtime\mongo-second`。

在第二个PowerShell终端可执行`Invoke-RestMethod http://127.0.0.1:8000/api/health`，应显示`status: ok`。页面空白时先确认服务终端无错误、URL和端口一致，再用浏览器控制台记录实际现象。缺少mongod时确认指定的是可执行文件；端口冲突时更换端口；不删除已有数据或密钥。重启使用原来的命令、数据目录及.env即可保留问卷。`run_local.py`运行时使用`--db-port`覆盖MONGO_URI；之后改用`run.py`时须保证.env的MONGO_URI指向实际数据库。

首次生成的.env不要公开或提交到Git。APP_SECRET用于会话校验和问卷内伪名，已有数据期间应保留此密钥；重新生成会影响匿名身份关联和单账号重复限制。

若使用已经准备好的MongoDB，可运行以下命令生成配置并单独启动网页；若.env已经存在，configure.py会保留原文件，请按需要编辑MONGO_URI。

```powershell
.\.venv\Scripts\python.exe scripts\configure.py --mongo-uri mongodb://127.0.0.1:27017
.\.venv\Scripts\python.exe scripts\init_db.py
.\.venv\Scripts\python.exe run.py
```

启动程序会确保四集合的验证器与索引存在，不清空已有数据。数据库账号需有对应数据库的建集合、调整验证器和建索引权限。

## 操作步骤

1. 注册并登录，点击“创建演示问卷”或“新建问卷”。演示问卷用于快速体验功能。
2. 设置标题、说明、匿名/多次策略及截止时间。添加单选、多选、文本或数字题；恰好选择N项时，将最少与最多均设为N。
3. 在题目下添加规则，配置优先级、匹配值和后续目标题。数字区间使用两个逗号分隔的十进制阈值。未命中默认进入下一题。
4. 保存草稿，返回列表后发布。发布会冻结题目、选项、规则和参与策略；管理者仍可设置未结束问卷的截止时间，或关闭问卷。
5. 复制分享链接。填写者先登录，选择允许的参与方式，新建填写；每次“保存并继续”保存进度，可通过链接恢复自己的近期草稿。
6. 通过题号返回已到达的题目修改答案。上游改变后系统重算路径、清理失效分支，最终核对后提交。
7. 创建者查看整份统计、单题回答指标和分页原始内容；关闭后仍可查看自己已保存的填写记录。

匿名表示对创建者隐藏账号身份，不表示对系统运营者不可关联。数字答案使用十进制字符串传输，例如 `"0.1"`，以Decimal128存储。整数手机号示例可通过数字题的整数约束表达，但不能保留前导零。

<a id="tests"></a>

## 运行测试

完整后端测试使用隔离MongoDB，测试数据库名由随机UUID生成。测试结果及具体输入、输出见[报告测试章节](docs/项目完成报告.md#testing)。

运行纯逻辑测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_domain.py -v
```

运行全部测试时使用专属临时MongoDB，不操作应用数据库：

```powershell
.\.venv\Scripts\python.exe scripts\test_isolated.py --data-dir .runtime\test-mongo --report-dir docs\test-results\my-run
```

若 mongod 不在PATH，追加 `--mongod '完整程序路径'`。直接运行pytest的集成测试时，可通过MONGO_TEST_URI指定测试MongoDB；测试数据库名由随机UUID生成，仅清理对应的survey_test_数据库。

运行HTTP检查：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_http.py --data-dir .runtime\smoke-mongo --report-dir docs\test-results\my-smoke
```

前端DOM检查为可选开发验证，需要Node.js 24和npm。在工程目录执行：

```powershell
npm --prefix tests/frontend install
.\.venv\Scripts\python.exe scripts\smoke_http.py --data-dir .runtime\dom-mongo --report-dir docs\test-results\my-dom --node node
```

若mongod不在PATH，同样追加`--mongod '完整程序路径'`。脚本会加载正式前端模块；Node需要支持SourceTextModule，脚本已传入相应实验标志。也可用`--jsdom-module`指定jsdom/lib/api.js路径。DOM检查用于验证前端交互，页面布局仍需浏览器验收。

<a id="history-baseline"></a>

## 历史数据恢复

基线名`phase1-history-v1`。内容、ID和伪名均为合成示例，不包含真实问卷数据。只包含合成创建者`synthetic_owner`，其passwordHash为明确的禁用标记，登录验证返回失败；没有真实口令、APP_SECRET、Cookie或会话。sessions为空集合。匿名答卷不含identifiedUserId。respondentKey是固定合成伪名散列，用于重现同人多次统计，不对应应用密钥下的可登录身份，因此不能恢复填写会话。

目录`data/phase1-history-v1`内四个JSON数组使用MongoDB Canonical Extended JSON，保留ObjectId、BSON Date和Decimal128，不可先用普通JSON把数字转float。[官方Extended JSON文档](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/data-formats/extended-json/)说明了类型保留方式。manifest.json记录每集合文件SHA256和数量，expected-stats.json给出固定预期统计。源码生成器不读取数据库、不使用随机数或当前时间，可再次生成完全相同的四个文件。

| 内容 | 固定值及含义 |
| --- | --- |
| users / surveys / responses / sessions | 1 / 1 / 4 / 0 |
| schemaVersion/contentVersion/ruleLanguageVersion/identityKeyVersion | 均为1；revision是修订计数，不能替代语义版本 |
| 问卷状态 | CLOSED，发布后定义冻结；1题单选、1题多选、1题数字、1题文本 |
| 跳转 | q_route选short跳过q_tools到q_score；其余按序 |
| 正式答卷 | 3份，对应2个固定匿名伪名；其中同一伪名提交2份 |
| 草稿 | 1份，另一个伪名只保存q_route；不参与统计 |
| 单选 | full=2次/2人，short=1次/1人 |
| 多选 | X=1次/1人，Y=2次/2人，Z=0次；到达/有效回答均2份 |
| 数字 | 10、20、显式跳过；到达3份、有效2份、有效人数1、均值15 |
| 文本 | 3条合成备注，3份回答/2人 |

### Windows恢复与复核

先按README安装依赖并用run_local.py启动MongoDB和网页，保持该终端运行。另开PowerShell，进入同一survey-system目录，执行：

```powershell
.\.venv\Scripts\python.exe scripts\history_baseline.py check
.\.venv\Scripts\python.exe scripts\history_baseline.py restore --uri mongodb://127.0.0.1:27030 --database survey_history_phase1_v1
.\.venv\Scripts\python.exe scripts\history_baseline.py verify --uri mongodb://127.0.0.1:27030 --database survey_history_phase1_v1
```

check无需MongoDB，核对文件散列。restore先检查文件，再要求新数据库完全没有集合，创建四集合验证器及全部索引，插入数据并核对每份BSON内容和应用统计。verify只读，不调整验证器、不建索引、不写数据。成功输出bsonContent为exact match、responseCount为3、respondentCount为2。使用其他数据库端口时同步改--uri；不自动读取或改写应用.env。

恢复脚本仅接受显式指定的`survey_history_`加1至40个字母/数字/下划线的数据库名，拒绝已有任何集合，不提供drop/覆盖选项。重复执行restore会拒绝，已有内容不变；再次验证用verify。恢复失败时先检查报错，再选择新库（如`survey_history_phase1_v1_repeat`）重试。每个目标库应只有一个恢复进程操作；工具不支持并行恢复或事务。

恢复后的样例用于CLI/服务层读取和历史兼容测试，不是可登录的演示环境。网页人工验收请另行注册测试账号并创建问卷，不修改基线用户及伪名。

### 可复现生成及第二阶段用法

```powershell
.\.venv\Scripts\python.exe scripts\generate_history_baseline.py
.\.venv\Scripts\python.exe scripts\history_baseline.py check
```

生成器仅重写这一合成基线目录的四个JSON和manifest；expected-stats.json为独立预期，不由数据库结果反写。生成后用Git diff检查应无差异。

第二阶段先记录本仓库当前提交，并保留`data/phase1-history-v1`原件，在新的专属数据库恢复；实现变更后同时验证旧版本读取、路径解释、Decimal128数值、草稿过滤、匿名去重与固定统计。若需求要求迁移，应另存迁移脚本、前后快照及新预期，保留这一版本1原件。当前verify严格要求原始BSON完全一致，适用于未迁移副本；需要改变数据结构的迁移验收应新增测试，原基线应保持不变，迁移后的数据另设预期。第二阶段迁移将在新需求确定后开展。

测试`tests/test_history_baseline.py`覆盖生成一致性、路径有效、文件篡改拒绝、目标库限制、MongoDB恢复与只读复核、拒绝覆盖、验证器/索引、Decimal128和统计。结果见[项目完成报告](docs/项目完成报告.md#testing)。

<a id="version-baseline"></a>

## 版本与基线

业务API版本为1.0.0，结构、题意、规则及身份版本均为1。公开基线标签为`phase1-public-v1.0.0`，只指向本仓库的脱敏源码快照。原`phase1-v1.0.0`、`phase1-final-20261021`、`phase1-submit-20261022`及`phase1-submit-20261022-r1`标签和开发提交仅在本地原工程保留，未推送到公开仓库。

在仓库根目录查看公开版本，或检出公开基线：

```powershell
git log --oneline --decorate --graph
git rev-parse HEAD
git worktree add --detach '../survey-public-baseline' phase1-public-v1.0.0
```

版本1合成历史数据的恢复使用上文脚本，不依赖原开发历史。公开证据中的日志以`LOCAL_USER`、`LOCAL_TEST_HOST`等占位符替换本机标识；E01为账号遮盖后的截图，E02为去除元数据的公开副本。它们不是未经处理的原始文件，处理范围和散列见[AI使用记录](docs/AI使用记录.md#public-release)。

.env包含应用密钥，应与运行数据一同妥善保留，不纳入提交。虚拟环境、node_modules和.runtime也不纳入提交。
