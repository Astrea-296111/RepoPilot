# 03｜Repo Map 与代码检索

想象去一座十万间房的城市找「注册用户」：把每间房的全部内容抄到一张纸不现实。仓库几十万行代码也一样：有上下文长度限制，传输花 Token，而且无关内容会分散注意力。**Repo Map 像城市地图**，先写「哪条街有什么楼」；`read_file` 才是走进一栋楼看具体细节。

先看简单 Python：

```python
def add(a, b):
    return a + b
```

Python 的 `ast` 能把它解析为一个结构：

```text
FunctionDef
├── name = add
├── args = a, b
└── body = return a + b
```

你可以把 AST 理解成「按语法拆好的零件清单」，不是程序的运行结果。`repopilot/context/repo_map.py:build_repo_map` 不执行目标代码，只提取顶层函数、类、方法、import、签名、文档首行。扫描跳过 `.git`、`.venv`、构建目录、符号链接、超过 512 KB 的文件与含 NUL 的文件；上限 4000 文件。非 Python 的少量语言仅做正则提取，不能像 Python AST 一样精确。

接下来要选房子。`repopilot/context/retrieval.py:retrieve` 给文件名匹配 +6、符号匹配 +4、正文词频最多 +5；取 Top-K。给 Demo 的中文需求用了一个很小的「邮箱→email、重复→duplicate」词表，所以能找到 `app/users.py`。这不是通用中文搜索；评分也不是训练出来的相关性概率。

```text
用户说「重复邮箱注册」
  ├─ 词：duplicate, email, register, user ...
  ├─ 路径：app/users.py
  ├─ 符号：UserService.register
  └─ 文本：DuplicateEmailError
       → 排在前面 → 模型再 read_file
```

重要限制：超过 4000 文件会只扫描前面的排序结果，初排可能漏掉关键文件；大库应加缓存、分目录检索、BM25 和语义向量，再结合调用关系。测试 `test_repo_map_extracts_symbols_and_skips_generated`、`test_retrieval_finds_chinese_task` 是最小行为验证。

### 这一章你面试时应该能说什么

「用 AST 抽取 Python 文件的符号做仓库地图，先用路径、符号、词频选 Top-K，再按需读源码。这样降低输入规模；当前实现有 4000 文件上限与有限中文词表，大型仓库需要增量索引和混合检索。」

### 可能的追问

1. AST 和直接正则找 `def` 有什么差别？
2. Repo Map 为什么不包含函数全部实现？
3. 评分 +6/+4/+5 是什么意思？
4. 仓库超大或函数动态生成时会漏掉什么？

