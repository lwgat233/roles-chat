# 环境配方：UML 建模（PlantUML）—— roles-chat / 调查者长期职责用

**依据**：本人 2026-09-26 给 `research.investigator` 定的长期职责（编写 UML 四张图 + 自测语法合规；女仆代转 #1418）。
**本机已就位（2026-09-26 实测通过）**：

| 件 | 路径 / 版本 | 说明 |
|---|---|---|
| Java | `/home/lwgat/tools/jdk-17.0.2/bin/java`（OpenJDK 17.0.2） | 无 sudo、不装系统包 |
| PlantUML | `/vol1/1000/aicache/tools/plantuml.jar`（1.2024.8，21.9MB） | **一次性下载当缓存**，不进项目、不再联网 |
| graphviz `dot` | **没装**（有意不装） | 类图/用例图用 `!pragma layout smetana` 绕开 |

**一次性安装命令（只需一次，已执行；换机器照抄）**：
```bash
curl -sS --max-time 120 --proxy http://127.0.0.1:7890 -L \
  -o /vol1/1000/aicache/tools/plantuml.jar \
  https://github.com/plantuml/plantuml/releases/download/v1.2024.8/plantuml-1.2024.8.jar
/home/lwgat/tools/jdk-17.0.2/bin/java -jar /vol1/1000/aicache/tools/plantuml.jar -version
```

**用法与判据**（详见 `experiences/research.investigator/UML交付与语法自测.md`）：
```bash
J=/home/lwgat/tools/jdk-17.0.2/bin/java
U=/vol1/1000/aicache/tools/plantuml.jar
$J -jar $U -checkonly 图.puml   # rc=0 且无 error ＝ 语法合格
$J -jar $U -tsvg 图.puml        # 多张图 → 图.svg / 图_001.svg / 图_002.svg …
```
坑：① 一个 `@startuml…@enduml` 只放一张图；② 类图/用例图必须加 `!pragma layout smetana`（否则找 `dot` 失败）；③ 时序图/活动图不需要 graphviz；④ `-checkonly` 过了不等于图好看。

**没装的东西与理由**：graphviz（无 sudo 且 smetana 够用，真要用再说）、mermaid（图一律 PlantUML 文本，可 diff、可归档、丢库能重建）。
