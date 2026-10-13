# 可选辅助脚本：从 BILI_COOKIE 环境变量解析出 Python 侧兼容用的分字段变量
# BILI_COOKIE 格式: SESSDATA=...; bili_jct=...; DedeUserID=...; buvid3=...
# 如果设置了 BILI_COOKIE，自动导出分字段变量（BILI_SESSDATA / BILI_JCT / BILI_USERID / BILI_BUVID3）
#
# 说明：
# - scripts/client.py 的 from_env() 会优先解析 BILI_COOKIE 本身，本文件**不是**必需步骤，
#   只有依赖分字段环境变量的外部调用方才需要 source 它。
# - 本文件不设置任何 TLS/SSL 相关开关（历史版本曾无条件导出 BILI_SSL_VERIFY=0，
#   该变量没有任何代码消费，且会误导用户以为“已跳过证书校验”，故删除）。
if [ -n "$BILI_COOKIE" ]; then
  _parse_cookie() {
    echo "$BILI_COOKIE" | tr ';' '\n' | while IFS='=' read -r k v; do
      k="$(echo "$k" | xargs)"
      case "$k" in
        SESSDATA)  echo "export BILI_SESSDATA=$v" ;;
        bili_jct)  echo "export BILI_JCT=$v" ;;
        DedeUserID) echo "export BILI_USERID=$v" ;;
        buvid3)    echo "export BILI_BUVID3=$v" ;;
      esac
    done
  }
  eval "$(_parse_cookie)"
fi
