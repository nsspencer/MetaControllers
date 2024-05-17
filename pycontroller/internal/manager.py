import ast
from abc import ABC, abstractmethod
from functools import cmp_to_key
from heapq import nsmallest
from typing import Callable, List, Tuple

from pycontroller.internal.signature_helper import SignatureHelper

PARTITION_NAME = "partition"
CHOSEN_NAME = "chosen"
GENERATED_FUNCTION_NAME = "call_fn"
GENERATED_ACTION_FN_NAME = "_action"
GENERATED_FILTER_FN_NAME = "_filter"
GENERATED_PREFERENCE_FN_NAME = "_preference"
CLASS_ARG_NAME = "self"
POSITIONAL_ARG_PREFIX = "arg_"
VAR_ARG_NAME = "args"
KWARG_NAME = "kwargs"

ACTION_FN_NAME = "action"
FILTER_FN_NAME = "filter"
PREFERENCE_FN_NAME = "preference"
CONTROLLED_METHODS = [ACTION_FN_NAME, FILTER_FN_NAME, PREFERENCE_FN_NAME]


class ControlledMethod(ABC):
    current_setup_instructions_lineno = 0

    def __init__(self, fn: Callable) -> None:
        self.fn = fn
        self.signature = SignatureHelper(self.fn)

    @abstractmethod
    def generate_expression(self) -> Tuple[ast.expr, List[ast.stmt]]:
        pass

    @abstractmethod
    def get_min_required_call_args(self) -> int:
        pass

    def get_new_lineno(self):
        self.current_setup_instructions_lineno += 1
        return self.current_setup_instructions_lineno


class Action(ControlledMethod):
    def generate_expression(self) -> Tuple[ast.expr, List[ast.stmt]]:
        # Create the nodes for the function name and the argument
        func_name = ast.Name(id=GENERATED_ACTION_FN_NAME, ctx=ast.Load())

        args = []
        args.append(ast.arg(arg=CHOSEN_NAME, annotation=None))
        args.extend(
            ControllerManager.generate_positional_args(
                len(self.signature.non_class_positional_args)
                - self.get_min_required_call_args()
            )
        )
        if self.signature.has_arg_unpack:
            args.append(
                ast.Starred(
                    value=ast.Name(id=VAR_ARG_NAME, ctx=ast.Load()), ctx=ast.Load()
                )
            )

        kwargs = []
        for keyword, default in self.signature.keyword_arguments:
            kwargs.append(
                ast.keyword(arg=keyword, value=ast.Name(id=keyword, ctx=ast.Load()))
            )
        if self.signature.has_kwarg_unpack:
            kwargs.append(
                ast.keyword(
                    arg=None,  # `arg` must be None for **kwargs
                    value=ast.Name(id=KWARG_NAME, ctx=ast.Load()),
                )
            )

        # Create the function call node
        call = ast.Call(func=func_name, args=args, keywords=kwargs)

        setup_statement = ast.Assign(
            targets=[ast.Name(id=GENERATED_ACTION_FN_NAME, ctx=ast.Store())],
            value=ast.Attribute(
                value=ast.Name(id=CLASS_ARG_NAME, ctx=ast.Load()),
                attr=ACTION_FN_NAME,
                ctx=ast.Load(),
            ),
            lineno=self.get_new_lineno(),
        )
        return call, [setup_statement]

    def get_min_required_call_args(self) -> int:
        return 1  # chosen


