
import itertools
from typing import *

from .data.casts import type_cast
from .data.data_ops import (
    DB, ArrExpr, ArrVal, BackLinkExpr, BoolVal, DBEntry,
    DetachedExpr, Expr, FilterOrderExpr, ForExpr, FreeVal, FreeVarExpr,
    FunAppExpr, InsertExpr, IntInfVal, IntVal, Invisible, Label,
    LinkPropLabel, LinkPropProjExpr, LinkPropVal, Marker, MultiSetExpr,
    MultiSetVal, NamedTupleExpr, NamedTupleVal, ObjectExpr, ObjectProjExpr,
    ObjectVal, OffsetLimitExpr, OptionalForExpr, OrderAscending,
    OrderDescending, OrderLabelSep, ParamOptional, ParamSetOf,
    ParamSingleton, RefVal, ShapedExprExpr, ShapeExpr, StrLabel, StrVal,
    SubqueryExpr, TpIntersectExpr, TypeCastExpr, UnionExpr,
    UnnamedTupleExpr, UnnamedTupleVal, UpdateExpr, Val, VarTp, Visible,
    WithExpr, next_id, RTData, RTExpr, RTVal)
from .data import data_ops as e
from .data import expr_ops as eops
from .data.expr_ops import (
    assume_link_target, coerce_to_storage, combine_object_val,
    get_object_val, instantiate_expr,
    map_assume_link_target, map_expand_multiset_val,
      val_is_link_convertible, val_is_ref_val)
from .data.type_ops import is_nominal_subtype_in_schema


def make_eval_only(data: RTData) -> RTData:
    return RTData(data.cur_db, data.read_snapshots, data.schema, True)


def eval_error(expr: Val | Expr | Sequence[Val], msg: str = "") -> Any:
    raise ValueError("Eval Error", msg, expr)


def eval_order_by(
        after_condition: Sequence[Val],
        orders: Sequence[ObjectVal]) -> Sequence[Val]:
    if len(after_condition) == 0:
        return after_condition
    if len(orders) == 0:
        return after_condition

    keys = [k.label for k in orders[0].val.keys()]
    if len(keys) == 0:
        return after_condition
    sort_specs = sorted([(int(idx), spec) for k in keys for [
                        idx, spec] in [k.split(OrderLabelSep)]])

    result: Sequence[Tuple[int, Val]] = list(enumerate(after_condition))
    # use reversed to achieve the desired effect
    for (idx, spec) in reversed(sort_specs):
        def key_extract(elem: Tuple[int, Val], idx=idx, spec=spec):
            return orders[elem[0]].val[
                StrLabel(str(idx) + OrderLabelSep + spec)]
        result = sorted(
            result, key=key_extract,
            reverse=(False if spec == OrderAscending else
                     True if spec == OrderDescending else
                     eval_error(
                         cast(Sequence[Val],
                              orders),
                         "unknown spec")))
    return [elem for (_, elem) in result]


def apply_shape(ctx: RTData, shape: ShapeExpr, value: Val) -> Val:
    def apply_shape_to_prodval(
            shape: ShapeExpr, objectval: ObjectVal) -> ObjectVal:
        result: Dict[Label, Tuple[Marker, MultiSetVal]] = {}
        for (key, (_, pval)) in objectval.val.items():
            if key not in shape.shape.keys():
                result = {
                    **result, key: (Invisible(), (pval))}
            else:
                pass
        for (key, shape_elem) in shape.shape.items():
            if key in objectval.val.keys():
                new_val: MultiSetVal = eval_config(
                    RTExpr(make_eval_only(ctx),
                           instantiate_expr(value, shape.shape[key]))).val
                result = {
                    **result, key: (Visible(), (new_val))}
            else:
                new_val = eval_config(RTExpr(make_eval_only(ctx),
                                             instantiate_expr(
                                                 value, shape_elem)
                                             )).val
                result = {
                    **result, key: (Visible(), (new_val))}

        return ObjectVal(result)

    # [value] = assume_link_target([value])
    match value:
        case FreeVal(val=dictval):
            return FreeVal(val=apply_shape_to_prodval(shape, dictval))
        case RefVal(refid=id, val=dictval):
            return RefVal(
                refid=id, val=apply_shape_to_prodval(shape, dictval))
        case LinkPropVal(refid=id, linkprop=_):
            return RefVal(
                refid=id, val=apply_shape_to_prodval(shape, ObjectVal({})))
        case _:
            return eval_error(value, "Cannot apply shape to value")


