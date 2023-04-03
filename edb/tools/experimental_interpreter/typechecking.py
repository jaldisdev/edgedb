
from functools import reduce
import operator
from typing import Tuple, Dict, Sequence

from .data import data_ops as e
from .data import expr_ops as eops
from .data import type_ops as tops


def enforce_singular(expr: e.Expr, card: e.CMMode) -> e.Expr:
    """ returns the singular expression of the upper bound
    of the cardinality is one"""
    if (isinstance(card.upper, e.FiniteCardinal)
            and card.upper.value == 1
            and not isinstance(expr, e.SingularExpr)):
        return e.SingularExpr(expr=expr)
    else:
        return expr


def synthesize_type_for_val_seq(ctx: e.RTData,
                                val_seq: Sequence[e.Val]) -> e.Tp:
    first_type = synthesize_type_for_val(ctx, val_seq[0])
    [check_type(e.TcCtx(ctx, {}), v,
                e.ResultTp(first_type, e.CardOne))
        for v in val_seq[1:]]
    return first_type


def synthesize_type_for_multiset_val(
        ctx: e.RTData,
        val: e.MultiSetVal) -> e.ResultTp:
    if len(val.vals) == 0:
        raise ValueError("Cannot synthesize type for empty list")
    else:
        card = len(val.vals)
        return e.ResultTp(
            synthesize_type_for_val_seq(ctx, val.vals),
            e.CMMode(e.FiniteCardinal(card), e.FiniteCardinal(card)))


def synthesize_type_for_object_val(
        ctx: e.RTData,
        val: e.ObjectVal) -> e.Tp:
    obj_tp: Dict[str, e.ResultTp] = {}
    linkprop_tp: Dict[str, e.ResultTp] = {}

    for lbl, v in val.val.items():
        match lbl:
            case e.StrLabel(label=s_lbl):
                if s_lbl in obj_tp.keys():
                    raise ValueError("duplicate keys in object val")
                else:
                    obj_tp = {
                        **obj_tp,
                        s_lbl: synthesize_type_for_multiset_val(ctx, v[1])}
            case e.LinkPropLabel(label=l_lbl):
                if l_lbl in linkprop_tp.keys():
                    raise ValueError("duplicate keys in object val")
                else:
                    linkprop_tp = {
                        **linkprop_tp,
                        l_lbl: synthesize_type_for_multiset_val(ctx, v[1])}

    if len(linkprop_tp.keys()) == 0:
        return e.ObjectTp(obj_tp)
    else:
        return e.LinkPropTp(
            e.ObjectTp(obj_tp),
            e.ObjectTp(linkprop_tp))


def synthesize_type_for_val(ctx: e.RTData,
                            val: e.Val) -> e.Tp:
    match val:
        case e.StrVal(_):
            return e.StrTp()
        case e.IntVal(_):
            return e.IntTp()
        case e.IntInfVal():
            return e.IntInfTp()
        case e.BoolVal(_):
            return e.BoolTp()
        case e.RefVal(refid=id, val=obj):
            # ref_tp = ctx.schema.val[ctx.cur_db.dbdata[id].tp]
            ref_obj = ctx.cur_db.dbdata[id].data
            combined = eops.combine_object_val(ref_obj, obj)
            return synthesize_type_for_object_val(ctx, combined)
        case e.FreeVal(val=obj):
            return synthesize_type_for_object_val(ctx, obj)
        case e.ArrVal(val=arr):
            return e.ArrTp(
                synthesize_type_for_val_seq(ctx, arr))
        case e.UnnamedTupleVal(val=arr):
            return e.UnnamedTupleTp(
                [synthesize_type_for_val(ctx, e) for e in arr])
        case e.NamedTupleVal(val=obj):
            return e.NamedTupleTp(
               {n: synthesize_type_for_val(ctx, e) for n, e in obj.items()})
        case e.LinkPropVal(refid=id, linkprop=linkprop):
            obj_tp: e.Tp = ctx.schema.val[ctx.cur_db.dbdata[id].tp.name]
            obj_tp = tops.get_runtime_tp(obj_tp)
            linkprop_tp = synthesize_type_for_object_val(ctx, linkprop)
            assert isinstance(linkprop_tp, e.ObjectTp)
            return e.LinkPropTp(obj_tp, linkprop_tp)
        case _:
            raise ValueError("Not implemented", val)


