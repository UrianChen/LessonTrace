# LessonTrace 设计方案 · Design Proposal

本文档是 LessonTrace 开工前的设计方案。实际实现见 [technical-documentation.md](technical-documentation.md)。

This is the design proposal written before LessonTrace was built. For the system as built see [technical-documentation.md](technical-documentation.md).

- [中文](#中文)
- [English](#english)

---

# 中文

作者：陈实当

Nov 22, 2026

## 1. 概述

LessonTrace 是一套课堂分析系统，把一节课的录像和课件变成带时间戳的文字稿和一组分析条目，老师逐条审阅后形成报告。

两条硬约束贯穿全部设计：

- **证据可追溯**：每条分析至少引用一个录像片段，点击即可播放。引用由程序校验，不通过的条目不会展示给老师。
- **不自动打分**：数据结构里没有分数、等级、排名字段，模型输出还要再过一遍规则过滤。

范围：

- 单节课录像，英语授课，课件为 PDF 或 PPTX。
- 单节录像不超过 2 小时、4 GB。
- 上传后异步处理，不要求实时。
- 单机部署：在一台带 GPU 的个人 PC 上用 Docker Compose 一条命令启动。
- 附带一两节处理好的示例课，启动后即可查看。

明确不做的事：

- 实时课堂分析。
- 跨老师的对比或排名。
- 识别学生个人身份（人脸、声纹）。
- 替老师下评价结论。

## 2. 用户与核心流程

主要用户是授课老师，教学发展中心是次要用户，只能看到老师确认并提交的报告。

| 角色 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| 老师 | 上传录像和课件；查看自己的文字稿和分析草稿；采纳、修改、删除、新增条目；生成并提交报告 | 查看其他老师的任何内容 |
| 教学发展中心 | 查看老师已提交的报告 | 查看未提交的草稿、原始录像和文字稿 |
| 管理员 | 添加和停用账号；查看登录和访问日志 | 查看课程内容 |

初始化脚本为三种角色各创建一个账号，之后的账号由管理员添加。

老师的一次完整使用：

1. 上传录像和课件，填写课程名称和授课日期。
2. 系统异步处理，页面显示当前阶段，处理完自动变为可审阅。
3. 打开审阅页：左侧是播放器和文字稿，右侧是分析条目。点击条目里的证据，播放器跳到对应片段。
4. 逐条采纳、修改或删除，也可以自己补充条目。
5. 全部处理完后生成报告，报告只包含保留下来的条目。可导出 PDF，可选择提交给中心。

## 3. 总体架构

系统是一条单向流水线：录像和课件进来，经转写、切分、分析、校验，最后由老师确认后成为报告。

&#91;embedded content: 系统架构 · 8 个模块，2 处存储\]

只有「大模型分析」一步使用大模型，它的输出必须通过程序校验才会到老师面前；报告只收老师确认过的条目。

| 模块 | 职责 | 输入 → 输出 | 实现方式 |
| --- | --- | --- | --- |
| 上传与任务管理 | 接收文件，创建任务，推进状态，失败重试 | 录像、课件 → 任务记录 | 程序 |
| 语音转写 | 语音转文字，给出句级时间戳，区分说话人 | 音频 → 句子列表 | 语音识别模型 |
| 课件解析与对齐 | 提取每页文字，确定每页的讲解时间段 | 课件、句子列表 → 页与时间的对应 | 程序 |
| 片段切分 | 把句子合并成教学片段，分配片段 ID | 句子、页对应 → 片段列表 | 程序（片段标题由大模型生成） |
| 规则统计 | 计算讲授占比、提问次数、语速等事实 | 片段列表 → 统计指标 | 程序 |
| 大模型分析 | 按维度写观察和建议，引用片段 ID | 片段、统计、课件文字 → 条目草稿 | 大模型 |
| 证据校验 | 检查引用是否真实、有无打分表述 | 条目草稿 → 通过的条目 | 程序规则 |
| 审阅与报告 | 老师逐条确认，生成报告 | 通过的条目 → 报告 | 人工 + 程序 |

模块之间只通过数据库里的记录交接，不直接互相调用。这样任何一个阶段都可以单独重跑，也方便替换实现。

## 4. 技术选型

选型原则是一台个人 PC 能跑、一条命令能启动、大模型可替换。具体版本号在开工时锁定并写进依赖文件。

| 层 | 选择 | 理由 |
| --- | --- | --- |
| 后端 API | Python + FastAPI | 与语音识别、大模型工具链同一语言；接口定义自带校验和文档 |
| 异步任务 | Celery + Redis | 处理一节课需要队列、分阶段任务和重试；只开一个工作进程，任务排队执行 |
| 数据库 | PostgreSQL | 关系数据为主，JSONB 存模型原始输出和报告内容 |
| 对象存储 | MinIO（S3 兼容） | 在本机以容器运行；大文件用签名地址直传，不经过 API 进程 |
| 音视频处理 | FFmpeg | 抽取音轨、转码、生成可按时间跳转的播放流 |
| 语音转写 | [WhisperX](https://github.com/m-bain/whisperx)（Whisper medium 模型 + 词级对齐 + 说话人分离） | 英语识别；在 Whisper 之上补了词级时间戳和说话人标签；在本机 GPU 上运行 |
| 课件解析 | PyMuPDF（PDF）、python-pptx（PPTX） | 按页提取文字 |
| 大模型 | 经适配层调用支持 JSON 结构化输出的外部模型 API | 本机 GPU 留给语音转写；适配层让更换模型只改一处 |
| 前端 | Vue 3 + TypeScript，播放器用 video.js | 审阅页需要播放器、文字稿、条目三者联动 |
| 部署 | Docker Compose + Nginx | 本机一条命令启动全部服务，Nginx 提供统一入口 |

备选：语音转写也可改用云厂商的录音文件识别接口。转写模块对外只暴露「音频进、句子列表出」一个接口，替换不影响其他模块。

## 5. 数据模型

所有时间用毫秒整数保存；分析条目表没有任何分数字段；证据的时间从片段表查出，不接受模型给的时间。

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `users` | id, name, role, dept | role 取 teacher / center / admin |
| `lessons` | id, teacher\_id, title, taught\_on, video\_key, slides\_key, duration\_ms, status, error | 一节课，也是一个处理任务；status 见第 6 节 |
| `sentences` | id, lesson\_id, idx, start\_ms, end\_ms, speaker, text | 转写结果，句级；speaker 取 teacher / student / unknown |
| `slides` | id, lesson\_id, page\_no, text, start\_ms, end\_ms | 课件每页文字及对齐到的时间段，未对齐时时间为空 |
| `segments` | id, lesson\_id, code, start\_ms, end\_ms, slide\_id, title, sentence\_from, sentence\_to | 教学片段；code 形如 S012，是模型引用的 ID |
| `metrics` | lesson\_id, key, value, segment\_id | 规则统计结果，segment\_id 为空表示整节课 |
| `analysis_runs` | id, lesson\_id, model, prompt\_version, raw\_output, stats, status | 每次调用模型的记录，用于回归和排查 |
| `findings` | id, run\_id, lesson\_id, dimension, observation, suggestion, status, source | 分析条目；status 取 draft / accepted / edited / rejected；source 取 model / teacher |
| `finding_evidence` | finding\_id, segment\_id, quote | 条目引用的片段和原文引文，一条可有多个 |
| `review_actions` | id, finding\_id, user\_id, action, before, after, at | 老师的每次操作，只增不改 |
| `reports` | id, lesson\_id, version, content, pdf\_key, submitted\_at | 报告快照；submitted\_at 为空表示未提交给中心 |
| audit\_logs | id, user\_id, action, target\_type, target\_id, ip, at | 登录、查看课程和报告、提交、删除等操作的记录，只增不改，管理员可查看 |

几点约定：

- 老师修改条目时，原文保留在 `review_actions.before`，`findings` 里存修改后的内容。
- 报告生成时把条目和证据复制进 `reports.content`，之后再改条目不影响已生成的报告。
- 删除一节课时级联删除以上所有记录和对象存储里的文件。

## 6. 任务状态机与异步处理

一节课从上传到可审阅要经过三个处理阶段，每个阶段独立执行、独立重试。

&#91;embedded content: 任务状态机 · 7 个状态\]

处理中的三个状态都可能进入失败；重试时回到出错的那个阶段，前面阶段的结果保留。

| 状态 | status 值 | 进入条件 | 这个阶段做什么 |
| --- | --- | --- | --- |
| 已上传 | `uploaded` | 录像和课件上传完成 | 等待进入队列 |
| 转写中 | `transcribing` | 任务被取出执行 | 抽音轨、转码、语音转写 |
| 对齐与切分中 | `segmenting` | 转写结果已入库 | 课件解析与对齐、片段切分、规则统计 |
| 分析与校验中 | `analyzing` | 片段已入库 | 大模型分析、证据校验 |
| 待审阅 | `ready` | 通过校验的条目已入库 | 等老师审阅 |
| 已确认 | `confirmed` | 老师生成报告 | 无 |
| 失败 | `failed` | 某阶段自动重试用尽 | 在 `error` 里记录阶段和原因 |

实现约定：

- **一阶段一任务**：每个阶段是一个队列任务。产物写入数据库后才更新状态，并触发下一阶段。
- **幂等**：阶段开始时先清掉本节课在该阶段的旧产物再重算，重复执行不会产生重复数据。
- **自动重试**：阶段内出错自动重试 3 次，间隔逐次加长；仍失败才进入失败状态。
- **手动重试**：老师或管理员点击重试，从记录的失败阶段继续。
- **超时**：每个阶段设时间上限，超时按失败处理，避免任务一直停在处理中。
- **进度展示**：前端定时查询状态，显示当前阶段；失败时显示原因和重试按钮。
- **重新分析**：老师修正文字稿后可要求重新分析，状态从待审阅回到分析与校验中。已采纳或修改过的条目保留，只替换未处理的草稿。

## 7. 处理流水线

流水线的产出是一组带 ID 和起止时间的教学片段，后面的分析和证据都建立在片段上。

1. **预处理**。用 FFmpeg 抽取音轨，转成 16 kHz 单声道 WAV；另转一份 HLS 供网页播放和按时间跳转。
2. **语音转写**。语音活动检测切分长音频，再识别、做词级时间对齐、区分说话人。输出句子列表：起止毫秒、说话人、文本。
   - 累计说话时长最长的说话人标为老师，其余标为学生，老师可在审阅页纠正。
   - 从课件文字里抽取专业术语作为提示词传给识别模型，减少术语识别错误。
3. **课件解析与对齐**。按页提取文字，计算每页与各时间窗口内文字稿的相似度，再用「页码大体递增」的约束求整体最优对应，得到每页的讲解时间段。
   - 相似度低于阈值的页标记为未对齐，不强行分配时间。
   - 录像拍到投影时，可加画面翻页检测作为补充信号，第一版不做。
4. **片段切分**。切点来自三类信号：翻页、较长的停顿、师生说话人切换。
   - 目标长度 30 秒到 3 分钟，过短的合并，过长的在停顿处再切。
   - 每段分配编号（S001、S002……），记录起止时间和所属课件页。
   - 大模型为每段写一句标题，只用于界面展示，不参与切分边界的决定。
5. **规则统计**。用程序算出可以精确计算的事实：
   - 老师与学生的说话时长占比、话轮次数。
   - 提问次数和位置（句末问号，加上以疑问词或助动词开头的句式规则粗筛）。
   - 提问后的等待时长（问句结束到下一句开始）。
   - 语速（词/分钟）、每页课件停留时长。

统计结果只作为事实展示和模型输入，不设阈值，不判好坏。

## 8. 大模型分析

模型只做一件事：读片段，按维度写出「观察 + 建议」，并指明依据的片段编号和原文引文。模型不输出时间，也不输出任何分数。

**输入**

- 片段列表：编号、说话人、文本。
- 课件每页的文字及其对应的片段编号。
- 规则统计结果。
- 分析维度的定义，写在配置文件里。默认四个：结构与节奏（Structure and pacing）、提问与互动（Questioning and interaction）、讲解清晰度（Clarity of explanation）、与课件的一致性（Alignment with slides）。

一节 45 分钟的英语课，文字稿大约六千到七千词（按每分钟 130 到 150 词估算），可以整节放进一次调用。更长的课按维度分次调用，每次仍给全部片段。

**输出结构**

```json
{
  "findings": [
    {
      "dimension": "Questioning and interaction",
      "observation": "The question was answered by the teacher almost immediately, leaving students no time to respond.",
      "suggestion": "Pause for a few seconds after asking, or invite one student to share their reasoning first.",
      "evidence": [
        { "segment_id": "S012", "quote": "So what does this limit equal? Right, it equals one." }
      ]
    }
  ]
}
```

用模型 API 的结构化输出功能约束成这个结构。结构里没有 score、level、rank 一类字段，模型没有地方写分数。

**提示词要点**

- 只描述课堂上发生了什么，并给出可操作的建议。
- 每条至少一个证据，quote 必须逐字摘自该片段。
- 找不到证据就不写这一条。
- 不给分数、等级、排名，不与其他老师或「一般水平」比较。
- 做得好的地方和可改进的地方都要写。
- 每个维度最多 5 条，宁少勿滥。
- 条目用英文书写，与授课语言一致。

**留痕**

每次调用都把模型名、提示词版本和原始输出写入 `analysis_runs`。提示词放在代码仓库里管理，改动即升版本号。

## 9. 证据校验

模型输出要先过下面的规则，全部通过的条目才会出现在审阅页。规则全部是确定性程序，不调用模型。

| 序号 | 规则 | 检查方式 | 不通过时 |
| --- | --- | --- | --- |
| 1 | 结构合法 | 按 JSON Schema 校验 | 整次调用重试 |
| 2 | 维度合法 | dimension 属于已配置的维度 | 丢弃该条目 |
| 3 | 片段存在 | segment\_id 在本节课的片段表中 | 丢弃该证据 |
| 4 | 引文匹配 | quote 统一大小写、去掉标点和多余空白后是该片段文本的子串；否则做模糊匹配，相似度需达到 0.9 | 丢弃该证据 |
| 5 | 至少一条有效证据 | 统计通过规则 3、4 的证据数 | 退回重新生成一次，仍失败则丢弃 |
| 6 | 无打分表述 | 正则匹配 score、grade、rating、rank、out of 10、百分比评分、与他人比较等英文说法 | 退回重写一次，仍失败则丢弃 |
| 7 | 去重 | 同一维度且证据片段相同的条目 | 合并为一条 |

通过校验后，程序从片段表查出每个证据的起止时间，并在片段内定位引文所在的句子，让跳转更精确。

每次运行的校验计数（每条规则拦下多少）写入 `analysis_runs.stats`，用来监控模型质量和比较提示词版本。

规则管不到的一点：引文真实存在，不等于它支撑得了观察。这一层靠老师审阅把关，并在基准集上做人工评估（见第 14 节）。

## 10. API 设计

接口统一前缀 `/api`，登录后携带令牌访问；每个接口都按角色和课程归属做校验。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/lessons` | 创建课程，返回录像和课件的直传签名地址 |
| POST | `/lessons/{id}/start` | 上传完成，开始处理 |
| GET | `/lessons/{id}` | 课程信息、当前状态和进度 |
| POST | `/lessons/{id}/retry` | 从失败的阶段重新开始 |
| DELETE | `/lessons/{id}` | 删除课程及全部数据 |
| GET | `/lessons/{id}/video` | 播放地址，短期有效 |
| GET | `/lessons/{id}/transcript` | 句子列表 |
| PATCH | `/sentences/{id}` | 老师修正转写文本或说话人 |
| GET | `/lessons/{id}/segments` | 片段列表 |
| GET | `/lessons/{id}/metrics` | 规则统计结果 |
| GET | `/lessons/{id}/findings` | 分析条目及证据 |
| POST | `/lessons/{id}/findings` | 老师新增条目，同样要选证据片段 |
| PATCH | `/findings/{id}` | 采纳、修改或删除 |
| POST | `/lessons/{id}/report` | 用已保留的条目生成报告 |
| POST | `/reports/{id}/submit` | 提交给教学发展中心 |
| GET | `/reports` | 中心查看已提交的报告；老师查看自己的报告 |
| GET | `/dimensions` | 读取分析维度，定义在配置文件里 |
| GET / POST | /users | 管理员查看和添加账号 |
| PATCH | /users/{id} | 管理员停用或启用账号 |
| GET | /audit-logs | 管理员查看登录和访问日志，可按用户和时间筛选 |

条目接口的返回示例。时间是服务端从片段表查出的，前端用它控制播放器：

```json
{
  "id": 381,
  "dimension": "Questioning and interaction",
  "observation": "The question was answered by the teacher almost immediately, leaving students no time to respond.",
  "suggestion": "Pause for a few seconds after asking, or invite one student to share their reasoning first.",
  "status": "draft",
  "source": "model",
  "evidence": [
    {
      "segment_id": "S012",
      "quote": "So what does this limit equal? Right, it equals one.",
      "start_ms": 754200,
      "end_ms": 801600
    }
  ]
}
```

修改条目的请求体：`{"action": "accept"}`、`{"action": "reject"}`，或 `{"action": "edit", "observation": "…", "suggestion": "…"}`。

## 11. 审阅界面与报告

审阅页的核心交互是「点证据，看片段」：老师不用自己去录像里找，每条分析的依据一点就能核对。

**页面结构**

- 左上：视频播放器。
- 左下：文字稿，按片段分组，随播放进度高亮当前句；点击任意句子跳转到该时刻。
- 右侧：分析条目，按维度分组；顶部显示「已处理 / 总数」。
- 另设「课堂数据」页签，展示规则统计：师生说话占比、提问在时间轴上的分布、每页课件停留时长。

**单条条目**

- 显示观察、建议和证据列表；每个证据显示时间范围和引文。
- 点击证据：播放器跳到片段起点并播放到片段终点，文字稿同步滚动并高亮引文。
- 三个操作：采纳、修改、删除。修改时可改文字，也可增删证据片段。
- 老师可新增条目：在文字稿上选中一段作为证据，再写观察和建议。

**报告**

- 还有未处理的条目时不能生成报告，避免未经确认的内容进入报告。
- 内容：课程信息、课堂数据（事实）、按维度排列的已确认条目（每条带时间码）、老师自己的反思备注。
- 没有总分、等级或排名；页眉注明「内容经授课教师审阅确认」。
- 网页版报告里的时间码可点击回看片段；PDF 版只打印时间码。
- 生成后默认只有老师自己可见，点「提交」后中心才能看到。

## 12. 权限、隐私与数据保留

课堂录像里有老师和学生的声音与画面，默认按最小可见范围处理，谁在什么时候看过什么都有记录。

- **访问控制**：老师只能访问自己的课；中心只能访问已提交的报告；管理员只管账号和日志，看不到课程内容。校验做在服务端每个接口上，不依赖前端隐藏按钮。
- **视频地址**：播放和下载都用短期有效的签名地址，对象存储不开放公开读。
- **不做身份识别**：只做语音转写，说话人只区分「老师 / 学生」，不做人脸或声纹识别，不记录学生姓名。
- **发给大模型的数据**：只发文字稿和课件文字，不发音视频。
- **数据保留**：老师可随时删除自己的课，删除时级联清掉录像、文字稿、条目和报告。
- **审计**：登录（含失败的尝试）、查看课程和报告、提交、删除都写入审计日志，记录用户、操作、对象、来源地址和时间。日志只增不改，由管理员查看。
- **用途限制**：系统不提供跨老师的对比视图或导出。

## 13. 部署

系统单机部署在一台带 NVIDIA GPU 的个人 PC 上：用 Docker Compose 启动全部服务，浏览器访问 `http://localhost`。只有 Nginx 映射宿主机端口，其余服务只在容器网络内互相访问。

```yaml
services:
  nginx:
    image: nginx:<固定版本>
    ports: ["80:80"]
    volumes: ["./nginx/conf.d:/etc/nginx/conf.d:ro"]
  web:
    build: ./frontend          # 构建后的静态文件
  api:
    build: ./backend
    env_file: .env
    expose: ["8000"]           # 不映射到宿主机
  worker:
    build: ./backend
    command: celery -A app.worker worker --concurrency=1
    env_file: .env
  asr:
    build: ./asr               # 语音转写服务，使用 GPU
    env_file: .env
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
  postgres:
    image: postgres:<固定版本>
    env_file: .env
    volumes: ["pgdata:<该版本镜像的数据目录>"]
  redis:
    image: redis:<固定版本>
  minio:
    image: minio/minio:<固定版本>
    command: server /data
    env_file: .env
    volumes: ["miniodata:/data"]
volumes:
  pgdata:
  miniodata:
```

交付前逐项检查：

- [ ] 在一个干净的目录里重新克隆仓库，按 README 操作，一条命令能启动。
- [ ] 宿主机装好 NVIDIA 驱动和容器运行时，语音转写服务的启动日志显示已识别到 GPU。
- [ ] 数据库和对象存储的数据目录都挂载了命名卷，删掉容器重建后数据还在。
- [ ] 所有镜像用固定版本号，不用 latest。
- [ ] 密钥（数据库口令、对象存储密钥、模型 API Key、Hugging Face 访问令牌）只在 `.env` 里；仓库只提交 `.env.example`。
- [ ] 只有 Nginx 映射宿主机端口，API、数据库、Redis、MinIO 都没有。
- [ ] 有导入示例数据的脚本：一两节处理好的课，启动后即可审阅。
- [ ] 从浏览器入口完整走过一遍「上传到生成报告」，而不是只用脚本请求 API 端口。
- [ ] 模型 API 不可用时，已处理的课仍能正常审阅和生成报告。

语音转写是最耗算力的一步，在 GPU 上运行。使用 [WhisperX](https://github.com/m-bain/whisperx) 的 medium 模型，以 int8\_float16 精度运行，4 GB 显存的显卡即可（large-v2 需要接近 8 GB，目标机器装不下）；说话人分离用到的模型要先在 Hugging Face 上同意使用协议并配置访问令牌。实测处理一节课的耗时后写进 README。

交付物包括代码仓库、README（含架构图和启动步骤）和一段操作录屏。

## 14. 测试与验收

验收看三层：程序逻辑对不对、整条链路在真实入口上通不通、模型产出的分析靠不靠谱。

**程序逻辑（自动化测试）**

- 证据校验的每条规则：各准备通过和不通过的样例，包括编造的片段编号、改写过的引文、带分数的句子。
- 片段切分的边界：空课件、全程无停顿、只有一个说话人。
- 状态机：每个阶段失败后重试、重复触发同一阶段。
- 权限：老师访问他人的课、中心访问未提交的报告，都应被拒绝。

测试用例由人来定，不只用 AI 编程工具自己写的测试。

**端到端**

在本机启动完整环境后，从浏览器入口上传一节录像，走到生成报告。逐条点击证据，核对跳转位置与引文是否一致。

**分析质量（基准集）**

准备 2 到 3 节不同学科的公开课作为基准集，自己标注后固定下来。每次改提示词或换模型都重跑并对比。下表的目标值是初始建议，跑过第一轮后再校准。

| 指标 | 怎么量 | 初始目标 |
| --- | --- | --- |
| 转写词错率 | 每节课抽 10 分钟人工校对 | 不高于 10% |
| 跳转时间误差 | 证据跳转位置与引文实际出现时刻之差 | 不超过 2 秒 |
| 引用有效率 | 模型原始输出中通过规则 3、4 的证据占比 | 不低于 95% |
| 证据支撑率 | 人工判断「证据确实支持该观察」的条目占比 | 不低于 85% |
| 打分表述泄漏 | 展示给老师的条目中含打分或排名表述的数量 | 0 |

## 15. 里程碑

先做风险最高的核心链路，每个里程碑都能独立演示和验收。做到第 3 步就是一个可以展示的作品。

1. **最小闭环（命令行）**。输入一份片段 JSON，调用大模型生成条目，跑证据校验，输出通过的条目。
   - 片段可先用手工整理的文字稿代替。
   - 验收：基准课上的引用有效率和打分表述泄漏达到第 14 节的目标。
2. **转写与切分**。录像进，片段出，接上第 1 步。
   - 验收：转写词错率和时间误差达标。
3. **审阅界面**。播放器、文字稿、条目列表、点击证据跳转、采纳 / 修改 / 删除。
   - 验收：一位老师能独立完成一次审阅。
4. **上传与任务管理**。直传、状态机、失败重试、进度展示。
5. **课件对齐与规则统计**。补上「与课件的一致性」维度和课堂数据页签。
6. **报告与权限**。报告生成、PDF 导出、提交给中心、角色权限、账号管理、审计日志。
7. **打包与展示**。按第 13 节清单在本机跑通，做端到端验收和基准集回归；导入示例数据，录制操作录屏，写好 README。

两件事要在动手前定好，之后各模块按它对接：片段的数据结构（第 5 节）和分析条目的输出结构（第 8 节）。

## 16. 风险

最大的风险在输入质量：转写错了，后面的分析再严谨也是建立在错误文本上。

| 风险 | 后果 | 应对 |
| --- | --- | --- |
| 专业术语、口音、课堂噪声导致转写错误 | 分析基于错误文本 | 课件术语作提示词；老师可修正文字稿；修正后可重新分析 |
| 录像里学生发言收音差，或没有学生发言 | 互动类统计和分析没有内容 | 示例课至少选一节有师生问答的；课堂数据页注明「学生语音可能缺失」 |
| 引文真实但支撑不了观察 | 误导老师 | 老师逐条审阅；基准集上评估证据支撑率 |
| 模型写出隐性评价（没有分数但在下结论） | 违背不打分的原则 | 提示词约束；规则过滤；人工抽检并补充规则 |
| 老师脱稿讲或用板书，课件对不上 | 片段切分变粗，一致性维度无法分析 | 切分退回到只用停顿和说话人；该维度跳过并说明原因 |
| 单机单 GPU，转写任务只能排队 | 连续上传多节课时等待时间长 | 页面显示当前阶段和排队情况；附带处理好的示例课 |
| 外部模型 API 不可用或被限流 | 分析阶段失败 | 自动重试，失败后可手动重试；模型原始输出已入库，已分析的课不受影响；适配层可切换备用模型 |
| 公开课录像有版权和转载限制 | 仓库或录屏不能公开 | 选许可明确的公开课，或用自己录的试讲；仓库不提交录像文件，只写获取方式 |

---

# English

Author: CHEN SHIDANG

Nov 22, 2026

## 1. Overview

LessonTrace is a classroom analysis system. It turns the recording and slides of one lesson into a time-stamped transcript and a set of findings, which the teacher reviews one by one to produce a report.

Two hard constraints run through the whole design:

- **Traceable evidence**: every finding cites at least one segment of the recording, playable with one click. Citations are checked by code, and findings that fail are not shown to the teacher.
- **No automatic scoring**: the data structures have no score, grade or rank fields, and model output passes through a rule filter as well.

Scope:

- One lesson recording at a time, taught in English, with slides as PDF or PPTX.
- A single recording is at most 2 hours and 4 GB.
- Processing is asynchronous after upload; real-time results are not required.
- Single-machine deployment: one Docker Compose command on a personal PC with a GPU.
- One or two processed sample lessons are included and can be viewed right after start-up.

Explicitly out of scope:

- Real-time classroom analysis.
- Comparison or ranking across teachers.
- Identifying individual students (face or voice).
- Reaching evaluative conclusions on the teacher's behalf.

## 2. Users and core flow

The main user is the teacher who taught the lesson. The teaching development center is a secondary user and sees only reports that a teacher has confirmed and submitted.

| Role | Can do | Cannot do |
| --- | --- | --- |
| Teacher | Upload recordings and slides; view their own transcripts and draft findings; accept, edit, remove and add findings; generate and submit reports | See anything belonging to another teacher |
| Teaching development center | View reports that teachers have submitted | See unsubmitted drafts, raw recordings or transcripts |
| Admin | Add and disable accounts; view login and access logs | See lesson content |

The initialization script creates one account for each of the three roles. Later accounts are added by the admin.

A teacher's complete session:

1. Upload the recording and slides, and enter the lesson title and the date it was taught.
2. The system processes the lesson asynchronously. The page shows the current stage and becomes reviewable by itself when processing finishes.
3. Open the review page: the player and transcript are on the left, the findings on the right. Clicking evidence in a finding makes the player jump to that segment.
4. Accept, edit or remove findings one by one, and add findings of their own.
5. When everything is handled, generate the report, which contains only the findings that were kept. It can be exported as PDF and optionally submitted to the center.

## 3. Architecture

The system is a one-way pipeline: a recording and slides go in, pass through transcription, segmentation, analysis and validation, and become a report once the teacher has confirmed the result.

[embedded diagram: system architecture · 8 modules, 2 stores]

Only the "LLM analysis" step uses a large language model. Its output must pass programmatic validation before it reaches the teacher, and the report contains only findings the teacher has confirmed.

| Module | Responsibility | Input → output | Implemented by |
| --- | --- | --- | --- |
| Upload and job management | Receive files, create jobs, advance status, retry failures | Recording, slides → job record | Code |
| Speech transcription | Speech to text with sentence-level timestamps and speaker labels | Audio → list of sentences | Speech recognition model |
| Slide parsing and alignment | Extract the text of each slide and determine when each slide was discussed | Slides, sentences → slide-to-time mapping | Code |
| Segmentation | Merge sentences into teaching segments and assign segment IDs | Sentences, slide mapping → list of segments | Code (segment titles are written by the LLM) |
| Rule-based statistics | Compute facts such as lecture share, number of questions and speech rate | Segments → statistics | Code |
| LLM analysis | Write observations and suggestions per dimension, citing segment IDs | Segments, statistics, slide text → draft findings | LLM |
| Evidence validation | Check that citations are real and that there is no scoring language | Draft findings → findings that pass | Rules in code |
| Review and report | The teacher confirms each finding; a report is generated | Findings that pass → report | Person + code |

Modules hand work to each other only through database records and never call each other directly. Any stage can therefore be re-run on its own, and an implementation can be swapped out easily.

## 4. Technology choices

The principles are: it runs on one personal PC, starts with one command, and the LLM is replaceable. Exact versions are pinned when work starts and written into the dependency files.

| Layer | Choice | Reason |
| --- | --- | --- |
| Backend API | Python + FastAPI | Same language as the speech recognition and LLM tooling; interface definitions come with validation and documentation |
| Asynchronous jobs | Celery + Redis | Processing a lesson needs a queue, staged tasks and retries; a single worker process runs tasks one after another |
| Database | PostgreSQL | Mostly relational data, with JSONB for raw model output and report content |
| Object storage | MinIO (S3 compatible) | Runs as a container on the machine; large files are uploaded directly through presigned URLs without passing through the API process |
| Audio and video | FFmpeg | Extract audio, transcode, and produce a stream that can be seeked by time |
| Speech transcription | [WhisperX](https://github.com/m-bain/whisperx) (Whisper medium model + word-level alignment + speaker diarization) | English recognition; adds word-level timestamps and speaker labels on top of Whisper; runs on the local GPU |
| Slide parsing | PyMuPDF (PDF), python-pptx (PPTX) | Extract text page by page |
| LLM | An external model API with JSON structured output, called through an adapter layer | The local GPU is reserved for transcription; with the adapter, changing models touches one place |
| Frontend | Vue 3 + TypeScript, with video.js as the player | The review page needs the player, the transcript and the findings to work together |
| Deployment | Docker Compose + Nginx | One command starts every service locally; Nginx provides a single entry point |

Alternative: transcription can also use a cloud vendor's recorded-audio recognition API. The transcription module exposes a single interface, "audio in, list of sentences out", so replacing it does not affect other modules.

## 5. Data model

All times are stored as integer milliseconds. The findings table has no score field of any kind. Evidence times are looked up from the segments table; times given by the model are not accepted.

| Table | Key fields | Notes |
| --- | --- | --- |
| `users` | id, name, role, dept | role is teacher / center / admin |
| `lessons` | id, teacher_id, title, taught_on, video_key, slides_key, duration_ms, status, error | One lesson, which is also one processing job; for status see section 6 |
| `sentences` | id, lesson_id, idx, start_ms, end_ms, speaker, text | Transcription result at sentence level; speaker is teacher / student / unknown |
| `slides` | id, lesson_id, page_no, text, start_ms, end_ms | Text of each slide and the time span it was aligned to; times are empty when unaligned |
| `segments` | id, lesson_id, code, start_ms, end_ms, slide_id, title, sentence_from, sentence_to | Teaching segments; code looks like S012 and is the ID the model cites |
| `metrics` | lesson_id, key, value, segment_id | Rule-based statistics; an empty segment_id means the whole lesson |
| `analysis_runs` | id, lesson_id, model, prompt_version, raw_output, stats, status | A record of every model call, for regression and troubleshooting |
| `findings` | id, run_id, lesson_id, dimension, observation, suggestion, status, source | Findings; status is draft / accepted / edited / rejected; source is model / teacher |
| `finding_evidence` | finding_id, segment_id, quote | The segment and verbatim quote a finding cites; one finding can have several |
| `review_actions` | id, finding_id, user_id, action, before, after, at | Every action by the teacher; append-only |
| `reports` | id, lesson_id, version, content, pdf_key, submitted_at | Report snapshot; an empty submitted_at means it has not been submitted to the center |
| audit_logs | id, user_id, action, target_type, target_id, ip, at | Records of sign-ins, viewing lessons and reports, submissions, deletions and so on; append-only, viewable by the admin |

A few conventions:

- When the teacher edits a finding, the original text is kept in `review_actions.before` and `findings` holds the edited content.
- When a report is generated, findings and evidence are copied into `reports.content`. Editing findings afterwards does not affect a report that already exists.
- Deleting a lesson cascades to all of the records above and to its files in object storage.

## 6. Job state machine and asynchronous processing

A lesson passes through three processing stages between upload and review. Each stage runs and retries independently.

[embedded diagram: job state machine · 7 states]

Any of the three processing states can move to failed. A retry returns to the stage that failed, and the results of earlier stages are kept.

| State | status value | Entered when | What this stage does |
| --- | --- | --- | --- |
| Uploaded | `uploaded` | The recording and slides have finished uploading | Waits to enter the queue |
| Transcribing | `transcribing` | The task is picked up | Audio extraction, transcoding, speech transcription |
| Aligning and segmenting | `segmenting` | The transcript has been stored | Slide parsing and alignment, segmentation, rule-based statistics |
| Analyzing and validating | `analyzing` | The segments have been stored | LLM analysis, evidence validation |
| Ready for review | `ready` | The findings that pass validation have been stored | Waits for the teacher's review |
| Confirmed | `confirmed` | The teacher generates a report | Nothing |
| Failed | `failed` | A stage has used up its automatic retries | Records the stage and reason in `error` |

Implementation conventions:

- **One task per stage**: each stage is one queue task. Status is updated, and the next stage triggered, only after the output is written to the database.
- **Idempotent**: a stage first clears the lesson's earlier output for that stage and then recomputes, so running it again never produces duplicate data.
- **Automatic retry**: an error inside a stage is retried 3 times with growing intervals; only then does the lesson enter the failed state.
- **Manual retry**: the teacher or the admin clicks retry, and processing continues from the recorded failed stage.
- **Timeout**: each stage has a time limit. A timeout is treated as a failure, so a job cannot stay in processing forever.
- **Progress display**: the frontend polls the status periodically and shows the current stage; on failure it shows the reason and a retry button.
- **Re-analysis**: after correcting the transcript the teacher can ask for re-analysis, which moves the status from ready for review back to analyzing and validating. Findings that were accepted or edited are kept; only unhandled drafts are replaced.

## 7. Processing pipeline

The pipeline produces a set of teaching segments with IDs and start and end times. Analysis and evidence are both built on segments.

1. **Preprocessing.** FFmpeg extracts the audio track as 16 kHz mono WAV, and separately produces HLS for web playback and seeking by time.
2. **Speech transcription.** Voice activity detection cuts the long audio, followed by recognition, word-level time alignment and speaker separation. The output is a list of sentences: start and end in milliseconds, speaker, text.
   - The speaker with the most total talk time is labelled as the teacher and the rest as students. The teacher can correct this on the review page.
   - Technical terms extracted from the slide text are passed to the recognition model as a prompt, to reduce errors on terminology.
3. **Slide parsing and alignment.** Text is extracted page by page. The similarity between each slide and the transcript in each time window is computed, and the best overall mapping is found under the constraint that page numbers generally increase. This gives the time span during which each slide was discussed.
   - Slides whose similarity is below a threshold are marked as unaligned and are not forced into a time span.
   - When the recording shows the projection, page-turn detection on the picture could be added as a supplementary signal. The first version does not do this.
4. **Segmentation.** Cut points come from three kinds of signal: slide changes, longer pauses, and switches between teacher and student speakers.
   - The target length is 30 seconds to 3 minutes. Segments that are too short are merged, and segments that are too long are cut again at pauses.
   - Each segment gets a number (S001, S002, …) and records its start and end time and the slide it belongs to.
   - The LLM writes a one-sentence title for each segment. Titles are for display only and play no part in deciding segment boundaries.
5. **Rule-based statistics.** Code computes the facts that can be computed exactly:
   - Share of talk time for teacher and students, and the number of turns.
   - Number and position of questions (a question mark at the end of a sentence, plus a rough rule for sentences that begin with a question word or auxiliary verb).
   - Wait time after a question (from the end of the question to the start of the next sentence).
   - Speech rate (words per minute) and time spent on each slide.

Statistics are shown as facts and given to the model as input. No thresholds are set and nothing is judged good or bad.

## 8. LLM analysis

The model does one thing: read the segments and write "observation + suggestion" per dimension, naming the segment IDs and verbatim quotes it relies on. The model outputs no times and no scores of any kind.

**Input**

- The list of segments: ID, speaker, text.
- The text of each slide and the IDs of the segments it corresponds to.
- The rule-based statistics.
- The definitions of the analysis dimensions, kept in a configuration file. There are four by default: Structure and pacing, Questioning and interaction, Clarity of explanation, Alignment with slides.

The transcript of a 45-minute English lesson is roughly six to seven thousand words (estimated at 130 to 150 words per minute) and fits in a single call. Longer lessons are analysed one dimension per call, each call still receiving all segments.

**Output structure**

```json
{
  "findings": [
    {
      "dimension": "Questioning and interaction",
      "observation": "The question was answered by the teacher almost immediately, leaving students no time to respond.",
      "suggestion": "Pause for a few seconds after asking, or invite one student to share their reasoning first.",
      "evidence": [
        { "segment_id": "S012", "quote": "So what does this limit equal? Right, it equals one." }
      ]
    }
  ]
}
```

The model API's structured output feature constrains the response to this structure. The structure has no fields such as score, level or rank, so the model has nowhere to write a score.

**Prompt essentials**

- Describe only what happened in the classroom, and give actionable suggestions.
- At least one piece of evidence per finding, and the quote must be copied word for word from that segment.
- If no evidence can be found, do not write the finding.
- No scores, grades or ranks, and no comparison with other teachers or with a "typical standard".
- Write about what went well as well as what could improve.
- At most 5 findings per dimension; fewer is better than padding.
- Findings are written in English, matching the language of the lesson.

**Audit trail**

Every call writes the model name, the prompt version and the raw output to `analysis_runs`. Prompts are managed in the code repository, and any change bumps the version.

## 9. Evidence validation

Model output must first pass the rules below. Only findings that pass all of them appear on the review page. Every rule is deterministic code; no model is called.

| No. | Rule | How it is checked | On failure |
| --- | --- | --- | --- |
| 1 | Valid structure | Validate against the JSON Schema | Retry the whole call |
| 2 | Valid dimension | dimension is one of the configured dimensions | Discard the finding |
| 3 | Segment exists | segment_id is in this lesson's segments table | Discard that evidence |
| 4 | Quote matches | After normalising case and removing punctuation and extra whitespace, the quote is a substring of the segment text; otherwise fuzzy matching must reach a similarity of 0.9 | Discard that evidence |
| 5 | At least one valid evidence | Count the evidence that passes rules 3 and 4 | Send back for regeneration once; discard if it still fails |
| 6 | No scoring language | Regular expressions for English wording such as score, grade, rating, rank, out of 10, percentage ratings and comparisons with others | Send back for a rewrite once; discard if it still fails |
| 7 | Deduplication | Findings with the same dimension and the same evidence segments | Merge into one |

After validation, the code looks up the start and end time of each piece of evidence from the segments table and locates the sentence containing the quote inside the segment, to make seeking more precise.

The validation counts of each run (how many items each rule stopped) are written to `analysis_runs.stats`, for monitoring model quality and comparing prompt versions.

One thing the rules cannot reach: a quote that really exists does not necessarily support the observation. This layer relies on the teacher's review, and on human evaluation over a benchmark set (see section 14).

## 10. API design

All endpoints share the `/api` prefix and are called with a token after sign-in. Every endpoint checks the role and the ownership of the lesson.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/lessons` | Create a lesson; returns presigned direct-upload URLs for the recording and slides |
| POST | `/lessons/{id}/start` | Upload finished; start processing |
| GET | `/lessons/{id}` | Lesson information, current status and progress |
| POST | `/lessons/{id}/retry` | Restart from the failed stage |
| DELETE | `/lessons/{id}` | Delete the lesson and all of its data |
| GET | `/lessons/{id}/video` | Playback URL, valid for a short time |
| GET | `/lessons/{id}/transcript` | List of sentences |
| PATCH | `/sentences/{id}` | The teacher corrects the transcribed text or the speaker |
| GET | `/lessons/{id}/segments` | List of segments |
| GET | `/lessons/{id}/metrics` | Rule-based statistics |
| GET | `/lessons/{id}/findings` | Findings with evidence |
| POST | `/lessons/{id}/findings` | The teacher adds a finding, which must also select evidence segments |
| PATCH | `/findings/{id}` | Accept, edit or remove |
| POST | `/lessons/{id}/report` | Generate a report from the findings that were kept |
| POST | `/reports/{id}/submit` | Submit to the teaching development center |
| GET | `/reports` | The center views submitted reports; teachers view their own |
| GET | `/dimensions` | Read the analysis dimensions, defined in a configuration file |
| GET / POST | /users | The admin views and adds accounts |
| PATCH | /users/{id} | The admin disables or enables an account |
| GET | /audit-logs | The admin views login and access logs, filterable by user and time |

An example response from the findings endpoint. The times are looked up by the server from the segments table, and the frontend uses them to control the player:

```json
{
  "id": 381,
  "dimension": "Questioning and interaction",
  "observation": "The question was answered by the teacher almost immediately, leaving students no time to respond.",
  "suggestion": "Pause for a few seconds after asking, or invite one student to share their reasoning first.",
  "status": "draft",
  "source": "model",
  "evidence": [
    {
      "segment_id": "S012",
      "quote": "So what does this limit equal? Right, it equals one.",
      "start_ms": 754200,
      "end_ms": 801600
    }
  ]
}
```

The request body for changing a finding: `{"action": "accept"}`, `{"action": "reject"}`, or `{"action": "edit", "observation": "…", "suggestion": "…"}`.

## 11. Review interface and report

The core interaction of the review page is "click the evidence, watch the segment". The teacher does not have to search the recording; the basis of every finding can be checked with one click.

**Page structure**

- Top left: the video player.
- Bottom left: the transcript, grouped by segment, with the current sentence highlighted as playback proceeds. Clicking any sentence jumps to that moment.
- Right: the findings, grouped by dimension, with "handled / total" shown at the top.
- A separate "class data" tab shows the rule-based statistics: the share of teacher and student talk, the distribution of questions along the timeline, and the time spent on each slide.

**A single finding**

- Shows the observation, the suggestion and the list of evidence. Each piece of evidence shows its time range and the quote.
- Clicking evidence makes the player jump to the start of the segment and play to the end of the segment, while the transcript scrolls in step and highlights the quote.
- Three actions: accept, edit, remove. Editing can change the text and also add or remove evidence segments.
- The teacher can add a finding: select a passage in the transcript as evidence, then write the observation and suggestion.

**Report**

- A report cannot be generated while findings remain unhandled, so that unconfirmed content never enters a report.
- Content: lesson information, class data (facts), confirmed findings arranged by dimension (each with timecodes), and the teacher's own reflection notes.
- There is no total score, grade or rank. The header states that the content has been reviewed and confirmed by the teacher.
- In the web version of the report, timecodes can be clicked to watch the segment again. The PDF version prints the timecodes only.
- After generation the report is visible only to the teacher by default. The center can see it only after the teacher clicks "submit".

## 12. Permissions, privacy and data retention

Classroom recordings contain the voices and images of the teacher and students. They are handled with the smallest possible visibility by default, and there is a record of who viewed what and when.

- **Access control**: teachers can access only their own lessons; the center can access only submitted reports; the admin manages only accounts and logs and cannot see lesson content. Checks are made on every endpoint on the server and do not rely on the frontend hiding buttons.
- **Video URLs**: playback and download both use short-lived signed URLs. Object storage does not allow public reads.
- **No identification**: only speech transcription is done. Speakers are distinguished only as "teacher / student". There is no face or voice recognition, and student names are not recorded.
- **Data sent to the LLM**: only the transcript and slide text, never audio or video.
- **Data retention**: teachers can delete their own lessons at any time. Deletion cascades to the recording, transcript, findings and reports.
- **Audit**: sign-ins (including failed attempts), viewing lessons and reports, submissions and deletions are all written to the audit log, recording the user, the action, the target, the source address and the time. The log is append-only and is viewed by the admin.
- **Purpose limitation**: the system provides no cross-teacher comparison views or exports.

## 13. Deployment

The system is deployed on a single personal PC with an NVIDIA GPU. Docker Compose starts every service and the browser opens `http://localhost`. Only Nginx maps a host port; the other services reach each other only on the container network.

```yaml
services:
  nginx:
    image: nginx:<pinned version>
    ports: ["80:80"]
    volumes: ["./nginx/conf.d:/etc/nginx/conf.d:ro"]
  web:
    build: ./frontend          # built static files
  api:
    build: ./backend
    env_file: .env
    expose: ["8000"]           # not mapped to the host
  worker:
    build: ./backend
    command: celery -A app.worker worker --concurrency=1
    env_file: .env
  asr:
    build: ./asr               # speech transcription service, uses the GPU
    env_file: .env
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
  postgres:
    image: postgres:<pinned version>
    env_file: .env
    volumes: ["pgdata:<data directory of that image version>"]
  redis:
    image: redis:<pinned version>
  minio:
    image: minio/minio:<pinned version>
    command: server /data
    env_file: .env
    volumes: ["miniodata:/data"]
volumes:
  pgdata:
  miniodata:
```

Checklist before delivery:

- [ ] Clone the repository again into a clean directory, follow the README, and confirm one command starts it.
- [ ] The host has the NVIDIA driver and the container runtime installed, and the start-up log of the transcription service shows that the GPU was recognised.
- [ ] The data directories of the database and object storage are both mounted on named volumes; the data survives removing and rebuilding the containers.
- [ ] Every image uses a pinned version number, never latest.
- [ ] Secrets (database password, object storage key, model API key, Hugging Face access token) exist only in `.env`; the repository commits only `.env.example`.
- [ ] Only Nginx maps a host port; the API, database, Redis and MinIO do not.
- [ ] There is a script that imports sample data: one or two processed lessons that can be reviewed right after start-up.
- [ ] The full path from "upload to generating a report" has been walked through from the browser entry point, not only by scripts calling the API port.
- [ ] When the model API is unavailable, lessons that were already processed can still be reviewed and turned into reports.

Speech transcription is the most compute-intensive step and runs on the GPU. It uses the medium model of [WhisperX](https://github.com/m-bain/whisperx) at int8_float16 precision, which a GPU with 4 GB of memory can run (large-v2 needs close to 8 GB, more than the target machine has). The model used for speaker diarization requires accepting its terms of use on Hugging Face and configuring an access token first. The measured time to process one lesson is written into the README.

The deliverables are the code repository, a README (with an architecture diagram and start-up steps) and a screen recording of the system in use.

## 14. Testing and acceptance

Acceptance looks at three layers: whether the program logic is right, whether the whole chain works through the real entry point, and whether the analysis the model produces can be trusted.

**Program logic (automated tests)**

- Each evidence validation rule: prepare passing and failing samples for each, including fabricated segment IDs, paraphrased quotes and sentences with scores.
- Segmentation boundaries: empty slides, no pauses at all, only one speaker.
- State machine: retry after each stage fails, and triggering the same stage repeatedly.
- Permissions: a teacher accessing another teacher's lesson, and the center accessing an unsubmitted report, must both be refused.

Test cases are decided by a person, not only by tests that an AI coding tool writes for itself.

**End to end**

With the full environment running locally, upload a recording from the browser entry point and go all the way to generating a report. Click each piece of evidence and check that the jump position agrees with the quote.

**Analysis quality (benchmark set)**

Prepare 2 to 3 open lectures from different subjects as a benchmark set, annotate them yourself, and freeze them. Re-run and compare every time the prompt or the model changes. The targets in the table below are initial suggestions, to be calibrated after the first run.

| Metric | How it is measured | Initial target |
| --- | --- | --- |
| Transcription word error rate | Manually proofread a 10-minute sample of each lesson | No higher than 10% |
| Jump time error | Difference between the position evidence jumps to and the moment the quote is actually spoken | No more than 2 seconds |
| Citation validity | Share of evidence in the raw model output that passes rules 3 and 4 | No lower than 95% |
| Evidence support rate | Share of findings a person judges as "the evidence really supports this observation" | No lower than 85% |
| Scoring language leakage | Number of findings shown to the teacher that contain scoring or ranking wording | 0 |

## 15. Milestones

Build the highest-risk core chain first. Each milestone can be demonstrated and accepted on its own. Reaching step 3 already gives something that can be shown.

1. **Minimal loop (command line).** Take a segments JSON as input, call the LLM to generate findings, run evidence validation, and output the findings that pass.
   - Segments can at first be replaced by a hand-prepared transcript.
   - Acceptance: citation validity and scoring language leakage on the benchmark lessons reach the targets in section 14.
2. **Transcription and segmentation.** Recording in, segments out, connected to step 1.
   - Acceptance: transcription word error rate and time error reach their targets.
3. **Review interface.** Player, transcript, list of findings, click evidence to jump, accept / edit / remove.
   - Acceptance: one teacher can complete a review unaided.
4. **Upload and job management.** Direct upload, state machine, failure retry, progress display.
5. **Slide alignment and rule-based statistics.** Add the "Alignment with slides" dimension and the class data tab.
6. **Reports and permissions.** Report generation, PDF export, submission to the center, role permissions, account management, audit log.
7. **Packaging and presentation.** Run through the section 13 checklist on the local machine, do end-to-end acceptance and the benchmark regression, import sample data, record the screen recording, and finish the README.

Two things must be settled before starting, and every module then builds against them: the data structure of a segment (section 5) and the output structure of a finding (section 8).

## 16. Risks

The biggest risk is input quality: if the transcript is wrong, even rigorous analysis is built on wrong text.

| Risk | Consequence | Response |
| --- | --- | --- |
| Technical terms, accents and classroom noise cause transcription errors | Analysis is based on wrong text | Slide terms as a prompt; the teacher can correct the transcript; re-analysis after correction |
| Student speech is poorly captured in the recording, or there is none | Interaction statistics and analysis have nothing to work with | Choose at least one sample lesson with teacher-student Q&A; state on the class data page that "student speech may be missing" |
| A quote is real but does not support the observation | Misleads the teacher | The teacher reviews each finding; evaluate the evidence support rate on the benchmark set |
| The model writes implicit evaluations (no score, but a verdict) | Violates the no-scoring principle | Prompt constraints; rule filtering; manual spot checks with rules added as needed |
| The teacher speaks off-script or uses the board, and the slides do not match | Segmentation becomes coarser and the alignment dimension cannot be analysed | Fall back to segmenting by pauses and speakers only; skip that dimension and explain why |
| One machine and one GPU, so transcription jobs must queue | Long waits when several lessons are uploaded in a row | Show the current stage and the queue on the page; include processed sample lessons |
| The external model API is unavailable or rate-limited | The analysis stage fails | Automatic retry, then manual retry after failure; raw model output is already stored, so analysed lessons are unaffected; the adapter layer can switch to a backup model |
| Open lecture recordings have copyright and redistribution restrictions | The repository or screen recording cannot be made public | Choose open lectures with a clear licence, or record a trial lesson yourself; the repository does not commit recordings and only describes how to obtain them |