class Filter(ControlledMethod):
    def generate_expression(self) -> Tuple[ast.expr, List[ast.stmt]]:
        # Create the nodes for the function name and the arguments
        filter_name = ast.Name(id="filter", ctx=ast.Load())

        args = []
        args.append(ast.arg(arg=CHOSEN_NAME, annotation=None))
        args.extend(
            ControllerManager.generate_positional_args(
                len(self.signature.non_class_positional_args)
                - self.get_min_required_call_args()
            )
        )
        if self.signature.has_arg_unpack:
            args.append(
                ast.Starred(
                    value=ast.Name(id=VAR_ARG_NAME, ctx=ast.Load()), ctx=ast.Load()
                )
            )

        kwargs = []
        for keyword, default in self.signature.keyword_arguments:
            kwargs.append(
                ast.keyword(arg=keyword, value=ast.Name(id=keyword, ctx=ast.Load()))
            )
        if self.signature.has_kwarg_unpack:
            kwargs.append(
                ast.keyword(
                    arg=None,  # `arg` must be None for **kwargs
                    value=ast.Name(id=KWARG_NAME, ctx=ast.Load()),
                )
            )

        elements_arg = ast.Name(id=PARTITION_NAME, ctx=ast.Load())
        if len(args) + len(kwargs) > self.get_min_required_call_args():
            # just do a generator expression (i for i in PARTITION if filter(i, *args, **kwargs))
            # Construct the generator expression
            filter_fn_name = ast.Name(id=GENERATED_FILTER_FN_NAME, ctx=ast.Load())

            call = ast.GeneratorExp(
                elt=ast.Name(id=CHOSEN_NAME, ctx=ast.Load()),
                generators=[
                    ast.comprehension(
                        target=ast.Name(id=CHOSEN_NAME, ctx=ast.Load()),
                        iter=elements_arg,
                        ifs=[ast.Call(func=filter_fn_name, args=args, keywords=kwargs)],
                        is_async=False,
                    )
                ],
            )
        else:
            filter_fn_name = ast.Attribute(
                value=ast.Name(id=CLASS_ARG_NAME, ctx=ast.Load()), attr=FILTER_FN_NAME
            )
            # Create the function call node
            call = ast.Call(
                func=filter_name, args=[filter_fn_name, elements_arg], keywords=[]
            )

        setup_statement = ast.Assign(
            targets=[ast.Name(id=GENERATED_FILTER_FN_NAME, ctx=ast.Store())],
            value=ast.Attribute(
                value=ast.Name(id=CLASS_ARG_NAME, ctx=ast.Load()),
                attr=FILTER_FN_NAME,
                ctx=ast.Load(),
            ),
            lineno=self.get_new_lineno(),
        )
        return call, [setup_statement]

    def get_min_required_call_args(self) -> int:
        return 1  # chosen


class Preference(ControlledMethod):
    def generate_expression(
        self, get_elements_expression: ast.expr
    ) -> Tuple[ast.expr, List[ast.stmt]]:
        # Create the nodes for the function names and the arguments
        nsmallest_name = ast.Name(id="nsmallest", ctx=ast.Load())
        len_call = ast.Call(
            func=ast.Name(id="len", ctx=ast.Load()),
            args=[ast.Name(id=PARTITION_NAME, ctx=ast.Load())],
            keywords=[],
        )

        cmp_to_key_name = ast.Name(id="cmp_to_key", ctx=ast.Load())
        preference_fn_name = ast.Attribute(
            value=ast.Name(id=CLASS_ARG_NAME, ctx=ast.Load()), attr=PREFERENCE_FN_NAME
        )
        key_arg = ast.keyword(
            arg="key",
            value=ast.Call(
                func=cmp_to_key_name, args=[preference_fn_name], keywords=[]
            ),
        )

        # Create the function call node
        call = ast.Call(
            func=nsmallest_name,
            args=[len_call, get_elements_expression],
            keywords=[key_arg],
        )

        return call, list()

    def get_min_required_call_args(self) -> int:
        return 2  # a, b


