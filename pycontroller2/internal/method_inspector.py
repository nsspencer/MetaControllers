import ast
import inspect
import warnings
from textwrap import dedent
from typing import Any, Callable, List, Tuple


class MethodInspector:
    def __init__(self, fn: Callable) -> None:
        if not callable(fn):
            try:
                name = fn.__name__
            except BaseException:
                name = "UNKNOWN"
            raise ValueError(
                f'MethodInspector expected a callable object, but "{name}" is not.'
            )

        self.fn = fn
        self.is_staticmethod = isinstance(fn, staticmethod)

        if hasattr(fn, "__wrapped__"):
            self.spec = inspect.getfullargspec(fn.__wrapped__)
            self._signature_dict = self.signature_to_dict(fn.__wrapped__)
            self.is_wrapped = True
        else:
            self.spec = inspect.getfullargspec(fn)
            self._signature_dict = self.signature_to_dict(fn)
            self.is_wrapped = False

        # set the placeholder values for the return options
        self.__has_explicit_void_return = None
        self.__has_explicit_value_return = None
        self.__has_value_yield = None
        self.__has_value_yield_from = None
        self.__error = None

    ###
    # Read Only Properties
    #

    @property
    def has_explicit_void_return(self) -> bool:
        if self.__has_explicit_void_return is None:
            self._parse_return_options()
        return self.__has_explicit_void_return

    @property
    def has_explicit_value_return(self) -> bool:
        if self.__has_explicit_value_return is None:
            self._parse_return_options()
        return self.__has_explicit_value_return

    @property
    def has_value_yield(self) -> bool:
        if self.__has_value_yield is None:
            self._parse_return_options()
        return self.__has_value_yield

    @property
    def has_value_yield_from(self) -> bool:
        if self.__has_value_yield_from is None:
            self._parse_return_options()
        return self.__has_value_yield_from

    @property
    def has_parse_error(self) -> bool:
        if self.__error is None:
            self._parse_return_options()
        return self.__error

    def _parse_return_options(self) -> None:
        """Inspection method to parse this instances' callable and determine the
        different ways it can exit:

        Explicit Void returns are when a return statement with no value is provided in the top
        level scope of the provided method.

        Explicit Value returns are when a return statement with a right hand value
        (including None) is provided in the top level scope of the method.

        Value Yield and Value Yield From are equivalent to the checks above, but for
        the yield and yield from keywords.
        """
        # pre-set the values
        self.__has_explicit_void_return = False
        self.__has_explicit_value_return = False
        self.__has_value_yield = False
        self.__has_value_yield_from = False
        self.__error = False

        try:
            source = inspect.getsource(self.fn)
            module = ast.parse(dedent(source))

            class InnerReturnVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.has_explicit_void_return = False
                    self.has_explicit_value_return = False
                    self.has_value_yield = False
                    self.has_value_yield_from = False
                    self.__func_hit = False
                    self.__parent_map = {}

                def visit(self, node):
                    if isinstance(node, list):
                        for item in node:
                            if isinstance(item, ast.AST):
                                self.__parent_map[item] = node
                                super().visit(item)
                    elif isinstance(node, ast.AST):
                        for child in ast.iter_child_nodes(node):
                            self.__parent_map[child] = node
                        super().visit(node)

                def visit_Return(self, node):
                    if node.value is not None:
                        self.has_explicit_value_return = True
                    else:
                        self.has_explicit_void_return = True

                def visit_Yield(self, node: ast.Yield):
                    if node.value is not None:
                        self.has_value_yield = True

                def visit_YieldFrom(self, node: ast.YieldFrom):
                    if node.value is not None:
                        self.has_value_yield_from = True

                def visit_FunctionDef(self, node):
                    if self.__func_hit == False:
                        self.__func_hit = True
                        self.generic_visit(node)
                    else:
                        next_node = self.get_next_node(node)
                        if next_node is not None:
                            self.visit(next_node)

                def visit_AsyncFunctionDef(self, node):
                    next_node = self.get_next_node(node)
                    if next_node is not None:
                        self.visit(next_node)

                def visit_Lambda(self, node):
                    next_node = self.get_next_node(node)
                    if next_node is not None:
                        self.visit(next_node)

                def visit_ClassDef(self, node: ast.ClassDef):
                    next_node = self.get_next_node(node)
                    if next_node is not None:
                        self.visit(next_node)

                def get_next_node(self, node):
                    parent = self.__parent_map[node]
                    if hasattr(parent, "body"):
                        next_sibling = (
                            parent.body[parent.body.index(node) + 1]
                            if parent.body.index(node) + 1 < len(parent.body)
                            else None
                        )
                    else:
                        next_sibling = None
                    return next_sibling

            visitor = InnerReturnVisitor()
            visitor.visit(module.body[0])  # Only visit the top-level function

            self.__has_explicit_value_return = visitor.has_explicit_value_return
            self.__has_explicit_void_return = visitor.has_explicit_void_return
            self.__has_value_yield = visitor.has_value_yield
            self.__has_value_yield_from = visitor.has_value_yield_from

        except BaseException as err:
            try:
                name = self.fn.__name__
            except BaseException:
                name = "UNKNOWN"
            warnings.warn(f'Unable to parse callable "{name}". Error message: {err}')
            self.__error = True

    @staticmethod
    def signature_to_dict(fn: Callable) -> dict:
        """
        returns a dict with the following keys:
        'posonlyargs', 'args', 'varargs', 'varkw', 'defaults', 'kwonlyargs', 'kwonlydefaults', 'annotations'

        NOTE: if "posonlyargs" exists, they will also be found in "args".

        Args:
            fn (Callable): callable object

        Returns:
            dict: dictionary with the components of the call signature
        """
        result = {}
        result["posonlyargs"] = [
            name
            for name, param in inspect.signature(fn).parameters.items()
            if param.kind == inspect.Parameter.POSITIONAL_ONLY
        ]
        result.update(inspect.getfullargspec(fn)._asdict())
        return result

    @property
    def posonlyargs(self) -> list:
        """
        Only the position only arguments in the args list.
        """
        return self._signature_dict["posonlyargs"]

    @property
    def args(self) -> list:
        """
        Args are made up of position only and keyword arguments.
        """
        return self._signature_dict["args"] or list()

    @property
    def varargs(self) -> str:
        return self._signature_dict["varargs"] or None

    @property
    def varkw(self) -> str:
        return self._signature_dict["varkw"] or None

    @property
    def defaults(self) -> list:
        return self._signature_dict["defaults"] or list()

    @property
    def kwonlyargs(self) -> list:
        return self._signature_dict["kwonlyargs"] or list()

    @property
    def kwonlydefaults(self) -> list:
        return self._signature_dict["kwonlydefaults"] or list()

    @property
    def annotations(self) -> list:
        return self._signature_dict["annotations"] or list()

    def get_defaulted_args(self) -> List[Tuple[str, Any]]:
        """
        Returns a list of tuples of (str,Any) being the argument name and its default.

        Returns:
            List[Tuple[str, Any]]: defaulted argument names and values
        """
        keywords = self.args[len(self.args) - len(self.defaults) :]
        if len(keywords) == 0:
            return list()

        return list(zip(keywords, self.defaults))

    def get_keyword_only_args(self) -> List[Tuple[str, Any]]:
        """
        Returns a list of tuples of (str,Any) being the keyword and its value.

        Returns:
            List[Tuple]: keyword only argument names and values
        """
        if len(self.kwonlyargs) == 0:
            return list()

        return list(self.kwonlydefaults.items())

    @property
    def has_arg_unpack(self):
        return self.varargs is not None

    @property
    def has_kwarg_unpack(self):
        return self.varkw is not None

    @property
    def full_call_arg_spec(self) -> inspect.FullArgSpec:
        if self.is_staticmethod:
            return self.spec

        # remove the self argument
        return inspect.FullArgSpec(
            args=self.spec.args[1:],
            varargs=self.spec.varargs,
            varkw=self.spec.varkw,
            defaults=self.spec.defaults,
            kwonlyargs=self.spec.kwonlyargs,
            kwonlydefaults=self.spec.kwonlydefaults,
            annotations=self.spec.annotations,
        )


if __name__ == "__main__":

    def test():
        class TestClass:
            def test2():
                return 0

        yield TestClass

    result = MethodInspector(test)
    print(result.has_explicit_value_return)
    print(result.has_explicit_void_return)
    print(result.has_value_yield)
    print(result.has_value_yield_from)
    print(result.has_parse_error)
