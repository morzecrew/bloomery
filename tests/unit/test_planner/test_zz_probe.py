from bloomery import MetricRequest
from bloomery.planner.policy import RowPolicy
from bloomery.planner.request import Op, Predicate
from support.planning import fixture_ir, make_planner
def test_probe():
    p=make_planner()
    ir=fixture_ir("ecom_basic")
    q=p.plan(ir, MetricRequest(metrics=("gross_revenue",),
        filters=(Predicate(dimension="quantity", op=Op.GTE, values=(2,)),
                 Predicate(dimension="line_no", op=Op.EQ, values=(1,)))),
        dialect="duckdb", policy=RowPolicy(dimension="order_customer_id", op=Op.EQ, value="c1"))
    print("EXPL", q.explanation.filters)
    print("PLAN", [n for n in q.semantic.nodes if type(n).__name__=="Filter"][0].predicates)
    ir2=fixture_ir("period_over_period")
    q2=p.plan(ir2, MetricRequest(metrics=("paid_revenue",)), dialect="duckdb")
    print("METRIC-FILTER PLAN", [n for n in q2.semantic.nodes if type(n).__name__=="Filter"][0].predicates)
    q3=p.plan(fixture_ir("non_additive_aov"), MetricRequest(metrics=("average_order_value",)), dialect="duckdb")
    print("DERIVED SEMANTIC:", q3.semantic)
