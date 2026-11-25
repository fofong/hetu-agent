/* Hetu Agent launcher: 直接嵌入 libpython(Py_Main), 不 exec python 二进制。
 * 框架版 python 的 bin/python3 会自动 re-exec 进 Python.app 获取 GUI 会话,
 * 导致菜单栏/Dock 身份变成 "Python"。嵌入 libpython 可绕过 re-exec:
 * 进程主 bundle = Hetu Agent.app -> 菜单栏显示 "Hetu Agent", Dock 用本 app 图标。
 * argv 约定: 无参数或 --flag 参数 -> 注入 GUI 脚本; "-m ..." -> 原样透传(当 python 用)。 */
#include <libgen.h>
#include <mach-o/dyld.h>
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char exe[PATH_MAX];
    uint32_t n = sizeof(exe);
    if (_NSGetExecutablePath(exe, &n) != 0) { fprintf(stderr, "path too long\n"); return 1; }
    char *dir = dirname(exe); /* .../Contents/MacOS */
    char src[PATH_MAX], script[PATH_MAX];
    snprintf(src, sizeof(src), "%s/../Resources/src", dir);
    setenv("PYTHONPATH", src, 1);
    snprintf(script, sizeof(script), "%s/../Resources/gui.py", dir);

    /* 注入规则: 无参数 或 --flag(如 --smoke) -> 注入 GUI 脚本;
       "-m ..." 或脚本路径 -> 原样透传(把启动器当 python 用)。 */
    int inject = (argc == 1) ||
                 (argv[1][0] == '-' && argv[1][1] == '-');
    int wargc = argc + (inject ? 1 : 0);
    wchar_t **wargv = calloc((size_t)wargc + 1, sizeof(wchar_t *));
    if (!wargv) { return 1; }
    wargv[0] = Py_DecodeLocale(argv[0], NULL);
    int i = 1;
    if (inject) { wargv[i++] = Py_DecodeLocale(script, NULL); }
    for (int j = 1; j < argc && i < wargc; j++) { wargv[i++] = Py_DecodeLocale(argv[j], NULL); }
    int rc = Py_Main(wargc, wargv);
    return rc;
}
