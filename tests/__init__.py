"""测试包导入时密封宿主环境。

hetu.guard 是 fail-closed：HETU_HOME/HETU_DB 若被宿主 shell 指进旧
旧产品（HongYun 前作） 树，一切开库测试都会被正确拦截。hetu 运行时并不用这两个
变量解析路径（仅 guard 审计用），因此测试进程内直接移除即可密封，
pytest 与 unittest 两种 runner 统一生效，无 ambient 依赖。
"""
import os

for _var in ("HETU_HOME", "HETU_DB", "HETU_HOST66_BASE_URL", "HETU_HOST66_API_KEY",
             "HETU_MODEL_BASE_URL", "HETU_MODEL_NAME", "HETU_MODEL_API_KEY"):
    os.environ.pop(_var, None)
