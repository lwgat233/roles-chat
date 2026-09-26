---
name: UML 交付与语法自测（调查者长期职责）
must: true
tags: [调查者, UML, plantuml, 语法自测, 长期职责, 交付]
when: 每轮 UML 任务（用例图/类图/时序图/活动图）开工与交付时
verify: 每张图都跑过 `-checkonly` 且 **rc=0**，并成功导出 svg/png；读数进证据文件
---

# UML 交付与语法自测（本人 2026-09-26 定的长期职责）

本人原话：「这个 investigator **以后要完成的任务就是编写 UML** …… 好像是 **UML 的四张图**；然后要**测试一下，让他测试自己编写的 UML 是不是符合 UML 语法**。」
**四张图的具体清单本人还在确认**（女仆在问）；先按最常见的四张备着：**用例图 / 类图 / 时序图 / 活动图**。**清单到之前不要自己开工立项**。

## 交什么（每轮 UML 任务）
1. **图源文件**（`.puml` 纯文本，可 diff、可归档，丢库能重建）；
2. **渲染出的图**（`svg` 优先，要 png 也行）；
3. **语法自测读数**（`-checkonly` 的输出与 rc）；
4. 落位：`/vol1/1000/airesults/<项目>/docs/`（源文件+图）与 `evidence/`（校验输出）。

## 怎么跑（本机已验证，2026-09-26）
工具（已就位，**不要再联网下**）：
- `java`：`/home/lwgat/tools/jdk-17.0.2/bin/java`（OpenJDK 17.0.2）
- `plantuml.jar`：`/vol1/1000/aicache/tools/plantuml.jar`（1.2024.8，21.9MB，一次性下好当缓存）

命令：
```bash
J=/home/lwgat/tools/jdk-17.0.2/bin/java
U=/vol1/1000/aicache/tools/plantuml.jar
$J -jar $U -checkonly 图.puml      # 语法自测：rc=0 = 合格；rc=200 + "Error line N" = 不合格
$J -jar $U -tsvg 图.puml           # 渲染：一个文件里多张图会产出 图.svg / 图_001.svg / 图_002.svg …
```
**判据：`-checkonly` 输出无 error 且 rc=0 且 svg 导出成功 ＝ 语法合格**（"渲染成功 + 0 error"）。

## 三个实测坑（别再踩）
1. **一张 `@startuml` 块里混两种图**（比如把类图与时序图塞进同一个块）⇒ `-checkonly` 直接报错、rc=200。**一个 `@startuml…@enduml` 只放一张图**；同一文件里可以有多块，导出会分别出 `_001/_002`。
2. **类图/用例图的渲染要 graphviz（`dot`）**，本机**没装** ⇒ 会抛 `Cannot run program "/opt/local/bin/dot"`（语法检查不受影响，照旧 rc=0）。
   **不用装 graphviz 的办法**：在类图/用例图那块加一行 `!pragma layout smetana`（PlantUML 自带的纯 Java 布局引擎）⇒ 实测 rc=0、四张图全部导出成功（svg 各自成文件）。
   时序图 / 活动图**不需要** graphviz。
3. **`-checkonly` 通过 ≠ 图好看**：布局/连线合理性要人看，别把 rc=0 当"图没问题"。

## 红线
- **只出图与文档，不改代码**（角色定位）；要改产品代码另立项、归 pipeline 角色。
- 图要写清**依据来源**（需求/接口/实测），别凭印象画；不确定的关系标注「待确认」。
- 不许为了"能编译"把图简化到没信息量；语法不过就改语法、别删语义。