def eval_expr_list(init_data: RTData,
                   exprs: Sequence[Expr]) -> Tuple[RTData,
                                                   Sequence[MultiSetVal]]:
    cur_data = init_data
    result: Sequence[MultiSetVal] = []
    for expr in exprs:
        (cur_data, val) = eval_config(RTExpr(cur_data, expr))
        result = [*result, val]
    return (cur_data, result)

# not sure why the semantics says to produce empty set when label not present


def singular_proj(data: RTData, subject: Val, label: Label) -> Sequence[Val]:
    match subject:
        case FreeVal(val=objVal):
            if label in objVal.val.keys():
                return objVal.val[label][1].vals
            else:
                raise ValueError("Label not found", label)
        case RefVal(refid=id, val=objVal):
            entry_obj = data.read_snapshots[0].dbdata[id].data
            if label in objVal.val.keys():
                return objVal.val[label][1].vals
            elif label in entry_obj.val.keys():
                return entry_obj.val[label][1].vals
            else:
                raise ValueError("Label not found", label)
        case NamedTupleVal(val=dic):
            match label:
                case StrLabel(l):
                    if l in dic.keys():
                        return [dic[l]]
                    else:
                        if l.isdigit() and int(l) < len(dic.keys()):
                            return [dic[list(dic.keys())[int(l)]]]
                        else:
                            raise ValueError("key DNE")
            raise ValueError("Label not Str")
        case UnnamedTupleVal(val=arr):
            match label:
                case StrLabel(l):
                    if l.isdigit() and int(l) < len(arr):
                        return [arr[int(l)]]
                    else:
                        raise ValueError("key DNE")
            raise ValueError("Label not Str")
        case LinkPropVal(refid=id, linkprop=linkprop):
            match label:
                case LinkPropLabel(label=lp_label):
                    return singular_proj(
                        data, FreeVal(val=linkprop),
                        label=StrLabel(lp_label))
                case StrLabel(_):
                    return singular_proj(data,
                                         RefVal(refid=id, val=ObjectVal({})),
                                         label=label)
                case _:
                    raise ValueError(label)
    raise ValueError("Cannot project, unknown subject", subject)


def offset_vals(val: Sequence[Val], offset: Val):
    match offset:
        case IntVal(val=v):
            return val[v:]
        case _:
            raise ValueError("offset must be an int")


def limit_vals(val: Sequence[Val],
               limit: Val) -> Sequence[Val]:
    match limit:
        case IntVal(val=v):
            return val[:v]
        case IntInfVal():
            return val
        case _:
            raise ValueError("offset must be an int")


class EvaluationLogsWrapper:
    def __init__(self):
        self.original_eval_config = None
        self.reset_logs(None)

    def reset_logs(self, logs: Optional[List[Any]]):
        self.logs = logs
        self.indexes: List[int] = []

    def __call__(self, eval_config: Callable[[RTExpr], RTVal]):
        self.original_eval_config = eval_config

        def wrapper(rt_expr: RTExpr) -> RTVal:
            if self.logs is None:
                return self.original_eval_config(rt_expr)
            else:
                parent = self.logs
                [parent := parent[i] for i in self.indexes]
                self.indexes.append(len(parent))
                parent.append([(rt_expr.expr, [StrVal("NOT AVAILABLE!!!")])])
                rt_val = self.original_eval_config(rt_expr)
                parent[self.indexes[-1]][0] = (parent[self.indexes[-1]][0][0],
                                               rt_val.val)
                assert len(parent[self.indexes[-1]][0]) == 2
                self.indexes.pop()
                return rt_val

        return wrapper


eval_logs_wrapper = EvaluationLogsWrapper()