def check_shape_transform(ctx: e.TcCtx, s: e.ShapeExpr,
                          tp: e.Tp) -> Tuple[e.Tp, e.ShapeExpr]:
    s_tp: e.ObjectTp
    l_tp: e.ObjectTp

    # populate result skeleton
    match tp:
        case e.LinkPropTp(subject=subject_tp, linkprop=linkprop_tp):
            if isinstance(subject_tp, e.ObjectTp):
                s_tp = subject_tp
                l_tp = linkprop_tp
            else:
                raise ValueError("NI")
        case e.ObjectTp(_):
            s_tp = tp
            l_tp = e.ObjectTp({})
        case _:
            raise ValueError("NI")

    result_s_tp = e.ObjectTp({})
    result_l_tp = e.ObjectTp({})
    result_expr = e.ShapeExpr({})

    for lbl, comp in s.shape.items():
        match lbl:
            case e.StrLabel(s_lbl):
                if s_lbl in s_tp.val.keys():
                    new_ctx, body, bnd_var = eops.tcctx_add_binding(
                        ctx, comp, e.ResultTp(tp, e.CardOne))
                    result_tp = s_tp.val[s_lbl]
                    checked_body = check_type(new_ctx, body, result_tp)
                    result_s_tp = e.ObjectTp({**result_s_tp.val,
                                              s_lbl: result_tp})
                    result_expr = e.ShapeExpr(
                        {**result_expr.shape,
                         lbl: eops.abstract_over_expr(checked_body, bnd_var)})
                else:
                    new_ctx, body, bnd_var = eops.tcctx_add_binding(
                        ctx, comp, e.ResultTp(tp, e.CardOne))
                    result_tp, checked_body = synthesize_type(
                        new_ctx, body)
                    result_s_tp = e.ObjectTp({**result_s_tp.val,
                                              s_lbl: result_tp})
                    result_expr = e.ShapeExpr(
                        {**result_expr.shape,
                         lbl: eops.abstract_over_expr(checked_body, bnd_var)})
            case e.LinkPropLabel(l_lbl):
                if l_lbl in l_tp.val.keys():
                    new_ctx, body, bnd_var = eops.tcctx_add_binding(
                        ctx, comp, e.ResultTp(tp, e.CardOne))
                    result_tp = l_tp.val[l_lbl]
                    checked_body = check_type(new_ctx, body, result_tp)
                    result_l_tp = e.ObjectTp({**result_l_tp.val,
                                              l_lbl: result_tp})
                    result_expr = e.ShapeExpr(
                        {**result_expr.shape,
                         lbl: eops.abstract_over_expr(checked_body, bnd_var)})
                else:
                    new_ctx, body, bnd_var = eops.tcctx_add_binding(
                        ctx, comp, e.ResultTp(tp, e.CardOne))
                    result_tp, checked_body = synthesize_type(
                        new_ctx, body)
                    result_l_tp = e.ObjectTp({**result_l_tp.val,
                                              l_lbl: result_tp})
                    result_expr = e.ShapeExpr(
                        {**result_expr.shape,
                         lbl: eops.abstract_over_expr(checked_body, bnd_var)})

    for t_lbl, s_comp_tp in s_tp.val.items():
        if e.StrLabel(t_lbl) not in s.shape.keys():
            result_s_tp = e.ObjectTp({**result_s_tp.val,
                                      t_lbl: s_comp_tp})

    for t_lbl, l_comp_tp in l_tp.val.items():
        if e.LinkPropLabel(t_lbl) not in s.shape.keys():
            result_l_tp = e.ObjectTp({**result_l_tp.val,
                                      t_lbl: l_comp_tp})

    return e.LinkPropTp(result_s_tp, result_l_tp), result_expr
     

def type_cast_tp(from_tp: e.ResultTp, to_tp: e.Tp) -> e.ResultTp:
    match from_tp, to_tp:
        case ((e.IntTp(), card), e.IntTp()):
            return e.ResultTp(e.IntTp(), card)
        case _:
            raise ValueError("Not Implemented")


