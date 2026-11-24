"""Print the sanitized diagnosis the UI would show for real CLI failures."""
from libtv_gateway import cli_failure

cases = [
    (['download', '-p', 'x', '-n', '成片'], "API Request Error: {\n  code: 401,\n  msg: '未登录'\n}\n接口错误 [401]: 未登录"),
    (['node', 'list', '-p', 'x'], 'API Request Error: {\n  code: 10001,\n  msg: \'用户未授权\'\n}\n拉取画布失败 [10001]: 用户未授权'),
    (['node', 'create'], 'code: 50000 opaque failure'),
]
for args, text in cases:
    print(args[0], '->', cli_failure(args, text, ''))
