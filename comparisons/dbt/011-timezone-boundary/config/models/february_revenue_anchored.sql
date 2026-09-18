-- The project-authored reading of the anchored metric. The store's zone is
-- not in the data and has no key to go in, so it is written here, as SQL.
select sum(revenue) as february_revenue
from {{ ref('orders') }}
where cast(placed_at as timestamp) at time zone 'America/New_York' at time zone 'UTC'
        >= timestamp '2025-02-01'
  and cast(placed_at as timestamp) at time zone 'America/New_York' at time zone 'UTC'
        < timestamp '2025-03-01'
