# 证据支撑率评估记录 · Evidence Support Evaluation

- [中文](#中文)
- [English](#english)

---

# 中文

作者：陈实当

Nov 23, 2026 · 第 1 轮

## 结论

| | 条目数 | 支撑 | 部分支撑 | 不支撑 | 严格口径 | 宽松口径 |
| --- | --- | --- | --- | --- | --- | --- |
| MIT 6.0001 Lecture 2 | 14 | 11 | 1 | 2 | 78.6% | 85.7% |
| MIT 15.S12 Session 1 | 13 | 12 | 1 | 0 | 92.3% | 100% |
| 合计 | 27 | 23 | 2 | 2 | **85.2%** | **92.6%** |

严格口径只算「支撑」，宽松口径把「部分支撑」也算上。设计方案的初始目标是不低于 85%。

评估方式：人工逐条判断，一位评估者，一轮。

## 评估对象

| 项 | 值 |
| --- | --- |
| 分析模型 | `claude-opus-5-5` |
| 提示词版本 | `2026-11-22.1` |
| 转写 | WhisperX `medium`，开启说话人分离 |
| 判定标准 | 只看条目引用的片段，观察说的事是否属实；不评价建议的好坏 |

## 不支撑和部分支撑的条目

### 6.0001 Lecture 2

| 条目 | 判定 | 原因 |
| --- | --- | --- |
| #12「第 9、12、22 页没有对上任何片段」 | 不支撑 | 条目描述的是系统的对齐结果，不是课堂上发生的事；引用的那句话和这个论断无关；而且第 12 页实际上对齐到了 24:00–24:30。 |
| #13「MIT 迷宫的地图不在课件上，第 10 页只列了规则」 | 不支撑 | 系统只提取课件的文字。第 10 页上很可能有地图图片，只是没被读到。条目把「系统看不到」当成了「课件上没有」。 |
| #4「好几个问题老师几乎立刻自己回答」 | 部分支撑 | 两处证据里，一处是反问句（"Do you know how many times the user might keep going right?"），不是真要学生回答；另一处的 "nine" 从字幕看不出是老师说的还是学生说的。 |

### 15.S12 Session 1

| 条目 | 判定 | 原因 |
| --- | --- | --- |
| #5「连续发问，学生还没回应老师就自己回答了」 | 部分支撑 | 第一处属实：老师自己说出了 "Tim Berners-Lee"。第二处不属实：官方字幕显示老师点了一位学生，学生答出了 "Satoshi Nakamoto"。文字稿漏掉了这几句声音很小的学生发言。 |

## 值得留意的「支撑」条目

- **6.0001 #11**（课件代码没有括号，讲解时说用了括号）：核对课件第 4 页原文 `silly = hi + " " + name * 3`，确实没有括号。条目成立，而且是一个真实的课件问题。
- **6.0001 #10**（口头说 print zero，随后又说打印的是字母 P）：文字稿和官方字幕一致，老师确实这样说了。
- **15.S12 #11**（课件写 Charles Schwab，口头说 D.E. Shaw）：文字稿和官方字幕都是 "DE Shaw"，与课件不一致（37:52 处）。
- **15.S12 #12**（课件写全球 GDP 的 ½–1%，口头说的是美国经济）：核对课件第 23 页，属实。

## 这一轮暴露的系统问题

| 问题 | 影响 | 可能的改法 |
| --- | --- | --- |
| 课件对齐结果被模型当成了课堂事实 | 产生「某页没被讲到」这类无法由证据支撑的条目 | 提示词里说明对齐是程序的估计；或不把「未对齐」的页交给模型 |
| 课件只提取文字，图片和图表看不到 | 模型会误以为课件上没有某些内容 | 提示词里说明课件文字不含图片；或提取课件页面图像 |
| 声音很小的学生发言没被转写出来 | 模型以为没人回答，高估「老师自问自答」 | 提示词里提醒学生发言可能缺失；条目涉及「无人回应」时要求更强的证据 |
| 模型把反问句当成提问 | 「提问与互动」维度的条目偏多 | 提示词里区分反问和真正的提问 |

这些都还没改。改提示词要升版本号，并在同样两节课上重跑、重判。

## 局限

- 样本只有 27 条，一条的出入约 3.7 个百分点。
- 只有一位评估者，没有复判，无法估计评估者之间的一致性。
- 模型输出每次不同，这个数字只对应这一轮的输出。

---

# English

Author: CHEN SHIDANG

Nov 23, 2026 · Round 1

## Result

| | Findings | Supported | Partly supported | Not supported | Strict | Lenient |
| --- | --- | --- | --- | --- | --- | --- |
| MIT 6.0001 Lecture 2 | 14 | 11 | 1 | 2 | 78.6% | 85.7% |
| MIT 15.S12 Session 1 | 13 | 12 | 1 | 0 | 92.3% | 100% |
| Total | 27 | 23 | 2 | 2 | **85.2%** | **92.6%** |

The strict figure counts only "supported". The lenient figure also counts "partly supported". The initial target in the design proposal is no lower than 85%.

Method: judged by a person, finding by finding. One evaluator, one round.

## What was evaluated

| Item | Value |
| --- | --- |
| Analysis model | `claude-opus-5-5` |
| Prompt version | `2026-11-22.1` |
| Transcription | WhisperX `medium`, speaker separation on |
| Criterion | Looking only at the segments a finding cites, is what the observation says true? The quality of the suggestion is not judged |

## Findings judged not supported or partly supported

### 6.0001 Lecture 2

| Finding | Judgement | Reason |
| --- | --- | --- |
| #12 "Slides 9, 12 and 22 were not matched to any segment" | Not supported | The finding describes the system's alignment result, not something that happened in class. The quote it cites has nothing to do with the claim. Slide 12 was in fact aligned, to 24:00–24:30. |
| #13 "The MIT maze map is not on the slides; slide 10 only lists the rules" | Not supported | The system extracts only the text of slides. Slide 10 very likely carries the map as an image that was not read. The finding treats "the system cannot see it" as "it is not on the slide". |
| #4 "Several questions are answered by the teacher almost immediately" | Partly supported | Of the two pieces of evidence, one is a rhetorical question ("Do you know how many times the user might keep going right?") that students were not meant to answer. For the other, the captions do not show whether "nine" was said by the teacher or a student. |

### 15.S12 Session 1

| Finding | Judgement | Reason |
| --- | --- | --- |
| #5 "Questions in quick succession, answered by the teacher before students could respond" | Partly supported | The first case is true: the teacher supplied "Tim Berners-Lee" himself. The second is not: the official captions show the teacher called on a student, who answered "Satoshi Nakamoto". The transcript missed these quiet student utterances. |

## Supported findings worth a second look

- **6.0001 #11** (the slide code has no parentheses, while the explanation says parentheses are used): slide 4 reads `silly = hi + " " + name * 3`, with no parentheses. The finding holds, and it points at a real problem in the slides.
- **6.0001 #10** (the teacher says "print zero" and then says the letter P is being printed): the transcript and the official captions agree that this is what was said.
- **15.S12 #11** (the slide says Charles Schwab, the teacher says D.E. Shaw): both the transcript and the official captions have "DE Shaw", which differs from the slide (at 37:52).
- **15.S12 #12** (the slide gives ½–1% of global GDP, the teacher speaks of the US economy): confirmed against slide 23.

## System problems this round exposed

| Problem | Effect | Possible change |
| --- | --- | --- |
| The model treats slide alignment results as classroom facts | Findings such as "this slide was not covered" that no evidence can support | Say in the prompt that alignment is the program's estimate, or do not pass unmatched slides to the model |
| Only slide text is extracted; images and charts are invisible | The model wrongly concludes that some content is not on the slides | Say in the prompt that slide text excludes images, or extract slide images |
| Quiet student speech is not transcribed | The model assumes nobody answered and overstates "the teacher answers their own questions" | Remind the model that student speech may be missing; require stronger evidence for claims that nobody responded |
| The model treats rhetorical questions as questions | Too many findings under "Questioning and interaction" | Distinguish rhetorical from genuine questions in the prompt |

None of these has been changed yet. Changing the prompt means bumping its version, then re-running and re-judging on the same two lectures.

## Limitations

- The sample is only 27 findings, so one finding moves the figure by about 3.7 percentage points.
- There was a single evaluator and no second pass, so agreement between evaluators cannot be estimated.
- Model output differs from run to run. The figure applies to this run only.