class ControllerManager:

    def __init__(self, cls, name, attrs) -> None:
        self.controller = cls
        self.name = name
        self.attrs = attrs
        self.generated_call_fn = None

        controlled_methods = {
            k: v for k, v in attrs.items() if callable(v) and k in CONTROLLED_METHODS
        }
        self.action = (
            Action(controlled_methods[ACTION_FN_NAME])
            if controlled_methods.get(ACTION_FN_NAME, None) is not None
            else None
        )
        self.filter = (
            Filter(controlled_methods[FILTER_FN_NAME])
            if controlled_methods.get(FILTER_FN_NAME, None) is not None
            else None
        )
        self.preference = (
            Preference(controlled_methods[PREFERENCE_FN_NAME])
            if controlled_methods.get(PREFERENCE_FN_NAME, None) is not None
            else None
        )

        self.validate_class_attributes()
        self.validate_class_methods()
        self.assign_call_method(self.generate_call_method())

    def validate_class_attributes(self):
        pass

    def validate_class_methods(self):
        pass

    @staticmethod
    def generate_positional_args(num_args: int) -> List[ast.arg]:
        args = []

        for i in range(num_args):
            args.append(
                ast.arg(
                    arg=f"{POSITIONAL_ARG_PREFIX}{i}",
                    annotation=None,
                    type_comment=None,
                )
            )
        return args

    def get_call_signature_args(self) -> ast.arguments:
        posonlyargs = []
        args = []
        kwonlyargs = []
        kw_defaults = []
        defaults = []

        # Create ast.arg objects for the function arguments
        class_arg = ast.arg(arg=CLASS_ARG_NAME, annotation=None, type_comment=None)
        partition_arg = ast.arg(arg=PARTITION_NAME, annotation=None, type_comment=None)
        args.append(class_arg)
        args.append(partition_arg)

        # generate positional args
        pos_args_to_generate = 0
        if self.has_action:
            arg_difference = (
                len(self.action.signature.non_class_positional_args)
                - self.action.get_min_required_call_args()
            )
            pos_args_to_generate = max(
                arg_difference,
                pos_args_to_generate,
            )
        if self.has_preference:
            arg_difference = (
                len(self.preference.signature.non_class_positional_args)
                - self.preference.get_min_required_call_args()
            )
            pos_args_to_generate = max(
                arg_difference,
                pos_args_to_generate,
            )
        if self.has_filter:
            arg_difference = (
                len(self.filter.signature.non_class_positional_args)
                - self.filter.get_min_required_call_args()
            )
            pos_args_to_generate = max(
                arg_difference,
                pos_args_to_generate,
            )
        args.extend(self.generate_positional_args(pos_args_to_generate))

        # get the keyword arguments
        if self.has_action:
            for keyword, default in self.action.signature.keyword_arguments:
                args.append(ast.arg(arg=keyword, annotation=None))
                defaults.append(ast.Constant(default))
        if self.has_filter:
            for keyword, default in self.filter.signature.keyword_arguments:
                args.append(ast.arg(arg=keyword, annotation=None))
                defaults.append(ast.Constant(default))
        if self.has_preference:
            for keyword, default in self.preference.signature.keyword_arguments:
                args.append(ast.arg(arg=keyword, annotation=None))
                defaults.append(ast.Constant(default))

        # check for arg unpacks
        var_arg = None
        has_var_arg = False
        if self.has_action:
            has_var_arg = self.action.signature.has_arg_unpack or has_var_arg
        if self.has_filter:
            has_var_arg = self.filter.signature.has_arg_unpack or has_var_arg
        if self.has_preference:
            has_var_arg = self.preference.signature.has_arg_unpack or has_var_arg
        if has_var_arg:
            var_arg = ast.arg(arg=VAR_ARG_NAME, annotation=None)

        # check for kwarg unpacks
        kwarg = None
        has_kwarg = False
        if self.has_action:
            has_kwarg = self.action.signature.has_kwarg_unpack or has_kwarg
        if self.has_filter:
            has_kwarg = self.filter.signature.has_kwarg_unpack or has_kwarg
        if self.has_preference:
            has_kwarg = self.preference.signature.has_kwarg_unpack or has_kwarg
        if has_kwarg:
            kwarg = ast.arg(arg=KWARG_NAME, annotation=None)

        func_args = ast.arguments(
            posonlyargs=posonlyargs,
            args=args,
            vararg=var_arg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=defaults,
        )
        return func_args

    def generate_call_method(self) -> Callable:
        get_elements = ast.Name(id=PARTITION_NAME, ctx=ast.Load())
        setup_statements = []

        chosen_element = ast.Name(id=CHOSEN_NAME, ctx=ast.Load())
        if self.has_action:
            action, _setup_stmt = self.action.generate_expression()
            setup_statements.extend(_setup_stmt)
        else:
            action = chosen_element

        if self.has_filter:
            get_elements, _setup_statements = self.filter.generate_expression()
            setup_statements.extend(_setup_statements)

        if self.has_preference:
            get_elements, _setup_stmt = self.preference.generate_expression(
                get_elements
            )
            setup_statements.extend(_setup_stmt)

        # can switch this with ast.GeneratorExp for generator
        generator_expr = get_elements
        if self.has_action:
            generator_expr = ast.ListComp(
                elt=action,
                generators=[
                    ast.comprehension(
                        target=chosen_element, iter=get_elements, ifs=[], is_async=0
                    )
                ],
            )

        return_statement = ast.Return(generator_expr)
        body_code = setup_statements + [return_statement]

        signature_args = self.get_call_signature_args()
        call_fn = ast.FunctionDef(
            name=GENERATED_FUNCTION_NAME,
            args=signature_args,
            body=[body_code],
            decorator_list=[],
            returns=None,
            lineno=0,
            col_offset=0,
        )

        self.generated_call_fn = ast.unparse(call_fn)
        _globals = {"nsmallest": nsmallest, "cmp_to_key": cmp_to_key}
        _locals = {}
        eval(
            compile(self.generated_call_fn, filename="<ast>", mode="exec"),
            _globals,
            _locals,
        )
        return _locals[GENERATED_FUNCTION_NAME]

    def assign_call_method(self, call_fn: Callable) -> None:
        self.controller.__call__ = call_fn

    @property
    def has_action(self) -> bool:
        return self.action is not None

    @property
    def has_filter(self) -> bool:
        return self.filter is not None

    @property
    def has_preference(self) -> bool:
        return self.preference is not None