def synthesize_type(ctx: e.TcCtx, expr: e.Expr) -> Tuple[e.ResultTp, e.Expr]:
    result_tp: e.Tp
    result_card: e.CMMode
    result_expr: e.Expr = expr  # by default we don't change expr

    match expr:
        case (e.StrVal(_)
              | e.IntVal(_)
              | e.BoolVal(_)
              | e.RefVal(_)
              | e.ArrVal(_)
              | e.UnnamedTupleVal(_)
              | e.FreeVal(_)
              | e.LinkPropVal(_)
              ):
            result_tp = synthesize_type_for_val(ctx.statics, expr)
            result_card = e.CardOne
        case e.FreeVarExpr(var=var):
            if var in ctx.varctx.keys():
                result_tp, result_card = ctx.varctx[var]
            elif var in ctx.statics.schema.val.keys():
                result_tp = ctx.statics.schema.val[var]
            else:
                raise ValueError("Unknown variable")
        case e.TypeCastExpr(tp=tp, arg=arg):
            (arg_tp, arg_v) = synthesize_type(ctx, arg)
            (result_tp, result_card) = type_cast_tp(arg_tp, tp)
            result_expr = e.TypeCastExpr(tp, arg_v)
        case e.ShapedExprExpr(expr=subject, shape=shape):
            (subject_tp, subject_ck) = synthesize_type(ctx, subject)
            result_tp, shape_ck = check_shape_transform(
                ctx, shape, subject_tp.tp)
            assert eops.is_effect_free(shape), "Shape should be effect free"
            result_card = subject_tp.mode
            result_expr = e.ShapedExprExpr(subject_ck, shape_ck)
        case e.UnionExpr(left=l, right=r):
            (l_tp, l_ck) = synthesize_type(ctx, l)
            (r_tp, r_ck) = synthesize_type(ctx, r)
            assert l_tp.tp == r_tp.tp, "Union types must match"
            result_tp = l_tp.tp
            result_card = l_tp.mode + r_tp.mode
            result_expr = e.UnionExpr(l_ck, r_ck)
        case e.FunAppExpr(fun=fname, args=args, overloading_index=idx):
            assert idx is None, ("Overloading should be empty "
                                 "before type checking")
            fun_tp = ctx.statics.schema.fun_defs[fname].tp
            if fun_tp.effect_free:
                assert all(eops.is_effect_free(arg) for arg in args), (
                    "Expect effectful arguments to effect-free functions")
            
            assert len(fun_tp.args_ret_types) == 1, "TODO: overloading"

            assert len(args) == len(fun_tp.args_mod), "argument count mismatch"

            arg_cards, arg_cks = zip(*[check_type_no_card(
                    ctx, arg, fun_tp.args_ret_types[0].args_tp[i])
                    for i, arg in enumerate(args)])

            # take the product of argument cardinalities
            arg_card_product = reduce(
                operator.mul,
                (tops.match_param_modifier(param_mod, arg_card)
                 for param_mod, arg_card
                 in zip(fun_tp.args_mod, arg_cards, strict=True)))
            result_tp = fun_tp.args_ret_types[0].ret_tp.tp
            result_card = (arg_card_product
                           * fun_tp.args_ret_types[0].ret_tp.mode)
            result_expr = e.FunAppExpr(fun=fname, args=arg_cks,
                                       overloading_index=idx)
        case e.ObjectExpr(val=dic):
            s_tp = e.ObjectTp({})
            link_tp = e.ObjectTp({})
            dic_ck: Dict[e.Label, e.Expr] = {}
            for k, v in dic.items():
                (v_tp, v_ck) = synthesize_type(ctx, v)
                dic_ck = {**dic_ck, k: v_ck}
                match k:
                    case e.StrLabel(s_lbl):
                        s_tp = e.ObjectTp({**s_tp.val,
                                           s_lbl: v_tp})
                    case e.LinkPropLabel(s_lbl):
                        link_tp = e.ObjectTp({**link_tp.val,
                                              s_lbl: v_tp})
            result_tp = e.LinkPropTp(s_tp, link_tp)
            result_card = e.CardOne
            result_expr = e.ObjectExpr(dic_ck)
        case e.ObjectProjExpr(subject=subject, label=label):
            (subject_tp, subject_ck) = synthesize_type(ctx, subject)
            result_expr = e.ObjectProjExpr(subject_ck, label)
            result_tp, result_card = tops.tp_project(
                subject_tp, e.StrLabel(label))
        case e.LinkPropProjExpr(subject=subject, linkprop=lp):
            (subject_tp, subject_ck) = synthesize_type(ctx, subject)
            result_expr = e.LinkPropProjExpr(subject_ck, lp)
            result_tp, result_card = tops.tp_project(
                subject_tp, e.LinkPropLabel(lp))
        case e.BackLinkExpr(subject=subject, label=label):
            (_, subject_ck) = synthesize_type(ctx, subject)
            result_expr = e.BackLinkExpr(subject_ck, label)
            result_tp = e.AnyTp()
            result_card = e.CardAny
        case e.TpIntersectExpr(subject=subject, tp=intersect_tp):
            (subject_tp, subject_ck) = synthesize_type(ctx, subject)
            result_expr = e.TpIntersectExpr(subject_ck, intersect_tp)
            result_tp = e.IntersectTp(subject_tp.tp, e.VarTp(intersect_tp))
            result_card = e.CMMode(
                e.Fin(0),
                subject_tp.mode.upper, 
                subject_tp.mode.multiplicity
            )
        case e.SubqueryExpr(expr=sub_expr):
            (sub_expr_tp, sub_expr_ck) = synthesize_type(ctx, sub_expr)
            result_expr = e.SubqueryExpr(sub_expr_ck)
            result_tp = sub_expr_tp.tp
            result_card = sub_expr_tp.mode
        case e.DetachedExpr(expr=sub_expr):
            (sub_expr_tp, sub_expr_ck) = synthesize_type(ctx, sub_expr)
            result_expr = e.SubqueryExpr(sub_expr_ck)
            result_tp = sub_expr_tp.tp
            result_card = sub_expr_tp.mode
        case e.WithExpr(bound=bound_expr, next=next_expr):
            (bound_tp, bound_ck) = synthesize_type(ctx, bound_expr)
            new_ctx, body, bound_var = eops.tcctx_add_binding(
                ctx, next_expr, bound_tp)
            (next_tp, next_ck) = synthesize_type(new_ctx, body)
            result_expr = e.WithExpr(
                bound_ck, eops.abstract_over_expr(next_ck, bound_var))
            result_tp, result_card = next_tp
        case e.FilterOrderExpr(subject=subject, filter=filter, order=order):
            (subject_tp, subject_ck) = synthesize_type(ctx, subject)
            filter_ctx, filter_body, filter_bound_var = eops.tcctx_add_binding(
                ctx, filter, e.ResultTp(subject_tp.tp, e.CardOne))
            order_ctx, order_body, order_bound_var = eops.tcctx_add_binding(
                ctx, order, e.ResultTp(subject_tp.tp, e.CardOne))
            
            assert eops.is_effect_free(filter), "Expecting effect-free filter"
            assert eops.is_effect_free(order), "Expecting effect-free filter"

            (_, filter_ck) = check_type_no_card(
                filter_ctx, filter_body, e.BoolTp())
            (order_tp, order_ck) = synthesize_type(order_ctx, order_body)

            assert tops.is_order_spec(order_tp), "Expecting order spec"

            result_expr = e.FilterOrderExpr(
                subject_ck,
                eops.abstract_over_expr(filter_ck, filter_bound_var),
                eops.abstract_over_expr(order_ck, order_bound_var))
            result_tp = subject_tp.tp
            result_card = e.CMMode(
                e.Fin(0),
                subject_tp.mode.upper,
                subject_tp.mode.multiplicity
            )
        case e.OffsetLimitExpr(subject=subject, offset=offset, limit=limit):
            (subject_tp, subject_ck) = synthesize_type(ctx, subject)
            offset_ck = check_type(ctx, offset,
                                   e.ResultTp(e.IntTp(), e.CardOne))
            limit_ck = check_type(ctx, limit,
                                  e.ResultTp(e.IntInfTp(), e.CardOne))
            result_expr = e.OffsetLimitExpr(subject_ck, offset_ck, limit_ck)
            result_tp = subject_tp.tp
            result_card = e.CMMode(
                e.Fin(0),
                subject_tp.mode.upper,
                subject_tp.mode.multiplicity
            )
        case e.InsertExpr(name=tname, new=arg):
            tname_tp = ctx.statics.schema.val[tname]
            arg_ck = check_type(ctx, arg, e.ResultTp(tname_tp, e.CardOne))
            assert isinstance(arg, e.ObjectExpr), (
                "Expecting object expr in inserts")
            assert all(isinstance(k, e.StrLabel) for k in arg.val.keys()), (
                        "Expecting object expr in inserts")
            result_expr = e.InsertExpr(tname, arg_ck)
            result_tp = tname_tp
            result_card = e.CardOne
        case e.UpdateExpr(subject=subject, shape=shape_expr):
            (subject_tp, subject_ck) = synthesize_type(ctx, subject)
            assert eops.is_effect_free(shape_expr), (
                "Expecting shape expr to be effect-free")
            assert eops.is_effect_free(subject), (
                "Expecting subject expr to be effect-free")
            (after_tp, shape_ck) = check_shape_transform(
                ctx, shape_expr, subject_tp.tp)
            assert tops.is_real_subtype(after_tp, subject_tp.tp)

            result_expr = e.UpdateExpr(subject_ck, shape_ck)
            result_tp, result_card = subject_tp
        case e.ForExpr(bound=bound, next=next):
            (bound_tp, bound_ck) = synthesize_type(ctx, bound)
            new_ctx, next_body, bound_var = eops.tcctx_add_binding(
                ctx, next, e.ResultTp(bound_tp.tp, e.CardOne))
            (next_tp, next_ck) = synthesize_type(new_ctx, next_body)
            result_expr = e.ForExpr(
                bound=bound_ck,
                next=eops.abstract_over_expr(next_ck, bound_var))
            result_tp = next_tp.tp
            result_card = next_tp.mode * bound_tp.mode
        case e.OptionalForExpr(bound=bound, next=next):
            (bound_tp, bound_ck) = synthesize_type(ctx, bound)
            new_ctx, next_body, bound_var = eops.tcctx_add_binding(
                ctx, next, e.ResultTp(bound_tp.tp, e.CardAtMostOne))
            (next_tp, next_ck) = synthesize_type(new_ctx, next_body)
            result_expr = e.OptionalForExpr(
                bound=bound_ck,
                next=eops.abstract_over_expr(next_ck, bound_var))
            result_tp = next_tp.tp
            result_card = next_tp.mode * e.CMMode(
                e.max_cardinal(e.min_cardinal(
                    e.Fin(1), bound_tp.mode.lower), bound_tp.mode.lower),
                e.max_cardinal(e.min_cardinal(
                    e.Fin(1), bound_tp.mode.upper), bound_tp.mode.upper),
                e.max_cardinal(e.min_cardinal(
                    e.Fin(1), bound_tp.mode.multiplicity),
                    bound_tp.mode.multiplicity))
        case e.UnnamedTupleExpr(val=arr):
            [res_tps, cks] = zip(*[synthesize_type(ctx, v) for v in arr])
            result_expr = e.UnnamedTupleExpr(list(cks))
            [tps, cards] = zip(*res_tps)
            result_tp = e.UnnamedTupleTp(list(tps))
            result_card = reduce(operator.mul, cards, e.CardOne)
        case e.NamedTupleExpr(val=arr):
            [res_tps, cks] = zip(*[synthesize_type(ctx, v)
                                   for _, v in arr.items()])
            result_expr = e.NamedTupleExpr({k: c
                                            for k, c in zip(arr.keys(), cks)})
            [tps, cards] = zip(*res_tps)
            result_tp = e.NamedTupleTp({k: t for k, t in zip(arr.keys(), tps)})
            result_card = reduce(operator.mul, cards, e.CardOne)
        case e.ArrExpr(elems=arr):
            assert len(arr) > 0, "Empty array does not support type synthesis"
            (first_tp, first_ck) = synthesize_type(ctx, arr[0])
            rest_card: Sequence[e.CMMode]
            (rest_card, rest_cks) = zip(
                *[check_type_no_card(ctx, arr_elem, first_tp.tp)
                  for arr_elem in arr[1:]])
            result_expr = e.ArrExpr([first_ck] + list(rest_cks))
            result_tp = e.ArrTp(first_tp.tp)
            rest_card = reduce(operator.mul, rest_card,
                               first_tp.mode)  # type: ignore[arg-type]
        case e.MultiSetExpr(expr=arr):
            assert len(arr) > 0, ("Empty multiset does not"
                                  " support type synthesis")
            (first_tp, first_ck) = synthesize_type(ctx, arr[0])
            (rest_card, rest_cks) = zip(
                *[check_type_no_card(ctx, arr_elem, first_tp.tp)
                    for arr_elem in arr[1:]])
            result_expr = e.MultiSetExpr([first_ck] + list(rest_cks))
            result_tp = first_tp.tp
            rest_card = reduce(operator.add, rest_card,
                               first_tp.mode)  # type: ignore[arg-type]
        case _:
            raise ValueError("Not Implemented", expr)

    # enforce singular
    # result_expr = enforce_singular(result_expr)

    return (e.ResultTp(result_tp, result_card), result_expr)


def check_type_no_card(ctx: e.TcCtx, expr: e.Expr,
                       tp: e.Tp) -> Tuple[e.CMMode, e.Expr]:
    match expr:
        case _:
            expr_tp, expr_ck = synthesize_type(ctx, expr)
            assert tops.is_real_subtype(expr_tp.tp, tp)
            return (expr_tp.mode, expr_ck)


def check_type(ctx: e.TcCtx, expr: e.Expr, tp: e.ResultTp) -> e.Expr:
    synth_mode, expr_ck = check_type_no_card(ctx, expr, tp.tp)
    assert tops.is_cardinal_subtype(synth_mode, tp.mode), (
        "Expecting cardinality %s, got %s" % (tp.mode, synth_mode))
    return expr_ck
    