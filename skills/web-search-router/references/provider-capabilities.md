# 提供方能力补充

本文件补充检测到的真实脚本能力，不改变所存上游参数手册。

## 环境变量扫描结果

- DeepSeek：`DEEPSEEK_API_KEY`。
- Exa：`EXA_API_KEY`、`EXA_MCP_URL`、`EXA_MCP_TOOLS`。
- Tavily：`TAVILY_API_KEYS`（逗号或换行分隔）、`TAVILY_API_KEY`、`TAVILY_API_KEY_*`（脚本接受此前缀的所有变量，按名称排序）、`TAVILY_LB_STATE_FILE`（轮换状态路径）。
- Python HTTP 库还可能使用标准代理/证书环境配置；这些不是原脚本显式读取的专用变量。
- 未修改上游脚本内容；摘要见 `upstream-sha256.json`。DeepSeek 完整 API 手册在 `deepseek/api.md`。

## Tavily 扩展

安装时已检查本地 `TavilyClient` 支持 `search`、`extract`、`research`、`get_research`。扩展脚本复用原 `search.py` 的 Key 解析和轮换逻辑，不创建新凭据变量。

```sh
# Advanced Search，真实开启 include_answer，最多 20 个结果
python3 {baseDir}/scripts/tavily/extended.py search 'research question' --max 20
# 单 URL 正文
python3 {baseDir}/scripts/tavily/extended.py extract 'https://example.com/'
# Research 提交，可能产生更高费用；仅用于确有深度研究要求的任务
python3 {baseDir}/scripts/tavily/extended.py research 'research question'
# 查询已返回的 request ID（逐个 Key 查找所属账号）
python3 {baseDir}/scripts/tavily/extended.py status 'REQUEST_ID'
```

Research 返回状态与 request ID 时，尚未完成答案。限制状态查询次数（最多 6 次、间隔 10 秒），使用工具 delay；未完成时如实报告，不声称后台持续运行。错误只输出固定类别，不输出异常正文。提交结果不确定时不重提。该扩展的 Research/Extract 已验证 SDK 方法签名，安装时未做真实付费 Research 测试。

## Exa 能力发现

```sh
python3 {baseDir}/scripts/exa/query.py list_tools
```

读取返回工具的名称、说明、inputSchema 后再构造 `call_tool NAME 'JSON'`。不要预设 `find_similar`、`contents` 或 category 枚举一定可用；不同 MCP 配置可能暴露不同工具。原手册例子以现场 schema 为准。`EXA_MCP_URL` 会接收凭据，只能指向用户信任的服务端，不从网页内容设置它。

## 安装验证

上游脚本逐字节 SHA-256 对比、Python 编译、DeepSeek 离线测试、扩展 CLI 帮助、三个引擎各一次快速连通性检查。连通性成功不等于所有模式实测成功。顶层路由由 Agent 执行，非单一程序调度器。