@eval_logs_wrapper
def eval_config(rt: RTExpr) -> RTVal:
    match rt.expr:
        case (StrVal(_)
              | IntVal(_)
              | BoolVal(_)
              | RefVal(_)
              | ArrVal(_)
              | UnnamedTupleVal(_)
              | FreeVal(_)
              | LinkPropVal(_)
              ):
            return RTVal(rt.data, MultiSetVal([rt.expr]))
        case ObjectExpr(val=dic):
            cur_data = rt.data
            result: Dict[Label, Tuple[Marker, MultiSetVal]] = {}
            for (key, expr) in dic.items():  # type: ignore[has-type]
                (cur_data, val) = eval_config(RTExpr(cur_data, expr))
                result = {
                    **result, key: (Visible(), (val))}
            return RTVal(cur_data, MultiSetVal([FreeVal(ObjectVal(result))]))
        case InsertExpr(tname, arg):
            if rt.data.eval_only:
                eval_error(
                    rt.expr,
                    "Attempting to Insert in an Eval-Only evaluation")
            (new_data, argmv) = eval_config(RTExpr(rt.data, arg))
            [argv] = argmv.vals
            id = next_id()
            new_object = coerce_to_storage(
                get_object_val(argv), new_data.schema.val[tname])
            new_db = DB(dbdata={**new_data.cur_db.dbdata,
                        id: DBEntry(tp=VarTp(tname), data=new_object)})
            # inserts return empty dict
            return RTVal(
                RTData(
                    new_db, new_data.read_snapshots, new_data.schema,
                    new_data.eval_only),
                MultiSetVal([RefVal(id, ObjectVal({}))]))
        case FilterOrderExpr(subject=subject, filter=filter, order=order):
            (new_data, selected) = eval_config(RTExpr(rt.data, subject))
            # assume data unchaged throught the evaluation of conditions
            conditions: Sequence[MultiSetVal] = [
                eval_config(
                    RTExpr(
                        make_eval_only(new_data),
                        instantiate_expr(select_i, filter))).val
                for select_i in selected.vals]
            after_condition: Sequence[Val] = [
                select_i
                for (select_i, condition) in zip(selected.vals, conditions)
                if BoolVal(True) in condition.vals]
            orders: Sequence[ObjectVal] = [
                raw_order[0].val
                if
                type(raw_order[0]) is FreeVal and
                type(raw_order[0].val) is ObjectVal else
                eval_error(raw_order[0],
                           "Order must be an object val")
                for after_condition_i in after_condition
                for raw_order
                in
                [
                    eval_config(
                        RTExpr(
                            make_eval_only(new_data),
                            instantiate_expr(after_condition_i, order)
                            )).val.vals]
                if len(raw_order) == 1]
            after_order = eval_order_by(after_condition, orders)
            return RTVal(new_data, MultiSetVal(after_order))
        case ShapedExprExpr(expr=subject, shape=shape):
            (new_data, subjectv) = eval_config(RTExpr(rt.data, subject))
            after_shape: Sequence[Val] = [apply_shape(
                new_data, shape, v) for v in subjectv.vals]
            return RTVal(new_data, MultiSetVal(after_shape))
        case FreeVarExpr(var=name):
            cur_db_data = rt.data.read_snapshots[0].dbdata
            all_ids: Sequence[Val] = [
                RefVal(id, ObjectVal({}))
                for (id, item) in cur_db_data.items()
                if item.tp.name == name]
            return RTVal(rt.data, MultiSetVal(all_ids))
        case FunAppExpr(fun=fname, args=args, overloading_index=_):
            (new_data, argsv) = eval_expr_list(rt.data, args)
            argsv = map_assume_link_target(argsv)
            looked_up_fun = rt.data.schema.fun_defs[fname]
            f_modifier = looked_up_fun.tp.args_mod
            assert len(f_modifier) == len(argsv)
            argv_final: Sequence[Sequence[Sequence[Val]]] = [[]]
            for i in range(len(f_modifier)):
                mod_i = f_modifier[i]
                argv_i: Sequence[Val] = argsv[i].vals
                match mod_i:
                    case ParamSingleton():
                        argv_final = [
                            [*cur, [new]]
                            for cur in argv_final for new in argv_i]
                    case ParamOptional():
                        if len(argv_i) == 0:
                            argv_final = [[*cur, []] for cur in argv_final]
                        else:
                            argv_final = [
                                [*cur, [new]]
                                for cur in argv_final for new in argv_i]
                    case ParamSetOf():
                        argv_final = [[*cur, argv_i] for cur in argv_final]
                    case _:
                        raise ValueError()
            # argv_final = [map_assume_link_target(f) for f in argv_final]
            after_fun_vals: Sequence[Val] = [
                v for arg in argv_final for v in looked_up_fun.impl(arg)]
            return RTVal(new_data, MultiSetVal(after_fun_vals))
        case ObjectProjExpr(subject=subject, label=label):
            (new_data, subjectv) = eval_config(RTExpr(rt.data, subject))
            projected = [
                p
                for v in assume_link_target(subjectv).vals
                for p in singular_proj(new_data, v, StrLabel(label))]
            return RTVal(new_data, MultiSetVal(projected))
            # if all([val_is_link_convertible(v) for v in projected]):
            #     return RTVal(
            #         new_data, [convert_to_link(v) for v in projected])
            # elif all([not val_is_link_convertible(v) for v in projected]):
            #     return RTVal(new_data, projected)
            # else:
            #     return eval_error(
            #         projected, "Returned objects are not uniform")
        case BackLinkExpr(subject=subject, label=label):
            (new_data, subjectv) = eval_config(RTExpr(rt.data, subject))
            subjectv = assume_link_target(subjectv)
            subject_ids = [v.refid
                           if
                           isinstance(v, RefVal) else
                           eval_error(v, "expecting references")
                           for v in subjectv.vals]
            cur_read_data: Dict[int,
                                DBEntry] = rt.data.read_snapshots[0].dbdata
            results: List[Val] = []
            for (id, obj) in cur_read_data.items():
                if StrLabel(label) in obj.data.val.keys():
                    object_vals = obj.data.val[StrLabel(label)][1].vals
                    if all(isinstance(object_val, LinkPropVal)
                           for object_val in object_vals):
                        object_id_mapping = {
                            object_val.refid: object_val.linkprop
                            for object_val in object_vals
                            if isinstance(object_val, LinkPropVal)}
                        for (object_id,
                             obj_linkprop_val) in object_id_mapping.items():
                            if object_id in subject_ids:
                                results = [
                                    *results,
                                    LinkPropVal(
                                        refid=id,
                                        linkprop=obj_linkprop_val)]
            return RTVal(new_data, MultiSetVal(results))
        case TpIntersectExpr(subject=subject, tp=tp_name):
            (new_data, subjectv) = eval_config(RTExpr(rt.data, subject))
            after_intersect: List[Val] = []
            for v in subjectv.vals:
                match v:
                    case (RefVal(refid=vid, val=_)
                          | LinkPropVal(refid=vid,
                                        linkprop=_)):
                        if is_nominal_subtype_in_schema(
                                new_data.cur_db.dbdata[vid].tp.name, tp_name,
                                new_data.schema):
                            after_intersect = [*after_intersect, v]
                    case _:
                        raise ValueError("Expecting References")
            return RTVal(new_data, MultiSetVal(after_intersect))
        case TypeCastExpr(tp=tp, arg=arg):
            (new_data, argv2) = eval_config(RTExpr(rt.data, arg))
            casted = [type_cast(tp, v) for v in argv2.vals]
            return RTVal(new_data, MultiSetVal(casted))
        case UnnamedTupleExpr(val=tuples):
            (new_data, tuplesv) = eval_expr_list(rt.data, tuples)
            constructed = [
                UnnamedTupleVal(list(p))
                for p in itertools.product(
                    *map_expand_multiset_val(
                      map_assume_link_target(tuplesv)))]
            return RTVal(
                new_data, MultiSetVal(constructed)
                )
        case NamedTupleExpr(val=tuples):
            (new_data, tuplesv) = eval_expr_list(
                rt.data, list(tuples.values()))
            result_list: List[Val] = [
                           NamedTupleVal({k: p})
                           for prod in itertools.product(
                             *map_expand_multiset_val(
                               map_assume_link_target(tuplesv)))
                           for (k, p) in zip(
                               tuples.keys(),
                               prod, strict=True)]
            return RTVal(new_data, MultiSetVal(result_list))
        case UnionExpr(left=l, right=r):
            (new_data, lvals) = eval_config(RTExpr(rt.data, l))
            (new_data2, rvals) = eval_config(RTExpr(new_data, r))
            return RTVal(new_data2, MultiSetVal([*lvals, *rvals]))
        case ArrExpr(elems=elems):
            (new_data, elemsv) = eval_expr_list(rt.data, elems)
            arr_result = [ArrVal(list(el))
                          for el in itertools.product(
                          *map_expand_multiset_val(
                              map_assume_link_target(elemsv)))]
            return RTVal(new_data, MultiSetVal(arr_result))
        case UpdateExpr(subject=subject, shape=shape):
            if rt.data.eval_only:
                eval_error(
                    rt.expr,
                    "Attempting to Update in an Eval-Only evaluation")
            (new_data, subjectv) = eval_config(RTExpr(rt.data, subject))
            if all([val_is_ref_val(v) for v in subjectv.vals]):
                updated: Sequence[Val] = [apply_shape(
                    new_data, shape, v)
                    for v in subjectv.vals]  # type: ignore[misc]
                old_dbdata = rt.data.cur_db.dbdata
                new_dbdata = {
                    **old_dbdata, **
                    {u.refid:
                     DBEntry(
                         old_dbdata[u.refid].tp,
                         coerce_to_storage(
                             combine_object_val(
                                 old_dbdata[u.refid].data, u.val),
                             rt.data.schema.val
                             [old_dbdata[u.refid].tp.name]))
                     for u in cast(Sequence[RefVal],
                                   updated)}}
                return RTVal(
                    RTData(
                        DB(new_dbdata),
                        rt.data.read_snapshots, rt.data.schema,
                        rt.data.eval_only),
                    MultiSetVal(updated))
            else:
                return eval_error(rt.expr, "expecting all references")
        case MultiSetExpr(expr=elems):
            (new_data, elemsv) = eval_expr_list(rt.data, elems)
            result_list = [e for el in elemsv for e in el.vals]
            return RTVal(new_data, MultiSetVal(result_list))
        case WithExpr(bound=bound, next=next):
            (new_data, boundv) = eval_config(RTExpr(rt.data, bound))
            (new_data2, nextv) = eval_config(RTExpr(new_data, instantiate_expr(
                MultiSetExpr(cast(Sequence[Expr], boundv.vals)), next)))
            return RTVal(new_data2, nextv)
        case OffsetLimitExpr(subject=subject, offset=offset, limit=limit):
            (new_data, subjectv) = eval_config(RTExpr(rt.data, subject))
            (new_data2, offsetv_m) = eval_config(RTExpr(new_data, offset))
            offsetv = offsetv_m.vals[0]
            (new_data3, limitv_m) = eval_config(RTExpr(new_data2, limit))
            limitv = limitv_m.vals[0]
            result_list = list(limit_vals(
                             offset_vals(subjectv.vals, offsetv),
                             limitv))
            return RTVal(new_data3, MultiSetVal(result_list))
        case SubqueryExpr(expr=expr):
            (new_data, exprv) = eval_config(RTExpr(rt.data, expr))
            return RTVal(new_data, exprv)
        case e.SingularExpr(expr=expr):
            (new_data, exprv) = eval_config(RTExpr(rt.data, expr))
            assert len(exprv.vals) <= 1
            return RTVal(new_data, MultiSetVal(exprv.vals, singleton=True))
        case DetachedExpr(expr=expr):
            (new_data, exprv) = eval_config(RTExpr(rt.data, expr))
            return RTVal(new_data, exprv)
        case LinkPropProjExpr(subject=subject, linkprop=label):
            (new_data, subjectv) = eval_config(RTExpr(rt.data, subject))
            projected = [p for v in subjectv.vals for p in singular_proj(
                new_data, v, LinkPropLabel(label))]
            return RTVal(new_data, MultiSetVal(projected))
        case ForExpr(bound=bound, next=next):
            (new_data, boundv) = eval_config(RTExpr(rt.data, bound))
            (new_data2, vv) = eval_expr_list(new_data, [
                instantiate_expr(v, next) for v in boundv.vals])
            result_list = [p for v in vv for p in v.vals]
            return RTVal(new_data2, MultiSetVal(result_list))
        case OptionalForExpr(bound=bound, next=next):
            (new_data, boundv) = eval_config(RTExpr(rt.data, bound))
            if boundv.vals:
                (new_data2, vv) = eval_expr_list(new_data, [
                    instantiate_expr(v, next) for v in boundv.vals])
                result_list = [p for v in vv for p in v.vals]
                return RTVal(new_data2, MultiSetVal(result_list))
            else:
                return eval_config(
                    RTExpr(
                        new_data, instantiate_expr(
                            MultiSetExpr([]),
                            next)))

    raise ValueError("Not Implemented", rt.expr)


def eval_config_toplevel(rt: RTExpr, logs: Optional[Any] = None) -> RTVal:

    # on exception, this is not none
    # assert eval_logs_wrapper.logs is None
    if logs is not None:
        eval_logs_wrapper.reset_logs(logs)

    final_v = eval_config(rt)

    # restore the decorator state
    eval_logs_wrapper.reset_logs(None)

    match (final_v):
        case RTVal(data=data, val=val):
            # Do not dedup (see one of the test cases)
            return RTVal(data=data, val=(val))
            # return RTVal(data=data, val=assume_link_target(val))
        case v:
            raise ValueError(v)