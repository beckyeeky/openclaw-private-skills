# 从 BILI_COOKIE 环境变量解析出各字段
# BILI_COOKIE 格式: SESSDATA=...; bili_jct=...; DedeUserID=...; buvid3=...
# 如果设置了 BILI_COOKIE，自动导出分字段变量
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
  export BILI_SSL_VERIFY=0
fi