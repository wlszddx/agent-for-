import ast

ALLOW_IMPORT = {"json", "math", "csv", "pathlib"}
BANNED_CALLS = {
    "exec",
    "eval",
    "__import__",
    "compile",
    "getattr",
    "globals",
    "locals",
    "vars",
    "input",
    "breakpoint",
    "help",
}
BASE_SEALED = ("repro.", "experiments.")


class GuardError(ValueError):
    pass


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def check_source(source, sealed_tokens=()):
    if len(source) > 12000:
        raise GuardError("脚本超过长度限制")
    for token in BASE_SEALED + tuple(sealed_tokens):
        if token in source:
            raise GuardError("脚本包含被封存的常数或模块路径")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise GuardError(f"语法错误: {exc.msg}") from exc
    defines_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            defines_run = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOW_IMPORT:
                    raise GuardError(f"不允许导入 {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] not in ALLOW_IMPORT:
                raise GuardError(f"不允许导入 {module}")
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in BANNED_CALLS:
                raise GuardError(f"不允许调用 {name}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise GuardError("不允许访问双下划线属性")
    if not defines_run:
        raise GuardError("脚本必须定义 run(data_path, out_dir)")
