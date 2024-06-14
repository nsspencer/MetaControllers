import ast
from typing import List

from pycontroller2.internal.method_inspector import MethodInspector
from pycontroller2.internal.namespace import CLASS_ARG_NAME


class MethodInvocation:
    def __init__(self, method: MethodInspector) -> None:
        self.method = method

    def to_function_call(self) -> ast.Call:
        """
        Generates the invocation call for this method, assuming the arguments
        being passed in are the same name as the parameters defined in this
        function.

        Returns:
            ast.Call: ast representation of a Callable that will call this instances method.
            This should be wrapped in an ast.Expr before compiling.
        """
        args = [ast.Name(id=arg, ctx=ast.Load()) for arg in self.method.call_args]
        if self.method.has_arg_unpack:
            args.append(
                ast.Starred(
                    value=ast.Name(id=self.method.varargs, ctx=ast.Load()),
                    ctx=ast.Load(),
                )
            )

        keywords = [
            ast.keyword(arg=keyword, value=ast.Name(id=keyword, ctx=ast.Load()))
            for keyword, _ in self.method.get_keyword_only_args()
        ]

        if self.method.has_kwarg_unpack:
            keywords.append(
                ast.keyword(
                    arg=None, value=ast.Name(id=self.method.varkw, ctx=ast.Load())
                )
            )

        return ast.Call(
            func=ast.Attribute(
                value=ast.Name(id=CLASS_ARG_NAME, ctx=ast.Load()),
                attr=self.method.name,
                ctx=ast.Load(),
            ),
            args=args,
            keywords=keywords,
        )

    def to_lambda(self, lambda_args: List[str]) -> ast.Lambda:
        args = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=arg, annotation=None) for arg in lambda_args],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
        return ast.Lambda(args=args, body=self.to_function_call())
