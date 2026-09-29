-- The monthly rollup the dashboard reads, built the way a rollup is built:
-- group the daily pre-aggregate by month and add the columns up. Materialized,
-- so a wrong column is wrong at build time.
{{ config(materialized='table') }}
select
    cast(date_trunc('month', ordered_on) as timestamp) as order_month,
    sum(revenue) as revenue,
    sum(buyers) as buyers
from {{ ref('orders_daily') }}
group by 1
